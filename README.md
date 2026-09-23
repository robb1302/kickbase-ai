# kickbase-ai

## Lokales Kickbase-Update

1. Den neuen `Strg+A`-Export als `data/raw/kickbase-22-09-26` ablegen und die vorhandene Datei ersetzen.
2. Im Projektordner einen Dry-Run starten:

```powershell
py -3 update_kickbase.py --dry-run
```

3. Wenn die Zahlen stimmen, das Update ausführen:

```powershell
py -3 update_kickbase.py
```

Das Script erstellt automatisch ein Backup von `data/final/ht.csv`. Es aktualisiert Kickbase-Werte, behält manuelle Maik-Scores, Team-Scores, Kader-Markierungen und manuelle Spieler bei. Dauerhaft entfernte Spieler werden nicht wieder hinzugefügt.