"""
Iteration 8 – Auto-Resume + persistent geocode cache tests.

Covers:
  * Test 1: restart backend mid-geocoding -> job must auto-resume (not 'error') and complete
  * Test 2: persistent Mongo 'geocode_cache' populated; second upload of same file is fast
  * Test 3: no 'file_data' binary leak in /api/jobs and /api/job/{id}
"""
import io
import os
import subprocess
import time

import openpyxl
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
MONGO_URL = os.environ.get("MONGO_URL") or backend_env.get("MONGO_URL")
mongo = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
db = mongo["sales_routes"]

BACKEND_LOG = "/var/log/supervisor/backend.out.log"

# Generated set of real German streets in Schwanebeck (39397) / Ballenstedt (06493)
# with a unique house-number range (200+) so nothing is pre-cached from earlier runs.
_STREETS = [
    ("Halberstädter Straße", "39397", "Schwanebeck"),
    ("Magdeburger Straße", "39397", "Schwanebeck"),
    ("Bahnhofstraße", "39397", "Schwanebeck"),
    ("Kirchstraße", "39397", "Schwanebeck"),
    ("Breite Straße", "39397", "Schwanebeck"),
    ("Gartenstraße", "39397", "Schwanebeck"),
    ("Schulstraße", "39397", "Schwanebeck"),
    ("Mühlenstraße", "39397", "Schwanebeck"),
    ("Wasserstraße", "39397", "Schwanebeck"),
    ("Am Markt", "39397", "Schwanebeck"),
    ("Allee", "06493", "Ballenstedt"),
    ("Rieder Straße", "06493", "Ballenstedt"),
    ("Quedlinburger Straße", "06493", "Ballenstedt"),
    ("Badeborner Weg", "06493", "Ballenstedt"),
    ("Anhaltiner Platz", "06493", "Ballenstedt"),
    ("Schlossstraße", "06493", "Ballenstedt"),
    ("Gartenstraße", "06493", "Ballenstedt"),
    ("Bahnhofstraße", "06493", "Ballenstedt"),
    ("Wilhelmstraße", "06493", "Ballenstedt"),
    ("Vogelherd", "06493", "Ballenstedt"),
]

# 120 addresses -> job runs ~2 min, giving a reliable mid-job restart window
ADDRESSES = []
for _n in range(6):
    for _i, (_st, _plz, _ort) in enumerate(_STREETS):
        ADDRESSES.append((_st, str(13 + _n), _plz, _ort))

TOTAL = len(ADDRESSES)


