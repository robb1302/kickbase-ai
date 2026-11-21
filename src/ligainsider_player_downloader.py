import re
from pathlib import Path
import time
import requests
import pandas as pd
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from ligainsider_status import reset_status, update_status

BASE = "https://www.ligainsider.de"
HEADERS = {"User-Agent": "Mozilla/5.0"}
OUTPUT_PATH = Path("data/raw/ligainsider_spielerlinks.csv")
CONTENT_ATTEMPTS = 3
MIN_PLAYERS_PER_TEAM = 11


def extract_team_players(html: str, slug: str, team_id: int) -> list[dict]:
    """Extract unique player profiles from a Kader page response."""
    soup = BeautifulSoup(html, "html.parser")
    players = []
    seen_urls = set()

    for anchor in soup.select("a[href]"):
        href = anchor.get("href", "")
        match = re.fullmatch(r"/([a-z0-9-]+)_(\d+)/", href)
        if not match:
            continue

        image = anchor.find("img")
        if image is None:
            continue
        name = (image.get("title") or image.get("alt") or "").strip()
        if not name:
            continue

        profile_url = BASE + href
        if profile_url in seen_urls:
            continue
        seen_urls.add(profile_url)
        players.append({
            "spieler": name,
            "verein": slug,
            "verein_id": team_id,
            "ligainsider_id": match.group(2),
            "url": profile_url,
        })

    return players


def cached_players_for_team(cached: pd.DataFrame, slug: str) -> list[dict]:
    if cached.empty or "verein" not in cached:
        return []
    team_rows = cached.loc[cached["verein"].astype(str) == slug]
    if "url" in team_rows:
        team_rows = team_rows.drop_duplicates("url")
    return team_rows.to_dict("records")


def valid_roster_size(player_count: int, cached_count: int) -> bool:
    minimum = max(MIN_PLAYERS_PER_TEAM, (cached_count + 1) // 2)
    return player_count >= minimum

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

    previous_team_rows = cached_players_for_team(cached, slug)
    cached_count = len(previous_team_rows)
    accepted_players = None
    last_error = None

    for attempt in range(1, CONTENT_ATTEMPTS + 1):
        if attempt > 1:
            time.sleep(2 ** (attempt - 2))
            try:
                response = session.get(url, timeout=(10, 45))
                response.raise_for_status()
            except requests.RequestException as error:
                last_error = f"{type(error).__name__}: {error}"
                break

        candidate_players = extract_team_players(response.text, slug, team_id)
        candidate_count = len(candidate_players)
        if valid_roster_size(candidate_count, cached_count):
            accepted_players = candidate_players
            break

        if candidate_count < MIN_PLAYERS_PER_TEAM:
            last_error = (
                f"nur {candidate_count} Spielerprofile gefunden "
                f"(mindestens {MIN_PLAYERS_PER_TEAM} erwartet)"
            )
        else:
            last_error = (
                f"nur {candidate_count} Spielerprofile gefunden; "
                f"Vorversion enthält {cached_count} "
                "(mindestens die Hälfte erwartet)"
            )
        print(
            f"             Unvollständige Kaderantwort ({last_error}); "
            f"Inhaltsversuch {attempt}/{CONTENT_ATTEMPTS}.",
            flush=True,
        )

    if accepted_players is None:
        failed_teams.append(slug)
        rows.extend(previous_team_rows)
        status = "Vorversion verwendet" if previous_team_rows else "Fehlt"
        update_status(
            team_id, slug, "kader_status", status,
            details=last_error or "Kaderantwort war unvollständig",
        )
        fallback = (
            f"Vorversion übernommen ({cached_count} Spieler)."
            if previous_team_rows else "Kein Cache vorhanden."
        )
        print(f"             Abruf nicht verwendbar ({last_error}). {fallback}", flush=True)
        continue

    rows.extend(accepted_players)
    update_status(team_id, slug, "kader_status", "Aktuell")
    print(f"             {len(accepted_players)} Spielerprofile gefunden.", flush=True)

if not rows:
    raise RuntimeError("Keine Spielerlinks verfügbar; vorherige Ausgabedatei bleibt erhalten.")

raw_count = len(rows)
df = pd.DataFrame(rows).drop_duplicates("url")
duplicate_count = raw_count - len(df)
OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
print(f"[LigaInsider 3/3] Schreibe CSV: {OUTPUT_PATH}", flush=True)
temporary_output = OUTPUT_PATH.with_suffix(OUTPUT_PATH.suffix + ".tmp")
df.to_csv(temporary_output, index=False, encoding="utf-8-sig", sep=";")
temporary_output.replace(OUTPUT_PATH)

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
