import re
from pathlib import Path
import requests
import pandas as pd
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from ligainsider_status import reset_status, update_status

BASE = "https://www.ligainsider.de"
HEADERS = {"User-Agent": "Mozilla/5.0"}
OUTPUT_PATH = Path("data/raw/ligainsider_spielerlinks.csv")

session = requests.Session()
session.headers.update(HEADERS)
retry = Retry(
    total=4,
    connect=4,
    read=4,
    status=4,
    backoff_factor=1,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=("GET",),
    respect_retry_after_header=True,
)
session.mount("https://", HTTPAdapter(max_retries=retry))

print("[LigaInsider 1/3] Lade Bundesliga-Tabelle und ermittle Vereine ...", flush=True)
table_url = f"{BASE}/bundesliga/tabelle/"
response = session.get(table_url, timeout=(10, 45))
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
reset_status([(team_id, slug, None) for slug, team_id in teams], "kader_status")

# 2. Kaderseiten auslesen
rows = []
failed_teams = []
cached = (
    pd.read_csv(OUTPUT_PATH, sep=";", encoding="utf-8-sig")
    if OUTPUT_PATH.exists()
    else pd.DataFrame()
)

for team_number, (slug, team_id) in enumerate(teams, start=1):
    url = f"{BASE}/{slug}/{team_id}/kader/"
    print(
        f"[LigaInsider 2/3] [{team_number}/{len(teams)}] "
        f"Lade Kader {slug} (ID {team_id}) ...",
        flush=True,
    )

    try:
        response = session.get(url, timeout=(10, 45))
        response.raise_for_status()
    except requests.RequestException as error:
        failed_teams.append(slug)
        previous_team_rows = (
            cached.loc[cached["verein"].astype(str) == slug].to_dict("records")
            if not cached.empty and "verein" in cached
            else []
        )
        rows.extend(previous_team_rows)
        update_status(
            team_id,
            slug,
            "kader_status",
            "Vorversion verwendet" if previous_team_rows else "Fehlt",
            details=type(error).__name__,
        )
        fallback = f"Vorherige Daten übernommen ({len(previous_team_rows)} Spieler)." if previous_team_rows else "Kein Cache vorhanden."
        print(f"             Abruf fehlgeschlagen: {error}. {fallback}", flush=True)
        continue

    soup = BeautifulSoup(response.text, "html.parser")
    update_status(team_id, slug, "kader_status", "Aktuell")
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

if not rows:
    raise RuntimeError("Keine Spielerlinks verfügbar; vorherige Ausgabedatei bleibt erhalten.")

raw_count = len(rows)
df = pd.DataFrame(rows).drop_duplicates("url")
duplicate_count = raw_count - len(df)
OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
print(f"[LigaInsider 3/3] Schreibe CSV: {OUTPUT_PATH}", flush=True)
df.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig", sep=";")

print(
    f"[LigaInsider] Fertig: {len(df)} eindeutige Spielerprofile gespeichert "
    f"({duplicate_count} Duplikate entfernt).",
    flush=True,
)
if failed_teams:
    print(f"             Fehlgeschlagene Kaderabrufe: {', '.join(failed_teams)}", flush=True)
if not df.empty:
    preview = ", ".join(df["spieler"].head(5).astype(str))
    print(f"             Vorschau: {preview}", flush=True)
if failed_teams:
    raise SystemExit(1)
