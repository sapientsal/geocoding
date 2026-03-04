# Sales Route Optimizer – PRD

## Original Problem Statement
Web tool for sales route optimization. Users upload Excel files with German addresses (various formats), the system geocodes them, sorts by street or optimizes geographically, and exports results as Excel.

**Critical recurring issue**: OpenStreetMap (Nominatim) rate-limiting made geocoding unusably slow (~20 addresses in 30 minutes).

## Architecture
```
/app/
├── backend/server.py      # Monolithic FastAPI server (all logic)
├── frontend/src/App.js    # React frontend
└── memory/PRD.md
```

**Stack**: FastAPI + React + MongoDB + aiohttp + pandas + openpyxl

## Key API Endpoints
- `POST /api/upload` – upload Excel, start background job
- `GET /api/jobs` – list all jobs
- `GET /api/jobs/{id}` – job status/progress
- `GET /api/export/street/{id}` – street-sorted Excel export
- `GET /api/export/optimized/{id}` – geo-optimized Excel export

## DB Schema
- `upload_jobs`: `{id, filename, status, created_at, progress, total_addresses}`
- `geocoded_addresses_cache`: `{address_key, latitude, longitude, ...}`

## What's Been Implemented

### Data Handling Fixes
- `clean_numeric_string()` – prevents Excel floats (31275.0) from breaking geocoding
- `clean_dataframe_for_excel()` – fixes NaT datetime export errors
- `apply_percentage_formatting()` – preserves % column formatting in exported Excel
- "nr." column detection – re-enabled support for Moormerland format

### Geocoding System (2026-02-04 – MAJOR UPGRADE)
- **Multi-API geocoding** (`geocode_address_with_cache`):
  - API cascade: Photon (Komoot) → LocationIQ → Geoapify → OpenCage → Nominatim
  - Per-API cooldown tracking – if one returns 429, immediately skip to next
  - No more exponential backoff hangs
  - Performance: ~0.7s/address (was: 30+ min for 20 addresses)
- **Job singleton lock** (`_geocoding_job_lock`) – prevents parallel jobs from hammering APIs
- **Startup cleanup** – orphaned "in-progress" jobs are marked as error on server restart

### API Keys Configured
- LocationIQ: 5,000 req/day free
- Geoapify: 3,000 req/day free
- OpenCage: 2,500 req/day free
- Photon (Komoot): unlimited, no key needed

## Prioritized Backlog

### P0 – Complete
- [x] Multi-API geocoding strategy
- [x] Job singleton lock

### P1 – Next
- [ ] Intelligent deduplication: geocode each unique address only once per job
- [ ] Pre-validation: report rows with missing PLZ/street before starting
- [ ] Better progress indicator (show API source, ETA)

### P2 – Future
- [ ] Pause/resume jobs
- [ ] Premium API option (Google Maps)
- [ ] Self-hosted Nominatim
- [ ] Modular architecture (split server.py)
- [ ] User accounts + job history
- [ ] CSV, GPX, KML export formats
