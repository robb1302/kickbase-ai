from pathlib import Path
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import pandas as pd
import re
import time

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

all_players = []

with sync_playwright() as p:

    browser = p.chromium.launch(headless=False)
    context = browser.new_context(
        viewport={"width":1600,"height":1200},
        locale="de-DE"
    )

    page = context.new_page()

    cookie_done = False

    for team, url in TEAMS.items():

        print(f"Download: {team}")

        page.goto(url, wait_until="domcontentloaded")

        if not cookie_done:
            try:
                page.frame_locator("iframe[title='Privacy Manager']")\
                    .get_by_role("button", name="ZUSTIMMEN")\
                    .click(timeout=10000)
                cookie_done = True
                page.wait_for_timeout(2000)
            except:
                pass

        page.wait_for_timeout(4000)

        # -------- HTML DOWNLOAD --------
        html = page.evaluate("() => document.documentElement.outerHTML")

        filename = team.lower().replace(" ", "_").replace(".", "")
        path = Path("html") / f"{filename}.html"
        path.write_text(html, encoding="utf-8")

        # -------- PARSEN --------
        soup = BeautifulSoup(html, "html.parser")

        seen = set()
        players = []

        for a in soup.select("a[href]"):

            href = a.get("href","")

            m = re.fullmatch(r"/([a-z0-9-]+)_(\d+)/?", href)

            if not m:
                continue

            slug, pid = m.groups()

            name = " ".join(x.capitalize() for x in slug.split("-"))

            if name in seen:
                continue

            seen.add(name)

            players.append({
                "verein": team,
                "position": len(players)+1,
                "spieler": name,
                "slug": slug,
                "spieler_ID": int(pid),
                "profil_URL": f"https://www.ligainsider.de{href}"
            })

        all_players.extend(players[:11])

        print(f"  -> {len(players[:11])} Spieler")

        time.sleep(1)

    browser.close()

df = pd.DataFrame(all_players)

df.to_csv(
    "C:/Users/rober/development/projects/kickbase-ai/data/matchday/bundesliga_startelf.csv",
    index=False,
    encoding="utf-8-sig",
    sep=";"
)

print(df)
print(f"\nFertig: {len(df)} Spieler")