"""Export current MAIK scores for active Bundesliga players."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


API_BASE = "https://maikmitai.com/api"
LEAGUE = "de.1"
USER_AGENT = "maik-bundesliga-scores/1.0"
FIELDNAMES = [
    "score_date",
    "league",
    "team_rank",
    "team",
    "team_slug",
    "spieler_id",
    "spieler",
    "maik_rolle",
    "maik_score",
    "maik_score_change",
    "source_url",
    "retrieved_at",
]


def fetch_json(path: str) -> dict:
    request = Request(f"{API_BASE}{path}", headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Abruf fehlgeschlagen: {path}: {exc}") from exc


def latest_score(scores: list[float | None], dates: list[str]) -> tuple[float, str, float | None] | None:
    values = [
        (float(score), dates[index])
        for index, score in enumerate(scores)
        if score is not None and index < len(dates)
    ]
    if not values:
        return None

    current_score, score_date = values[-1]
    previous = next((score for score, _ in reversed(values[:-1]) if score != current_score), None)
    change = None if previous is None else round(current_score - previous, 1)
    return current_score, score_date, change


def collect_rows() -> list[dict[str, object]]:
    roster = fetch_json("/kader")
    teams = roster.get("ligen", {}).get(LEAGUE, {}).get("rows", [])
    if not teams:
        raise RuntimeError("Keine Bundesliga-Vereine im MAIK-Kader-Endpunkt gefunden.")

    retrieved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    rows: list[dict[str, object]] = []
    for team in teams:
        slug = team.get("slug")
        if not slug:
            raise RuntimeError("Verein ohne Slug im MAIK-Kader-Endpunkt gefunden.")

        history = fetch_json(f"/score-history?team={slug}")
        dates = history.get("dates", [])
        source_url = f"{API_BASE}/score-history?team={slug}"
        for player in history.get("players", []):
            if not player.get("active"):
                continue
            score = latest_score(player.get("scores", []), dates)
            if score is None:
                continue
            value, score_date, change = score
            rows.append(
                {
                    "score_date": score_date,
                    "league": LEAGUE,
                    "team_rank": team.get("rank"),
                    "team": history.get("name") or team.get("name"),
                    "team_slug": slug,
                    "spieler_id": player.get("id"),
                    "spieler": player.get("name"),
                    "maik_rolle": player.get("pos"),
                    "maik_score": round(value, 1),
                    "maik_score_change": change,
                    "source_url": source_url,
                    "retrieved_at": retrieved_at,
                }
            )

    return sorted(
        rows,
        key=lambda row: (
            int(row["team_rank"]) if row["team_rank"] is not None else 999,
            str(row["team"]),
            -float(row["maik_score"]),
            str(row["spieler"]),
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/raw/maik-bundesliga-scores.csv"),
        help="Zielpfad der semikolongetrennten CSV.",
    )
    args = parser.parse_args()

    rows = collect_rows()
    if not rows:
        raise SystemExit("Keine aktiven Spieler mit aktuellem MAIK-Score gefunden.")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDNAMES, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)

    teams = {row["team_slug"] for row in rows}
    print(f"Gespeichert: {args.output}")
    print(f"Vereine: {len(teams)}")
    print(f"Aktive Spieler mit Score: {len(rows)}")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1)
