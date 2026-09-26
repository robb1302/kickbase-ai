from pathlib import Path
import pandas as pd
import unicodedata
import re


def normalize(name: str) -> str:
    if pd.isna(name):
        return ""

    table = str.maketrans({
        "ø": "o", "æ": "ae", "œ": "oe",
        "ł": "l", "đ": "d", "ð": "d",
        "þ": "th", "ß": "ss",
    })

    name = (
        unicodedata.normalize("NFKD", str(name).casefold().strip().translate(table))
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    return re.sub(r"[^a-z0-9]", "", name)


def merge_player_csvs(
    base_file: str | Path,
    merge_file: str | Path,
    output_file: str | Path,
    base_sep: str = ";",
    merge_sep: str = ";",
):
    """Merged zwei CSVs über den normalisierten Spielernamen."""

    kb = pd.read_csv(base_file, sep=base_sep, encoding="utf-8-sig")
    se = pd.read_csv(merge_file, sep=merge_sep, encoding="utf-8-sig")

    kb.columns = kb.columns.str.strip()
    se.columns = se.columns.str.strip()

    if "pieler" in se.columns:
        se = se.rename(columns={"pieler": "spieler"})
    elif "Spieler" in se.columns:
        se = se.rename(columns={"Spieler": "spieler"})

    kb["_key"] = kb["spieler"].map(normalize)
    se["_key"] = se["spieler"].map(normalize)

    result = kb.merge(
        se.drop(columns=["spieler"]),
        on="_key",
        how="left"
    )

    result.columns = (
        result.columns
        .str.replace("_x", "", regex=False)
        .str.replace("_y", "", regex=False)
    )

    result = result.drop(columns="_key")

    result.to_csv(
        output_file,
        sep=";",
        index=False,
        encoding="utf-8-sig"
    )

    matched = result["team"].notna().sum() if "team" in result.columns else len(result)
    print(f"Gematcht: {matched} / {len(result)}")

    return result


# Beispiel
merge_player_csvs(
    base_file="data/raw/basexi-bundesliga-players.csv",
    merge_file="data/raw/maik-bundesliga-scores.csv",
    output_file="data/processed/kickbase_spieler_datenbank_merged.csv",
)

merge_player_csvs(
    base_file="data/processed/kickbase_spieler_datenbank_merged.csv",
    merge_file="data/raw/ligainsider_spielerlinks.csv",
    output_file="data/processed/kickbase_maik_ligainsider.csv",
)