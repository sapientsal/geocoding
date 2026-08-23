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
- **Testing-Agent-Verifikation (iteration_1.json): 100% pass** – zusätzlich `/app/backend/tests/test_e2e_upload.py` erstellt

## 2026-07-26: Ballenstedt-Liste erfolgreich verarbeitet (OHNE Code-Änderung)
- Job e3dbe9db: 2661/2682 geocodiert (99,2%), 6 OT-Blöcke (Asmusstedt→Radisleben→Ballenstedt→Opperode→Rieder→Badeborn), Start nördlichster OT
- Erkenntnisse: `ORT`-Spalte (Dorf) gewinnt in Erkennungsschleife über `STADT` (letzter Treffer) → Geocoding + OT-Gruppierung funktionieren nativ; Photon toleriert 4-stellige PLZ (6493→06493)
- 21 Fehler = "o.N."-Platzhalter (ohne Nummer) + exotische HNr ("901 W") → landen by design am Routenende
- P0 "Ballenstedt-Format ergänzen" damit ERLEDIGT (keine Änderung nötig)

## 2026-07-26: BUGFIX Geocoding-Ausreißer (Testing-Agent verifiziert, 12/12 pass)
- User-Bug: distance_to_next mit 256.000+ m mitten in derselben Straße (Schimmelgasse Opperode) – Photon matchte einzelne Hausnummern quer durch Deutschland (z.B. "Schimmelgasse 64, 06493" → "Schiemesgasse, 64832 Langstadt", 256 km; 86 Ausreißer in der Ballenstedt-Liste, max 6.456 km!)
- Fix Layer 1: PLZ-Plausibilitätsprüfung in `geocode_address_with_cache` – erwartete PLZ aus Query (Regex nach Komma), Photon liefert jetzt `postcode`; Abgleich erste 2 Ziffern (zfill 5) → Mismatch = Treffer verwerfen, nächste API
- Fix Layer 2: Ausreißer-Korrektur in `optimize_geographic_route` (nach Straßensortierung) – Adresse >2 km vom Straßen-Median (Gruppe ≥3) oder >30 km vom Global-Median → auf Straßen-Median gesnappt, geocoding_error='Koordinate korrigiert: ...'
- Bestehender Ballenstedt-Job via `reoptimize_job.py` geheilt: 86 korrigiert, max Sprung jetzt 8,4 km, Gesamtdistanz 208,5 km
- Neue Tests: `/app/backend/tests/test_geocoding_fixes.py` (Outlier-Unit, PLZ-Live, Job-Heilung)
- Bekannte Grenzen (Review-Hinweise): PLZ-Check nur 2-stellig-Präfix; Median-Snapping versagt, falls Mehrheit einer Straße falsch läge (bisher nie beobachtet)

## 2026-08-02: BUGFIX Wolfsburg-Format `HSNR` nicht erkannt (Testing-Agent: 100% pass)
- User-Bug: "0 Adressen" + "Hausnummer: Nicht erkannt" bei Wolfsburg_Neuland (Spalten STRASSE, HSNR, HSNR_ZUSATZ, PLZ, ORT + WH1-25 Status-Spalten)
- Root Cause: exakte Hausnummer-Tokens ('nummer','nr','nr.','hnr','number') enthielten 'hsnr' nicht → Fallback Single-Address-Column → 0 Adressen
- Fix: 'hsnr' + 'hausnr' in alle 6 Erkennungsschleifen (replace_all); HSNR_ZUSATZ mappt weiterhin korrekt auf zusatz
- Verifiziert: Preview (222 Adressen erkannt), E2E-Upload inkl. Status-Spalten-Erhalt im Export, alle Regressions-Suites grün (test_hsnr_detection.py neu)
- OFFEN: User-Entscheidung Trennzeilen-Handling (Option A Sektions-Erkennung / B eine Route / C manuell splitten) – User hat Trennzeilen manuell entfernt, Datei jetzt direkt verarbeitbar

## 2026-08-16: Straßenmitte-Fallback-Interpolation (Testing-Agent iteration_4+5: 100% pass)
- User-Bug: große distance_to_next_m-Sprünge INNERHALB derselben Straße (Kitzscher: Landstraße Thierbach 29b→29 = 776 m Ping-Pong)
- Root Cause: Photon liefert für unbekannte Hausnummern die Straßenmitte → mehrere verschiedene Hausnummern teilen sich exakt eine Koordinate weit weg von den echten Häusern
- Fix: Interpolations-Block in `optimize_geographic_route` (nach Ausreißer-Korrektur): Koordinaten, die von ≥2 VERSCHIEDENEN house_number_numeric geteilt werden = Fallback → betroffene Zeilen auf Mittelwert der nächsten vertrauenswürdigen Hausnummern-Nachbarn gesetzt, geocoding_error='Koordinate interpoliert: nur Straßenmitte gefunden'. Gleiche-Hausnummer-Duplikate (Mehrfamilienhäuser) bleiben unberührt. Guard: bereits 'Koordinate korrigiert'-Zeilen gelten als vertrauenswürdig und werden nie re-interpoliert
- Kitzscher-Job (990ecb84) geheilt: 7 interpoliert, 776m-Phantomsprung weg, verbleibende >400m-Sprünge = echte lange Dorfstraßen
- Neue Tests: tests/test_street_center_interpolation.py; Gesamtsuite 14/14 + rebuild grün

