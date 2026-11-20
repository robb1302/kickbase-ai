from pathlib import Path
import pandas as pd
import unicodedata
import re

PLAYER_DATA = Path("data/processed/kickbase_maik_ligainsider.csv")
STARTELF = Path("data/matchday/bundesliga_startelf.csv")
KICKER_STARTELF = Path("data/matchday/kicker_startelf.csv")
OUTPUT = Path("data/final/final.csv")
ALIASES = Path("config/player_name_aliases.csv")


def normalize(name):
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
    name = name.replace("ae", "a").replace("oe", "o").replace("ue", "u")
    return re.sub(r"[^a-z0-9]", "", name)


def load_alias_keys(path):
    aliases = pd.read_csv(path, sep=";", encoding="utf-8-sig", dtype=str).fillna("")
    return {
        (row.source.strip().casefold(), normalize(row.alias)): normalize(row.canonical_name)
        for row in aliases.itertuples(index=False)
    }


def player_key(name, source, aliases):
    normalized_name = normalize(name)
    return aliases.get((source, normalized_name), normalized_name)


# Dateien laden. Aufstellungsquellen sind optionale Anreicherungen: Ihr Ausfall
# darf die Aktualisierung der Kickbase-Basisdaten nicht verhindern.
kb = pd.read_csv(PLAYER_DATA, sep=";", encoding="utf-8-sig")
se = (
    pd.read_csv(STARTELF, sep=";", encoding="utf-8-sig")
    if STARTELF.exists()
    else pd.DataFrame(columns=["spieler", "verein"])
)
kicker = (
    pd.read_csv(KICKER_STARTELF, sep=";", encoding="utf-8-sig")
    if KICKER_STARTELF.exists()
    else pd.DataFrame(columns=["spieler", "verein"])
)
previous = (
    pd.read_csv(OUTPUT, sep=";", encoding="utf-8-sig", dtype={"spieler_id": "string"})
    if OUTPUT.exists()
    else pd.DataFrame()
)
alias_keys = load_alias_keys(ALIASES)

# Spalten bereinigen
kb.columns = kb.columns.str.strip()
se.columns = se.columns.str.strip()
kicker.columns = kicker.columns.str.strip()
if "spieler" not in se:
    se["spieler"] = pd.Series(dtype="string")
if "spieler" not in kicker:
    kicker["spieler"] = pd.Series(dtype="string")

# Spieler-Spalte vereinheitlichen
if "pieler" in se.columns:
    se = se.rename(columns={"pieler": "spieler"})
elif "Spieler" in se.columns:
    se = se.rename(columns={"Spieler": "spieler"})

# Normalisierte Schlüssel mit quellenspezifischen Aliasen
kb["_key"] = kb["spieler"].map(
    lambda name: player_key(name, "kickbase", alias_keys)
)
se_keys = se["spieler"].map(
    lambda name: player_key(name, "ligainsider", alias_keys)
)
kicker_keys = kicker["spieler"].map(
    lambda name: player_key(name, "kicker", alias_keys)
)

# Startelf-Flag setzen
def previous_flag(column):
    if previous.empty or "spieler_id" not in previous or column not in previous:
        return pd.Series(False, index=kb.index)
    flags = previous.drop_duplicates("spieler_id").set_index("spieler_id")[column]
    flags.index = flags.index.astype("string")
    return kb["spieler_id"].astype("string").map(flags).map(
        lambda value: str(value).strip().casefold() in {"true", "1", "yes"}
    )


kb["startelf"] = (
    kb["_key"].isin(set(se_keys)) if not se.empty else previous_flag("startelf")
)
kb["startelf_kicker"] = (
    kb["_key"].isin(set(kicker_keys))
    if not kicker.empty
    else previous_flag("startelf_kicker")
)
unmatched = se.loc[~se_keys.isin(kb["_key"]), "spieler"].drop_duplicates()
unmatched_kicker = kicker.loc[~kicker_keys.isin(kb["_key"]), "spieler"].drop_duplicates()

# Hilfsspalte entfernen
kb = kb.drop(columns="_key")

# Speichern
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
kb.to_csv(
    OUTPUT,
    sep=";",
    index=False,
    encoding="utf-8-sig"
)

print(f"Startelf: {kb['startelf'].sum()} / {len(kb)} Spieler")
print(f"Kicker-Startelf: {kb['startelf_kicker'].sum()} / {len(kb)} Spieler")
if not unmatched.empty:
    print(f"Nicht in der Spielerdatenbank: {', '.join(unmatched)}")
if not unmatched_kicker.empty:
    print(f"Kicker-Spieler ohne Match: {', '.join(unmatched_kicker)}")
