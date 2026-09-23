import base64
import io
import os
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
import requests
import streamlit as st


# ============================================================
# Konfiguration
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
CSV_PATH = BASE_DIR / "data" / "final" / "ht.csv"
SCORE_OVERRIDES_PATH = BASE_DIR / "data" / "processed" / "maik_score_overrides.csv"
TEAM_SCORE_OVERRIDES_PATH = BASE_DIR / "data" / "processed" / "team_score_overrides.csv"
ROSTER_OVERRIDES_PATH = BASE_DIR / "data" / "processed" / "roster_overrides.csv"
PLAYER_ADDITIONS_PATH = BASE_DIR / "data" / "processed" / "player_additions.csv"
PLAYER_REMOVALS_PATH = BASE_DIR / "data" / "processed" / "player_removals.csv"
GITHUB_API = "https://api.github.com"


# ============================================================
# Hilfsfunktionen
# ============================================================

def load_csv() -> pd.DataFrame:
    """Lädt die Spieler-CSV robust."""
    if not CSV_PATH.exists():
        st.error(f"CSV nicht gefunden: {CSV_PATH}")
        return pd.DataFrame()

    try:
        df = pd.read_csv(CSV_PATH, sep=";", encoding="utf-8")
    except UnicodeDecodeError:
        df = pd.read_csv(CSV_PATH, encoding="latin-1")

    # Unsichtbare Leerzeichen/BOM aus Spaltennamen entfernen.
    df.columns = (
        df.columns.astype(str)
        .str.replace("\ufeff", "", regex=False)
        .str.strip()
    )

    df = apply_score_overrides(df)
    df = apply_player_additions(df)
    df = apply_team_score_overrides(df)
    df = apply_roster_overrides(df)
    return apply_player_removals(df)


def normalize_key_part(value: object) -> str:
    """Normalisiert einen Spieler- oder Teamnamen für den Override-Schlüssel."""
    if pd.isna(value):
        return ""
    return " ".join(str(value).strip().casefold().split())


def score_key(player: object, team: object) -> str:
    """Verwendet Spieler plus Team als stabilen Schlüssel ohne Spieler-ID."""
    return f"{normalize_key_part(player)}|{normalize_key_part(team)}"


def load_player_additions() -> pd.DataFrame:
    """Lädt manuell hinzugefügte Spieler aus lokalem Speicher oder GitHub."""
    try:
        if github_configured():
            repo = github_setting("GITHUB_REPO")
            branch = github_setting("GITHUB_BRANCH", "main")
            path = github_setting(
                "GITHUB_PLAYER_ADDITIONS_PATH",
                "data/processed/player_additions.csv",
            )
            response = requests.get(
                f"{GITHUB_API}/repos/{repo}/contents/{path}",
                headers=github_headers(),
                params={"ref": branch},
                timeout=10,
            )
            if response.status_code == 404:
                return pd.DataFrame()
            response.raise_for_status()
            content = base64.b64decode(response.json()["content"]).decode("utf-8")
            return pd.read_csv(io.StringIO(content), sep=";")

        if not PLAYER_ADDITIONS_PATH.exists():
            return pd.DataFrame()
        return pd.read_csv(PLAYER_ADDITIONS_PATH, sep=";", encoding="utf-8")
    except (OSError, UnicodeDecodeError, pd.errors.ParserError, requests.RequestException) as exc:
        st.error(f"Manuelle Spieler konnten nicht geladen werden: {exc}")
        return pd.DataFrame()


def apply_player_additions(df: pd.DataFrame) -> pd.DataFrame:
    """Fügt manuell angelegte Spieler hinzu, ohne Importdaten zu verändern."""
    additions = load_player_additions()
    required = {"spieler", "team", "maik_score"}
    if additions.empty or not required.issubset(additions.columns):
        return df

    result = df.copy()
    existing_keys = {
        score_key(row["spieler"], row["team"])
        for _, row in result.iterrows()
    }
    rows = []
    for _, addition in additions.iterrows():
        key = score_key(addition["spieler"], addition["team"])
        if key in existing_keys:
            continue
        row = {column: pd.NA for column in result.columns}
        row.update(
            {
                "spieler": addition["spieler"],
                "team": addition["team"],
                "position": addition.get("position", "Unbekannt"),
                "maik_score": pd.to_numeric(
                    addition["maik_score"], errors="coerce"
                ),
                "maik_match": "manual_addition",
                "im_kader": False,
            }
        )
        rows.append(row)
    if not rows:
        return result
    return pd.concat([result, pd.DataFrame(rows, columns=result.columns)], ignore_index=True)


def save_player_addition(
    player: str,
    team: str,
    position: str,
    score: float,
) -> bool:
    """Speichert oder aktualisiert einen manuell hinzugefügten Spieler."""
    additions = load_player_additions()
    if additions.empty:
        additions = pd.DataFrame(columns=["spieler", "team", "maik_score", "position"])
    for column in ["spieler", "team", "maik_score", "position"]:
        if column not in additions.columns:
            additions[column] = pd.NA

    key = score_key(player, team)
    matches = additions.apply(
        lambda row: score_key(row["spieler"], row["team"]) == key,
        axis=1,
    )
    row = {
        "spieler": player,
        "team": team,
        "maik_score": score,
        "position": position,
    }
    if matches.any():
        additions.loc[matches, list(row)] = list(row.values())
    else:
        additions = pd.concat([additions, pd.DataFrame([row])], ignore_index=True)

    try:
        content = additions[["spieler", "team", "maik_score", "position"]].to_csv(
            index=False, sep=";"
        ).encode("utf-8")
        if github_configured():
            repo = github_setting("GITHUB_REPO")
            branch = github_setting("GITHUB_BRANCH", "main")
            path = github_setting(
                "GITHUB_PLAYER_ADDITIONS_PATH",
                "data/processed/player_additions.csv",
            )
            endpoint = f"{GITHUB_API}/repos/{repo}/contents/{path}"
            current = requests.get(
                endpoint,
                headers=github_headers(),
                params={"ref": branch},
                timeout=10,
            )
            payload = {
                "message": "Add manual player",
                "content": base64.b64encode(content).decode("ascii"),
                "branch": branch,
            }
            if current.status_code == 200:
                payload["sha"] = current.json()["sha"]
            requests.put(
                endpoint,
                headers=github_headers(),
                json=payload,
                timeout=10,
            ).raise_for_status()
        else:
            PLAYER_ADDITIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
            PLAYER_ADDITIONS_PATH.write_bytes(content)
        return True
    except (OSError, requests.RequestException) as exc:
        st.error(f"Spieler konnte nicht gespeichert werden: {exc}")
        return False


