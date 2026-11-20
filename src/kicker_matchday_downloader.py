"""Download the current Bundesliga matchday starting lineups from kicker.de."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import re
import time
from urllib.parse import urljoin, urlparse

import pandas as pd
from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright


BASE = "https://www.kicker.de"
OUTPUT = Path("data/matchday/kicker_startelf.csv")
SCHEDULE_URL = "https://www.kicker.de/bundesliga/spieltag/{season}"
FIXTURE_PATH = re.compile(r"^/([^?#]+?-\d{4}-bundesliga-\d+)(?:/[^?#]*)?/?$")
PLAYER_PATH = re.compile(r"/(?:spieler|profil)/", re.IGNORECASE)


def current_season(today: date | None = None) -> str:
    today = today or date.today()
    first_year = today.year if today.month >= 7 else today.year - 1
    return f"{first_year}-{str(first_year + 1)[-2:]}"


def fixture_urls(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    urls = []
    for anchor in soup.select("a[href]"):
        href = anchor["href"].strip()
        match = FIXTURE_PATH.fullmatch(urlparse(href).path)
        if not match:
            continue
        base_path = "/" + match.group(1)
        if base_path not in urls:
            urls.append(base_path)
    return [urljoin(BASE, path + "/aufstellung") for path in urls]


def lineup_players(html: str, fixture_url: str) -> list[dict[str, str]]:
    """Extract both starting elevens, failing closed unless 22 are identifiable."""
    soup = BeautifulSoup(html, "html.parser")
    selectors = (
        "[data-testid*='lineup']", "[data-testid*='aufstellung']",
        "[class*='lineup']", "[class*='Lineup']",
        "[class*='aufstellung']", "[class*='Aufstellung']",
    )
    candidates = []
    seen_candidates = set()
    for selector in selectors:
        for node in soup.select(selector):
            key = id(node)
            if key not in seen_candidates:
                seen_candidates.add(key)
                candidates.append(node)

    # Kicker's markup has changed over time. Collect lineup regions containing
    # exactly 11 distinct player links (one team) or 22 (both teams).
    groups = []
    for node in sorted(candidates, key=lambda item: len(item.select("*"))):
        players = []
        seen = set()
        for anchor in node.select("a[href]"):
            href = anchor.get("href", "")
            name = anchor.get_text(" ", strip=True)
            if not name or not PLAYER_PATH.search(urlparse(href).path):
                continue
            key = re.sub(r"\s+", " ", name).casefold()
            if key not in seen:
                seen.add(key)
                players.append({"spieler": name, "profil_URL": urljoin(BASE, href)})
        if len(players) in {11, 22}:
            groups.append(players)

    merged = []
    seen_players = set()
    seen_groups = set()
    for group in groups:
        group_key = frozenset(player["spieler"].casefold() for player in group)
        if group_key in seen_groups:
            continue
        seen_groups.add(group_key)
        for player in group:
            key = player["spieler"].casefold()
            if key not in seen_players:
                seen_players.add(key)
                merged.append(player)
        if len(merged) == 22:
            return merged

    raise ValueError(f"Keine vollständigen 22 Startelfspieler gefunden: {fixture_url}")


def main() -> None:
    season = current_season()
    schedule_url = SCHEDULE_URL.format(season=season)
    print(f"[Kicker Startelf 1/3] Ermittle aktuellen Spieltag: {season}", flush=True)

    rows: list[dict[str, str]] = []
    failures: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(locale="de-DE", viewport={"width": 1500, "height": 1100})
        page = context.new_page()
        page.goto(schedule_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1500)
        fixtures = fixture_urls(page.content())
        if not fixtures:
            browser.close()
            raise RuntimeError(f"Keine Bundesliga-Partien im Kicker-Spielplan gefunden: {schedule_url}")
        print(f"[Kicker Startelf 1/3] {len(fixtures)} Partien im Spielplan gefunden.", flush=True)

        for number, fixture_url in enumerate(fixtures, start=1):
            print(f"[Kicker Startelf 2/3] [{number}/{len(fixtures)}] Lade {fixture_url} ...", flush=True)
            try:
                try:
                    page.goto(fixture_url, wait_until="domcontentloaded", timeout=45000)
                except PlaywrightTimeoutError:
                    # A page can remain usable while a third-party resource stalls.
                    if page.url != fixture_url:
                        raise
                page.wait_for_timeout(1200)
                players = lineup_players(page.content(), fixture_url)
                for player in players:
                    rows.append({
                        "spieler": player["spieler"],
                        "profil_URL": player["profil_URL"],
                        "spiel_URL": fixture_url,
                    })
                print(f"             {len(players)} Startelfspieler gefunden.", flush=True)
            except Exception as error:
                failures.append(f"{fixture_url}: {error}")
                print(f"             Übersprungen: {error}", flush=True)
            time.sleep(0.5)
        browser.close()

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=["spieler", "profil_URL", "spiel_URL"]).drop_duplicates(
        ["spieler", "spiel_URL"]
    ).to_csv(OUTPUT, sep=";", index=False, encoding="utf-8-sig")
    print(f"[Kicker Startelf 3/3] {len(rows)} Spieler gespeichert: {OUTPUT}", flush=True)
    if failures:
        print(f"[Kicker Startelf] {len(failures)} Partien ohne Aufstellung:", flush=True)
        for failure in failures:
            print(f"  - {failure}", flush=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
