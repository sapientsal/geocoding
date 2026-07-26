import sys
sys.path.insert(0, '/app/backend')
from dotenv import load_dotenv
load_dotenv('/app/backend/.env')
import pandas as pd
import server

ok = True

# --- Test 1: Haldensleben-Format (STREET_NAME, NUMBER, NUMBER_AFFIX, MUNICIPALITY, DISTRICT) ---
df1 = pd.DataFrame({
    'U_ASSIGNED_ISP': ['O2']*8,
    'STREET_NAME': ['Lange Straße','Lange Straße','Lange Straße','Lange Straße','Kurze Straße','Kurze Straße','Bahnhofstraße','Bahnhofstraße'],
    'NUMBER': [1, 2, 1, 2, 5, 3, 7, 9],
    'NUMBER_AFFIX': [None,'A',None,None,None,None,None,'B'],
    'DISTRICT': ['Uthmöden','Uthmöden','Haldensleben','Haldensleben','Uthmöden','Uthmöden','Haldensleben','Haldensleben'],
    'PLZ': [39345]*2+[39340]*2+[39345]*2+[39340]*2,
    'MUNICIPALITY': ['Haldensleben']*8,
})
# Uthmöden liegt nördlich von Haldensleben-Kernstadt
coords = {
    ('Lange Straße','Uthmöden'): (52.351, 11.357),
    ('Kurze Straße','Uthmöden'): (52.353, 11.359),
    ('Lange Straße','Haldensleben'): (52.289, 11.412),
    ('Bahnhofstraße','Haldensleben'): (52.287, 11.410),
}
geocoded1 = []
for _, r in df1.iterrows():
    lat, lon = coords[(r['STREET_NAME'], r['DISTRICT'])]
    geocoded1.append({'latitude': lat, 'longitude': lon, 'formatted_address': f"{r['STREET_NAME']}", 'geocoded': True, 'error': ''})
addr1 = [f"{r['STREET_NAME']} {r['NUMBER']}, {r['PLZ']} {r['DISTRICT']}" for _, r in df1.iterrows()]

opt1, dist1 = server.optimize_geographic_route(df1, geocoded1, addr1)
seq = list(zip(opt1['DISTRICT'], opt1['STREET_NAME'], opt1['NUMBER']))
print('\nTest 1 – Haldensleben-Format, Ergebnis-Reihenfolge:')
for s in seq: print('  ', s)
# Check: keine OT-Fragmentierung
segs, prev = 0, None
for d, _, _ in seq:
    if d != prev: segs += 1; prev = d
assert segs == 2, f'FEHLER: {segs} OT-Segmente statt 2'
# Check: Start im nördlichsten OT (Uthmöden)
assert seq[0][0] == 'Uthmöden', f'FEHLER: Start-OT ist {seq[0][0]}'
# Check: Lange Straße getrennt nach OT
print('✅ Test 1: 2 OT-Segmente, Start Uthmöden (nördlichster), Straßen nach OT getrennt')

# --- Test 2: Vor/Hinter dem Dorfe dürfen NICHT vermischt werden ---
df2 = pd.DataFrame({
    'Straße': ['Hinter dem Dorfe','Hinter dem Dorfe','Vor dem Dorfe','Vor dem Dorfe'],
    'Hausnummer': [1, 3, 2, 4],
    'PLZ': [37308]*4,
    'Ort': ['Heilbad Heiligenstadt']*4,
    'OT': ['Rengelrode','Rengelrode','Kalteneber','Kalteneber'],
})
geocoded2 = [
    {'latitude': 51.380, 'longitude': 10.091, 'formatted_address': 'x', 'geocoded': True, 'error': ''},
    {'latitude': 51.380, 'longitude': 10.092, 'formatted_address': 'x', 'geocoded': True, 'error': ''},
    {'latitude': 51.322, 'longitude': 10.139, 'formatted_address': 'x', 'geocoded': True, 'error': ''},
    {'latitude': 51.322, 'longitude': 10.140, 'formatted_address': 'x', 'geocoded': True, 'error': ''},
]
addr2 = ['a','b','c','d']
opt2, _ = server.optimize_geographic_route(df2, geocoded2, addr2)
seq2 = list(zip(opt2['Straße'], opt2['Hausnummer']))
print('\nTest 2 – Reihenfolge:', seq2)
streets_order = [s for s, _ in seq2]
# beide Straßen müssen zusammenhängend sein
changes = sum(1 for i in range(1, len(streets_order)) if streets_order[i] != streets_order[i-1])
assert changes == 1, f'FEHLER: Straßen vermischt ({changes} Wechsel)'
print('✅ Test 2: Vor/Hinter dem Dorfe bleiben getrennt')

# --- Test 3: Legacy-Format (Deutsche Glasfaser Stil, kein OT) ---
df3 = pd.DataFrame({
    'Projektname Strasse': ['624 Worpswede Hauptstraße','624 Worpswede Hauptstraße','624 Worpswede Findorffstraße'],
    'Hausnummer': [2, 1, 5],
    'PLZ': [27726]*3,
    'Ort': ['Worpswede']*3,
})
geocoded3 = [{'latitude': 53.22, 'longitude': 8.92, 'formatted_address': 'x', 'geocoded': True, 'error': ''}]*3
opt3, _ = server.optimize_geographic_route(df3, geocoded3, ['a','b','c'])
print('\nTest 3 – street_clean:', list(opt3['street_clean'].unique()))
assert 'Hauptstraße' in list(opt3['street_clean'].unique()), 'FEHLER: Projekt-Präfix nicht entfernt'
hn = list(opt3[opt3['street_clean']=='Hauptstraße']['Hausnummer'])
assert hn == [1, 2], f'FEHLER: Hausnummern nicht sortiert: {hn}'
print('✅ Test 3: Legacy Worpswede-Format funktioniert weiter (Präfix entfernt, sortiert)')

# --- Test 4: Spaltenerkennung isoliert (Haldensleben) ---
street_col = house_num_col = zusatz_col = plz_col = ort_col = teilort_col = None
for col in df1.columns:
    col_lower = col.lower().strip()
    if any(k in col_lower for k in ['projektname strasse', 'strasse', 'straße', 'street']):
        street_col = col
    elif any(k in col_lower for k in ['hausnummer', 'haus nummer', 'haus-nummer']) or (col_lower in ('nummer','nr','nr.','hnr','number')):
        house_num_col = col
    elif any(k in col_lower for k in ['zusatz', 'zusätze', 'affix']):
        zusatz_col = col
    elif any(k in col_lower for k in ['plz', 'postleitzahl', 'postal']):
        plz_col = col
    elif any(k in col_lower for k in ['ort', 'stadt', 'city', 'location', 'municipality']) and 'teil' not in col_lower:
        ort_col = col
    elif any(k in col_lower for k in ['teilort', 'stadtteil', 'ortsteil', 'district']):
        teilort_col = col
print(f'\nTest 4 – Erkennung: street={street_col}, hnr={house_num_col}, zusatz={zusatz_col}, plz={plz_col}, ort={ort_col}, ot={teilort_col}')
assert street_col == 'STREET_NAME' and house_num_col == 'NUMBER' and zusatz_col == 'NUMBER_AFFIX'
assert plz_col == 'PLZ' and ort_col == 'MUNICIPALITY' and teilort_col == 'DISTRICT'
print('✅ Test 4: Haldensleben-Spalten korrekt erkannt')

print('\n🎉 ALLE TESTS BESTANDEN' if ok else 'FEHLER')
