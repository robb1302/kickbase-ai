from pathlib import Path
import pandas as pd
import unicodedata
import re

BASE_DIR = Path(__file__).resolve().parents[1]
ALIASES_FILE = BASE_DIR / "config" / "player_name_aliases.csv"


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


def load_player_aliases(path: str | Path) -> dict[tuple[str, str], str]:
    aliases = pd.read_csv(path, sep=";", encoding="utf-8-sig", dtype=str).fillna("")
    required_columns = {"source", "alias", "canonical_name"}
    missing_columns = required_columns.difference(aliases.columns)
    if missing_columns:
        raise ValueError(f"Fehlende Alias-Spalten in {path}: {sorted(missing_columns)}")

    alias_keys: dict[tuple[str, str], str] = {}
    for row in aliases.itertuples(index=False):
        source = row.source.strip().casefold()
        alias_key = normalize(row.alias)
        canonical_key = normalize(row.canonical_name)
        if not source or not alias_key or not canonical_key:
            raise ValueError(f"Ungültiger Spieler-Alias in {path}: {row}")

        key = (source, alias_key)
        if key in alias_keys:
            raise ValueError(f"Doppelter Spieler-Alias für {source}: {row.alias}")
        alias_keys[key] = canonical_key
    return alias_keys


def player_key(name: str, source: str, aliases: dict[tuple[str, str], str]) -> str:
    normalized_name = normalize(name)
    return aliases.get((source.casefold(), normalized_name), normalized_name)


def merge_player_csvs(
    base_file: str | Path,
    merge_file: str | Path,
    output_file: str | Path,
    base_sep: str = ";",
    merge_sep: str = ";",
    base_source: str = "kickbase",
    merge_source: str = "maik",
    aliases_file: str | Path = ALIASES_FILE,
):
    """Merged zwei CSVs über normalisierte Namen und optionale Quell-Aliase."""

    kb = pd.read_csv(base_file, sep=base_sep, encoding="utf-8-sig")
    se = pd.read_csv(merge_file, sep=merge_sep, encoding="utf-8-sig")
    aliases = load_player_aliases(aliases_file)

    kb.columns = kb.columns.str.strip()
    se.columns = se.columns.str.strip()

    if "pieler" in se.columns:
        se = se.rename(columns={"pieler": "spieler"})
    elif "Spieler" in se.columns:
        se = se.rename(columns={"Spieler": "spieler"})

    kb["_key"] = kb["spieler"].map(lambda name: player_key(name, base_source, aliases))
    se["_key"] = se["spieler"].map(lambda name: player_key(name, merge_source, aliases))

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
    Path(output_file).parent.mkdir(parents=True, exist_ok=True)

    result.to_csv(
        output_file,
        sep=";",
        index=False,
        encoding="utf-8-sig"
    )

    matched = result["team"].notna().sum() if "team" in result.columns else len(result)
    print(f"Gematcht: {matched} / {len(result)}")

    return result


def main() -> None:
    merge_player_csvs(
        base_file="data/raw/basexi-bundesliga-players.csv",
        merge_file="data/raw/maik-bundesliga-scores.csv",
        output_file="data/processed/kickbase_spieler_datenbank_merged.csv",
    )

    merge_player_csvs(
        base_file="data/processed/kickbase_spieler_datenbank_merged.csv",
        merge_file="data/raw/ligainsider_spielerlinks.csv",
        output_file="data/processed/kickbase_maik_ligainsider.csv",
        base_source="kickbase",
        merge_source="ligainsider",
    )


if __name__ == "__main__":
    main()