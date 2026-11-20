"""Download the current Bundesliga matchday starting lineups from kicker.de."""

from __future__ import annotations

from pathlib import Path
import re
import time
from urllib.parse import urljoin, urlparse

import pandas as pd
from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright


BASE = "https://www.kicker.de"
OUTPUT = Path("data/matchday/kicker_startelf.csv")
SCHEDULE_URL = "https://www.kicker.de/bundesliga/spieltag"
FIXTURE_PATH = re.compile(r"^/([^?#]+?-\d{4}-bundesliga-\d+)(?:/[^?#]*)?/?$")
PLAYER_PATH = re.compile(r"/(?:spieler|profil)/", re.IGNORECASE)


def fixture_links(html: str) -> list[tuple[str, str, str]]:
    """Return unique fixture IDs, paths and preview URLs found on the schedule."""
    soup = BeautifulSoup(html, "html.parser")
    fixtures = []
    seen = set()
    for anchor in soup.select("a[href]"):
        href = anchor["href"].strip()
        match = FIXTURE_PATH.fullmatch(urlparse(href).path)
        if not match:
            continue
        base_path = "/" + match.group(1)
        match_id = match.group(1).rsplit("-", 1)[-1]
        if base_path not in seen:
            seen.add(base_path)
            fixtures.append((match_id, base_path, urljoin(BASE, base_path)))
    return fixtures


def fixture_links_by_click(page, schedule_url: str) -> tuple[list[tuple[str, str, str]], int]:
    """Click visible kickoff-time links and read the resulting match preview URLs."""
    time_links = page.evaluate(
        """() => [...document.querySelectorAll('a')].map((a, index) => ({
            index,
            href: a.href,
            text: (a.innerText || a.textContent || '').trim()
        })).filter(item => /\\b\\d{1,2}:\\d{2}\\b/.test(item.text))"""
    )
    fixtures = []
    seen = set()
    for item in time_links:
        direct = fixture_links(f'<a href="{item["href"]}"></a>')
        if direct:
            fixture = direct[0]
        else:
            page.goto(schedule_url, wait_until="domcontentloaded", timeout=60000)
            kickoff_link = page.locator("a").nth(item["index"])
            try:
                with page.expect_navigation(wait_until="domcontentloaded", timeout=12000):
                    kickoff_link.click(timeout=12000)
            except PlaywrightTimeoutError:
                # Kicker may change the route through client-side navigation.
                pass
            page.wait_for_timeout(1000)
            current_url = page.url
            direct = fixture_links(f'<a href="{current_url}"></a>')
            if not direct:
                continue
            fixture = direct[0]
        if fixture[1] not in seen:
            seen.add(fixture[1])
            fixtures.append(fixture)
    return fixtures, len(time_links)


def open_fixture_lineup(page, schedule_url: str, match_id: str, match_path: str) -> str:
    """Click the time-linked fixture and its lineup tab, then return the URL."""
    page.goto(schedule_url, wait_until="domcontentloaded", timeout=60000)
    fixture_link = page.locator(f'a[href*="{match_path}"]').first
    if fixture_link.count():
        try:
            fixture_link.click(timeout=15000)
        except PlaywrightTimeoutError:
            if match_id not in page.url:
                page.goto(urljoin(BASE, match_path), wait_until="domcontentloaded", timeout=45000)
    else:
        page.goto(urljoin(BASE, match_path), wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(800)

    lineup_link = page.locator('a[href*="/aufstellung"]').first
    if lineup_link.count():
        try:
            lineup_link.click(timeout=10000)
        except PlaywrightTimeoutError:
            if not page.url.rstrip("/").endswith("/aufstellung"):
                page.goto(
                    urljoin(BASE, match_path.rstrip("/") + "/aufstellung"),
                    wait_until="domcontentloaded",
                    timeout=45000,
                )
    elif not page.url.rstrip("/").endswith("/aufstellung"):
        page.goto(
            urljoin(BASE, match_path.rstrip("/") + "/aufstellung"),
            wait_until="domcontentloaded",
            timeout=45000,
        )
    page.wait_for_timeout(1500)
    return page.url


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
    schedule_url = SCHEDULE_URL
    print(f"[Kicker Startelf 1/3] Ermittle aktuelle Partien: {schedule_url}", flush=True)

    rows: list[dict[str, str]] = []
    failures: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(locale="de-DE", viewport={"width": 1500, "height": 1100})
        page = context.new_page()
        page.goto(schedule_url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_function(
                "() => [...document.querySelectorAll('a[href]')].some(a => "
                "/-\\d{4}-bundesliga-\\d+/.test(new URL(a.href).pathname))",
                timeout=12000,
            )
        except PlaywrightTimeoutError:
            # Continue to diagnostics below so an empty schedule or bot page is
            # reported with its visible text and sample links.
            pass
        page.wait_for_timeout(2000)
        schedule_html = page.content()
        fixtures = fixture_links(schedule_html)
        time_link_count = 0
        if not fixtures:
            print("             Keine Standard-Spiel-URLs; prüfe klickbare Anstoßzeiten ...", flush=True)
            fixtures, time_link_count = fixture_links_by_click(page, schedule_url)
        if not fixtures:
            page.goto(schedule_url, wait_until="domcontentloaded", timeout=60000)
            schedule_html = page.content()
            debug_path = Path("html/kicker_spieltag_debug.html")
            debug_path.parent.mkdir(parents=True, exist_ok=True)
            debug_path.write_text(schedule_html, encoding="utf-8")
            page_text = page.locator("body").inner_text(timeout=5000)[:400].replace("\n", " ")
            page_title = page.title()
            sample_links = [
                anchor.get("href", "")
                for anchor in BeautifulSoup(schedule_html, "html.parser").select("a[href]")[:12]
            ]
            browser.close()
            raise RuntimeError(
                "Keine Kicker-Partienlinks erkannt. "
                f"Titel={page_title!r}; Seitentext={page_text!r}; "
                f"Anstoßzeit-Links={time_link_count}; Beispiellinks={sample_links!r}; "
                f"HTML gespeichert: {debug_path}"
            )
        print(f"[Kicker Startelf 1/3] {len(fixtures)} Partien im Spielplan gefunden.", flush=True)

        for number, (match_id, match_path, preview_url) in enumerate(fixtures, start=1):
            print(f"[Kicker Startelf 2/3] [{number}/{len(fixtures)}] Öffne Partie {preview_url} ...", flush=True)
            try:
                lineup_url = open_fixture_lineup(page, schedule_url, match_id, match_path)
                print(f"             Aufstellung geöffnet: {lineup_url}", flush=True)
                players = lineup_players(page.content(), lineup_url)
                for player in players:
                    rows.append({
                        "spieler": player["spieler"],
                        "profil_URL": player["profil_URL"],
                        "spiel_URL": lineup_url,
                    })
                print(f"             {len(players)} Startelfspieler gefunden.", flush=True)
            except Exception as error:
                failures.append(f"{preview_url}: {type(error).__name__}: {error}")
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