## 2026-08-17: BUGFIX numpy-Bool BSON-Crash (Testing-Agent iteration_6+7: 20/20 pass)
- User-Bug: Regis-Breitingen-Job crashte nach Geocoding beim Speichern: "cannot encode object: np.True_"
- RCA (Testing-Agent): Wenn ≥1 Geocode fehlschlägt, werden lat/lon-Spalten object-dtype → row.get() liefert rohe numpy-Skalare → `is_geocoded = (...)`-Vergleich ergibt np.bool_ → pymongo kann nicht encoden
- Fix: (1) `is_geocoded = bool(...)`, (2) rekursiver Helper `to_bson_safe()` (np.generic→.item(), ndarray→tolist) an ALLEN 3 routes_collection.insert_one-Stellen, (3) np.generic-Branch in row_dict-Loops
- Regis-Breitingen erfolgreich neu verarbeitet (Job 0cc914d1): 665/671 geocodiert, 6 saubere OT-Blöcke (Regis→Regis-Stadt→Breitingen→Wildenhain→Ramsdorf→Hagenest), max Sprung 3,1 km, 16 interpoliert, 2 Ausreißer korrigiert, PLZ-Guard verwarf 24 Falsch-Treffer
- Neue Tests: test_numpy_bool_rca.py, test_numpy_bool_storage.py, test_numpy_storage_unit.py, test_e2e_numpy_bool_upload.py
- Optionale Härtung (Testing-Agent-Hinweis, offen): to_bson_safe auch für addresses_collection.insert_many (Legacy-Pfad, Zeile ~2092); HTTPException-Re-Raise in /api/optimized-Handlern (404 statt 500)

## 2026-08-23: Auto-Resume + persistenter Geocoding-Cache + PLZ-Nullen (Testing-Agent it. 8+9: 100% pass)
- User-Bug: Schwanebeck-Job (892 Adr.) "hing" bei ~310 – Umgebung ging in Schlafmodus, Neustart killte den Job, aller Fortschritt weg
- Fix 1 AUTO-RESUME: Upload-Datei wird als BSON Binary im Job-Doc gespeichert (<14MB); Startup-Handler setzt unterbrochene Jobs (mit file_data) automatisch fort statt auf error
- Fix 2 PERSISTENTER CACHE: Mongo-Collection `geocode_cache` ({_id: adresse, result}); Cache-Hits überspringen APIs UND das 0.1s-Delay → Resume spult bereits erledigte Adressen in Sekunden durch. Fehlschläge werden bewusst NICHT persistiert
- Fix 3 PLZ-NULLEN (kritisch!): pandas las PLZ als int64 → 06493 wurde "6493" → Geocoding bis 4,5 km daneben. Neuer Helper `normalize_plz()` (zfill(5) bei 3-4-stelligen Ziffern) an allen 4 Adressbau-Stellen. Alle 0er-PLZ-Regionen (Sachsen/Sachsen-Anhalt/Thüringen!) betroffen gewesen
- Weitere Fixes: /api/cache/stats 500 (entry['lat']→get('latitude')), /api/jobs gehärtet (.get defaults), Progress-Flush alle 5 statt 10, /api/health-Endpoint repariert (Decorator fehlte), toter Legacy-Helper geocode_address_cached gelöscht
- Schwanebeck-Job selbst hatte kein file_data (vor Fix hochgeladen) → USER MUSS 1x NEU HOCHLADEN, danach greift alles automatisch
- Neue Tests: test_auto_resume_persistence.py (Hard-Kill-Szenario!), test_plz_zeropad_e2e.py
- Offen (P2, kosmetisch): FastAPI on_event→lifespan-Migration, TTL für geocode_cache, 16 verwaiste routes-Docs, Fehlschläge mit Versuchszähler persistieren

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
- [ ] **Format-erhaltender Export** (User: "eventuell zukünftig", 02.08.26 zurückgestellt): Original-Workbook als Vorlage, Zeilen umsortieren statt neu schreiben → erhält Dropdowns (VP-/Status-Listen K:L, WH-Spalten), lebende Formeln (Restpoti `=X-COUNTIF(Nx:BJx,"Abschluss")` mit Zeilen-Translation) und Zellformatierung. Analyse liegt vor (Wolfsburg_Neuland).
- [ ] Pre-Geocoding-Deduplizierung (gleiche Adresse nur 1x geocoden)
- [ ] 2-opt Nachoptimierung / OSRM echte Fahrzeiten (Optionen B/C, User unentschieden)
- [ ] Planstraßen-Filter (Platzhalter "Planstr. XXXXX" in separates Tab)
### P2
- [ ] server.py modularisieren, Pause/Resume, Kartenvisualisierung, CSV/GPX/KML-Export, User-Accounts

## Bekannte Datenanomalien
- "Planstr. 1013562 1009" etc. = Platzhalter für geplante Straßen → Geocoding schlägt korrekt fehl, landen am Routenende
- Utility-Skript-Idee: `reoptimize_job.py <job_id>` (Re-Sortierung ohne Re-Geocoding aus DB) – ging beim Rollback verloren, bei Bedarf neu erstellen
