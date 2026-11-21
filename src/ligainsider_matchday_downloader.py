from pathlib import Path
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright
from bs4 import BeautifulSoup
import pandas as pd
import re
import time
from ligainsider_status import reset_status, update_status

CONTENT_ATTEMPTS = 5
OUTPUT_PATH = Path("data/matchday/bundesliga_startelf.csv")

TEAMS = {
    "Bayern München":      "https://www.ligainsider.de/bundesliga/team/fc-bayern-muenchen/1/",
    "Borussia Dortmund":   "https://www.ligainsider.de/bundesliga/team/borussia-dortmund/14/",
    "RB Leipzig":          "https://www.ligainsider.de/bundesliga/team/rb-leipzig/1311/",
    "Bayer Leverkusen":    "https://www.ligainsider.de/bundesliga/team/bayer-04-leverkusen/4/",
    "VfB Stuttgart":       "https://www.ligainsider.de/bundesliga/team/vfb-stuttgart/12/",
    "TSG Hoffenheim":      "https://www.ligainsider.de/bundesliga/team/tsg-hoffenheim/10/",
    "Mainz 05":           "https://www.ligainsider.de/bundesliga/team/1-fsv-mainz-05/17/",
    "Gladbach":           "https://www.ligainsider.de/bundesliga/team/borussia-moenchengladbach/5/",
    "1. FC Köln":         "https://www.ligainsider.de/bundesliga/team/1-fc-koeln/15/",
    "SC Freiburg":        "https://www.ligainsider.de/bundesliga/team/sc-freiburg/18/",
    "FC Augsburg":        "https://www.ligainsider.de/bundesliga/team/fc-augsburg/21/",
    "Union Berlin":       "https://www.ligainsider.de/bundesliga/team/1-fc-union-berlin/1246/",
    "Eintracht Frankfurt":"https://www.ligainsider.de/bundesliga/team/eintracht-frankfurt/3/",
    "Hamburger SV":       "https://www.ligainsider.de/bundesliga/team/hamburger-sv/9/",
    "Werder Bremen":      "https://www.ligainsider.de/bundesliga/team/sv-werder-bremen/2/",

    "SC Paderborn":      "https://www.ligainsider.de/bundesliga/team/sc-paderborn-07/1249/",
    "SV Elversberg":      "https://www.ligainsider.de/bundesliga/team/sv-07-elversberg/1331//",
    "FC Schalke":      "https://www.ligainsider.de/bundesliga/team/fc-schalke-04/13/",


}
Path("html").mkdir(exist_ok=True)


def team_html_path(team: str) -> Path:
    filename = team.lower().replace(" ", "_").replace(".", "") + ".html"
    return Path("html") / filename


def parse_lineup(html: str, team: str) -> list[dict]:
    """Parse one team's projected starting XI from LigaInsider HTML."""
    soup = BeautifulSoup(html, "html.parser")
    seen = set()
    players = []
    position_columns = soup.select(".stadium_container_bg .player_position_column")

    for column in position_columns:
        player_link = column.select_one(
            '.sub_child[style*="display: block"] .player_name a[href]'
        )
        if player_link is None:
            player_link = next(
                (
                    link
                    for link in column.select(".player_name a[href]")
                    if link.find_parent(class_="sub_child") is None
                ),
                None,
            )
        if player_link is None:
            continue

        href = player_link.get("href", "")
        match = re.fullmatch(r"/([a-z0-9-]+)_(\d+)/?", href)
        if not match:
            continue

        slug, player_id = match.groups()
        if player_id in seen:
            continue
        seen.add(player_id)
        players.append({
            "verein": team,
            "position": len(players) + 1,
            "spieler": " ".join(part.capitalize() for part in slug.split("-")),
            "slug": slug,
            "spieler_ID": int(player_id),
            "profil_URL": f"https://www.ligainsider.de{href}",
        })

    return players


def valid_lineup(players: list[dict]) -> bool:
    return len(players) == 11 and len({player["spieler_ID"] for player in players}) == 11


def cached_csv_lineup(cached: pd.DataFrame, team: str) -> list[dict] | None:
    if cached.empty or "verein" not in cached:
        return None
    rows = cached.loc[cached["verein"].astype(str) == team].copy()
    if rows.empty:
        return None
    key = "spieler_ID" if "spieler_ID" in rows else "spieler"
    rows = rows.drop_duplicates(key)
    if len(rows) != 11:
        return None
    return rows.to_dict("records")


def cached_html_lineup(path: Path, team: str) -> list[dict] | None:
    if not path.exists():
        return None
    try:
        players = parse_lineup(path.read_text(encoding="utf-8"), team)
    except (OSError, UnicodeError):
        return None
    return players if valid_lineup(players) else None

all_players = []
failed_teams = []
cached_startelf = (
    pd.read_csv(OUTPUT_PATH, sep=";", encoding="utf-8-sig")
    if OUTPUT_PATH.exists()
    else pd.DataFrame()
)
team_count = len(TEAMS)
status_teams = []
for team, url in TEAMS.items():
    team_id = re.search(r"/(\d+)/+?$", url).group(1)
    filename = team.lower().replace(" ", "_").replace(".", "") + ".html"
    status_teams.append((team_id, team, filename))
reset_status(status_teams, "startelf_status")

