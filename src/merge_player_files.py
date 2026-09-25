"""Merge the player database with the Maik player export by player name."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_PATH = BASE_DIR / "data" / "processed" / "kickbase_spieler_datenbank.csv"
DEFAULT_MAIK_PATH = BASE_DIR / "data" / "raw" / "maik-2026-09.csv"
DEFAULT_OUTPUT_PATH = BASE_DIR / "data" / "processed" / "kickbase_spieler_datenbank_merged.csv"


def normalize_player_name(value: object) -> str:
    """Normalize case, whitespace, punctuation, and accents for matching."""
    if pd.isna(value):
        return ""
    transliteration = str.maketrans(
        {
            "ø": "o",
            "æ": "ae",
            "œ": "oe",
            "ł": "l",
            "đ": "d",
            "ð": "d",
            "þ": "th",
            "ß": "ss",
        }
    )
    ascii_name = (
        unicodedata.normalize(
            "NFKD", str(value).strip().casefold().translate(transliteration)
        )
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    return re.sub(r"[^a-z0-9]", "", ascii_name)


def _make_unique_name_keys(names: pd.Series, source: Path) -> pd.Series:
    keys = names.map(normalize_player_name)
    if keys.eq("").any():
        raise ValueError(f"Leere Spielernamen in {source}.")

    duplicates = keys[keys.duplicated(keep=False)]
    if not duplicates.empty:
        duplicate_names = names.loc[duplicates.index].tolist()
        raise ValueError(
            f"Spielernamen in {source} sind nach Normalisierung nicht eindeutig: "
            f"{duplicate_names[:10]}"
        )
    return keys


def _match_unique_name_prefixes(database: pd.DataFrame, maik: pd.DataFrame) -> None:
    """Match shortened/full name variants when a same-team pair is unambiguous."""
    database_team = database["team"].map(normalize_player_name)
    maik_team = maik["Mannschaft"].map(normalize_player_name)
    database_keys = database["_player_key"]
    maik_keys = maik["_player_key"]
    exact_keys = set(database_keys).intersection(maik_keys)

    possible_matches: dict[int, list[int]] = {}
    for maik_index, maik_key in maik_keys.items():
        if maik_key in exact_keys:
            continue
        candidates = []
        for database_index, database_key in database_keys.items():
            if database_key in exact_keys:
                continue
            if database_team[database_index] != maik_team[maik_index]:
                continue
            shorter, longer = sorted((database_key, maik_key), key=len)
            if len(shorter) / len(longer) >= 0.55 and longer.startswith(shorter):
                candidates.append(database_index)
        if candidates:
            possible_matches[maik_index] = candidates

    reverse_counts: dict[int, int] = {}
    for candidates in possible_matches.values():
        if len(candidates) == 1:
            database_index = candidates[0]
            reverse_counts[database_index] = reverse_counts.get(database_index, 0) + 1

    for maik_index, candidates in possible_matches.items():
        if len(candidates) != 1:
            continue
        database_index = candidates[0]
        if reverse_counts[database_index] == 1:
            maik.at[maik_index, "_player_key"] = database_keys[database_index]


def merge_player_files(
    database_path: Path = DEFAULT_DATABASE_PATH,
    maik_path: Path = DEFAULT_MAIK_PATH,
    output_path: Path | None = DEFAULT_OUTPUT_PATH,
) -> pd.DataFrame:
    """Outer-merge both semicolon CSVs by normalized player name.

    Existing database rows are retained, Maik-only players are added, and the
    Maik fields are prefixed to distinguish them from database columns.
    If ``output_path`` is None, the merged DataFrame is returned without saving.
    """
    database_path = Path(database_path)
    maik_path = Path(maik_path)

    database = pd.read_csv(database_path, sep=";", encoding="utf-8-sig")
    maik = pd.read_csv(maik_path, sep=";", encoding="utf-8-sig", decimal=",")

    if "spieler" not in database.columns:
        raise ValueError(f"Die Datenbank braucht eine 'spieler'-Spalte: {database_path}")

    required_maik_columns = {
        "Spieler",
        "Rang",
        "Rolle",
        "Score",
        "Marktwert_Delta",
        "Mannschaft",
    }
    missing_columns = required_maik_columns.difference(maik.columns)
    if missing_columns:
        raise ValueError(
            f"Fehlende Maik-Spalten in {maik_path}: {sorted(missing_columns)}"
        )

    database_columns = database.columns.tolist()
    database["_player_key"] = _make_unique_name_keys(database["spieler"], database_path)
    maik["_player_key"] = _make_unique_name_keys(maik["Spieler"], maik_path)
    _match_unique_name_prefixes(database, maik)
    maik = maik.rename(
        columns={
            "Spieler": "spieler_maik",
            "Rang": "maik_rang",
            "Rolle": "maik_rolle",
            "Score": "maik_score",
            "Marktwert_Delta": "maik_score_change",
            "Mannschaft": "maik_team",
        }
    )

    merged = database.merge(
        maik,
        on="_player_key",
        how="outer",
        validate="one_to_one",
    )
    merged["spieler"] = merged["spieler"].fillna(merged["spieler_maik"])
    merged["team"] = merged["team"].fillna(merged["maik_team"])
    merged["maik_rang"] = merged["maik_rang"].astype("Int64")
    merged["maik_score"] = merged["maik_score"].astype("Int64")

    maik_columns = [
        "maik_rang",
        "maik_rolle",
        "maik_score",
        "maik_score_change",
        "maik_team",
    ]
    result = merged[[*database_columns, *maik_columns]].copy()

    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        result.to_csv(output_path, index=False, sep=";", encoding="utf-8", decimal=",")

    return result


if __name__ == "__main__":
    merged_players = merge_player_files()
    print(f"Zusammengeführte Spieler: {len(merged_players)}")
    print(f"CSV erstellt: {DEFAULT_OUTPUT_PATH}")