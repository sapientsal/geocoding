# PRD – Sales Route Optimizer

## Original Problem Statement
Full-stack Tool für Vertriebs-Routenoptimierung: Excel-Adresslisten hochladen, Adressen geocodieren (Multi-API-Kaskade ohne Rate-Limits), geografisch/straßenbasiert sortieren, "Restpotenzial" berechnen, Ergebnis als Excel exportieren.

## Architektur
- Frontend: React (`/app/frontend/src/App.js`)
- Backend: FastAPI Monolith (`/app/backend/server.py`, ~3900 Zeilen), MongoDB
- Geocoding: Photon (Haupt-API, unlimitiert, sequenziell ~1 req/s) → LocationIQ → Geoapify → OpenCage → Nominatim (Keys in backend/.env)
- Routing: Hierarchischer Nearest-Neighbor (Ortsteil → Straße → Hausnummer), Haversine-Distanzen

## ⚠️ WICHTIGER VORFALL (23./24.07.2026)
Die Umgebung wurde auf den Stand von ~04.03.2026 zurückgesetzt (Rollback). Alle Arbeit von März–Juli ging verloren und wurde am 24.07. NEU IMPLEMENTIERT (siehe unten). Alte DB-Jobs (Haldensleben, Heilbad Heiligenstadt) sind weg.

## 2026-07-24: Wiederaufbau nach Rollback (getestet, E2E verifiziert)
1. **Haldensleben/SDU-Spaltenerkennung** (additiv in allen 6 Erkennungsschleifen):
   - `NUMBER` (exakt) → Hausnummer; `AFFIX` → Zusatz; `MUNICIPALITY` → Ort; `DISTRICT` → Teilort/OT
   - `STREET_NAME` wird über bestehendes 'street'-Keyword erkannt
2. **Hierarchische Sortierung** in `optimize_geographic_route`:
   - Level 1: Straßengruppen nach Ortsteil (teilort_col, Fallback ort_col) bucketen
   - Level 2: OT-Reihenfolge per Nearest-Neighbor ab NÖRDLICHSTEM OT
   - Level 3: Straßen im OT per Nearest-Neighbor ab nördlichster Straße
   - Level 4: Hausnummern numerisch (bestehend)
3. **Bugfix Straßen-Präfix** (alle clean_street_name-Varianten + Geocoding-Adressbau):
   - Erstes Wort wird NUR entfernt, wenn es Ziffern enthält (Projekt-Codes wie "624"), NIE deutsche Wörter ("Vor", "Hinter", "Am", "Alte") → verhindert Vermischen von "Vor dem Dorfe"/"Hinter dem Dorfe"
4. **Bugfix Gruppierungsschlüssel**: `street_city_key` = "Straße, OT, Stadt" wenn OT vorhanden (sonst wie bisher "Straße, Stadt") → gleiche Straßennamen in verschiedenen OTs (Lange Straße in Uthmöden vs. Haldensleben) bleiben getrennt
- Tests: `/app/backend/tests/test_rebuild.py` (4/4 bestanden) + E2E-Upload via API (Format erkannt, 6/6 geocodiert, OT-Reihenfolge korrekt, Export 200)

## Unterstützte Excel-Formate
1. Deutsche Glasfaser/Worpswede: `Projektname Strasse` (mit Code-Präfix "624 Worpswede X"), Hausnummer, PLZ, Ort
2. Standard deutsch: Straße/Strasse, Hausnummer, Zusatz, PLZ, Ort, (Teilort/Ortsteil/Stadtteil/District → OT)
3. Haldensleben SDU: STREET_NAME, NUMBER, NUMBER_AFFIX, PLZ, MUNICIPALITY, DISTRICT
4. Single-Address-Spalte (Fallback)

## Offene Punkte / Backlog
### P0 – Nächste Schritte
- [ ] **Ballenstedt SDU-Format** (Datei liegt vor: STADT, STREET_NAME, NUMBER, NUMBER_AFFIX, ORT, PLZ):
  - `ORT` ist dort der ORTSTEIL, `STADT` die Gemeinde → Erkennungslogik: wenn STADT+ORT beide da, ORT als OT behandeln
  - PLZ 4-stellig (6493) → führende Null auffüllen (06493, Sachsen-Anhalt), sonst Geocoding-Fehler
- [ ] Gebiets-Kennzeichnung im Export (Spalte "Gebiet 1 – Uthmöden" etc.) – User-Diskussion lief, wartet auf Entscheidung:
  - Option: große Kernstädte per Clustering in Tagespakete aufteilen (nach Adressen/WE/Restpotenzial)
  - Option: ein Excel-Tab pro Gebiet
### P1
- [ ] Pre-Geocoding-Deduplizierung (gleiche Adresse nur 1x geocoden)
- [ ] 2-opt Nachoptimierung / OSRM echte Fahrzeiten (Optionen B/C, User unentschieden)
- [ ] Planstraßen-Filter (Platzhalter "Planstr. XXXXX" in separates Tab)
### P2
- [ ] server.py modularisieren, Pause/Resume, Kartenvisualisierung, CSV/GPX/KML-Export, User-Accounts

## Bekannte Datenanomalien
- "Planstr. 1013562 1009" etc. = Platzhalter für geplante Straßen → Geocoding schlägt korrekt fehl, landen am Routenende
- Utility-Skript-Idee: `reoptimize_job.py <job_id>` (Re-Sortierung ohne Re-Geocoding aus DB) – ging beim Rollback verloren, bei Bedarf neu erstellen
