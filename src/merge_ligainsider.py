from pathlib import Path
import pandas as pd
import unicodedata
import re

KICKBASE = Path("data/processed/kickbase_spieler_datenbank_merged.csv")
STARTELF = Path("data/raw/ligainsider_spielerlinks.csv")
OUTPUT = Path("data/processed/kickbase_final.csv")


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
kb = pd.read_csv(KICKBASE, sep=";", encoding="utf-8-sig")
se = pd.read_csv(STARTELF, sep=",", encoding="utf-8-sig")  # <-- Komma!

# Spalten bereinigen
kb.columns = kb.columns.str.strip()
se.columns = se.columns.str.strip()

# Spieler-Spalte vereinheitlichen
if "pieler" in se.columns:      # falls das S fehlt
    se = se.rename(columns={"pieler": "spieler"})
elif "Spieler" in se.columns:
    se = se.rename(columns={"Spieler": "spieler"})

# Schlüssel
kb["_key"] = kb["spieler"].map(normalize)
se["_key"] = se["spieler"].map(normalize)

# Merge
result = kb.merge(
    se.drop(columns=["spieler"]),
    on="_key",
    how="left"
)

result.drop(columns="_key").to_csv(
    OUTPUT,
    sep=";",
    index=False,
    encoding="utf-8-sig"
)

print(f"Gematcht: {result['verein'].notna().sum()} / {len(result)}")