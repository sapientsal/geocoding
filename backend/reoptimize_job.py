import sys, math, uuid
import pandas as pd
import numpy as np
from datetime import datetime
from dotenv import load_dotenv
load_dotenv('/app/backend/.env')
sys.path.insert(0, '/app/backend')
import server

JOB_ID = sys.argv[1]
HELPER_COLS = ['original_address', 'latitude', 'longitude', 'formatted_address', 'geocoded',
               'geocoding_error', 'street_clean', 'street_city_key', 'house_number_numeric',
               'house_number_letter', 'distance_to_next_m', 'street_from_geocoding']

route = server.routes_collection.find_one({'job_id': JOB_ID})
addrs = route['optimized_addresses']
rows, geocoded_data, addresses = [], [], []
for a in addrs:
    rd = dict(a['row_data'])
    for c in HELPER_COLS:
        rd.pop(c, None)
    rows.append(rd)
    geocoded_data.append({
        'latitude': a.get('latitude'),
        'longitude': a.get('longitude'),
        'formatted_address': a.get('formatted_address', ''),
        'geocoded': a.get('geocoded', False),
        'error': a.get('geocoding_error', ''),
    })
    addresses.append(a.get('original_address', ''))

df = pd.DataFrame(rows)
print(f"Re-optimiere {len(df)} Adressen für Job {JOB_ID}...")
optimized_df, total_distance = server.optimize_geographic_route(df, geocoded_data, addresses)

optimized_addresses = []
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
    lat, lon = row.get('latitude'), row.get('longitude')
    is_geo = lat is not None and lon is not None and not pd.isna(lat) and not pd.isna(lon) and lat != 0 and lon != 0
    optimized_addresses.append({
        "id": str(uuid.uuid4()),
        "original_address": row.get('original_address', ''),
        "latitude": None if pd.isna(lat) else lat,
        "longitude": None if pd.isna(lon) else lon,
        "formatted_address": row.get('formatted_address', ''),
        "geocoded": is_geo,
        "geocoding_error": row.get('geocoding_error', ''),
        "distance_to_next": None if pd.isna(row.get('distance_to_next_m')) else row.get('distance_to_next_m'),
        "row_data": row_dict
    })

server.routes_collection.update_one(
    {'_id': route['_id']},
    {'$set': {'optimized_addresses': optimized_addresses, 'total_distance': total_distance,
              'created_at': datetime.utcnow()}}
)
print(f"Fertig. Neue Gesamtdistanz: {round(total_distance/1000, 1)} km")
