"""
Tests for the new Straßenmitte-Fallback-Interpolation block in
server.optimize_geographic_route.

Tests 1 & 2 use synthetic geocoded_data (no live geocoding).
Test 3 is a read-only verification of the healed real Kitzscher job.
"""

import os
import sys

import pandas as pd
import pytest

# Ensure /app/backend is importable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import server  # noqa: E402


# --- Test 1: Interpolation of street-center fallbacks -----------------------
def _build_df_and_geocoded(rows):
    """
    rows: list of dicts {nr, lat, lon}. Uses same street/city/plz for all.
    """
    df_rows = []
    geocoded = []
    addresses = []
    for r in rows:
        df_rows.append({
            "Straße": "Testweg",
            "Hausnummer": str(r["nr"]),
            "PLZ": "04567",
            "Ort": "Kitzscher",
        })
        geocoded.append({
            "latitude": r["lat"],
            "longitude": r["lon"],
            "formatted_address": f"Testweg {r['nr']}, 04567 Kitzscher",
            "geocoded": True,
            "error": "",
        })
        addresses.append(f"Testweg {r['nr']}, 04567 Kitzscher")
    df = pd.DataFrame(df_rows)
    return df, geocoded, addresses


def test_interpolation_moves_street_center_fallbacks():
    """Nr 3 and Nr 5 share an identical fake street-center coordinate and must
    be re-positioned to the midpoint of their numeric neighbours."""
    center_lat, center_lon = 51.1660, 12.5310  # shared fallback (within 2km of median)
    rows = [
        {"nr": 1, "lat": 51.1702, "lon": 12.5300},
        {"nr": 2, "lat": 51.1704, "lon": 12.5300},
        {"nr": 3, "lat": center_lat, "lon": center_lon},
        {"nr": 4, "lat": 51.1708, "lon": 12.5300},
        {"nr": 5, "lat": center_lat, "lon": center_lon},
        {"nr": 6, "lat": 51.1712, "lon": 12.5300},
    ]
    df, geocoded, addresses = _build_df_and_geocoded(rows)
    optimized_df, _total = server.optimize_geographic_route(df, geocoded, addresses)

    # Locate rows by house number
    by_nr = {int(r["house_number_numeric"]): r for _, r in optimized_df.iterrows()}

    # Expected midpoints
    exp_nr3_lat = (51.1704 + 51.1708) / 2  # 51.1706
    exp_nr5_lat = (51.1708 + 51.1712) / 2  # 51.1710

    # Rows 3 and 5 must have been moved onto the neighbour midpoint
    assert abs(by_nr[3]["latitude"] - exp_nr3_lat) < 1e-6, \
        f"Nr 3 lat not interpolated: got {by_nr[3]['latitude']}"
    assert abs(by_nr[5]["latitude"] - exp_nr5_lat) < 1e-6, \
        f"Nr 5 lat not interpolated: got {by_nr[5]['latitude']}"

    # Longitude should be trusted-neighbour average (12.5300) or thereabouts
    assert abs(by_nr[3]["longitude"] - 12.5300) < 1e-6
    assert abs(by_nr[5]["longitude"] - 12.5300) < 1e-6

    # Distance to nearest neighbour midpoint <= ~100 m
    d3 = server.calculate_distance_meters(
        by_nr[3]["latitude"], by_nr[3]["longitude"], exp_nr3_lat, 12.5300)
    d5 = server.calculate_distance_meters(
        by_nr[5]["latitude"], by_nr[5]["longitude"], exp_nr5_lat, 12.5300)
    assert d3 < 100, f"Nr 3 more than 100m from expected midpoint: {d3}"
    assert d5 < 100, f"Nr 5 more than 100m from expected midpoint: {d5}"

    # Error label must indicate interpolation
    assert "Koordinate interpoliert" in str(by_nr[3]["geocoding_error"])
    assert "Koordinate interpoliert" in str(by_nr[5]["geocoding_error"])

    # Untouched trusted rows must NOT be flagged as interpolated
    for nr in (1, 2, 4, 6):
        assert "Koordinate interpoliert" not in str(by_nr[nr].get("geocoding_error", ""))

    # No distance_to_next_m within the same street exceeds ~300 m
    if "distance_to_next_m" in optimized_df.columns:
        street_rows = optimized_df[optimized_df["street_city_key"].astype(str).str.startswith("Testweg")]
        dists = [d for d in street_rows["distance_to_next_m"].tolist()
                 if d is not None and not pd.isna(d)]
        # Last row has no "next" -> may be NaN/None; drop above already.
        assert all(d <= 300 for d in dists[:-1] if d is not None), \
            f"Intra-street distance too large after interpolation: {dists}"


