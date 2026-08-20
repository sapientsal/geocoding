"""Unit-level reproduction of the np.True_ BSON encode crash.

Replicates the exact storage snippet from server.py (geographic optimization loop)
against optimize_geographic_route output where some geocodes failed (None lat/lon),
which makes the latitude/longitude columns object dtype and makes row.get() return
raw numpy scalars (row.to_dict() boxes them, row.get() does NOT).
"""
import math
import sys

import pandas as pd
import numpy as np
import pytest
from dotenv import dotenv_values
from pymongo import MongoClient

sys.path.insert(0, "/app/backend")
from server import optimize_geographic_route  # noqa: E402

backend_env = dotenv_values("/app/backend/.env")


@pytest.fixture(scope="module")
def coll():
    client = MongoClient(backend_env["MONGO_URL"])
    c = client[backend_env["DB_NAME"]]["TEST_tmp_numpy_check"]
    yield c
    c.drop()
    client.close()


def _build():
    df = pd.DataFrame({
        'STREET_NAME': ['Bahnhofstraße', 'Bahnhofstraße', 'Hauptstraße', 'Hauptstraße', 'Hauptstraße'],
        'NUMBER': [1, 2, 5, 7, 9],
        'NUMBER_AFFIX': [None] * 5,
        'PLZ': [4565] * 5,
        'MUNICIPALITY': ['Regis-Breitingen'] * 5,
        'DISTRICT': ['Regis-Breitingen'] * 5,
        'TEST_BOOL': [True, False, True, True, False],
    })
    addresses = [f"{r.STREET_NAME} {r.NUMBER}, 04565 Regis-Breitingen" for r in df.itertuples()]
    geocoded_data = [
        {'latitude': 51.0854, 'longitude': 12.4300, 'formatted_address': 'a', 'geocoded': True, 'error': ''},
        {'latitude': None, 'longitude': None, 'formatted_address': '', 'geocoded': False, 'error': 'not found'},
        {'latitude': 51.0860, 'longitude': 12.4310, 'formatted_address': 'c', 'geocoded': True, 'error': ''},
        {'latitude': 51.0865, 'longitude': 12.4320, 'formatted_address': 'd', 'geocoded': True, 'error': ''},
        {'latitude': None, 'longitude': None, 'formatted_address': '', 'geocoded': False, 'error': 'not found'},
    ]
    return df, geocoded_data, addresses


def test_storage_snippet_is_bson_safe(coll):
    df, geocoded_data, addresses = _build()
    optimized_df, total_distance = optimize_geographic_route(df, geocoded_data, addresses)

    optimized_addresses = []
    numpy_leaks = []
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
        is_geocoded = (lat is not None and lon is not None and
                       not pd.isna(lat) and not pd.isna(lon) and
                       lat != 0 and lon != 0)
        address_data = {
            "original_address": row.get('original_address', ''),
            "latitude": None if pd.isna(lat) else lat,
            "longitude": None if pd.isna(lon) else lon,
            "formatted_address": row.get('formatted_address', ''),
            "geocoded": is_geocoded,
            "geocoding_error": row.get('geocoding_error', ''),
            "distance_to_next": None if pd.isna(row.get('distance_to_next_m')) else row.get('distance_to_next_m'),
            "row_data": row_dict,
        }
        for k, v in address_data.items():
            if type(v).__module__ == 'numpy':
                numpy_leaks.append((k, type(v).__name__, repr(v)))
        optimized_addresses.append(address_data)

    route_data = {
        "job_id": "TEST_unit_numpy",
        "optimized_addresses": optimized_addresses,
        "total_distance": total_distance,
    }
    if type(total_distance).__module__ == 'numpy':
        numpy_leaks.append(("total_distance", type(total_distance).__name__, repr(total_distance)))

    try:
        coll.insert_one(route_data)
        inserted = True
        err = None
    except Exception as exc:  # pragma: no cover
        inserted = False
        err = str(exc)

    print("numpy leaks:", numpy_leaks)
    assert inserted, f"BSON insert failed ({err}); numpy leaks: {numpy_leaks}"
    assert not numpy_leaks, f"numpy scalars present outside row_data: {numpy_leaks}"
