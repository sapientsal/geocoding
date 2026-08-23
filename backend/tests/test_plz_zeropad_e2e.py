"""
Iteration 9 verification tests.

Covers:
  - Test 1: PLZ leading-zero normalization end-to-end via POST /api/upload-optimized
            (numeric PLZ 6493 in xlsx -> '06493' in original_address + geocode_cache keys)
  - Test 2: GET /api/cache/stats -> 200 with valid JSON (after a geocode has run)
  - Test 3: GET /api/jobs -> 200 valid JSON list
  - Unit: normalize_plz() behaviour
"""
import os
import time
from io import BytesIO

import pandas as pd
import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

frontend_env = dotenv_values("/app/frontend/.env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = base_url.rstrip("/")

backend_env = dotenv_values("/app/backend/.env")
MONGO_URL = backend_env.get("MONGO_URL")
DB_NAME = backend_env.get("DB_NAME")

PROTECTED_JOB_PREFIXES = ("990ecb84", "e3dbe9db", "0cc914d1", "bcea122c")


@pytest.fixture(scope="module")
def db():
    client = MongoClient(MONGO_URL)
    yield client[DB_NAME]
    client.close()


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    yield s
    s.close()


# ---------------------------------------------------------------- unit tests
def test_normalize_plz_unit():
    import sys
    sys.path.insert(0, "/app/backend")
    from server import normalize_plz

    assert normalize_plz(6493) == "06493"
    assert normalize_plz(6493.0) == "06493"
    assert normalize_plz("6493") == "06493"
    assert normalize_plz(31275) == "31275"
    assert normalize_plz("06493") == "06493"
    assert normalize_plz(999) == "00999"
    assert normalize_plz(None) == ""
    assert normalize_plz("") == ""
    assert normalize_plz("ABC") == "ABC"


# ----------------------------------------------------- Test 1: E2E PLZ padding
@pytest.fixture(scope="module")
def uploaded_job(api, db):
    """Upload a tiny xlsx with numeric PLZ 6493 and wait for completion."""
    df = pd.DataFrame({
        "Straße": ["Schloßplatz", "Allee", "Markt", "Bahnhofstraße"],
        "Hausnummer": [3, 21, 7, 12],
        "PLZ": [6493, 6493, 6493, 6493],   # int64 -> leading zero lost by pandas
        "Ort": ["Ballenstedt"] * 4,
    })
    assert str(df["PLZ"].dtype).startswith("int"), f"PLZ dtype not int: {df['PLZ'].dtype}"

    buf = BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    buf.seek(0)

    resp = api.post(
        f"{BASE_URL}/api/upload-optimized",
        files={"file": ("TEST_plz_zeropad.xlsx", buf.getvalue(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        timeout=60,
    )
    assert resp.status_code == 200, f"upload failed: {resp.status_code} {resp.text[:400]}"
    job_id = resp.json().get("job_id")
    assert job_id

    # poll for completion (Photon ~1 addr/s, allow generous margin + singleton lock)
    status, last = None, None
    deadline = time.time() + 300
    while time.time() < deadline:
        r = api.get(f"{BASE_URL}/api/job/{job_id}", timeout=30)
        if r.status_code == 200:
            last = r.json()
            status = last.get("status")
            if status in ("completed", "error"):
                break
        time.sleep(3)

    yield {"job_id": job_id, "status": status, "job": last}

    # cleanup: only our own test job
    assert not job_id.startswith(PROTECTED_JOB_PREFIXES)
    api.delete(f"{BASE_URL}/api/job/{job_id}", timeout=30)


def test_job_completed(uploaded_job):
    assert uploaded_job["status"] == "completed", (
        f"job did not complete: {uploaded_job['status']} / {uploaded_job['job']}")
    assert uploaded_job["job"].get("total_addresses") == 4


def test_original_address_has_padded_plz(api, uploaded_job):
    job_id = uploaded_job["job_id"]
    r = api.get(f"{BASE_URL}/api/optimized/{job_id}", timeout=60)
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
    data = r.json()
    assert "_id" in data and isinstance(data["_id"], str)
    addrs = data["optimized_addresses"]
    assert len(addrs) == 4
    for a in addrs:
        orig = a["original_address"]
        assert "06493" in orig, f"PLZ not zero-padded in original_address: {orig!r}"
        assert ", 6493 " not in orig, f"unpadded PLZ found: {orig!r}"


def test_geocode_cache_keys_have_padded_plz(db, uploaded_job):
    docs = list(db["geocode_cache"].find({"_id": {"$regex": "Ballenstedt"}}))
    assert docs, "no geocode_cache entries for Ballenstedt were created"
    padded = [d["_id"] for d in docs if "06493" in d["_id"]]
    unpadded = [d["_id"] for d in docs if ", 6493 " in d["_id"]]
    assert padded, f"no cache key with 06493. keys={[d['_id'] for d in docs][:10]}"
    assert not unpadded, f"cache keys with unpadded PLZ: {unpadded[:10]}"


def test_geocoding_succeeded_for_padded_addresses(api, uploaded_job):
    """Sanity: zero-padded PLZ should still geocode (not break lookups)."""
    r = api.get(f"{BASE_URL}/api/optimized/{uploaded_job['job_id']}", timeout=60)
    assert r.status_code == 200
    addrs = r.json()["optimized_addresses"]
    geocoded = [a for a in addrs if a["geocoded"]]
    assert len(geocoded) >= 1, f"none of 4 addresses geocoded: {addrs}"


# --------------------------------------------- Test 2: cache stats / Test 3: jobs
def test_cache_stats(api, uploaded_job):
    r = api.get(f"{BASE_URL}/api/cache/stats", timeout=30)
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
    d = r.json()
    for k in ("cache_size", "successful_geocodes", "failed_geocodes",
              "estimated_hit_rate", "memory_usage_estimate"):
        assert k in d, f"missing key {k} in {d}"
    assert isinstance(d["cache_size"], int)
    assert d["cache_size"] >= 1, f"cache should be non-empty after geocoding: {d}"
    assert d["successful_geocodes"] + d["failed_geocodes"] == d["cache_size"]


def test_jobs_list(api):
    r = api.get(f"{BASE_URL}/api/jobs", timeout=60)
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
    jobs = r.json()
    assert isinstance(jobs, list)
    if jobs:
        j = jobs[0]
        for k in ("id", "filename", "status", "total_addresses",
                  "processed_addresses", "geocoded_addresses", "created_at"):
            assert k in j, f"missing {k} in job payload {j}"
        assert all("_id" not in job for job in jobs), "mongo _id leaked in /api/jobs"