# --- Test 2: Multi-unit safety (same house number twice) --------------------
def test_multiunit_same_housenumber_not_interpolated():
    """Two rows with the SAME house number sharing coordinates must NOT be
    flagged/moved — legitimate multi-unit building."""
    shared_lat, shared_lon = 51.1708, 12.5300  # on-the-line coord for nr 4
    rows = [
        {"nr": 1, "lat": 51.1702, "lon": 12.5300},
        {"nr": 2, "lat": 51.1704, "lon": 12.5300},
        {"nr": 3, "lat": 51.1706, "lon": 12.5300},
        {"nr": 4, "lat": shared_lat, "lon": shared_lon},  # unit A
        {"nr": 4, "lat": shared_lat, "lon": shared_lon},  # unit B (same coord + same nr)
        {"nr": 5, "lat": 51.1710, "lon": 12.5300},
        {"nr": 6, "lat": 51.1712, "lon": 12.5300},
    ]
    df, geocoded, addresses = _build_df_and_geocoded(rows)
    optimized_df, _ = server.optimize_geographic_route(df, geocoded, addresses)

    # Rows with house_number_numeric == 4 must keep their exact coordinate
    nr4_rows = optimized_df[optimized_df["house_number_numeric"] == 4]
    assert len(nr4_rows) == 2
    for _, r in nr4_rows.iterrows():
        assert abs(r["latitude"] - shared_lat) < 1e-9, \
            f"Multi-unit nr 4 got moved: lat={r['latitude']}"
        assert abs(r["longitude"] - shared_lon) < 1e-9
        assert "Koordinate interpoliert" not in str(r.get("geocoding_error", ""))


# --- Test 3: Healed real Kitzscher job (read-only) --------------------------
def test_healed_kitzscher_job_readonly():
    from pymongo import MongoClient
    from dotenv import dotenv_values

    env = dotenv_values("/app/backend/.env")
    mongo_url = os.environ.get("MONGO_URL") or env.get("MONGO_URL")
    if not mongo_url:
        pytest.skip("MONGO_URL not set")
    client = MongoClient(mongo_url, serverSelectionTimeoutMS=5000)
    db = client["sales_routes"]
    doc = db["routes"].find_one({"job_id": "990ecb84-8116-4219-9ece-0a9b29ba85d5"})
    if not doc:
        pytest.skip("Kitzscher job not present in this environment")

    entries = doc.get("optimized_addresses") or []
    assert entries, "Kitzscher job has no route entries"

    interp = [e for e in entries
              if "Koordinate interpoliert" in str(e.get("geocoding_error", ""))]
    assert len(interp) >= 7, f"Expected >=7 interpolated entries, got {len(interp)}"

    for e in entries:
        d = e.get("distance_to_next")
        if d is None or (isinstance(d, float) and pd.isna(d)):
            continue
        assert d <= 5000, f"Distance {d} exceeds 5000 m in healed job"

    # District from row_data.DISTRICT
    def district_of(entry):
        rd = entry.get("row_data") or {}
        v = rd.get("DISTRICT") or rd.get("Teilort") or rd.get("district")
        return str(v).strip() if v else ""
    seq = [district_of(e) for e in entries]
    # Collapse to blocks
    blocks = []
    for d in seq:
        if not d:
            continue
        if not blocks or blocks[-1] != d:
            blocks.append(d)
    if blocks:
        assert len(blocks) == 6, f"Expected 6 contiguous district blocks, got {len(blocks)}: {blocks}"
        assert len(set(blocks)) == 6, f"Districts not unique across blocks: {blocks}"
        expected = {"Hainichen", "Trages", "Thierbach", "Braußwig", "Dittmannsdorf", "Kitzscher"}
        assert set(blocks) == expected, f"District set mismatch: {set(blocks)}"
