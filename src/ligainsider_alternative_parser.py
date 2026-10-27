from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup
from bs4.element import Tag


HTML_DIR = Path("html")
OUTPUT = Path("data/matchday/bundesliga_alternativen.csv")
PLAYER_HREF = re.compile(r"/[a-z0-9-]+_(\d+)/?")


def player_id(container: Tag) -> str | None:
    link = container.select_one(".player_name a[href]")
    if link is None:
        return None

    match = PLAYER_HREF.fullmatch(link["href"])
    return match.group(1) if match else None


def main() -> None:
    html_files = sorted(HTML_DIR.glob("*.html"))
    if not html_files:
        raise FileNotFoundError(f"Keine LigaInsider-HTML-Dateien in {HTML_DIR} gefunden.")

    rows = []
    for html_file in html_files:
        soup = BeautifulSoup(html_file.read_text(encoding="utf-8"), "html.parser")
        columns = soup.select(".player_position_column")
        if not columns:
            raise RuntimeError(f"Keine Aufstellungspositionen in {html_file} gefunden.")

        for column in columns:
            children = column.find_all("div", class_="sub_child", recursive=False)
            if len(children) < 2:
                continue

            for alternative in children[1:]:
                alternative_link = alternative.select_one(".player_name a[href]")
                alternative_id = player_id(alternative)
                if alternative_id is None or alternative_link is None:
                    continue

                rows.append(
                    {
                        "ligainsider_id": alternative_id,
                        "spieler": alternative_link.get_text(" ", strip=True),
                        "alternative_fuer_id": player_id(children[0]),
                        "quelle": html_file.name,
                    }
                )

    alternatives = pd.DataFrame(
        rows,
        columns=["ligainsider_id", "spieler", "alternative_fuer_id", "quelle"],
    ).drop_duplicates(["ligainsider_id", "alternative_fuer_id"])

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    alternatives.to_csv(OUTPUT, sep=";", index=False, encoding="utf-8-sig")
    print(f"Alternativen: {len(alternatives)} Spieler gespeichert in {OUTPUT}")


if __name__ == "__main__":
    main()
