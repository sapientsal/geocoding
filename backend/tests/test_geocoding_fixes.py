"""Tests for the PLZ-validation + outlier-correction fix (Ballenstedt bug)."""
import os
import sys
import asyncio
import pytest
import pandas as pd
from dotenv import dotenv_values
from pymongo import MongoClient

sys.path.insert(0, '/app/backend')
from dotenv import load_dotenv
load_dotenv('/app/backend/.env')

import server  # noqa: E402

backend_env = dotenv_values("/app/backend/.env")
MONGO_URL = backend_env.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = backend_env.get("DB_NAME") or os.environ.get("DB_NAME")


# ---------------------------------------------------------------------------
# Test 1 – Outlier correction (unit-level, NO live geocoding)
# ---------------------------------------------------------------------------
class TestOutlierCorrection:
    def test_single_outlier_snapped_to_street_median(self):
        # 6 addresses on Schimmelgasse in Opperode. 5 real, 1 wrong (250 km away).
        df = pd.DataFrame({
            'Straße':    ['Schimmelgasse'] * 6,
            'Hausnummer': [60, 61, 62, 63, 64, 65],
            'PLZ':       [6493] * 6,
            'Ort':       ['Opperode'] * 6,
        })
        # 5 correct coords near Opperode (51.72, 11.25), one bad at Erzhausen (49.92, 8.95)
        good_coords = [
            (51.720, 11.250),
            (51.721, 11.251),
            (51.722, 11.252),
            (51.719, 11.249),
            (51.720, 11.250),
        ]
        bad = (49.920, 8.950)  # the outlier – position 4 (index 4 → hausnr 64)
        coords = good_coords[:4] + [bad] + good_coords[4:]  # 6 items
        geocoded = [
            {'latitude': lat, 'longitude': lon,
             'formatted_address': f'Schimmelgasse {60+i}', 'geocoded': True, 'error': ''}
            for i, (lat, lon) in enumerate(coords)
        ]
        addresses = [f'Schimmelgasse {60+i}, 06493 Opperode' for i in range(6)]

        opt_df, total = server.optimize_geographic_route(df, geocoded, addresses)
        assert len(opt_df) == 6

        # Find the outlier row (originally Hausnummer 64)
        outlier_row = opt_df[opt_df['Hausnummer'] == 64].iloc[0]
        assert outlier_row['latitude'] is not None
        # Must be snapped near Opperode (within ~1 km of median 51.72/11.25)
        d = server.calculate_distance_meters(
            outlier_row['latitude'], outlier_row['longitude'], 51.720, 11.250)
        assert d is not None and d < 1000, \
            f'Outlier not snapped: still {d}m from street median'

        assert 'Koordinate korrigiert' in str(outlier_row.get('geocoding_error', '')), \
            f"geocoding_error should note correction, got '{outlier_row.get('geocoding_error')}'"

        # No consecutive distance should exceed 5 km after correction
        for d_next in opt_df['distance_to_next_m'].dropna():
            assert d_next <= 5000, f'distance_to_next_m={d_next} exceeds 5000m after correction'

    def test_no_correction_when_all_coords_valid(self):
        """Sanity check: valid addresses must NOT be modified."""
        df = pd.DataFrame({
            'Straße':    ['Schimmelgasse'] * 4,
            'Hausnummer': [1, 2, 3, 4],
            'PLZ':       [6493] * 4,
            'Ort':       ['Opperode'] * 4,
        })
        geocoded = [
            {'latitude': 51.720 + i*0.0001, 'longitude': 11.250 + i*0.0001,
             'formatted_address': 'x', 'geocoded': True, 'error': ''}
            for i in range(4)
        ]
        opt_df, _ = server.optimize_geographic_route(df, geocoded, ['a', 'b', 'c', 'd'])
        for _, row in opt_df.iterrows():
            assert 'Koordinate korrigiert' not in str(row.get('geocoding_error', ''))


# ---------------------------------------------------------------------------
# Test 2 – PLZ plausibility live-API check (small)
# ---------------------------------------------------------------------------
class TestPlzValidation:
    def _run(self, coro):
        # Isolate cache between tests to avoid stale entries
        server.address_cache.clear()
        return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)

    def test_opperode_rejects_erzhausen_hit(self):
        addr = 'Hauptstraße 99, 06493 Opperode'
        server.address_cache.pop(addr, None)
        res = asyncio.run(server.geocode_address_with_cache(addr))
        # Case A: geocoded false (all rejected) – acceptable
        # Case B: geocoded true with coords in the 06xxx region
        if res.get('geocoded'):
            lat, lon = res.get('latitude'), res.get('longitude')
            assert lat is not None and lon is not None
            # Reject Erzhausen-like coords
            assert not (49.5 < lat < 50.3 and 8.3 < lon < 9.0), \
                f'Returned known-bad Erzhausen coords: {lat},{lon}'
            # Must be in reasonable 06xxx range (roughly lat 51-52, lon 11-12)
            assert 51.0 < lat < 52.5, f'lat {lat} outside 06xxx PLZ region'
            assert 10.5 < lon < 12.0, f'lon {lon} outside 06xxx PLZ region'
        else:
            assert res.get('latitude') is None

    def test_valid_ballenstedt_still_geocodes(self):
        addr = 'Schloßplatz 3, 06493 Ballenstedt'
        server.address_cache.pop(addr, None)
        res = asyncio.run(server.geocode_address_with_cache(addr))
        assert res.get('geocoded') is True, f'Expected valid address to geocode, got {res}'
        lat, lon = res['latitude'], res['longitude']
        assert 51.5 < lat < 52.0, f'lat {lat} not near Ballenstedt (~51.7)'
        assert 11.0 < lon < 11.5, f'lon {lon} not near Ballenstedt (~11.2)'


# ---------------------------------------------------------------------------
# Test 3 – Existing user job (read-only)
# ---------------------------------------------------------------------------
class TestUserJobHealed:
    JOB_ID = 'e3dbe9db-6710-48d5-9306-39b12841c24e'

    def test_job_has_no_giant_distances_and_many_corrections(self):
        client = MongoClient(MONGO_URL)
        try:
            db = client[DB_NAME]
            doc = db['routes'].find_one({'job_id': self.JOB_ID})
            assert doc is not None, f'Route {self.JOB_ID} not found in routes'
            opts = doc.get('optimized_addresses', [])
            assert len(opts) > 0

            bad = []
            corrected = 0
            for o in opts:
                d = o.get('distance_to_next')
                if d is not None and d > 50000:
                    bad.append(d)
                err = str(o.get('geocoding_error') or '')
                if 'Koordinate korrigiert' in err:
                    corrected += 1

            assert not bad, f'{len(bad)} distances > 50 km still present (first: {bad[:5]})'
            assert corrected >= 80, \
                f'Only {corrected} corrected entries found, expected ≥ 80'
        finally:
            client.close()