def load_player_removals() -> set[str]:
    """Lädt Spieler, die aus der App ausgeblendet werden sollen."""
    try:
        if github_configured():
            repo = github_setting("GITHUB_REPO")
            branch = github_setting("GITHUB_BRANCH", "main")
            path = github_setting(
                "GITHUB_PLAYER_REMOVALS_PATH",
                "data/processed/player_removals.csv",
            )
            response = requests.get(
                f"{GITHUB_API}/repos/{repo}/contents/{path}",
                headers=github_headers(),
                params={"ref": branch},
                timeout=10,
            )
            if response.status_code == 404:
                return set()
            response.raise_for_status()
            content = base64.b64decode(response.json()["content"]).decode("utf-8")
            removals = pd.read_csv(io.StringIO(content), sep=";")
        else:
            if not PLAYER_REMOVALS_PATH.exists():
                return set()
            removals = pd.read_csv(PLAYER_REMOVALS_PATH, sep=";", encoding="utf-8")
    except (OSError, UnicodeDecodeError, pd.errors.ParserError, requests.RequestException) as exc:
        st.error(f"Entfernte Spieler konnten nicht geladen werden: {exc}")
        return set()

    if not {"spieler", "team"}.issubset(removals.columns):
        return set()
    return {
        score_key(row["spieler"], row["team"])
        for _, row in removals.iterrows()
    }


def apply_player_removals(df: pd.DataFrame) -> pd.DataFrame:
    """Entfernt gespeicherte Spieler aus der App-Ansicht."""
    removals = load_player_removals()
    if not removals:
        return df
    mask = df.apply(
        lambda row: score_key(row.get("spieler"), row.get("team")) not in removals,
        axis=1,
    )
    return df.loc[mask].copy()


def save_player_removal(player: str, team: str) -> bool:
    """Speichert einen Spieler als dauerhaft aus der App entfernt."""
    removals = load_player_removals()
    removals.add(score_key(player, team))
    rows = [{"spieler": player, "team": team}]

    try:
        if github_configured():
            repo = github_setting("GITHUB_REPO")
            branch = github_setting("GITHUB_BRANCH", "main")
            path = github_setting(
                "GITHUB_PLAYER_REMOVALS_PATH",
                "data/processed/player_removals.csv",
            )
            endpoint = f"{GITHUB_API}/repos/{repo}/contents/{path}"
            current = requests.get(
                endpoint,
                headers=github_headers(),
                params={"ref": branch},
                timeout=10,
            )
            if current.status_code == 200:
                content = base64.b64decode(current.json()["content"]).decode("utf-8")
                old = pd.read_csv(io.StringIO(content), sep=";")
                rows = old[["spieler", "team"]].to_dict("records")
            rows = [
                row for row in rows
                if score_key(row["spieler"], row["team"]) in removals
            ]
            payload = {
                "message": "Remove player",
                "content": base64.b64encode(
                    pd.DataFrame(rows).to_csv(index=False, sep=";").encode("utf-8")
                ).decode("ascii"),
                "branch": branch,
            }
            if current.status_code == 200:
                payload["sha"] = current.json()["sha"]
            requests.put(
                endpoint,
                headers=github_headers(),
                json=payload,
                timeout=10,
            ).raise_for_status()
            return True

        existing = (
            pd.read_csv(PLAYER_REMOVALS_PATH, sep=";", encoding="utf-8")
            if PLAYER_REMOVALS_PATH.exists()
            else pd.DataFrame(columns=["spieler", "team"])
        )
        existing = pd.concat([existing, pd.DataFrame(rows)], ignore_index=True)
        existing = existing.drop_duplicates(subset=["spieler", "team"])
        PLAYER_REMOVALS_PATH.parent.mkdir(parents=True, exist_ok=True)
        existing.to_csv(PLAYER_REMOVALS_PATH, index=False, sep=";", encoding="utf-8")
        return True
    except (OSError, requests.RequestException) as exc:
        st.error(f"Spieler konnte nicht entfernt werden: {exc}")
        return False


def load_roster_overrides() -> dict[str, bool]:
    """Lädt die gespeicherten Markierungen für den eigenen Kader."""
    try:
        if github_configured():
            repo = github_setting("GITHUB_REPO")
            branch = github_setting("GITHUB_BRANCH", "main")
            path = github_setting(
                "GITHUB_ROSTER_OVERRIDES_PATH",
                "data/processed/roster_overrides.csv",
            )
            response = requests.get(
                f"{GITHUB_API}/repos/{repo}/contents/{path}",
                headers=github_headers(),
                params={"ref": branch},
                timeout=10,
            )
            if response.status_code == 404:
                return {}
            response.raise_for_status()
            content = base64.b64decode(response.json()["content"]).decode("utf-8")
            overrides = pd.read_csv(io.StringIO(content), sep=";")
        else:
            if not ROSTER_OVERRIDES_PATH.exists():
                return {}
            overrides = pd.read_csv(ROSTER_OVERRIDES_PATH, sep=";", encoding="utf-8")
    except (OSError, UnicodeDecodeError, pd.errors.ParserError, requests.RequestException) as exc:
        st.error(f"Kader-Markierungen konnten nicht geladen werden: {exc}")
        return {}

    if not {"spieler", "team", "im_kader"}.issubset(overrides.columns):
        return {}

    return {
        score_key(row["spieler"], row["team"]): str(
            row["im_kader"]
        ).strip().casefold() in {"true", "1", "yes", "ja"}
        for _, row in overrides.iterrows()
    }


def apply_roster_overrides(df: pd.DataFrame) -> pd.DataFrame:
    """Fügt die Kader-Markierung hinzu und wendet gespeicherte Werte an."""
    df = df.copy()
    player_col = find_column(df, ["spieler", "player", "name"])
    team_col = find_column(df, ["team", "verein", "club"])
    if player_col is None or team_col is None:
        return df

    overrides = load_roster_overrides()
    df["im_kader"] = False
    for index, row in df.iterrows():
        key = score_key(row[player_col], row[team_col])
        if key in overrides:
            df.at[index, "im_kader"] = overrides[key]
    return df


