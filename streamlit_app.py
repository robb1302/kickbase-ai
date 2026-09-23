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
    return apply_team_score_overrides(df)


def normalize_key_part(value: object) -> str:
    """Normalisiert einen Spieler- oder Teamnamen für den Override-Schlüssel."""
    if pd.isna(value):
        return ""
    return " ".join(str(value).strip().casefold().split())


def score_key(player: object, team: object) -> str:
    """Verwendet Spieler plus Team als stabilen Schlüssel ohne Spieler-ID."""
    return f"{normalize_key_part(player)}|{normalize_key_part(team)}"


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
            "MAIK-Scores speichern",
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

                if save_score_overrides(updates) and save_team_score_overrides(
                    team_updates
                ):
                    fresh = load_csv()
                    if not fresh.empty:
                        fresh = ensure_score_columns(fresh)
                        st.session_state.df = fresh
                        st.session_state.original_df = fresh.copy()
                        st.session_state.pop("edited_data", None)
                        st.session_state.pop("player_editor", None)
                        st.session_state.pop("team_editor_data", None)

                    st.success("Spieler- und Team-Scores gespeichert.")
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
            "trend",
            "maik_score",
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

    st.subheader("Spielerdaten")

    st.caption(
        "Nur der MAIK Score wird manuell gepflegt und separat gespeichert."
    )

    disabled_columns = [col for col in editor_df.columns if col != "maik_score"]

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
            "Zum dauerhaften Speichern links „MAIK-Scores speichern“ klicken."
        )
    else:
        st.caption("Keine ungespeicherten Änderungen.")

if __name__ == "__main__":
    main()
