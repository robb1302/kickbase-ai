"""Update the final Kickbase CSV from a copied raw export.

Usage:
    py -3 update_kickbase.py
    py -3 update_kickbase.py --dry-run
"""

from __future__ import annotations

import argparse
import csv
import re
import shutil
import unicodedata
from datetime import datetime
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = BASE_DIR / "data" / "raw" / "kickbase-22-09-26"
FINAL_PATH = BASE_DIR / "data" / "final" / "ht.csv"
OVERRIDES_PATH = BASE_DIR / "data" / "processed" / "maik_score_overrides.csv"
REMOVALS_PATH = BASE_DIR / "data" / "processed" / "player_removals.csv"

POSITIONS = {"Tor", "Abwehr", "Mittelfeld", "Sturm"}
STATUS_TOKENS = {"🔒", "🔥", "HOT", "DEAL", "●"}
IGNORED_LINES = {
    "BaseXI", "Spielerdaten", "XI-trablatt", "MW-Graph", "🔒 Liga",
    "🔒 Team", "🔒 Transfermarkt", "🔒 Scouting", "Matchday", "🔒 DreamTeam",
    "Updates", "Support", "Login", "1. Bundesliga", "2. Bundesliga", "2026/27",
    "2025/26", "2024/25", "2023/24", "Alle Spieltage wählen",
    "Nur freie Spieler", "Nur verkaufte Spieler", "🔥 Nur Hot Picks", "💰 Nur Deal",
    "🎲 Nur Gamble", "⭐ Nur Wunschliste", "Anwenden", "🔍 Suche Spieler oder Verein...",
    "Min. MW €", "Max. MW €", "Min. Ø Pkt", "Max. Ø Pkt", "Alle Positionen",
    "Alle Status", "Spalten:", "Team", "Pos", "MW", "Trend 24h", "Trend",
    "KI-Trend", "Punkte", "Ø Pkt", "Median", "Pkt/Mio", "Punkte Vorsaison",
    "Ø Vorsaison", "Einsätze", "Einsätze Vorsaison", "S11", "S11 Vorsaison", "Besitzer",
}


def normalize(value: object) -> str:
    text = "" if pd.isna(value) else str(value)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", text.casefold())


