"""Shared per-team LigaInsider fetch status used by the update scripts and app."""

from pathlib import Path

import pandas as pd


STATUS_PATH = Path("data/matchday/ligainsider_status.csv")
STATUS_COLUMNS = [
    "team_id", "verein", "html_file", "kader_status", "startelf_status",
    "alternativen_status", "details",
]


def load_status() -> pd.DataFrame:
    if not STATUS_PATH.exists():
        return pd.DataFrame(columns=STATUS_COLUMNS)
    status = pd.read_csv(STATUS_PATH, sep=";", encoding="utf-8-sig", dtype={"team_id": "string"})
    for column in STATUS_COLUMNS:
        if column not in status:
            status[column] = pd.Series("", index=status.index, dtype="string")
        else:
            status[column] = status[column].fillna("").astype("string")
    return status[STATUS_COLUMNS]


def update_status(
    team_id: str | int,
    verein: str,
    source_column: str,
    value: str,
    *,
    html_file: str | None = None,
    details: str = "",
) -> None:
    if source_column not in {"kader_status", "startelf_status", "alternativen_status"}:
        raise ValueError(f"Ungültige Statusspalte: {source_column}")
    status = load_status()
    key = str(team_id)
    matches = status["team_id"].astype("string") == key
    if not matches.any():
        new_index = len(status)
        status.loc[new_index, STATUS_COLUMNS] = pd.Series(
            {column: "" for column in STATUS_COLUMNS}, dtype="string"
        )
        matches = status.index == new_index
        status.loc[matches, "team_id"] = key
    status.loc[matches, "verein"] = verein
    status.loc[matches, source_column] = value
    if html_file is not None:
        status.loc[matches, "html_file"] = html_file
    status.loc[matches, "details"] = details
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    status.to_csv(STATUS_PATH, sep=";", index=False, encoding="utf-8-sig")


def reset_status(team_records: list[tuple[str | int, str, str | None]], source_column: str) -> None:
    for team_id, verein, html_file in team_records:
        update_status(
            team_id,
            verein,
            source_column,
            "Nicht geladen",
            html_file=html_file,
            details="",
        )
