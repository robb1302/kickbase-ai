from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup
from bs4.element import Tag
from ligainsider_status import load_status, reset_status, update_status


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

    status = load_status()
    reset_status(
        [
            (row.team_id, row.verein, row.html_file or None)
            for row in status.itertuples(index=False)
            if str(row.team_id).strip()
        ],
        "alternativen_status",
    )
    for row in load_status().itertuples(index=False):
        if str(row.team_id).strip() and (
            not str(row.html_file).strip()
            or not (HTML_DIR / str(row.html_file)).exists()
        ):
            update_status(
                row.team_id,
                row.verein,
                "alternativen_status",
                "Fehlt",
                details="Keine HTML-Kaderseite verfügbar",
            )
    cached = pd.read_csv(OUTPUT, sep=";", encoding="utf-8-sig") if OUTPUT.exists() else pd.DataFrame()
    rows = []
    failed_teams = []
    for html_file in html_files:
        source_status = load_status()
        team_rows = source_status.loc[source_status["html_file"] == html_file.name]
        team_id = team_rows.iloc[0]["team_id"] if not team_rows.empty else ""
        team_name = team_rows.iloc[0]["verein"] if not team_rows.empty else html_file.stem
        startelf_status = team_rows.iloc[0]["startelf_status"] if not team_rows.empty else "Unbekannt"
        team_alternatives = []
        try:
            soup = BeautifulSoup(html_file.read_text(encoding="utf-8"), "html.parser")
            columns = soup.select(".player_position_column")
            if not columns:
                raise RuntimeError("Keine Aufstellungspositionen erkannt")

            for column in columns:
                children = column.find_all("div", class_="sub_child", recursive=False)
                if len(children) < 2:
                    continue

                for alternative in children[1:]:
                    alternative_link = alternative.select_one(".player_name a[href]")
                    alternative_id = player_id(alternative)
                    if alternative_id is None or alternative_link is None:
                        continue

                    team_alternatives.append(
                        {
                            "ligainsider_id": alternative_id,
                            "spieler": alternative_link.get_text(" ", strip=True),
                            "alternative_fuer_id": player_id(children[0]),
                            "quelle": html_file.name,
                        }
                    )
            rows.extend(team_alternatives)
            result_status = (
                "Vorversion verwendet"
                if startelf_status == "Vorversion verwendet"
                else "Aktuell"
            )
            if team_id:
                update_status(team_id, team_name, "alternativen_status", result_status, html_file=html_file.name)
        except Exception as error:
            failed_teams.append(html_file.name)
            if not cached.empty and "quelle" in cached.columns:
                team_alternatives = cached.loc[cached["quelle"] == html_file.name].to_dict("records")
            rows.extend(team_alternatives)
            result_status = "Vorversion verwendet" if team_alternatives else "Fehlt"
            if team_id:
                update_status(
                    team_id, team_name, "alternativen_status", result_status,
                    html_file=html_file.name, details=type(error).__name__,
                )
            print(f"Alternativen {html_file.name}: {result_status} ({error})", flush=True)

    alternatives = pd.DataFrame(
        rows,
        columns=["ligainsider_id", "spieler", "alternative_fuer_id", "quelle"],
    ).drop_duplicates(["ligainsider_id", "alternative_fuer_id"])

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    alternatives.to_csv(OUTPUT, sep=";", index=False, encoding="utf-8-sig")
    print(f"Alternativen: {len(alternatives)} Spieler gespeichert in {OUTPUT}")
    if failed_teams:
        print(f"Alternativen unvollständig: {', '.join(failed_teams)}", flush=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
