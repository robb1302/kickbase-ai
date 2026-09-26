import re
import requests
import pandas as pd
from bs4 import BeautifulSoup

BASE = "https://www.ligainsider.de"
HEADERS = {"User-Agent": "Mozilla/5.0"}

session = requests.Session()
session.headers.update(HEADERS)

# 1. Vereins-IDs automatisch aus der Tabelle holen
html = session.get(f"{BASE}/bundesliga/tabelle/").text
soup = BeautifulSoup(html, "html.parser")

teams = []
for a in soup.select('a[href*="/kader/"]'):
    href = a.get("href", "")
    m = re.search(r"/([a-z0-9-]+)/(\d+)/kader/?", href)
    if m:
        teams.append((m.group(1), int(m.group(2))))

teams = list(dict.fromkeys(teams))

# 2. Kaderseiten auslesen
rows = []

for slug, team_id in teams:
    url = f"{BASE}/{slug}/{team_id}/kader/"
    print(url)

    soup = BeautifulSoup(session.get(url).text, "html.parser")

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

df = pd.DataFrame(rows).drop_duplicates("url")
df.to_csv("data/raw/ligainsider_spielerlinks.csv", index=False, encoding="utf-8-sig",sep=";")

print(df.head())
print(f"{len(df)} Spieler gespeichert.")