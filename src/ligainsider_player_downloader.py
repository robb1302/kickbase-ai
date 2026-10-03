import re
from pathlib import Path
import requests
import pandas as pd
from bs4 import BeautifulSoup

BASE = "https://www.ligainsider.de"
HEADERS = {"User-Agent": "Mozilla/5.0"}

session = requests.Session()
session.headers.update(HEADERS)

print("[LigaInsider 1/3] Lade Bundesliga-Tabelle und ermittle Vereine ...", flush=True)
table_url = f"{BASE}/bundesliga/tabelle/"
response = session.get(table_url, timeout=30)
response.raise_for_status()
soup = BeautifulSoup(response.text, "html.parser")

teams = []
for a in soup.select('a[href*="/kader/"]'):
    href = a.get("href", "")
    m = re.search(r"/([a-z0-9-]+)/(\d+)/kader/?", href)
    if m:
        teams.append((m.group(1), int(m.group(2))))

teams = list(dict.fromkeys(teams))
if not teams:
    raise RuntimeError(f"Keine Vereine in der LigaInsider-Tabelle gefunden: {table_url}")
print(f"[LigaInsider 1/3] {len(teams)} Vereine gefunden.", flush=True)

# 2. Kaderseiten auslesen
rows = []

for team_number, (slug, team_id) in enumerate(teams, start=1):
    url = f"{BASE}/{slug}/{team_id}/kader/"
    print(
        f"[LigaInsider 2/3] [{team_number}/{len(teams)}] "
        f"Lade Kader {slug} (ID {team_id}) ...",
        flush=True,
    )

    response = session.get(url, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    team_start_count = len(rows)

    for a in soup.select('a[href]'):
        href = a.get("href", "")

        if re.fullmatch(r"/[a-z0-9-]+_\d+/", href):
            img = a.find("img")
            if img is None:
                continue

            name = img.get("title") or img.get("alt")

            rows.append({
                "spieler": name,
                "verein": slug,
                "verein_id": team_id,
                "ligainsider_id": re.search(r"_(\d+)/$", href).group(1),
                "url": BASE + href
            })
    print(
        f"             {len(rows) - team_start_count} Spielerprofile gefunden.",
        flush=True,
    )

raw_count = len(rows)
df = pd.DataFrame(rows).drop_duplicates("url")
duplicate_count = raw_count - len(df)
output_path = Path("data/raw/ligainsider_spielerlinks.csv")
output_path.parent.mkdir(parents=True, exist_ok=True)
print(f"[LigaInsider 3/3] Schreibe CSV: {output_path}", flush=True)
df.to_csv(output_path, index=False, encoding="utf-8-sig", sep=";")

print(
    f"[LigaInsider] Fertig: {len(df)} eindeutige Spielerprofile gespeichert "
    f"({duplicate_count} Duplikate entfernt).",
    flush=True,
)
if not df.empty:
    preview = ", ".join(df["spieler"].head(5).astype(str))
    print(f"             Vorschau: {preview}", flush=True)