def github_setting(name: str, default: str = "") -> str:
    """Liest Deployment-Konfiguration aus Streamlit Secrets oder Umgebungsvariablen."""
    try:
        value = st.secrets.get(name, default)
    except Exception:
        value = os.getenv(name, default)
    return str(value or default).strip()


def github_configured() -> bool:
    """Prüft, ob die App Scores in GitHub persistieren soll."""
    return bool(
        github_setting("GITHUB_TOKEN")
        and github_setting("GITHUB_REPO")
    )


def github_file() -> tuple[str, str]:
    """Liefert Repository-Pfad und Branch für die Override-Datei."""
    path = github_setting(
        "GITHUB_OVERRIDES_PATH",
        "data/processed/maik_score_overrides.csv",
    )
    branch = github_setting("GITHUB_BRANCH", "main")
    return path, branch


def github_headers() -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {github_setting('GITHUB_TOKEN')}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def load_github_overrides() -> pd.DataFrame | None:
    """Lädt die Override-CSV aus GitHub; None bedeutet: kein GitHub-Backend."""
    if not github_configured():
        return None

    repo = github_setting("GITHUB_REPO")
    path, branch = github_file()
    response = requests.get(
        f"{GITHUB_API}/repos/{repo}/contents/{path}",
        headers=github_headers(),
        params={"ref": branch},
        timeout=10,
    )
    if response.status_code == 404:
        return pd.DataFrame(columns=["spieler", "team", "maik_score", "updated_at"])
    response.raise_for_status()
    payload = response.json()
    content = base64.b64decode(payload["content"]).decode("utf-8")
    return pd.read_csv(io.StringIO(content), sep=";")


def load_team_score_overrides() -> dict[str, float]:
    """Lädt Team-Scores, die für alle Spieler des Teams gelten."""
    try:
        if github_configured():
            repo = github_setting("GITHUB_REPO")
            branch = github_setting("GITHUB_BRANCH", "main")
            path = github_setting(
                "GITHUB_TEAM_OVERRIDES_PATH",
                "data/processed/team_score_overrides.csv",
            )
            response = requests.get(
                f"{GITHUB_API}/repos/{repo}/contents/{path}",
                headers=github_headers(),
                params={"ref": branch},
                timeout=10,
            )
            if response.status_code == 404:
                return {}
            response.raise_for_status()
            content = base64.b64decode(response.json()["content"]).decode("utf-8")
            overrides = pd.read_csv(io.StringIO(content), sep=";")
        else:
            if not TEAM_SCORE_OVERRIDES_PATH.exists():
                return {}
            overrides = pd.read_csv(TEAM_SCORE_OVERRIDES_PATH, sep=";", encoding="utf-8")
    except (OSError, UnicodeDecodeError, pd.errors.ParserError, requests.RequestException) as exc:
        st.error(f"Team-Scores konnten nicht geladen werden: {exc}")
        return {}

    if not {"team", "team_score"}.issubset(overrides.columns):
        return {}

    result = {}
    for _, row in overrides.iterrows():
        value = pd.to_numeric(row["team_score"], errors="coerce")
        if pd.notna(value):
            result[normalize_key_part(row["team"])] = float(value)
    return result


def apply_team_score_overrides(df: pd.DataFrame) -> pd.DataFrame:
    """Wendet einen Team-Score auf jede Zeile dieses Teams an."""
    df = df.copy()
    team_col = find_column(df, ["team", "verein", "club"])
    score_col = find_column(df, ["maik_kaderscore_team", "team_score"])
    if team_col is None or score_col is None:
        return df

    team_scores = load_team_score_overrides()
    for index, team in df[team_col].items():
        score = team_scores.get(normalize_key_part(team))
        if score is not None:
            df.at[index, score_col] = score
    return df


def load_score_overrides() -> dict[str, float]:
    """Lädt manuelle Scores, falls bereits eine Override-Datei existiert."""
    try:
        overrides = load_github_overrides()
        if overrides is None:
            if not SCORE_OVERRIDES_PATH.exists():
                return {}
            overrides = pd.read_csv(SCORE_OVERRIDES_PATH, sep=";", encoding="utf-8")
    except (OSError, UnicodeDecodeError, pd.errors.ParserError, requests.RequestException) as exc:
        st.error(f"Maik-Score-Overrides konnten nicht geladen werden: {exc}")
        return {}

    required = {"spieler", "team", "maik_score"}
    if not required.issubset(overrides.columns):
        st.error(
            "Die Override-Datei braucht die Spalten: "
            "spieler, team, maik_score."
        )
        return {}

    result = {}
    for _, row in overrides.iterrows():
        value = pd.to_numeric(row["maik_score"], errors="coerce")
        if pd.notna(value):
            result[score_key(row["spieler"], row["team"])] = float(value)
    return result


def apply_score_overrides(df: pd.DataFrame) -> pd.DataFrame:
    """Legt manuelle Scores über importierte Werte, ohne die Importdatei zu ändern."""
    df = df.copy()
    if "maik_score" not in df.columns:
        return df

    player_col = find_column(df, ["spieler", "player", "name"])
    team_col = find_column(df, ["team", "verein", "club"])
    if player_col is None or team_col is None:
        return df

    overrides = load_score_overrides()
    if not overrides:
        return df

    for index, row in df.iterrows():
        key = score_key(row[player_col], row[team_col])
        if key in overrides:
            df.at[index, "maik_score"] = overrides[key]
    return df


