"""E2E: reproduce original np.True_ BSON failure chain via public API.

Small SDU-style xlsx with 1 intentionally unfindable address (forces object-dtype
lat/lon column -> numpy bool path) + 5 real Regis-Breitingen addresses.
Verifies job reaches 'completed', routes doc stored, geocoded flags are native
JSON bools, and export returns 200. Cleans up its own job.
"""
import io
import os
import time

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

ROWS = [
    # STREET_NAME, NUMBER, NUMBER_AFFIX, PLZ, MUNICIPALITY, DISTRICT
    ("Bahnhofstraße", 1, "", "04565", "Regis-Breitingen", "Regis-Breitingen"),
    ("Bahnhofstraße", 3, "", "04565", "Regis-Breitingen", "Regis-Breitingen"),
    ("Hauptstraße", 5, "", "04565", "Regis-Breitingen", "Regis-Breitingen"),
    ("Hauptstraße", 7, "a", "04565", "Regis-Breitingen", "Regis-Breitingen"),
    ("Qqqxyzstraße", 999, "", "04565", "Regis-Breitingen", "Regis-Breitingen"),
    ("Pegauer Straße", 2, "", "04565", "Regis-Breitingen", "Regis-Breitingen"),
]


@pytest.fixture(scope="module")
def xlsx_bytes():
    import pandas as pd
    df = pd.DataFrame(
        ROWS,
        columns=["STREET_NAME", "NUMBER", "NUMBER_AFFIX", "PLZ", "MUNICIPALITY", "DISTRICT"],
    )
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


@pytest.fixture(scope="module")
def created_jobs():
    ids = []
    yield ids
    for jid in ids:
        try:
            requests.delete(f"{BASE_URL}/api/job/{jid}", timeout=30)
        except Exception:
            pass


class TestNumpyBoolE2E:
    def test_upload_geocode_store_export(self, xlsx_bytes, created_jobs):
        files = {"file": ("TEST_regis_numpy.xlsx", xlsx_bytes,
                          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        r = requests.post(f"{BASE_URL}/api/upload-optimized", files=files, timeout=120)
        assert r.status_code == 200, r.text[:500]
        job_id = r.json()["job_id"]
        created_jobs.append(job_id)

        status, job = None, {}
        deadline = time.time() + 240
        while time.time() < deadline:
            jr = requests.get(f"{BASE_URL}/api/job/{job_id}", timeout=30)
            assert jr.status_code == 200, jr.text[:300]
            job = jr.json()
            status = job.get("status")
            if status in ("completed", "error"):
                break
            time.sleep(5)

        assert status == "completed", f"job status={status} error={job.get('error_message')}"

        # routes doc stored and readable via API
        opt = requests.get(f"{BASE_URL}/api/optimized/{job_id}", timeout=60)
        assert opt.status_code == 200, opt.text[:300]
        data = opt.json()
        addresses = data.get("optimized_addresses") or []
        assert len(addresses) == len(ROWS), f"expected {len(ROWS)} addresses, got {len(addresses)}"

        # geocoded flags are native JSON booleans; at least one failed geocode present
        flags = []
        for a in addresses:
            assert "geocoded" in a, f"missing geocoded flag: {list(a.keys())}"
            assert isinstance(a["geocoded"], bool), f"geocoded not bool: {type(a['geocoded'])}"
            flags.append(a["geocoded"])
        assert flags, "no geocoded flag found in response"
        assert False in flags, "expected at least one failed geocode (unfindable address)"
        assert True in flags, "expected at least one successful geocode"

        # export works
        ex = requests.get(f"{BASE_URL}/api/optimized/{job_id}/export", timeout=120)
        assert ex.status_code == 200, ex.text[:300]
        assert len(ex.content) > 0

        # DB-level: stored doc has no numpy types (bson would have failed anyway)
        if MONGO_URL and DB_NAME:
            client = MongoClient(MONGO_URL)
            doc = client[DB_NAME]["routes"].find_one({"job_id": job_id})
            assert doc is not None, "routes doc not stored in MongoDB"
            for a in doc.get("optimized_addresses", []):
                assert type(a["geocoded"]) is bool
            client.close()
