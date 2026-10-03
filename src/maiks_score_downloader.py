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
    print(f"[MAIK 1/3] Lade Bundesliga-Kader ({LEAGUE}) ...", flush=True)
    roster = fetch_json("/kader")
    teams = roster.get("ligen", {}).get(LEAGUE, {}).get("rows", [])
    if not teams:
        raise RuntimeError("Keine Bundesliga-Vereine im MAIK-Kader-Endpunkt gefunden.")
    print(f"[MAIK 1/3] {len(teams)} Vereine gefunden.", flush=True)

    retrieved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    rows: list[dict[str, object]] = []
    active_players = 0
    players_without_score = 0
    for team_number, team in enumerate(teams, start=1):
        slug = team.get("slug")
        if not slug:
            raise RuntimeError("Verein ohne Slug im MAIK-Kader-Endpunkt gefunden.")

        team_name = team.get("name") or slug
        print(
            f"[MAIK 2/3] [{team_number}/{len(teams)}] {team_name}: "
            "lade Score-Verlauf ...",
            flush=True,
        )
        history = fetch_json(f"/score-history?team={slug}")
        dates = history.get("dates", [])
        source_url = f"{API_BASE}/score-history?team={slug}"
        team_active_players = 0
        team_players_with_score = 0
        for player in history.get("players", []):
            if not player.get("active"):
                continue
            active_players += 1
            team_active_players += 1
            score = latest_score(player.get("scores", []), dates)
            if score is None:
                players_without_score += 1
                continue
            value, score_date, change = score
            team_players_with_score += 1
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
        print(
            f"             {team_players_with_score}/{team_active_players} aktive "
            "Spieler mit Score",
            flush=True,
        )

    sorted_rows = sorted(
        rows,
        key=lambda row: (
            int(row["team_rank"]) if row["team_rank"] is not None else 999,
            str(row["team"]),
            -float(row["maik_score"]),
            str(row["spieler"]),
        ),
    )
    print(
        f"[MAIK 3/3] Fertig: {len(sorted_rows)} Scores aus {len(teams)} Vereinen; "
        f"{active_players} aktive Spieler, {players_without_score} ohne Score.",
        flush=True,
    )
    return sorted_rows


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
    print(f"[MAIK] Gespeichert: {args.output}", flush=True)
    print(f"[MAIK] Vereine mit Score: {len(teams)}", flush=True)
    print(f"[MAIK] Aktive Spieler mit Score: {len(rows)}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1)