def save_score_overrides(updates: dict[str, dict[str, object]]) -> bool:
    """Speichert nur manuelle Score-Änderungen in einer separaten CSV."""
    try:
        source = load_github_overrides()
        if source is None:
            if SCORE_OVERRIDES_PATH.exists():
                source = pd.read_csv(SCORE_OVERRIDES_PATH, sep=";")
            else:
                source = pd.DataFrame()
    except (OSError, UnicodeDecodeError, pd.errors.ParserError, requests.RequestException) as exc:
        st.error(f"Bestehende Maik-Scores konnten nicht geladen werden: {exc}")
        return False

    existing = {
        score_key(row["spieler"], row["team"]): row.to_dict()
        for _, row in source.iterrows()
        if {"spieler", "team", "maik_score"}.issubset(row.index)
    }

    for key, update in updates.items():
        value = pd.to_numeric(update["maik_score"], errors="coerce")
        if pd.isna(value):
            existing.pop(key, None)
        else:
            existing[key] = {
                "spieler": update["spieler"],
                "team": update["team"],
                "maik_score": float(value),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

    result = pd.DataFrame(
        list(existing.values()),
        columns=["spieler", "team", "maik_score", "updated_at"],
    )
    if github_configured():
        try:
            repo = github_setting("GITHUB_REPO")
            path, branch = github_file()
            endpoint = f"{GITHUB_API}/repos/{repo}/contents/{path}"
            current = requests.get(
                endpoint,
                headers=github_headers(),
                params={"ref": branch},
                timeout=10,
            )
            sha = current.json().get("sha") if current.status_code == 200 else None
            content = result.to_csv(index=False, sep=";").encode("utf-8")
            payload = {
                "message": "Update Maik scores",
                "content": base64.b64encode(content).decode("ascii"),
                "branch": branch,
            }
            if sha:
                payload["sha"] = sha
            saved = requests.put(
                endpoint,
                headers=github_headers(),
                json=payload,
                timeout=10,
            )
            saved.raise_for_status()
            return True
        except requests.RequestException as exc:
            st.error(f"Maik-Scores konnten nicht zu GitHub gespeichert werden: {exc}")
            return False

    try:
        SCORE_OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
        result.to_csv(SCORE_OVERRIDES_PATH, index=False, sep=";", encoding="utf-8")
        return True
    except OSError as exc:
        st.error(f"Maik-Scores konnten nicht gespeichert werden: {exc}")
        return False


def save_roster_overrides(updates: dict[str, dict[str, object]]) -> bool:
    """Speichert die Markierung, ob ein Spieler im eigenen Kader ist."""
    existing = load_roster_overrides()
    for key, update in updates.items():
        existing[key] = bool(update["im_kader"])

    rows = [
        {
            "spieler": update["spieler"],
            "team": update["team"],
            "im_kader": existing[key],
        }
        for key, update in updates.items()
        if existing[key]
    ]

    if github_configured():
        try:
            repo = github_setting("GITHUB_REPO")
            branch = github_setting("GITHUB_BRANCH", "main")
            path = github_setting(
                "GITHUB_ROSTER_OVERRIDES_PATH",
                "data/processed/roster_overrides.csv",
            )
            endpoint = f"{GITHUB_API}/repos/{repo}/contents/{path}"
            current = requests.get(
                endpoint,
                headers=github_headers(),
                params={"ref": branch},
                timeout=10,
            )
            sha = current.json().get("sha") if current.status_code == 200 else None
            result = pd.DataFrame(rows, columns=["spieler", "team", "im_kader"])
            payload = {
                "message": "Update roster marks",
                "content": base64.b64encode(
                    result.to_csv(index=False, sep=";").encode("utf-8")
                ).decode("ascii"),
                "branch": branch,
            }
            if sha:
                payload["sha"] = sha
            requests.put(
                endpoint,
                headers=github_headers(),
                json=payload,
                timeout=10,
            ).raise_for_status()
            return True
        except requests.RequestException as exc:
            st.error(f"Kader-Markierungen konnten nicht zu GitHub gespeichert werden: {exc}")
            return False

    try:
        ROSTER_OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows, columns=["spieler", "team", "im_kader"]).to_csv(
            ROSTER_OVERRIDES_PATH,
            index=False,
            sep=";",
            encoding="utf-8",
        )
        return True
    except OSError as exc:
        st.error(f"Kader-Markierungen konnten nicht gespeichert werden: {exc}")
        return False


def save_team_score_overrides(updates: dict[str, object]) -> bool:
    """Speichert einen Team-Score, der für das gesamte Team gilt."""
    existing = load_team_score_overrides()
    existing.update(
        {
            normalize_key_part(team): value
            for team, value in updates.items()
        }
    )

    rows = []
    for team, value in existing.items():
        if isinstance(value, dict):
            value = value.get("team_score")
        numeric_value = pd.to_numeric(value, errors="coerce")
        if pd.notna(numeric_value):
            rows.append({"team": team, "team_score": float(numeric_value)})

    result = pd.DataFrame(rows, columns=["team", "team_score"])
    try:
        if github_configured():
            repo = github_setting("GITHUB_REPO")
            branch = github_setting("GITHUB_BRANCH", "main")
            path = github_setting(
                "GITHUB_TEAM_OVERRIDES_PATH",
                "data/processed/team_score_overrides.csv",
            )
            endpoint = f"{GITHUB_API}/repos/{repo}/contents/{path}"
            current = requests.get(
                endpoint,
                headers=github_headers(),
                params={"ref": branch},
                timeout=10,
            )
            sha = current.json().get("sha") if current.status_code == 200 else None
            payload = {
                "message": "Update team scores",
                "content": base64.b64encode(
                    result.to_csv(index=False, sep=";").encode("utf-8")
                ).decode("ascii"),
                "branch": branch,
            }
            if sha:
                payload["sha"] = sha
            requests.put(
                endpoint,
                headers=github_headers(),
                json=payload,
                timeout=10,
            ).raise_for_status()
            return True

        TEAM_SCORE_OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
        result.to_csv(
            TEAM_SCORE_OVERRIDES_PATH,
            index=False,
            sep=";",
            encoding="utf-8",
        )
        return True
    except (OSError, requests.RequestException) as exc:
        st.error(f"Team-Scores konnten nicht gespeichert werden: {exc}")
        return False


def save_csv(df: pd.DataFrame) -> bool:
    """Speichert den kompletten DataFrame wieder in die Original-CSV."""
    try:
        CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(
            CSV_PATH,
            index=False,
            sep=";",
            encoding="utf-8",
        )
        return True
    except Exception as exc:
        st.error(f"CSV konnte nicht gespeichert werden: {exc}")
        return False


def find_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    """
    Findet eine Spalte unabhängig von Groß-/Kleinschreibung,
    Leerzeichen und kleinen Namensabweichungen.
    """
    normalized = {
        str(col).strip().lower().replace(" ", "_"): col
        for col in df.columns
    }

    for candidate in candidates:
        key = candidate.strip().lower().replace(" ", "_")
        if key in normalized:
            return normalized[key]

    return None


