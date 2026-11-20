"""Mobile-friendly Kickbase player and market dashboard."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st


st.set_page_config(
    page_title="Kickbase Assistant",
    page_icon="⚽",
    layout="wide",
)


NUMERIC_COLUMNS = [
    "maik_score",
    "marktwert",
    "marktwert_trend_24h",
    "marktwert_trend_7t",
    "ki_trend",
    "punkte",
    "durchschnitt_punkte",
    "roh_punkte",
    "roh_durchschnitt",
    "form_5",
    "median_punkte",
    "punkte_pro_mio",
    "marktwert_fair_value",
    "status_code",
    "tore",
    "assists",
    "gelbe_karten",
    "rote_karten",
]

DETAIL_COLUMNS = {
    "marktwert_trend_24h": "Trend 24h",
    "marktwert_trend_7t": "Trend 7 Tage",
    "ki_trend": "KI-Trend",
    "ki_trend_status": "KI-Trend-Status",
    "roh_punkte": "Rohpunkte",
    "roh_durchschnitt": "Ø Rohpunkte",
    "form_5": "Form (5)",
    "punkte": "Kickbase-Punkte gesamt",
    "durchschnitt_punkte": "Ø Kickbase-Punkte",
    "median_punkte": "Median Punkte",
    "punkte_pro_mio": "Punkte pro Mio",
    "tore": "Tore",
    "assists": "Assists",
    "gelbe_karten": "Gelbe Karten",
    "rote_karten": "Rote Karten",
    "marktwert_fair_value": "Fair Value",
    "status": "Status",
    "status_text": "Statusdetail (Quelle)",
    "einsaetze": "Einsätze",
    "startelf_einsaetze": "Startelf-Einsätze",
    "durchschnitt_minuten": "Ø Minuten",
    "maik_score_change": "MAIK-Veränderung",
    "maik_rolle": "MAIK-Rolle",
    "url": "LigaInsider",
}

STATUS_LABELS = {
    0: "Fit / verf\u00fcgbar",
    1: "Verletzt",
    2: "Angeschlagen",
    4: "Aufbautraining / Reha",
    8: "Rot gesperrt",
    16: "Gelb-Rot gesperrt",
    32: "5. Gelbe Karte",
    64: "Nicht im Kader",
    128: "Nicht in der Liga",
    256: "Abwesend",
}


def decode_status(value: object) -> str:
    """Translate Kickbase status codes and keep unknown values recognizable."""
    try:
        code = int(value)
    except (TypeError, ValueError, OverflowError):
        return "Unbekannt"
    return STATUS_LABELS.get(code, "Unbekannt")


@st.cache_data(ttl=60)
def load_update_status() -> pd.DataFrame:
    try:
        return pd.read_csv("data/update_status.csv", sep=";", encoding="utf-8-sig")
    except FileNotFoundError:
        return pd.DataFrame(columns=["step", "status", "updated_at"])


@st.cache_data(ttl=300)
def load_data() -> tuple[pd.DataFrame, pd.Timestamp, pd.DataFrame]:
    players = pd.read_csv(
        "data/final/final.csv",
        sep=";",
        encoding="utf-8-sig",
        dtype={"ligainsider_id": "string"},
    )
    try:
        alternatives = pd.read_csv(
            "data/matchday/bundesliga_alternativen.csv",
            sep=";",
            encoding="utf-8-sig",
            dtype={"ligainsider_id": "string"},
        )
    except FileNotFoundError:
        alternatives = pd.DataFrame(columns=["ligainsider_id"])
    if "ligainsider_id" not in alternatives:
        alternatives["ligainsider_id"] = pd.Series(dtype="string")
    try:
        ligainsider_status = pd.read_csv(
            "data/matchday/ligainsider_status.csv",
            sep=";",
            encoding="utf-8-sig",
            dtype={"team_id": "string"},
        )
    except FileNotFoundError:
        ligainsider_status = pd.DataFrame()

    last_update = pd.to_datetime(
        players.get("retrieved_at"), errors="coerce", utc=True
    ).max()

    # Older exports may not contain every optional BaseXI field yet.
    for column in [*NUMERIC_COLUMNS, *DETAIL_COLUMNS]:
        if column not in players:
            players[column] = pd.NA

    required_columns = [
        "spieler",
        "team",
        "position",
        "maik_score",
        "marktwert",
        "punkte",
        "durchschnitt_punkte",
        "startelf",
        "startelf_kicker",
        "ligainsider_id",
    ]
    for column in required_columns:
        if column not in players:
            players[column] = pd.NA

    players = players.drop(columns=[c for c in ["team.1"] if c in players])
    selected_columns = list(dict.fromkeys([
        *required_columns,
        "status_code",
        *[column for column in DETAIL_COLUMNS if column in players],
    ]))
    players = players[selected_columns].copy()

    for column in NUMERIC_COLUMNS:
        if column in players:
            players[column] = pd.to_numeric(players[column], errors="coerce")

    players["startelf"] = players["startelf"].map(
        lambda value: str(value).strip().casefold() in {"true", "1", "yes"}
    )
    players["startelf_kicker"] = players["startelf_kicker"].map(
        lambda value: str(value).strip().casefold() in {"true", "1", "yes"}
    )
    players["status"] = players["status_code"].map(decode_status)
    players["startelf_quote"] = (
        players["startelf_einsaetze"]
        .div(players["einsaetze"].where(players["einsaetze"] > 0))
        .mul(100)
    )
    player_ids = (
        players["ligainsider_id"]
        .astype("string")
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
    )
    alternative_ids = (
        alternatives["ligainsider_id"]
        .dropna()
        .astype("string")
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
    )
    players["alternative"] = player_ids.isin(alternative_ids)
    players = players.drop(columns="ligainsider_id")

    players["marktwert_mio"] = players["marktwert"] / 1_000_000
    return players, last_update, ligainsider_status


def player_table(
    data: pd.DataFrame,
    columns: list[str],
    *,
    height: int = 340,
    trend_label: str = "Trend",
    trend_format: str = "%+.2f",
) -> None:
    """Render a compact, consistently formatted player table."""
    visible = data[[column for column in columns if column in data]].copy()
    if "marktwert" in visible:
        visible["marktwert"] = visible["marktwert"] / 1_000_000
    if "trend_value" in visible and "Tsd." in trend_label:
        visible["trend_value"] = visible["trend_value"] / 1_000
    if "ki_trend" in visible:
        visible["ki_trend"] = visible["ki_trend"] / 1_000
    labels = {
        "spieler": "Spieler",
        "team": "Team",
        "position": "Pos.",
        "marktwert": "MW (Mio €)",
        "maik_score": "MAIK",
        "ki_trend": "KI-Trend (Tsd. \u20ac)",
        "durchschnitt_punkte": "Ø KB",
        "punkte": "KB gesamt",
        "trend_value": trend_label,
        "value_ratio": "Score/Mio €",
        "startelf_kicker": "Startelf Kicker",
        "url": "LigaInsider",
    }
    visible = visible.rename(columns=labels)
    config = {
        "MW (Mio €)": st.column_config.NumberColumn(format="%.2f"),
        "MAIK": st.column_config.NumberColumn(format="%.1f"),
        "KI-Trend (Tsd. \u20ac)": st.column_config.NumberColumn(format="%+.1f"),
        "Ø KB": st.column_config.NumberColumn(format="%.1f"),
        "KB gesamt": st.column_config.NumberColumn(format="%.0f"),
        trend_label: st.column_config.NumberColumn(format=trend_format),
        "Score/Mio €": st.column_config.NumberColumn(format="%.1f"),
        "LigaInsider": st.column_config.LinkColumn(display_text="Öffnen"),
    }
    st.dataframe(
        visible,
        width="content",
        height=height,
        hide_index=True,
        column_config=config,
    )


df, last_update, ligainsider_status = load_data()

st.title("Kickbase Markt & Spieler", icon=":material/sports_soccer:")
update_status = load_update_status()
if not update_status.empty and {"step", "status"}.issubset(update_status.columns):
    latest = update_status.loc[update_status["step"] == "Update"].tail(1)
    if not latest.empty:
        result = str(latest.iloc[0]["status"])
        result_label = {
            "complete": "✅ vollständig",
            "partial": "⚠️ teilweise abgeschlossen",
            "failed": "❌ fehlgeschlagen",
            "running": "🔄 läuft gerade",
        }.get(result, result)
        timestamp = latest.iloc[0].get("updated_at")
        time_label = ""
        if pd.notna(timestamp):
            parsed_time = pd.to_datetime(timestamp, errors="coerce", utc=True)
            if pd.notna(parsed_time):
                time_label = f" · {parsed_time.strftime('%d.%m. %H:%M UTC')}"
        st.markdown(f"**Letztes Update: {result_label}{time_label}**")

        latest_steps = update_status.drop_duplicates("step", keep="last").set_index("step")["status"]
        step_labels = {
            "Download Kickbase player data": "Kickbase",
            "Download MAIK scores": "MAIK",
            "Download LigaInsider player links": "LI Kader",
            "Download LigaInsider matchday lineups": "LI Startelf",
            "Parse LigaInsider alternatives": "LI Alternativen",
            "Download Kicker matchday lineups": "Kicker",
            "Merge player data": "Merge",
            "Update starting lineup flags": "Flags",
        }
        icons = {"success": "✅", "failed": "❌", "pending": "⏳", "running": "🔄"}
        summary = [
            f"{label} {icons.get(str(latest_steps.get(step, 'pending')), '❔')}"
            for step, label in step_labels.items()
        ]
        st.caption(" · ".join(summary))
else:
    st.caption("Update-Status noch nicht vorhanden; sichtbar nach dem nächsten Lauf.")
if pd.notna(last_update):
    st.caption(f"Datenstand: {last_update.strftime('%d.%m.%Y %H:%M UTC')}")

status_expander = st.expander("LigaInsider-Datenstatus", expanded=False)
if ligainsider_status.empty:
    status_expander.info("Abrufstatus wird beim nächsten Datenlauf erfasst.")
else:
    status_columns = [
        "verein", "kader_status", "startelf_status", "alternativen_status", "details"
    ]
    for column in status_columns:
        if column not in ligainsider_status:
            ligainsider_status[column] = "Unbekannt"
    visible_status = ligainsider_status[status_columns].fillna("Unbekannt").rename(
        columns={
            "verein": "Verein",
            "kader_status": "Kader / Spielerdaten",
            "startelf_status": "Voraussichtliche Startelf",
            "alternativen_status": "Alternativen",
            "details": "Hinweis",
        }
    )
    stale_count = visible_status[
        ["Kader / Spielerdaten", "Voraussichtliche Startelf", "Alternativen"]
    ].isin(["Vorversion verwendet", "Fehlt", "Nicht geladen"]).any(axis=1).sum()
    if stale_count:
        status_expander.warning(
            f"{stale_count} Vereine haben mindestens eine veraltete, fehlende "
            "oder nicht geladene LigaInsider-Quelle. Details stehen in der Tabelle."
        )
    else:
        status_expander.success("Kader, Startelf und Alternativen sind für alle erfassten Vereine aktuell.")
    status_expander.dataframe(
        visible_status.sort_values("Verein"),
        width="content",
        hide_index=True,
    )

# Filters stay in the main page so they are immediately reachable on mobile.
with st.container(border=True):
    st.subheader("Filter", anchor=False)
    range_row = st.columns(3, gap="small")
    market_values = df["marktwert_mio"].dropna()
    market_bounds = (
        float(market_values.min()),
        float(market_values.max()),
    ) if not market_values.empty else (0.0, 0.0)
    maik_values = df["maik_score"].dropna()
    maik_bounds = (
        float(maik_values.min()),
        float(maik_values.max()),
    ) if not maik_values.empty else (0.0, 0.0)
    point_values = df["durchschnitt_punkte"].dropna()
    point_bounds = (
        float(point_values.min()),
        float(point_values.max()),
    ) if not point_values.empty else (0.0, 0.0)
    with range_row[0]:
        market_range = st.slider(
            "Marktwert (Mio. €)", *market_bounds, value=market_bounds,
            step=0.5, format="%.1f",
        )
    with range_row[1]:
        maik_range = st.slider(
            "MAIK Score", *maik_bounds, value=maik_bounds,
            step=100.0, format="%.0f",
        )
    with range_row[2]:
        points_range = st.slider(
            "Durchschnittliche Punkte", *point_bounds, value=point_bounds,
            step=10.0, format="%.0f",
        )

    filter_row = st.columns([1.3, 1, 1], gap="small")
    with filter_row[0]:
        with st.form("player_search_form", clear_on_submit=False):
            search = st.text_input(
                "Spieler oder Verein suchen",
                placeholder="Name oder Verein",
                key="player_search_query",
            )
            st.form_submit_button("Suchen", icon=":material/search:")
    with filter_row[1]:
        teams = st.multiselect("Team", sorted(df["team"].dropna().unique()))
    with filter_row[2]:
        positions = st.multiselect(
            "Position", sorted(df["position"].dropna().unique())
        )

    trend_row = st.columns([1, 1, 1], gap="small")
    with trend_row[0]:
        trend_period = st.segmented_control(
            "Trendzeitraum",
            ["24 Stunden", "7 Tage"],
            default="24 Stunden",
            key="trend_period",
        )
    with trend_row[1]:
        trend_unit = st.segmented_control(
            "Einheit",
            ["Euro", "Prozent"],
            default="Euro",
            key="trend_unit",
        )
    with trend_row[2]:
        trend_direction = st.selectbox(
            "Trendrichtung", ["Alle", "Anstieg", "Abstieg"]
        )

    options_row = st.columns([1.4, 1, 1, 1], gap="small")
    with options_row[0]:
        min_move = st.number_input(
            "Mindestbewegung (€, bzw. %)",
            min_value=0.0,
            value=0.0,
            step=0.25 if trend_unit == "Prozent" else 100_000.0,
            format="%.2f" if trend_unit == "Prozent" else "%.0f",
        )
    with options_row[1]:
        only_startelf = st.checkbox("Startelf LigaInsider", value=True)
    with options_row[2]:
        only_alternatives = st.checkbox("Alternativen LigaInsider", value=False)
    with options_row[3]:
        only_kicker_startelf = st.checkbox("Startelf Kicker", value=False)

    status_options = sorted(df["status"].dropna().unique())
    selected_statuses = st.multiselect(
        "Spielerstatus",
        status_options,
        placeholder="Alle Status",
        key="status_filter",
    )

# Apply common filters first. The mover lists deliberately ignore direction and
# minimum movement so risers and decliners remain visible side by side.
scope = df.copy()
scope = scope[
    scope["marktwert_mio"].between(*market_range, inclusive="both")
    & scope["maik_score"].between(*maik_range, inclusive="both")
    & scope["durchschnitt_punkte"].between(*points_range, inclusive="both")
]
if search:
    scope = scope[
        scope["spieler"].astype("string").str.contains(search, case=False, na=False)
        | scope["team"].astype("string").str.contains(search, case=False, na=False)
    ]
if teams:
    scope = scope[scope["team"].isin(teams)]
if positions:
    scope = scope[scope["position"].isin(positions)]
if selected_statuses:
    scope = scope[scope["status"].isin(selected_statuses)]
if only_startelf or only_alternatives or only_kicker_startelf:
    scope = scope[
        (only_startelf & scope["startelf"])
        | (only_alternatives & scope["alternative"])
        | (only_kicker_startelf & scope["startelf_kicker"])
    ]

trend_column = (
    "marktwert_trend_24h" if trend_period == "24 Stunden" else "marktwert_trend_7t"
)
scope["trend_value"] = scope[trend_column]
previous_market_value = scope["marktwert"] - scope["trend_value"]
scope["trend_percent"] = (
    scope["trend_value"] / previous_market_value.where(previous_market_value > 0) * 100
)
trend_measure_column = "trend_value" if trend_unit == "Euro" else "trend_percent"
scope["trend_measure"] = scope[trend_measure_column]

view = scope.dropna(subset=["trend_measure"]).copy()
if trend_direction == "Anstieg":
    view = view[view["trend_measure"] > 0]
elif trend_direction == "Abstieg":
    view = view[view["trend_measure"] < 0]
if min_move > 0:
    view = view[view["trend_measure"].abs() >= min_move]


st.subheader("Spielerauswahl")
metric_options = {
    "Ø Kickbase-Score": "durchschnitt_punkte",
    "Kickbase-Gesamt-Score": "punkte",
    "KI-Trend": "ki_trend",
    "MAIK-Score": "maik_score",
}
selected_metric = st.segmented_control(
    "Kennzahl",
    list(metric_options),
    default="\u00d8 Kickbase-Score",
    key="value_metric",
)
metric_column = metric_options[selected_metric]
trend_display_label = "Trend (Tsd. €)" if trend_unit == "Euro" else "Trend (%)"
trend_display_format = "%+.1f" if trend_unit == "Euro" else "%+.2f %%"
view["value_ratio"] = view[metric_column] / view["marktwert_mio"].where(
    view["marktwert_mio"] > 0
)
main_table = view.sort_values("value_ratio", ascending=False, na_position="last")
main_table = main_table.assign(trend_value=main_table["trend_measure"])
player_table(
    main_table,
    [
        "spieler",
        "team",
        "position",
        "marktwert",
        "trend_value",
        "ki_trend",
        "value_ratio",
        "durchschnitt_punkte",
        "punkte",
        "maik_score",
        "startelf_kicker",
        "url",
    ],
    height=480,
    trend_label=trend_display_label,
    trend_format=trend_display_format,
)

st.subheader("Marktbewegung")
with st.container(horizontal=True, horizontal_alignment="distribute"):
    st.metric("Spieler im Filter", f"{len(view):,}", border=True)
    st.metric(
        "Ø Marktwert",
        f"{view['marktwert'].mean() / 1_000_000:.1f} Mio €" if view["marktwert"].notna().any() else "–",
        border=True,
    )
    st.metric(
        "Ø MAIK",
        f"{view['maik_score'].mean():.0f}" if view["maik_score"].notna().any() else "–",
        border=True,
    )

movers = scope.dropna(subset=["trend_measure"])
rise_data = movers[movers["trend_measure"] > 0].nlargest(10, "trend_measure").copy()
fall_data = movers[movers["trend_measure"] < 0].nsmallest(10, "trend_measure").copy()
for frame in (rise_data, fall_data):
    frame["trend_value"] = frame["trend_measure"]

rise_col, fall_col = st.columns(2, gap="small")
with rise_col:
    with st.container(border=True):
        st.markdown("**Top Marktanstiege**")
        player_table(
            rise_data,
            ["spieler", "team", "marktwert", "trend_value"],
            height=340,
            trend_label=trend_display_label,
            trend_format=trend_display_format,
        )
with fall_col:
    with st.container(border=True):
        st.markdown("**Top Marktabstiege**")
        player_table(
            fall_data,
            ["spieler", "team", "marktwert", "trend_value"],
            height=340,
            trend_label=trend_display_label,
            trend_format=trend_display_format,
        )

st.subheader("Punkte im Verhältnis zum Marktwert")
view["value_ratio"] = view[metric_column] / view["marktwert_mio"].where(
    view["marktwert_mio"] > 0
)
chart_data = view.dropna(subset=["marktwert_mio", "value_ratio"])
chart_data = chart_data[chart_data["marktwert_mio"] > 0]

if chart_data.empty:
    st.info("Für diese Filter gibt es keine vollständigen Marktwert- und Punktewerte.")
else:
    metric_label = {
        "maik_score": "MAIK-Score",
        "durchschnitt_punkte": "Ø Kickbase-Score",
        "punkte": "Kickbase-Gesamt-Score",
    }[metric_column]
    fig = px.scatter(
        chart_data,
        x="marktwert_mio",
        y="value_ratio",
        color="position",
        hover_name="spieler",
        hover_data={
            "team": True,
            "marktwert_mio": ":.2f",
            metric_column: ":.1f",
            "value_ratio": ":.2f",
            "position": False,
        },
        labels={
            "marktwert_mio": "Marktwert (Mio €)",
            "value_ratio": f"{metric_label} je Mio € Marktwert",
            "position": "Position",
        },
        render_mode="svg",
    )
    fig.update_layout(
        height=440,
        margin={"l": 10, "r": 10, "t": 15, "b": 10},
        legend_title_text="Position",
    )
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    st.caption("Weiter oben bedeutet mehr Punkte beziehungsweise Score je eingesetztem Marktwert.")



with st.expander("Weitere Rohdaten einblenden", icon=":material/database:"):
    available_detail_columns = [
        column for column in DETAIL_COLUMNS if column in view and view[column].notna().any()
    ]
    selected_details = st.multiselect(
        "Zusätzliche Spalten",
        available_detail_columns,
        format_func=lambda column: DETAIL_COLUMNS[column],
        placeholder="Spalten auswählen",
    )
    detail_columns = ["spieler", "team", *selected_details]
    detail_table = view.sort_values("marktwert", ascending=False, na_position="last")
    for column in ("marktwert_trend_24h", "marktwert_trend_7t"):
        if column in selected_details:
            detail_table[column] = detail_table[column] / 1_000
    if "marktwert_fair_value" in selected_details:
        detail_table["marktwert_fair_value"] = detail_table["marktwert_fair_value"] / 1_000_000
    detail_table = detail_table.rename(columns=DETAIL_COLUMNS)
    detail_labels = {"spieler": "Spieler", "team": "Team"}
    detail_table = detail_table.rename(columns=detail_labels)
    detail_table = detail_table.rename(columns={
        "Trend 24h": "Trend 24h (Tsd. €)",
        "Trend 7 Tage": "Trend 7 Tage (Tsd. €)",
        "Fair Value": "Fair Value (Mio. €)",
    })
    detail_config = {
        "Trend 24h (Tsd. €)": st.column_config.NumberColumn(format="%+.1f"),
        "Trend 7 Tage (Tsd. €)": st.column_config.NumberColumn(format="%+.1f"),
        "Fair Value (Mio. €)": st.column_config.NumberColumn(format="%.2f"),
        "LigaInsider": st.column_config.LinkColumn(display_text="Öffnen"),
    }
    if selected_details:
        st.dataframe(
            detail_table[[detail_labels.get(column, DETAIL_COLUMNS.get(column, column)) for column in detail_columns]],
            width="content",
            height=420,
            hide_index=True,
            column_config=detail_config,
        )
    else:
        st.caption("Wähle Spalten aus, um zusätzliche Werte aus der Rohdatenbank einzublenden.")


st.subheader("Echtdaten")
st.caption("Status und Einsatzwerte der Saison, einschliesslich beider Ratio-Kennzahlen.")
real_data_columns = [
    "spieler",
    "team",
    "status",
    "status_text",
    "einsaetze",
    "startelf_einsaetze",
    "punkte_pro_mio",
    "startelf_quote",
]
optional_stats = ["tore", "assists", "gelbe_karten", "rote_karten"]
real_data_columns.extend(
    column
    for column in optional_stats
    if column in view and view[column].notna().any()
)
real_data = view[real_data_columns].rename(columns={
    "spieler": "Spieler",
    "team": "Team",
    "status": "Status",
    "status_text": "Statusdetail (Quelle)",
    "einsaetze": "Eins\u00e4tze Saison",
    "startelf_einsaetze": "Startelf-Eins\u00e4tze",
    "punkte_pro_mio": "Punkte pro Mio",
    "tore": "Tore",
    "assists": "Assists",
    "gelbe_karten": "Gelbe Karten",
    "rote_karten": "Rote Karten",
    "startelf_quote": "Startelfquote (%)",
}).sort_values(["Status", "Spieler"])
st.dataframe(
    real_data,
    width="content",
    hide_index=True,
    column_config={
        "Eins\u00e4tze Saison": st.column_config.NumberColumn(format="%.0f"),
        "Startelf-Eins\u00e4tze": st.column_config.NumberColumn(format="%.0f"),
        "Punkte pro Mio": st.column_config.NumberColumn(format="%.1f"),
        "Startelfquote (%)": st.column_config.NumberColumn(format="%.1f%%"),
        "Tore": st.column_config.NumberColumn(format="%.0f"),
        "Assists": st.column_config.NumberColumn(format="%.0f"),
        "Gelbe Karten": st.column_config.NumberColumn(format="%.0f"),
        "Rote Karten": st.column_config.NumberColumn(format="%.0f"),
    },
)
