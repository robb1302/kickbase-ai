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


def _alias_match_count(
    names: pd.Series,
    source: str,
    aliases: dict[tuple[str, str], str],
) -> int:
    source_key = source.casefold()
    return sum((source_key, normalize(name)) in aliases for name in names)


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

    base_file = Path(base_file)
    merge_file = Path(merge_file)
    output_file = Path(output_file)

    print(f"\n=== Merge: {base_source} + {merge_source} ===", flush=True)
    print(f"[1/5] Lade Basisdatei: {base_file}", flush=True)
    kb = pd.read_csv(base_file, sep=base_sep, encoding="utf-8-sig")
    print(f"      Basiszeilen: {len(kb):,}", flush=True)

    print(f"[2/5] Lade Quelldatei: {merge_file}", flush=True)
    se = pd.read_csv(merge_file, sep=merge_sep, encoding="utf-8-sig")
    print(f"      Quellzeilen: {len(se):,}", flush=True)

    aliases = load_player_aliases(aliases_file)

    kb.columns = kb.columns.str.strip()
    se.columns = se.columns.str.strip()

    if "pieler" in se.columns:
        se = se.rename(columns={"pieler": "spieler"})
    elif "Spieler" in se.columns:
        se = se.rename(columns={"Spieler": "spieler"})

    print("[3/5] Erzeuge Match-Schlüssel", flush=True)
    base_aliases = _alias_match_count(kb["spieler"], base_source, aliases)
    source_aliases = _alias_match_count(se["spieler"], merge_source, aliases)
    kb["_key"] = kb["spieler"].map(lambda name: player_key(name, base_source, aliases))
    se["_key"] = se["spieler"].map(lambda name: player_key(name, merge_source, aliases))
    print(
        f"      Alias-Treffer: {base_source} {base_aliases}, "
        f"{merge_source} {source_aliases}",
        flush=True,
    )

    matched_base_rows = kb["_key"].isin(set(se["_key"]))
    matched_count = int(matched_base_rows.sum())
    unmatched_names = (
        kb.loc[~matched_base_rows, "spieler"]
        .dropna()
        .astype(str)
        .drop_duplicates()
        .tolist()
    )

    print("[4/5] Führe Dateien zusammen", flush=True)
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
    output_file.parent.mkdir(parents=True, exist_ok=True)

    print(f"[5/5] Schreibe Ergebnis: {output_file}", flush=True)
    result.to_csv(
        output_file,
        sep=";",
        index=False,
        encoding="utf-8-sig"
    )

    print(
        f"      Match-Ergebnis: {matched_count:,}/{len(kb):,} Basiszeilen "
        f"({matched_count / len(kb):.1%})",
        flush=True,
    )
    if unmatched_names:
        shown_names = ", ".join(unmatched_names[:15])
        remainder = len(unmatched_names) - 15
        if remainder > 0:
            shown_names += f" ... und {remainder} weitere"
        print(f"      Ohne Match ({len(unmatched_names)}): {shown_names}", flush=True)

    for column, label in (("maik_score", "MAIK scores"), ("url", "LigaInsider-URLs")):
        if column in result.columns:
            count = int(result[column].notna().sum())
            print(f"      {label}: {count:,}/{len(result):,}", flush=True)

    preview_columns = [
        column for column in ("spieler", "team", "maik_score", "url")
        if column in result.columns
    ]
    if preview_columns:
        print("      Vorschau:", flush=True)
        print(result[preview_columns].head(5).to_string(index=False), flush=True)

    return result


def main() -> None:
    print("Kickbase-Datenmerge gestartet", flush=True)
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
    print("Kickbase-Datenmerge abgeschlossen", flush=True)


if __name__ == "__main__":
    main()