def ensure_score_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Stellt sicher, dass die für die Oberfläche verwendeten Score-Spalten
    vorhanden sind.

    Wichtig:
    'durchschnitt_pts' wird NICHT blind vorausgesetzt. Die vorhandene
    Kickbase-Spalte 'Ø Punkte', 'durchschnitt_pts', 'avg_pts' usw. wird
    erkannt und intern als 'durchschnitt_pts' verfügbar gemacht.
    """
    df = df.copy()

    # --------------------------------------------------------
    # Kickbase Durchschnittspunkte
    # --------------------------------------------------------
    avg_col = find_column(
        df,
        [
            "durchschnitt_pts",
            "durchschnitt_punkte",
            "Ø Punkte",
            "ø_punkte",
            "avg_pts",
            "average_pts",
            "average_points",
        ],
    )

    if avg_col is not None:
        if avg_col != "durchschnitt_pts":
            df["durchschnitt_pts"] = pd.to_numeric(
                df[avg_col], errors="coerce"
            )
        else:
            df["durchschnitt_pts"] = pd.to_numeric(
                df["durchschnitt_pts"], errors="coerce"
            )
    else:
        # Die Spalte wird angelegt, damit die App nicht mehr mit
        # KeyError abstürzt.
        df["durchschnitt_pts"] = pd.NA

    # --------------------------------------------------------
    # MAIK Score
    # --------------------------------------------------------
    maik_col = find_column(
        df,
        [
            "maik_score",
            "MAIK Score",
            "maik_ai_score",
            "MAIK AI Score",
            "score",
        ],
    )

    if maik_col is not None:
        df["maik_score"] = pd.to_numeric(
            df[maik_col], errors="coerce"
        )
    else:
        df["maik_score"] = pd.NA

    # --------------------------------------------------------
    # Kickbase Punkte
    # --------------------------------------------------------
    points_col = find_column(
        df,
        [
            "punkte",
            "points",
            "kickbase_punkte",
            "kickbase_points",
        ],
    )

    if points_col is not None:
        df["punkte"] = pd.to_numeric(
            df[points_col], errors="coerce"
        )
    else:
        df["punkte"] = pd.NA

    return df


def numeric_columns(df: pd.DataFrame) -> list[str]:
    """Gibt Spalten zurück, die sinnvoll numerisch formatiert werden können."""
    result = []

    for col in df.columns:
        if pd.api.types.is_numeric_dtype(df[col]):
            result.append(col)

    return result


def make_unique_key(df: pd.DataFrame) -> pd.DataFrame:
    """
    Erstellt einen stabilen internen Zeilen-Key.

    Der Key wird nicht in die CSV geschrieben.
    """
    df = df.copy()
    df["_editor_id"] = range(len(df))
    return df


def restore_original_columns(
    edited_df: pd.DataFrame,
    original_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Überträgt Änderungen aus der Oberfläche zurück auf die originale
    CSV-Struktur.

    Zusätzliche interne Spalten werden nicht gespeichert.
    """
    result = original_df.copy()

    # Falls die Anzeige interne Hilfsspalten enthält, ignorieren.
    edited = edited_df.copy()
    edited = edited.drop(
        columns=["_editor_id"],
        errors="ignore",
    )

    # --------------------------------------------------------
    # Änderungen an vorhandenen Originalspalten übernehmen.
    # --------------------------------------------------------
    for col in original_df.columns:
        if col in edited.columns:
            result[col] = edited[col].values

    # --------------------------------------------------------
    # Falls eine vorhandene Originalspalte anders heißt, werden
    # die intern normalisierten Werte zurückgeschrieben.
    # --------------------------------------------------------

    # durchschnitt_pts -> tatsächliche CSV-Spalte
    avg_original = find_column(
        original_df,
        [
            "durchschnitt_pts",
            "durchschnitt_punkte",
            "Ø Punkte",
            "ø_punkte",
            "avg_pts",
            "average_pts",
            "average_points",
        ],
    )

    if avg_original is not None and "durchschnitt_pts" in edited.columns:
        result[avg_original] = pd.to_numeric(
            edited["durchschnitt_pts"],
            errors="coerce",
        ).values

    # maik_score -> tatsächliche CSV-Spalte
    maik_original = find_column(
        original_df,
        [
            "maik_score",
            "MAIK Score",
            "maik_ai_score",
            "MAIK AI Score",
            "score",
        ],
    )

    if maik_original is not None and "maik_score" in edited.columns:
        result[maik_original] = pd.to_numeric(
            edited["maik_score"],
            errors="coerce",
        ).values

    # punkte -> tatsächliche CSV-Spalte
    points_original = find_column(
        original_df,
        [
            "punkte",
            "points",
            "kickbase_punkte",
            "kickbase_points",
        ],
    )

    if points_original is not None and "punkte" in edited.columns:
        result[points_original] = pd.to_numeric(
            edited["punkte"],
            errors="coerce",
        ).values

    return result


def search_dataframe(
    df: pd.DataFrame,
    search: str,
) -> pd.DataFrame:
    """Sucht über alle Text-/Spielerspalten."""
    if not search:
        return df

    search = search.strip().lower()

    mask = pd.Series(False, index=df.index)

    for col in df.columns:
        try:
            mask |= (
                df[col]
                .astype(str)
                .str.lower()
                .str.contains(search, na=False)
            )
        except Exception:
            pass

    return df.loc[mask].copy()


# ============================================================
# Streamlit App
# ============================================================