def build_xlsx() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Kundennummer", "Straße", "Hausnummer", "PLZ", "Ort"])
    for idx, (street, hnr, plz, ort) in enumerate(ADDRESSES, start=1):
        ws.append([f"TEST_{idx:03d}", street, hnr, plz, ort])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def upload(content: bytes, name="TEST_auto_resume.xlsx") -> str:
    resp = requests.post(
        f"{BASE_URL}/api/upload-optimized",
        files={"file": (name, content,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        timeout=60,
    )
    assert resp.status_code == 200, f"upload failed {resp.status_code}: {resp.text[:400]}"
    data = resp.json()
    assert "job_id" in data
    return data["job_id"]


def job_status(job_id: str) -> dict:
    r = requests.get(f"{BASE_URL}/api/job/{job_id}", timeout=30)
    assert r.status_code == 200, f"job status {r.status_code}: {r.text[:300]}"
    return r.json()


def wait_for(job_id, predicate, timeout, label):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            last = job_status(job_id)
        except Exception as exc:  # transient during restart
            print(f"  (transient poll error: {exc})")
            time.sleep(2)
            continue
        if predicate(last):
            return last
        if last.get("status") == "error":
            pytest.fail(f"Job went to error while waiting for {label}: {last}")
        time.sleep(2)
    pytest.fail(f"Timeout waiting for {label}; last state={last}")


def hard_kill_backend():
    """Emulate a pod going to sleep / OOM: SIGKILL the whole backend."""
    subprocess.run(
        "for p in $(ss -Hltnp 'sport = :8001' | grep -o 'pid=[0-9]*' | cut -d= -f2); "
        "do sudo kill -9 $p; done",
        shell=True, check=False, timeout=60)
    subprocess.run("sudo pkill -9 -f 'uvicorn backend[.]server'",
                   shell=True, check=False, timeout=60)
    time.sleep(4)


CREATED_JOBS = []


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    for jid in CREATED_JOBS:
        try:
            requests.delete(f"{BASE_URL}/api/job/{jid}", timeout=30)
        except Exception:
            pass


def test_1_restart_mid_job_auto_resumes_and_completes():
    content = build_xlsx()
    log_offset = os.path.getsize(BACKEND_LOG)
    job_id = upload(content)
    CREATED_JOBS.append(job_id)
    print(f"job_id={job_id}")

    # file_data must be persisted for auto-resume
    doc = db.upload_jobs.find_one({"id": job_id})
    assert doc is not None
    assert doc.get("file_data"), "file_data not persisted in job doc"

    # wait until mid-geocoding (progress is flushed every 10 addresses)
    mid = wait_for(job_id,
                   lambda j: j.get("processed_addresses", 0) >= 3
                   or (j.get("status") == "geocoding" and j.get("processed_addresses", 0) >= 3),
                   180, "processed_addresses >= 3")
    print(f"mid-job state: status={mid['status']} processed={mid['processed_addresses']}")
    assert mid["status"] in ("geocoding", "optimizing", "sorting"), mid["status"]
    assert mid["processed_addresses"] >= 3

    # ── THE user scenario: server restarts mid-job ────────────────────────────
    # NOTE: `supervisorctl restart` is a GRACEFUL stop -> uvicorn waits for the
    # BackgroundTask to finish, so the job is never actually interrupted.
    # A sleeping/evicted pod is a hard kill, so we emulate that with SIGKILL.
    # `supervisorctl signal KILL` / `pkill -f uvicorn` only hit the reloader
    # parent; the actual server child (spawned via multiprocessing) keeps :8001
    # and supervisor's restart then dies with "Address already in use".
    # So kill every process listening on the backend port + the reloader.
    hard_kill_backend()
    subprocess.run(["sudo", "supervisorctl", "start", "backend"],
                   check=False, capture_output=True, timeout=120)
    # wait for the API to answer again
    api_back = False
    for _ in range(45):
        try:
            if requests.get(f"{BASE_URL}/api/jobs", timeout=10).status_code == 200:
                api_back = True
                break
        except Exception:
            pass
        time.sleep(2)
    assert api_back, "backend did not come back up after hard kill"
    time.sleep(5)

    # (a) status must NOT be error and job must keep progressing.
    #     (stdout of the backend is block-buffered, so the log line is checked
    #      later, after enough output has been flushed.)
    st = wait_for(job_id, lambda j: j.get("status") in
                  ("geocoding", "optimizing", "sorting", "completed"),
                  120, "post-restart status")
    print(f"post-restart status={st['status']} processed={st['processed_addresses']} "
          f"msg={st.get('progress_message')}")
    assert st["status"] != "error", st

    # (b) completes
    final = wait_for(job_id, lambda j: j.get("status") == "completed", 600, "completed")
    assert final["total_addresses"] == TOTAL, final
    assert final["processed_addresses"] == TOTAL, final
    print(f"completed: geocoded={final['geocoded_addresses']}/{TOTAL}")

    # (c) auto-resume log line
    with open(BACKEND_LOG, "r", errors="replace") as fh:
        fh.seek(log_offset)
        new_log = fh.read()
    assert f"Auto-Resume für Job {job_id}" in new_log, \
        f"No auto-resume log entry for {job_id}. Tail: {new_log[-1200:]}"

    # (d) routes doc with all addresses + export 200
    route = db.routes.find_one({"job_id": job_id,
                                "optimization_type": "geographic_door_to_door"})
    assert route is not None, "no routes document created"
    assert len(route["optimized_addresses"]) == TOTAL, len(route["optimized_addresses"])

    exp = requests.get(f"{BASE_URL}/api/optimized/{job_id}/export", timeout=120)
    assert exp.status_code == 200, f"export {exp.status_code}: {exp.text[:300]}"
    assert len(exp.content) > 1000

    pytest.first_job = job_id
    pytest.first_geocoded = final["geocoded_addresses"]


def test_2_persistent_cache_and_fast_second_run():
    # cache documents exist for geocoded addresses
    total_cached = db.geocode_cache.count_documents({})
    assert total_cached > 0, "geocode_cache collection is empty"
    sample = db.geocode_cache.find_one({})
    assert isinstance(sample["_id"], str)
    assert "result" in sample
    assert sample["result"].get("latitude") is not None
    assert sample["result"].get("longitude") is not None
    print(f"geocode_cache docs={total_cached}, sample _id={sample['_id']}")

    # at least one of our addresses must be cached
    probe = f"{ADDRESSES[0][0]} {ADDRESSES[0][1]}, {ADDRESSES[0][2]} {ADDRESSES[0][3]}"
    matches = db.geocode_cache.count_documents({"_id": {"$regex": "39397|06493"}})
    print(f"cached docs for test PLZ regions: {matches} (probe form: {probe})")
    assert matches > 0, "none of the test addresses were persisted to cache"

    # second identical upload -> successful addresses come from cache (no API call)
    log_offset = os.path.getsize(BACKEND_LOG)
    job_id = upload(build_xlsx(), name="TEST_auto_resume_2.xlsx")
    CREATED_JOBS.append(job_id)
    start = time.time()
    final = wait_for(job_id, lambda j: j.get("status") == "completed", 300, "2nd run completed")
    elapsed = time.time() - start
    with open(BACKEND_LOG, "r", errors="replace") as fh:
        fh.seek(log_offset)
        run2_log = fh.read()
    live_calls = run2_log.count(f"Job {job_id}: Geocoding: ")
    print(f"second run: {elapsed:.1f}s, geocoded={final['geocoded_addresses']}/{TOTAL}, "
          f"live geocoding attempts={live_calls}")
    assert final["geocoded_addresses"] == getattr(pytest, "first_geocoded", final["geocoded_addresses"])
    # cached (successful) addresses must NOT trigger a live geocoding attempt
    expected_max_live = TOTAL - final["geocoded_addresses"] + 2
    assert live_calls <= expected_max_live, (
        f"{live_calls} live geocoding attempts on a cached rerun "
        f"(expected <= {expected_max_live}) – persistent cache not used")
    print(f"cache effective: only failed addresses were retried ({live_calls} attempts)")


def test_3_no_binary_leak_in_api_responses():
    r = requests.get(f"{BASE_URL}/api/jobs", timeout=60)
    assert r.status_code == 200
    jobs = r.json()
    assert isinstance(jobs, list) and len(jobs) > 0
    assert "file_data" not in r.text, "file_data leaked in /api/jobs"

    jid = getattr(pytest, "first_job", None) or jobs[0]["id"]
    r2 = requests.get(f"{BASE_URL}/api/job/{jid}", timeout=30)
    assert r2.status_code == 200
    assert "file_data" not in r2.text, "file_data leaked in /api/job/{id}"
    assert "_id" not in r2.json(), "_id leaked in /api/job/{id}"
    for j in jobs:
        assert "_id" not in j, "_id leaked in /api/jobs"