def parse_number(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip().replace("€", "").replace(" ", "")
    if not text or text in {"-", "—"}:
        return None
    # Kickbase exports use dots as thousands separators for market values.
    if text.count(".") > 1 and "," not in text:
        text = text.replace(".", "")
    text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def parse_raw_export(path: Path) -> pd.DataFrame:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    rows: list[dict[str, object]] = []
    pending_status: list[str] = []
    last_name: str | None = None

    for line in lines:
        parts = line.split("\t")
        if len(parts) >= 9 and parts[1] in POSITIONS:
            values = parts[2:]
            if last_name:
                rows.append(
                    {
                        "spieler": last_name,
                        "team": parts[0],
                        "position": parts[1],
                        "marktwert": parse_number(values[0]),
                        "trend_24h": values[1] if len(values) > 1 else pd.NA,
                        "trend": values[2] if len(values) > 2 else pd.NA,
                        "ki_trend": values[3] if len(values) > 3 else pd.NA,
                        "punkte": parse_number(values[4]) if len(values) > 4 else None,
                        "durchschnitt_punkte": parse_number(values[5]) if len(values) > 5 else None,
                        "median": parse_number(values[6]) if len(values) > 6 else None,
                        "status": ";".join(dict.fromkeys(pending_status)),
                    }
                )
            pending_status = []
            last_name = None
        elif line in STATUS_TOKENS:
            pending_status.append(line)
        elif "\t" not in line and line not in IGNORED_LINES:
            last_name = line

    return pd.DataFrame(rows)


def find_target(name: object, team: object, final: pd.DataFrame) -> int | None:
    name_key = normalize(name)
    exact = final.index[final["spieler"].map(normalize).eq(name_key)].tolist()
    if len(exact) == 1:
        return exact[0]

    surname = name_key.split()[-1] if name_key else ""
    candidates = final.index[final["spieler"].map(normalize).str.endswith(surname)].tolist()
    if len(candidates) == 1:
        return candidates[0]
    return None


def load_score_overrides() -> dict[str, float]:
    if not OVERRIDES_PATH.exists():
        return {}
    overrides = pd.read_csv(OVERRIDES_PATH, sep=";", encoding="utf-8")
    if not {"spieler", "maik_score"}.issubset(overrides.columns):
        return {}
    return {
        normalize(row["spieler"]): float(row["maik_score"])
        for _, row in overrides.iterrows()
        if pd.notna(pd.to_numeric(row["maik_score"], errors="coerce"))
    }


def load_removals() -> set[str]:
    if not REMOVALS_PATH.exists():
        return set()
    removals = pd.read_csv(REMOVALS_PATH, sep=";", encoding="utf-8")
    if not {"spieler", "team"}.issubset(removals.columns):
        return set()
    return {
        f"{normalize(row['spieler'])}|{normalize(row['team'])}"
        for _, row in removals.iterrows()
    }


def update_final(raw: pd.DataFrame, final: pd.DataFrame) -> tuple[pd.DataFrame, int, int]:
    score_overrides = load_score_overrides()
    removals = load_removals()
    updated = final.copy()
    matched = 0
    added = 0

    for _, source in raw.iterrows():
        target = find_target(source["spieler"], source["team"], updated)
        if target is None:
            row = {column: pd.NA for column in updated.columns}
            row.update(source.to_dict())
            row["maik_score"] = score_overrides.get(normalize(source["spieler"]), pd.NA)
            row["maik_match"] = "kickbase_update"
            updated = pd.concat([updated, pd.DataFrame([row])], ignore_index=True)
            added += 1
            continue

        for column in [
            "spieler", "team", "position", "marktwert", "trend_24h", "trend",
            "ki_trend", "punkte", "durchschnitt_punkte", "median", "status",
        ]:
            if column in updated.columns and column in source:
                updated.at[target, column] = source[column]
        matched += 1

    updated["marktwert_num"] = updated["marktwert"].map(parse_number)
    updated["punkte_num"] = pd.to_numeric(updated["punkte"], errors="coerce")
    updated["durchschnitt_pts"] = pd.to_numeric(
        updated["durchschnitt_punkte"], errors="coerce"
    )
    updated["maik_score_num"] = pd.to_numeric(
        updated["maik_score"], errors="coerce") * 10
    updated = updated[
        ~updated.apply(
            lambda row: f"{normalize(row['spieler'])}|{normalize(row['team'])}"
            in removals,
            axis=1,
        )
    ].reset_index(drop=True)
    return updated, matched, added


def main() -> None:
    parser = argparse.ArgumentParser(description="Update ht.csv from a Kickbase raw export")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.input.exists():
        raise SystemExit(f"Rohdatei nicht gefunden: {args.input}")
    if not FINAL_PATH.exists():
        raise SystemExit(f"Finale CSV nicht gefunden: {FINAL_PATH}")

    raw = parse_raw_export(args.input)
    final = pd.read_csv(FINAL_PATH, sep=";", encoding="utf-8")
    updated, matched, added = update_final(raw, final)

    print(f"Rohspieler erkannt: {len(raw)}")
    print(f"Bestehende Spieler aktualisiert: {matched}")
    print(f"Neue Spieler hinzugefügt: {added}")
    print(f"Maik-Scores erhalten: {updated['maik_score'].notna().sum()}")

    if args.dry_run:
        print("Dry-run: Keine Datei geändert.")
        return

    backup = FINAL_PATH.with_name(
        f"{FINAL_PATH.stem}.backup-{datetime.now():%Y%m%d-%H%M%S}.csv"
    )
    shutil.copy2(FINAL_PATH, backup)
    updated.to_csv(FINAL_PATH, sep=";", index=False, encoding="utf-8")
    print(f"Backup: {backup.name}")
    print(f"Aktualisiert: {FINAL_PATH}")


if __name__ == "__main__":
    main()
