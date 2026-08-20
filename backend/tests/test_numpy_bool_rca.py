"""RCA test: reproduce 'cannot encode object: np.True_' at the real storage code path.

Hypothesis: when the first geocode fails, working_df['latitude'/'longitude'] become
object dtype. Later median/interpolation writes (.at) store np.float64 in that object
column. row.get('latitude') on an object column returns the RAW np.float64 (unlike
row.to_dict(), which boxes to native). The expression

    is_geocoded = (... and lat != 0 and lon != 0)

then evaluates to np.bool_ -> address_data['geocoded'] = np.True_ -> BSON crash.
np.float64 is a float subclass so lat/lon themselves encode fine; np.bool_ is not a
bool subclass -> exactly the reported error.
"""
import math
import sys

import numpy as np
import pandas as pd
import pytest
from dotenv import dotenv_values
from pymongo import MongoClient

sys.path.insert(0, "/app/backend")
from server import optimize_geographic_route, to_bson_safe  # noqa: E402

backend_env = dotenv_values("/app/backend/.env")


@pytest.fixture(scope="module")
def coll():
    client = MongoClient(backend_env["MONGO_URL"])
    c = client[backend_env["DB_NAME"]]["TEST_tmp_numpy_rca"]
    yield c
    c.drop()
    client.close()


def test_np_bool_leak_first_row_failed(coll):
    n = 8
    df = pd.DataFrame({
        'STREET_NAME': ['Bahnhofstraße'] * n,
        'NUMBER': list(range(1, n + 1)),
        'NUMBER_AFFIX': [None] * n,
        'PLZ': [4565] * n,
        'MUNICIPALITY': ['Regis-Breitingen'] * n,
        'DISTRICT': ['Regis-Breitingen'] * n,
    })
    addresses = [f"Bahnhofstraße {i}, 04565 Regis-Breitingen" for i in range(1, n + 1)]

    # first geocode FAILS -> latitude/longitude columns become object dtype
    geocoded_data = [{'latitude': None, 'longitude': None, 'formatted_address': '',
                      'geocoded': False, 'error': 'not found'}]
    # valid coordinates + one far outlier (>2 km) so the outlier correction writes
    # the street MEDIAN (np.float64 on an object-dtype column) back via .at
    for i in range(1, n):
        if i == 4:
            geocoded_data.append({'latitude': 51.2000, 'longitude': 12.7000,
                                  'formatted_address': 'outlier', 'geocoded': True, 'error': ''})
        else:
            geocoded_data.append({'latitude': 51.0854 + i * 0.0002, 'longitude': 12.4300 + i * 0.0002,
                                  'formatted_address': f'addr {i}', 'geocoded': True, 'error': ''})

    optimized_df, total_distance = optimize_geographic_route(df, geocoded_data, addresses)
    print("dtypes:", {c: str(t) for c, t in optimized_df.dtypes.items() if c in ('latitude', 'longitude')})

    leaks = []
    docs = []
    for idx, row in optimized_df.iterrows():
        row_dict = {}
        for k, v in row.to_dict().items():
            if isinstance(v, float) and (pd.isna(v) or math.isinf(v)):
                row_dict[k] = None
            elif pd.isna(v):
                row_dict[k] = None
            elif isinstance(v, np.generic):
                row_dict[k] = v.item()
            else:
                row_dict[k] = v

        lat = row.get('latitude')
        lon = row.get('longitude')
        # mirrors FIXED server path: bool(...) cast
        is_geocoded = bool(lat is not None and lon is not None and
                       not pd.isna(lat) and not pd.isna(lon) and
                       lat != 0 and lon != 0)
        ad = {
            "original_address": row.get('original_address', ''),
            "latitude": None if pd.isna(lat) else lat,
            "longitude": None if pd.isna(lon) else lon,
            "formatted_address": row.get('formatted_address', ''),
            "geocoded": is_geocoded,
            "geocoding_error": row.get('geocoding_error', ''),
            "distance_to_next": None if pd.isna(row.get('distance_to_next_m')) else row.get('distance_to_next_m'),
            "row_data": row_dict,
        }
        for k, v in ad.items():
            if type(v).__module__ == 'numpy' and not isinstance(v, (float, int)) or isinstance(v, np.bool_):
                leaks.append((idx, k, type(v).__name__, repr(v)))
        docs.append(ad)

    err = None
    try:
        # mirrors FIXED server path: to_bson_safe before insert
        coll.insert_one(to_bson_safe({"job_id": "TEST_rca", "optimized_addresses": docs,
                         "total_distance": total_distance}))
    except Exception as exc:
        err = str(exc)

    print("INSERT ERROR:", err)
    assert err is None, f"BSON insert failed: {err} | leaks: {leaks}"
