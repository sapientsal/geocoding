"""Regression test for numpy scalar (np.bool_/np.int64) BSON encoding bug.

Bug: 'cannot encode object: np.True_, of type: <class numpy.bool>' when storing
optimized results (row.to_dict() contains numpy scalars). Fix: np.generic -> .item().
"""
import io
import os
import time

import pandas as pd
import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

frontend_env = dotenv_values("/app/frontend/.env")
_base = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not _base:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = _base.rstrip("/")

backend_env = dotenv_values("/app/backend/.env")
MONGO_URL = backend_env.get("MONGO_URL")
DB_NAME = backend_env.get("DB_NAME")

_test_job_ids = []


@pytest.fixture(scope="module")
def db():
    client = MongoClient(MONGO_URL)
    yield client[DB_NAME]
    for jid in _test_job_ids:
        client[DB_NAME]["upload_jobs"].delete_many({"id": jid})
        client[DB_NAME]["routes"].delete_many({"job_id": jid})
    client.close()


def _upload_df(df, filename):
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    buf.seek(0)
    r = requests.post(
        f"{BASE_URL}/api/upload-optimized",
        files={"file": (filename, buf.getvalue(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        timeout=60,
    )
    assert r.status_code == 200, f"upload failed {r.status_code}: {r.text[:300]}"
    jid = r.json()["job_id"]
    _test_job_ids.append(jid)
    return jid


def _wait(job_id, timeout_s=240):
    start = time.time()
    last = None
    while time.time() - start < timeout_s:
        r = requests.get(f"{BASE_URL}/api/job/{job_id}", timeout=15)
        assert r.status_code == 200, f"job status HTTP {r.status_code}"
        d = r.json()
        if d["status"] != last:
            last = d["status"]
            print(f"[{job_id[:8]}] status={last} {d.get('processed_addresses')}/{d.get('total_addresses')}")
        if d["status"] == "completed":
            return d
        if d["status"] == "error":
            pytest.fail(f"Job errored: {d.get('error_message')}")
        time.sleep(2)
    pytest.fail(f"Job {job_id} not completed in {timeout_s}s (last={last})")


class TestNumpyBoolStorage:
    """Test 1 + Test 2: SDU-format upload with pure bool column must not crash BSON encode."""

    def test_sdu_upload_with_bool_column(self, db):
        df = pd.DataFrame({
            'STREET_NAME': ['Bahnhofstraße', 'Bahnhofstraße', 'Bahnhofstraße', 'Hauptstraße', 'Hauptstraße'],
            'NUMBER': [1, 2, 3, 5, 7],
            'NUMBER_AFFIX': [None, None, None, None, None],
            'PLZ': [4565] * 5,
            'MUNICIPALITY': ['Regis-Breitingen'] * 5,
            'DISTRICT': ['Regis-Breitingen'] * 5,
            'TEST_BOOL': [True, False, True, True, False],
        })
        assert df['TEST_BOOL'].dtype == bool, "fixture must have real bool dtype"

        job_id = _upload_df(df, "TEST_regis_numpybool.xlsx")
        job = _wait(job_id)

        assert job["status"] == "completed"
        assert job["total_addresses"] == 5
        assert job.get("geocoded_addresses", 0) >= 4, f"geocoded={job.get('geocoded_addresses')}"
        assert not job.get("error_message"), f"unexpected error_message: {job.get('error_message')}"

        route = db["routes"].find_one({"job_id": job_id})
        assert route is not None, "no route document stored"
        opts = route.get("optimized_addresses")
        assert opts and len(opts) == 5, f"expected 5 optimized addresses got {len(opts or [])}"

        bools = []
        for o in opts:
            rd = o["row_data"]
            assert 'TEST_BOOL' in rd, f"TEST_BOOL missing in row_data keys: {list(rd.keys())}"
            v = rd['TEST_BOOL']
            assert type(v) is bool, f"TEST_BOOL is {type(v)} not native bool"
            bools.append(v)
            # address-level and row-level geocoded flags must be plain bools
            assert type(o["geocoded"]) is bool, f"address geocoded is {type(o['geocoded'])}"
            if 'geocoded' in rd:
                assert type(rd['geocoded']) is bool, f"row_data.geocoded is {type(rd['geocoded'])}"
            # no numpy repr leaked into any stored scalar
            for k, val in rd.items():
                assert type(val).__module__ != 'numpy', f"numpy scalar stored in {k}: {type(val)}"
        assert sorted(bools) == [False, False, True, True, True], f"bool values altered: {bools}"

        # API JSON must expose native true/false
        r = requests.get(f"{BASE_URL}/api/optimized/{job_id}", timeout=30)
        if r.status_code == 200:
            payload = r.json()
            addrs = payload.get("optimized_addresses") or payload.get("addresses") or []
            if addrs:
                assert isinstance(addrs[0]["row_data"]["TEST_BOOL"], bool)

        TestNumpyBoolStorage.job_id = job_id

    def test_export_works(self):
        job_id = getattr(TestNumpyBoolStorage, "job_id", None)
        assert job_id, "no job_id from previous test"
        r = requests.get(f"{BASE_URL}/api/optimized/{job_id}/export", timeout=90)
        assert r.status_code == 200, f"export HTTP {r.status_code}: {r.text[:300]}"
        assert len(r.content) > 100


class TestNumpyBoolWithFailedGeocodes:
    """Test 3: rows that fail geocoding make latitude/longitude columns object-dtype
    (None mixed with floats) -> row.get() returns raw numpy scalars -> np.bool_ in
    address_data['geocoded']. This is the real trigger of the reported BSON crash."""

    def test_mixed_geocode_success_failure(self, db):
        df = pd.DataFrame({
            'STREET_NAME': ['Bahnhofstraße', 'Qxzzyvnotexiststr', 'Bahnhofstraße', 'Wwqzznonexistentweg', 'Hauptstraße'],
            'NUMBER': [1, 999, 3, 888, 7],
            'NUMBER_AFFIX': [None, None, None, None, None],
            'PLZ': [4565] * 5,
            'MUNICIPALITY': ['Regis-Breitingen'] * 5,
            'DISTRICT': ['Regis-Breitingen'] * 5,
            'TEST_BOOL': [True, False, True, True, False],
        })
        job_id = _upload_df(df, "TEST_regis_partialfail.xlsx")
        job = _wait(job_id)
        assert job["status"] == "completed", f"error_message={job.get('error_message')}"

        route = db["routes"].find_one({"job_id": job_id})
        assert route is not None, "no route document stored (BSON encode failure?)"
        opts = route["optimized_addresses"]
        assert len(opts) == 5
        for o in opts:
            assert type(o["geocoded"]) is bool, f"address geocoded is {type(o['geocoded'])}"
            for k in ("latitude", "longitude", "distance_to_next"):
                v = o.get(k)
                assert v is None or type(v).__module__ != 'numpy', f"{k} stored as {type(v)}"
            for k, v in o["row_data"].items():
                assert type(v).__module__ != 'numpy', f"numpy scalar stored in row_data.{k}: {type(v)}"