print(
    f"[LigaInsider Startelf 1/3] Starte Chromium für {team_count} Vereine ...",
    flush=True,
)
with sync_playwright() as p:

    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width":1600,"height":1200},
        locale="de-DE"
    )

    page = context.new_page()

    cookie_done = False

    for team_number, (team, url) in enumerate(TEAMS.items(), start=1):
        team_id = re.search(r"/(\d+)/+?$", url).group(1)

        print(
            f"[LigaInsider Startelf 2/3] [{team_number}/{team_count}] "
            f"Lade Aufstellung: {team} ...",
            flush=True,
        )

        path = team_html_path(team)
        players = None
        valid_html = None
        last_error = None

        for attempt in range(1, CONTENT_ATTEMPTS + 1):
            try:
                page.goto(url, wait_until="commit", timeout=60000)
            except Exception as error:
                last_error = f"{type(error).__name__}: {error}"
                print(f"             Laden fehlgeschlagen (Versuch {attempt}/{CONTENT_ATTEMPTS}): {error}", flush=True)
                if attempt < CONTENT_ATTEMPTS:
                    page.wait_for_timeout(min(2 ** (attempt - 1), 8) * 1000)
                continue

            if f"/{url.rstrip('/').split('/')[-2]}/{team_id}/" not in page.url:
                last_error = f"Unerwartete Zielseite geladen: {page.url}"
                print(f"             {last_error}", flush=True)
                if attempt < CONTENT_ATTEMPTS:
                    page.wait_for_timeout(min(2 ** (attempt - 1), 8) * 1000)
                continue

            try:
                page.wait_for_load_state("domcontentloaded", timeout=10000)
            except PlaywrightTimeoutError:
                print(
                    "             DOM-Ladevorgang dauert an; pruefe den aktuellen Seitenstand.",
                    flush=True,
                )

            if not cookie_done:
                try:
                    page.frame_locator("iframe[title='Privacy Manager']")\
                        .get_by_role("button", name="ZUSTIMMEN")\
                        .click(timeout=10000)
                    cookie_done = True
                    print("             Cookie-Abfrage bestaetigt.", flush=True)
                    page.wait_for_timeout(2000)
                except Exception:
                    pass

            page.wait_for_timeout(4000)
            html = page.evaluate("() => document.documentElement.outerHTML")
            candidate_players = parse_lineup(html, team)
            if valid_lineup(candidate_players):
                players = candidate_players
                valid_html = html
                break

            last_error = f"{len(candidate_players)} statt 11 eindeutiger Spieler erkannt"
            print(
                f"             Unvollstaendige Startelf: {last_error} "
                f"(Versuch {attempt}/{CONTENT_ATTEMPTS}).",
                flush=True,
            )
            if attempt < CONTENT_ATTEMPTS:
                page.wait_for_timeout(min(2 ** (attempt - 1), 8) * 1000)

        if players is not None:
            # Keep only a known-good HTML snapshot for future fallback runs.
            path.write_text(valid_html, encoding="utf-8")
            update_status(team_id, team, "startelf_status", "Aktuell", html_file=path.name)
            all_players.extend(players)
            preview = ", ".join(player["spieler"] for player in players[:5])
            print(f"             11 Spieler: {preview} ...", flush=True)
        else:
            cached_players = cached_csv_lineup(cached_startelf, team)
            fallback_source = "CSV-Vorversion"
            if cached_players is None:
                cached_players = cached_html_lineup(path, team)
                fallback_source = "HTML-Vorversion"

            if cached_players is not None:
                all_players.extend(cached_players)
                update_status(
                    team_id, team, "startelf_status", "Vorversion verwendet",
                    html_file=path.name, details=last_error or "Aktueller Abruf unvollstaendig",
                )
                failed_teams.append(team)
                print(
                    f"             {last_error}; {fallback_source} mit 11 Spielern verwendet.",
                    flush=True,
                )
            else:
                update_status(
                    team_id, team, "startelf_status", "Fehlt",
                    html_file=path.name, details=last_error or "Keine gueltige Startelf gefunden",
                )
                failed_teams.append(team)
                print(f"             {last_error}; keine g?ltige Vorversion vorhanden.", flush=True)

        time.sleep(1)

    browser.close()

df = pd.DataFrame(
    all_players,
    columns=["verein", "position", "spieler", "slug", "spieler_ID", "profil_URL"],
)

if not all_players:
    raise RuntimeError(
        "Keine gueltigen Startelfdaten verfuegbar; vorhandene Ausgabedatei bleibt erhalten."
    )

OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
temporary_output = OUTPUT_PATH.with_suffix(OUTPUT_PATH.suffix + ".tmp")
print(f"[LigaInsider Startelf 3/3] Schreibe CSV: {OUTPUT_PATH}", flush=True)
df.to_csv(temporary_output, index=False, encoding="utf-8-sig", sep=";")
temporary_output.replace(OUTPUT_PATH)

print(
    f"[LigaInsider Startelf] Fertig: {len(df)} Spieler aus "
    f"{team_count} Vereinen gespeichert.",
    flush=True,
)
if failed_teams:
    print(f"[LigaInsider Startelf] Unvollständig: {', '.join(failed_teams)}", flush=True)
    raise SystemExit(1)