def main() -> None:
    st.set_page_config(
        page_title="Kickbase Spielereditor",
        page_icon="⚽",
        layout="wide",
    )

    st.title("Kickbase Spielereditor")

    # --------------------------------------------------------
    # Initiales Laden
    # --------------------------------------------------------
    if "df" not in st.session_state:
        st.session_state.df = load_csv()

    if "original_df" not in st.session_state:
        st.session_state.original_df = st.session_state.df.copy()

    if st.session_state.df.empty:
        st.stop()

    # Normalisierte Hilfsspalten sicherstellen.
    st.session_state.df = ensure_score_columns(
        st.session_state.df
    )

    # --------------------------------------------------------
    # Sidebar
    # --------------------------------------------------------
    with st.sidebar:
        st.header("Optionen")

        search = st.text_input(
            "Spieler suchen",
            placeholder="z. B. Neuhaus",
        )

        show_only_maik = st.checkbox(
            "Nur Spieler mit MAIK Score",
            value=False,
        )

        st.divider()

        st.subheader("Spieler schnell hinzufügen")
        team_options = sorted(
            str(team)
            for team in st.session_state.df["team"].dropna().unique()
        )
        position_options = ["Torhüter", "Abwehr", "Mittelfeld", "Sturm"]
        with st.form("add_player_form", clear_on_submit=True):
            new_player = st.text_input("Spielername")
            new_team = st.selectbox("Team", team_options)
            new_position = st.selectbox("Position", position_options)
            new_score = st.number_input(
                "MAIK Score",
                min_value=0.0,
                max_value=10000.0,
                step=0.1,
                value=0.0,
            )
            add_player = st.form_submit_button(
                "Spieler hinzufügen",
                use_container_width=True,
            )

        if add_player:
            if not new_player.strip():
                st.warning("Bitte einen Spielernamen eingeben.")
            elif save_player_addition(
                new_player.strip(),
                new_team,
                new_position,
                new_score,
            ):
                fresh = ensure_score_columns(load_csv())
                st.session_state.df = fresh
                st.session_state.original_df = fresh.copy()
                st.session_state.pop("player_editor", None)
                st.success(f"{new_player.strip()} wurde hinzugefügt.")
                st.rerun()

        st.subheader("Spieler entfernen")
        removable_players = [
            (str(row["spieler"]), str(row["team"]))
            for _, row in st.session_state.df.iterrows()
        ]
        removable_labels = [
            f"{player} — {team}" for player, team in removable_players
        ]
        with st.form("remove_player_form", clear_on_submit=True):
            selected_label = st.selectbox(
                "Spieler auswählen",
                removable_labels,
            )
            remove_player = st.form_submit_button(
                "Spieler entfernen",
                use_container_width=True,
            )

        if remove_player:
            selected_index = removable_labels.index(selected_label)
            selected_player, selected_team = removable_players[selected_index]
            if save_player_removal(selected_player, selected_team):
                fresh = ensure_score_columns(load_csv())
                st.session_state.df = fresh
                st.session_state.original_df = fresh.copy()
                st.session_state.pop("player_editor", None)
                st.success(f"{selected_player} wurde entfernt.")
                st.rerun()

        if st.button(
            "CSV neu laden",
            use_container_width=True,
        ):
            fresh = load_csv()

            if not fresh.empty:
                fresh = ensure_score_columns(fresh)
                st.session_state.df = fresh
                st.session_state.original_df = fresh.copy()

                # Editor zurücksetzen
                st.session_state.pop("player_editor", None)

                st.rerun()

        if st.button(
            "Änderungen speichern",
            type="primary",
            use_container_width=True,
        ):
            if "edited_data" not in st.session_state:
                st.warning(
                    "Es wurden noch keine Änderungen im Editor erkannt."
                )
            else:
                edited = st.session_state.edited_data

                updates = {}
                for _, row in edited.iterrows():
                    player = row.get("spieler", row.get("Spieler", ""))
                    team = row.get("team", row.get("Team", ""))
                    if normalize_key_part(player) and normalize_key_part(team):
                        updates[score_key(player, team)] = {
                            "spieler": player,
                            "team": team,
                            "maik_score": row.get("maik_score"),
                        }

                roster_updates = {}
                roster_source = st.session_state.df
                for _, row in roster_source.iterrows():
                    player = row.get("spieler", "")
                    team = row.get("team", "")
                    if normalize_key_part(player) and normalize_key_part(team):
                        roster_updates[score_key(player, team)] = {
                            "spieler": player,
                            "team": team,
                            "im_kader": row.get("im_kader", False),
                        }
                for _, row in edited.iterrows():
                    player = row.get("spieler", "")
                    team = row.get("team", "")
                    key = score_key(player, team)
                    if key in roster_updates:
                        roster_updates[key]["im_kader"] = row.get(
                            "im_kader", False
                        )

                team_updates = {}
                team_editor = st.session_state.get("team_editor_data")
                if team_editor is not None:
                    for _, row in team_editor.iterrows():
                        team = row.get("team", "")
                        if normalize_key_part(team):
                            team_updates[normalize_key_part(team)] = {
                                "team": team,
                                "team_score": row.get("team_score"),
                            }

                if (
                    save_score_overrides(updates)
                    and save_roster_overrides(roster_updates)
                    and save_team_score_overrides(team_updates)
                ):
                    fresh = load_csv()
                    if not fresh.empty:
                        fresh = ensure_score_columns(fresh)
                        st.session_state.df = fresh
                        st.session_state.original_df = fresh.copy()
                        st.session_state.pop("edited_data", None)
                        st.session_state.pop("player_editor", None)
                        st.session_state.pop("team_editor_data", None)

                    st.success(
                        "Maik-Scores, Kader-Markierungen und Team-Scores gespeichert."
                    )
                    st.rerun()

        st.divider()

        st.caption(f"CSV: `{CSV_PATH}`")
        st.caption(f"MAIK-Overrides: `{SCORE_OVERRIDES_PATH}`")
        st.caption(f"Team-Overrides: `{TEAM_SCORE_OVERRIDES_PATH}`")

    # --------------------------------------------------------
    # Daten vorbereiten
    # --------------------------------------------------------
    df = st.session_state.df.copy()

    # Suchfilter
    display_df = search_dataframe(df, search)

    # MAIK Filter
    if show_only_maik:
        display_df = display_df[
            pd.to_numeric(
                display_df["maik_score"],
                errors="coerce",
            ).notna()
        ].copy()

    # Stabiler Editor-Key
    display_df = display_df.reset_index(drop=True)
    display_df = make_unique_key(display_df)

    # --------------------------------------------------------
    # KPI-Zeile
    # --------------------------------------------------------
    total_players = len(df)
    visible_players = len(display_df)

    maik_values = pd.to_numeric(
        df["maik_score"],
        errors="coerce",
    )

    avg_values = pd.to_numeric(
        df["durchschnitt_pts"],
        errors="coerce",
    )

    c1, c2, c3, c4 = st.columns(4)

    c1.metric(
        "Spieler",
        total_players,
    )

    c2.metric(
        "Angezeigt",
        visible_players,
    )

    c3.metric(
        "MAIK Scores",
        int(maik_values.notna().sum()),
    )

    if avg_values.notna().any():
        c4.metric(
            "Ø Punkte",
            f"{avg_values.mean():.1f}",
        )
    else:
        c4.metric(
            "Ø Punkte",
            "–",
        )

    st.divider()

    export_columns = [
        col
        for col in [
            "spieler",
            "team",
            "marktwert",
            "punkte",
            "durchschnitt_pts",
            "maik_score",
            "maik_kaderscore_team",
        ]
        if col in df.columns
    ]
    download_csv = df[export_columns].to_csv(
        index=False,
        sep=";",
        encoding="utf-8-sig",
    ).encode("utf-8-sig")

    st.download_button(
        "Spielerdaten als CSV herunterladen",
        data=download_csv,
        file_name="kickbase_spieler_mit_maik_scores.csv",
        mime="text/csv",
        use_container_width=True,
    )

    # --------------------------------------------------------
    # Spaltenauswahl
    # --------------------------------------------------------
    visible_columns = [
        col
        for col in [
            "spieler",
            "team",
            "marktwert",
            "punkte",
            "durchschnitt_pts",
            "maik_score",
            "im_kader",
        ]
        if col in display_df.columns
    ]

    editor_df = display_df[
        ["_editor_id"] + visible_columns
    ].copy()

    # --------------------------------------------------------
    # Datentypen für Editierbarkeit
    # --------------------------------------------------------
    for col in ["maik_score", "marktwert"]:
        if col in editor_df.columns:
            editor_df[col] = pd.to_numeric(
                editor_df[col],
                errors="coerce",
            )

    # --------------------------------------------------------
    # Editor
    # --------------------------------------------------------
    st.subheader("Spielerdaten")

    st.caption(
        "MAIK Score und Kader-Markierung bearbeiten, danach links speichern."
    )

    disabled_columns = [
        col for col in editor_df.columns
        if col not in {"maik_score", "im_kader"}
    ]

    column_config = {
        "_editor_id": st.column_config.NumberColumn(
            "ID",
            disabled=True,
            width="small",
        ),
    }

    if "maik_score" in editor_df.columns:
        column_config["maik_score"] = st.column_config.NumberColumn(
            "MAIK Score",
            min_value=0,
            max_value=10000,
            step=0.1,
            format="%.1f",
        )

    if "im_kader" in editor_df.columns:
        column_config["im_kader"] = st.column_config.CheckboxColumn(
            "Mein Kader",
            help="Spieler für den eigenen Kader markieren.",
        )

    if "durchschnitt_pts" in editor_df.columns:
        column_config["durchschnitt_pts"] = st.column_config.NumberColumn(
            "Ø Punkte",
            step=0.1,
            format="%.1f",
        )

    if "punkte" in editor_df.columns:
        column_config["punkte"] = st.column_config.NumberColumn(
            "Punkte",
            step=1,
        )

    if "marktwert" in editor_df.columns:
        column_config["marktwert"] = st.column_config.NumberColumn(
            "Marktwert",
            format="%.0f",
        )

    if "maik_fmv_mio" in editor_df.columns:
        column_config["maik_fmv_mio"] = st.column_config.NumberColumn(
            "MAIK FMV Mio.",
            step=0.01,
            format="%.2f",
        )

    if "maik_rang" in editor_df.columns:
        column_config["maik_rang"] = st.column_config.NumberColumn(
            "MAIK Rang",
            step=1,
        )

    if "maik_kaderscore" in editor_df.columns:
        column_config["maik_kaderscore"] = st.column_config.NumberColumn(
            "MAIK Kaderscore",
            step=0.1,
            format="%.1f",
        )

    edited_data = st.data_editor(
        editor_df,
        key="player_editor",
        hide_index=True,
        use_container_width=True,
        num_rows="fixed",
        disabled=disabled_columns,
        column_config=column_config,
    )

    marked_players = df[df["im_kader"]].copy()
    st.subheader("Mein Kader")
    if marked_players.empty:
        st.info("Noch keine Spieler markiert.")
    else:
        squad_columns = [
            col
            for col in [
                "spieler",
                "team",
                "position",
                "marktwert",
                "punkte",
                "durchschnitt_pts",
                "maik_score",
            ]
            if col in marked_players.columns
        ]
        st.dataframe(
            marked_players[squad_columns].sort_values(
                ["position", "maik_score"],
                ascending=[True, False],
                na_position="last",
            ),
            hide_index=True,
            use_container_width=True,
        )
        squad_csv = marked_players[squad_columns].to_csv(
            index=False,
            sep=";",
            encoding="utf-8-sig",
        ).encode("utf-8-sig")
        st.download_button(
            "Meinen Kader als CSV herunterladen",
            data=squad_csv,
            file_name="mein_kader.csv",
            mime="text/csv",
            use_container_width=True,
        )

    st.subheader("Team-Scores")

    team_score_column = find_column(
        display_df,
        ["maik_kaderscore_team", "team_score"],
    )
    team_column = find_column(display_df, ["team", "verein", "club"])
    if team_score_column and team_column:
        team_editor_df = (
            display_df[[team_column, team_score_column]]
            .drop_duplicates(subset=[team_column])
            .rename(columns={team_column: "team", team_score_column: "team_score"})
            .reset_index(drop=True)
        )
        team_editor_df["team_score"] = pd.to_numeric(
            team_editor_df["team_score"], errors="coerce"
        )
        edited_team_data = st.data_editor(
            team_editor_df,
            key="team_editor",
            hide_index=True,
            use_container_width=True,
            num_rows="fixed",
            disabled=["team"],
            column_config={
                "team_score": st.column_config.NumberColumn(
                    "Team Score", min_value=0, step=0.1, format="%.1f"
                )
            },
        )
        st.session_state.team_editor_data = edited_team_data.copy()

    st.subheader("MAIK Score nach Position")
    position_col = find_column(display_df, ["position", "pos"])
    if position_col:
        position_columns = [
            col
            for col in ["spieler", "team", "maik_score", "marktwert"]
            if col in display_df.columns
        ]
        for position, position_players in (
            df.groupby(position_col, dropna=False, sort=True)
        ):
            position_name = str(position) if pd.notna(position) else "Ohne Position"
            position_players = position_players.sort_values(
                "maik_score", ascending=False, na_position="last"
            )
            with st.expander(position_name):
                st.dataframe(
                    position_players[position_columns],
                    hide_index=True,
                    use_container_width=True,
                )

    st.subheader("MAIK- und Kickbase-Value-Dashboard")
    dashboard = df.copy()
    dashboard["maik_score"] = pd.to_numeric(
        dashboard["maik_score"], errors="coerce"
    )
    dashboard["punkte"] = pd.to_numeric(
        dashboard["punkte"], errors="coerce"
    )
    dashboard["durchschnitt_pts"] = pd.to_numeric(
        dashboard["durchschnitt_pts"], errors="coerce"
    )
    dashboard["marktwert_num"] = pd.to_numeric(
        dashboard["marktwert"], errors="coerce"
    )
    if dashboard["marktwert_num"].median() > 100000:
        dashboard["marktwert_mio"] = dashboard["marktwert_num"] / 1_000_000
    else:
        dashboard["marktwert_mio"] = dashboard["marktwert_num"]

    valid_value = dashboard[
        (dashboard["marktwert_mio"] > 0)
        & dashboard["maik_score"].notna()
        & dashboard["durchschnitt_pts"].notna()
    ].copy()
    valid_value["maik_value"] = (
        valid_value["maik_score"] / valid_value["marktwert_mio"]
    )
    valid_value["kickbase_value"] = (
        valid_value["durchschnitt_pts"] / valid_value["marktwert_mio"]
    )

    d1, d2, d3, d4 = st.columns(4)
    if valid_value.empty:
        d1.metric("Maik Score / Mio.", "-")
        d2.metric("Ø Punkte / Mio.", "-")
        d3.metric("Korrelation", "-")
        d4.metric("Top-10 Übereinstimmung", "-")
    else:
        d1.metric("Maik Score / Mio.", f"{valid_value['maik_value'].median():.1f}")
        d2.metric(
            "Ø Punkte / Mio.",
            f"{valid_value['kickbase_value'].median():.1f}",
        )
        correlation = valid_value["maik_score"].corr(
            valid_value["durchschnitt_pts"]
        )
        d3.metric(
            "Korrelation Maik / Ø Punkte",
            f"{correlation:.2f}" if pd.notna(correlation) else "-",
        )
        maik_top = set(
            valid_value.nlargest(min(10, len(valid_value)), "maik_value")[
                "spieler"
            ]
        )
        kickbase_top = set(
            valid_value.nlargest(min(10, len(valid_value)), "kickbase_value")[
                "spieler"
            ]
        )
        overlap = len(maik_top & kickbase_top) / max(len(maik_top), 1) * 100
        d4.metric("Top-10 Übereinstimmung", f"{overlap:.0f}%")

    st.caption(
        "Maik Value = Maik Score / Marktwert in Mio. | "
        "Kickbase Value = durchschnittliche Kickbase-Punkte / Marktwert in Mio. | "
        "Korrelation und Top-10-Übereinstimmung zeigen, wie gut beide Signale zusammenpassen."
    )

    st.subheader("Team-Score vs. Kickbase-Performance")
    team_col = find_column(dashboard, ["team", "verein", "club"])
    team_score_col = find_column(
        dashboard,
        ["maik_kaderscore_team", "team_score"],
    )
    if team_col and team_score_col:
        team_dashboard = dashboard.copy()
        team_dashboard[team_score_col] = pd.to_numeric(
            team_dashboard[team_score_col], errors="coerce"
        )
        team_dashboard = (
            team_dashboard.dropna(subset=[team_col])
            .groupby(team_col, as_index=False)
            .agg(
                maik_team_score=(team_score_col, "mean"),
                kickbase_avg_points=("durchschnitt_pts", "mean"),
                players=("spieler", "count"),
            )
            .dropna(subset=["maik_team_score", "kickbase_avg_points"])
        )
        team_dashboard["maik_rank"] = team_dashboard[
            "maik_team_score"
        ].rank(ascending=False, method="min")
        team_dashboard["kickbase_rank"] = team_dashboard[
            "kickbase_avg_points"
        ].rank(ascending=False, method="min")

        t1, t2, t3, t4 = st.columns(4)
        team_correlation = team_dashboard["maik_team_score"].corr(
            team_dashboard["kickbase_avg_points"]
        )
        top_count = min(5, len(team_dashboard))
        maik_teams = set(
            team_dashboard.nlargest(top_count, "maik_team_score")[team_col]
        )
        kickbase_teams = set(
            team_dashboard.nlargest(top_count, "kickbase_avg_points")[team_col]
        )
        team_overlap = len(maik_teams & kickbase_teams) / max(top_count, 1) * 100
        t1.metric("Team-Korrelation", f"{team_correlation:.2f}")
        t2.metric(
            "Ø Team-Score",
            f"{team_dashboard['maik_team_score'].mean():.0f}",
        )
        t3.metric(
            "Ø Kickbase-Team-Punkte",
            f"{team_dashboard['kickbase_avg_points'].mean():.1f}",
        )
        t4.metric("Top-5-Team-Übereinstimmung", f"{team_overlap:.0f}%")

        team_table = team_dashboard.rename(
            columns={
                team_col: "Team",
                "maik_team_score": "MAIK Team Score",
                "kickbase_avg_points": "Kickbase Ø Punkte",
                "players": "Spieler",
                "maik_rank": "MAIK Rang",
                "kickbase_rank": "Kickbase Rang",
            }
        )
        st.dataframe(
            team_table[
                [
                    "Team",
                    "MAIK Team Score",
                    "Kickbase Ø Punkte",
                    "MAIK Rang",
                    "Kickbase Rang",
                    "Spieler",
                ]
            ].sort_values("MAIK Team Score", ascending=False),
            hide_index=True,
            use_container_width=True,
        )
        st.caption(
            "Die Team-Korrelation zeigt, ob höhere MAIK Team Scores mit höheren "
            "durchschnittlichen Kickbase-Punkten der Teams einhergehen."
        )

    # --------------------------------------------------------
    # Änderungen sofort im Session-State aktualisieren
    # --------------------------------------------------------
    st.session_state.edited_data = edited_data.copy()

    # --------------------------------------------------------
    # Änderungsanzeige
    # --------------------------------------------------------
    original_for_display = display_df[
        ["_editor_id"] + visible_columns
    ].copy()

    changed_rows = 0
    changed_cells = 0

    common_columns = [
        col
        for col in original_for_display.columns
        if col in edited_data.columns
    ]

    if common_columns:
        for col in common_columns:
            if col == "_editor_id":
                continue

            before = original_for_display[col].astype(str).fillna("")
            after = edited_data[col].astype(str).fillna("")

            differences = before != after
            changed_cells += int(differences.sum())

        row_diff = pd.Series(False, index=edited_data.index)

        for col in common_columns:
            if col == "_editor_id":
                continue

            before = original_for_display[col].astype(str).fillna("")
            after = edited_data[col].astype(str).fillna("")

            row_diff |= before != after

        changed_rows = int(row_diff.sum())

    if changed_rows > 0:
        st.warning(
            f"{changed_rows} Spieler geändert / {changed_cells} Werte geändert. "
            "Zum dauerhaften Speichern links „Änderungen speichern“ klicken."
        )
    else:
        st.caption("Keine ungespeicherten Änderungen.")

if __name__ == "__main__":
    main()
