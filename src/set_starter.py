from pathlib import Path
import pandas as pd
import unicodedata
import re

PLAYER_DATA = Path("data/processed/kickbase_maik_ligainsider.csv")
STARTELF = Path("data/matchday/bundesliga_startelf.csv")
OUTPUT = Path("data/final/final.csv")


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
    return re.sub(r"[^a-z0-9]", "", name)


# Dateien laden
kb = pd.read_csv(PLAYER_DATA, sep=";", encoding="utf-8-sig")
se = pd.read_csv(STARTELF, sep=";", encoding="utf-8-sig")

# Spalten bereinigen
kb.columns = kb.columns.str.strip()
se.columns = se.columns.str.strip()

# Spieler-Spalte vereinheitlichen
if "pieler" in se.columns:
    se = se.rename(columns={"pieler": "spieler"})
elif "Spieler" in se.columns:
    se = se.rename(columns={"Spieler": "spieler"})

# Normalisierte Schlüssel
kb["_key"] = kb["spieler"].map(normalize)
se_keys = set(se["spieler"].map(normalize))

# Startelf-Flag setzen
kb["startelf"] = kb["_key"].isin(se_keys)

# Hilfsspalte entfernen
kb = kb.drop(columns="_key")

# Speichern
kb.to_csv(
    OUTPUT,
    sep=";",
    index=False,
    encoding="utf-8-sig"
)

print(f"Startelf: {kb['startelf'].sum()} / {len(kb)} Spieler")