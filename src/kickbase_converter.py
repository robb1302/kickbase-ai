import csv, re
from pathlib import Path

src = Path("C://Users/rober/development/projects/kickbase/data/kickbase-22-09-26")
text = src.read_text(encoding="utf-8", errors="replace")
lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

positions = {"Tor", "Abwehr", "Mittelfeld", "Sturm"}
status_tokens = {"🔒", "🔥", "HOT", "DEAL", "●"}

rows = []
pending_status = []
last_name = None

for ln in lines:
    parts = ln.split("\t")
    if len(parts) >= 9 and parts[1] in positions:
        # This is a player data row.
        team, pos = parts[0], parts[1]
        data = parts[2:]
        name = last_name
        if name:
            rows.append([
                name, team, pos,
                *data[:7],  # MW, Trend24h, Trend, KI-Trend, Punkte, ØPkt, Median
                ";".join(dict.fromkeys(pending_status))
            ])
        pending_status = []
        last_name = None
    elif ln in status_tokens:
        pending_status.append(ln)
    elif "\t" not in ln and ln not in {
        "BaseXI","Spielerdaten","XI-trablatt","MW-Graph","🔒 Liga","🔒 Team",
        "🔒 Transfermarkt","🔒 Scouting","Matchday","🔒 DreamTeam","Updates",
        "Support","Login","1. Bundesliga","2. Bundesliga","2026/27","2025/26",
        "2024/25","2023/24","Spieler: 462 (Gefiltert: 462)",
        "Spieltage wählen: Spieltage: 4","Alle Spieltage wählen","Nur freie Spieler",
        "Nur verkaufte Spieler","🔥 Nur Hot Picks","💰 Nur Deal","🎲 Nur Gamble",
        "⭐ Nur Wunschliste","Anwenden","🔍 Suche Spieler oder Verein...",
        "Min. MW €","Max. MW €","Min. Ø Pkt","Max. Ø Pkt","Alle Positionen",
        "Alle Status","Spalten:","Team","Pos","MW","Trend 24h","Trend","KI-Trend",
        "Punkte","Ø Pkt","Median","Pkt/Mio","Punkte Vorsaison","Ø Vorsaison",
        "Einsätze","Einsätze Vorsaison","S11","S11 Vorsaison","Besitzer"
    }:
        # Candidate player name. Status preceding the name belongs to this player.
        if last_name is not None:
            # In case an unexpected line occurs, keep it as the latest candidate.
            pass
        last_name = ln

headers = [
    "spieler","team","position","marktwert","trend_24h","trend","ki_trend",
    "punkte","durchschnitt_punkte","median","status"
]

out = Path("kickbase_spieler_datenbank.csv")
with out.open("w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f, delimiter=";")
    w.writerow(headers)
    w.writerows(rows)

print(f"CSV erstellt: {out}")
print(f"Spieler erkannt: {len(rows)}")
print("Erste 10 Datensätze:")
for r in rows[:10]:
    print(r)
