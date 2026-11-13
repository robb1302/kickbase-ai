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


@st.cache_data(ttl=300)
def load_data() -> tuple[pd.DataFrame, pd.Timestamp]:
    players = pd.read_csv("data/final/final.csv", sep=";", encoding="utf-8-sig")
    alternatives = pd.read_csv(
        "data/matchday/bundesliga_alternativen.csv",
        sep=";",
        encoding="utf-8-sig",
        dtype={"ligainsider_id": "string"},
    )

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
    players["status"] = players["status_code"].map(decode_status)
    players["startelf_quote"] = (
        players["startelf_einsaetze"]
        .div(players["einsaetze"].where(players["einsaetze"] > 0))
        .mul(100)
    )
    players["alternative"] = (
        players["ligainsider_id"]
        .astype("string")
        .str.strip()
        .isin(alternatives["ligainsider_id"].dropna().astype("string").str.strip())
    )
    players = players.drop(columns="ligainsider_id")

    players["marktwert_mio"] = players["marktwert"] / 1_000_000
    return players, last_update


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
    labels = {
        "spieler": "Spieler",
        "team": "Team",
        "position": "Pos.",
        "marktwert": "Marktwert",
        "maik_score": "MAIK",
        "trend_value": trend_label,
        "value_ratio": "Punkte je Mio €",
        "url": "LigaInsider",
    }
    visible = visible.rename(columns=labels)
    config = {
        "Marktwert": st.column_config.NumberColumn(format="%.0f €"),
        "MAIK": st.column_config.NumberColumn(format="%.1f"),
        trend_label: st.column_config.NumberColumn(format=trend_format),
        "Punkte je Mio €": st.column_config.NumberColumn(format="%.1f"),
        "LigaInsider": st.column_config.LinkColumn(display_text="Öffnen"),
    }
    st.dataframe(
        visible,
        width="content",
        height=height,
        hide_index=True,
        column_config=config,
    )


df, last_update = load_data()

st.title("Kickbase Markt & Spieler", icon=":material/sports_soccer:")
if pd.notna(last_update):
    st.caption(f"Datenstand: {last_update.strftime('%d.%m.%Y %H:%M UTC')}")

# Filters stay in the main page so they are immediately reachable on mobile.
with st.container(border=True):
    st.subheader("Filter", anchor=False)
    filter_row = st.columns([1.3, 1, 1], gap="small")
    with filter_row[0]:
        search = st.text_input("Spieler suchen", placeholder="Name oder Verein")
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

    options_row = st.columns([1, 1, 1], gap="small")
    with options_row[0]:
        min_move = st.number_input(
            "Mindestbewegung (€, bzw. %)",
            min_value=0.0,
            value=0.0,
            step=0.25 if trend_unit == "Prozent" else 100_000.0,
            format="%.2f" if trend_unit == "Prozent" else "%.0f",
        )
    with options_row[1]:
        only_startelf = st.checkbox("Nur Startelf", value=True)
    with options_row[2]:
        only_alternatives = st.checkbox("Nur Alternativen", value=False)

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
if only_startelf or only_alternatives:
    scope = scope[
        (only_startelf & scope["startelf"])
        | (only_alternatives & scope["alternative"])
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
    "MAIK-Score": "maik_score",
    "Ø Kickbase-Punkte": "durchschnitt_punkte",
    "Kickbase-Punkte gesamt": "punkte",
}
selected_metric = st.segmented_control(
    "Kennzahl",
    list(metric_options),
    default="MAIK-Score",
    key="value_metric",
)
metric_column = metric_options[selected_metric]
trend_display_label = "Trend (EUR)" if trend_unit == "Euro" else "Trend (%)"
trend_display_format = "%+.0f EUR" if trend_unit == "Euro" else "%+.2f %%"
view["value_ratio"] = view[metric_column] / view["marktwert_mio"].where(
    view["marktwert_mio"] > 0
)
main_table = view.sort_values("value_ratio", ascending=False, na_position="last")
main_table = main_table.assign(trend_value=main_table["trend_measure"])
player_table(
    main_table,
    ["spieler", "team", "position", "marktwert", "maik_score", "trend_value", "value_ratio", "url"],
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
        "durchschnitt_punkte": "Ø Kickbase-Punkte",
        "punkte": "Kickbase-Punkte gesamt",
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
    detail_table = detail_table.rename(columns=DETAIL_COLUMNS)
    detail_labels = {"spieler": "Spieler", "team": "Team"}
    detail_table = detail_table.rename(columns=detail_labels)
    detail_config = {
        "Marktwert": st.column_config.NumberColumn(format="%.0f €"),
        "Trend 24h": st.column_config.NumberColumn(format="%+.0f €"),
        "Trend 7 Tage": st.column_config.NumberColumn(format="%+.0f €"),
        "Fair Value": st.column_config.NumberColumn(format="%.0f €"),
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
