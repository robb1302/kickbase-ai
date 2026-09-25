"""Export the current public BaseXI Bundesliga player database."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SOURCE_URL = "https://www.base-xi.de/api/players"
USER_AGENT = "basexi-bundesliga-players/1.0"
FIELDS = [
    "retrieved_at",
    "source_url",
    "spieler_id",
    "spieler",
    "team",
    "team_kuerzel",
    "position",
    "trikotnummer",
    "marktwert",
    "marktwert_trend_24h",
    "marktwert_trend_7t",
    "ki_trend",
    "ki_trend_status",
    "punkte",
    "durchschnitt_punkte",
    "median_punkte",
    "punkte_pro_mio",
    "einsaetze",
    "startelf_einsaetze",
    "durchschnitt_minuten",
    "marktwert_fair_value",
    "hot",
    "gamble",
    "neuzugang",
    "status_code",
    "status_text",
    "punkte_vorsaison",
    "durchschnitt_punkte_vorsaison",
    "einsaetze_vorsaison",
    "startelf_vorsaison",
    "vorsaison",
    "vorsaison_liga",
    "naechstes_spiel",
    "naechster_gegner",
    "naechster_spieltag",
]


def fetch_players() -> list[dict[str, object]]:
    request = Request(SOURCE_URL, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"BaseXI-Abruf fehlgeschlagen: {exc}") from exc

    if not isinstance(payload, list) or not payload:
        raise RuntimeError("BaseXI lieferte keine Spielerliste.")
    return payload


def to_row(player: dict[str, object], retrieved_at: str) -> dict[str, object]:
    next_match = player.get("next_match") or {}
    return {
        "retrieved_at": retrieved_at,
        "source_url": SOURCE_URL,
        "spieler_id": player.get("id"),
        "spieler": player.get("name"),
        "team": player.get("teamName"),
        "team_kuerzel": player.get("teamAbbr"),
        "position": player.get("position"),
        "trikotnummer": player.get("shirtNumber"),
        "marktwert": player.get("marketValue"),
        "marktwert_trend_24h": player.get("mvTrend"),
        "marktwert_trend_7t": player.get("trend7d"),
        "ki_trend": player.get("kiTrend"),
        "ki_trend_status": player.get("kiTrendStatus"),
        "punkte": player.get("totalPoints"),
        "durchschnitt_punkte": player.get("avgPoints"),
        "median_punkte": player.get("medianPoints"),
        "punkte_pro_mio": player.get("pointsPerMio"),
        "einsaetze": player.get("matchesPlayed"),
        "startelf_einsaetze": player.get("starts"),
        "durchschnitt_minuten": player.get("avgMinutes"),
        "marktwert_fair_value": player.get("fairValue"),
        "hot": player.get("isHot"),
        "gamble": player.get("gamble"),
        "neuzugang": player.get("isNewcomer"),
        "status_code": player.get("status"),
        "status_text": player.get("statusText"),
        "punkte_vorsaison": player.get("totalPrevSeason"),
        "durchschnitt_punkte_vorsaison": player.get("avgPrevSeason"),
        "einsaetze_vorsaison": player.get("gamesPrevSeason"),
        "startelf_vorsaison": player.get("startsPrevSeason"),
        "vorsaison": player.get("prevSeasonLabel"),
        "vorsaison_liga": player.get("prevSeasonLeague"),
        "naechstes_spiel": next_match.get("date_iso"),
        "naechster_gegner": next_match.get("pairing"),
        "naechster_spieltag": next_match.get("matchday"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/raw/basexi-bundesliga-players.csv"),
        help="Zielpfad der semikolongetrennten CSV.",
    )
    args = parser.parse_args()

    retrieved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    rows = [to_row(player, retrieved_at) for player in fetch_players()]
    ids = [row["spieler_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise SystemExit("BaseXI lieferte doppelte Spieler-IDs.")

    rows.sort(
        key=lambda row: (
            str(row["team"] or ""),
            -int(row["marktwert"] or 0),
            str(row["spieler"] or ""),
        )
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)

    print(f"Gespeichert: {args.output}")
    print(f"Spieler: {len(rows)}")
    print(f"Vereine: {len({row['team'] for row in rows})}")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1)
