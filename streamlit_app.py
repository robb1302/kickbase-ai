import streamlit as st
import pandas as pd
import plotly.express as px

st.set_page_config("Kickbase Assistant", "⚽", layout="wide")

# -----------------------
# Daten laden
# -----------------------
@st.cache_data(ttl=300)
def load_data():
    df = pd.read_csv(
        "data/final/final.csv",
        sep=";",
        encoding="utf-8-sig"
    )

    last_update = pd.to_datetime(
        df["retrieved_at"], errors="coerce", utc=True
    ).max()

    df = df[[
        "spieler", "team", "position",
        "maik_score", "marktwert",
        "punkte", "url", "startelf"
    ]].copy()

    df["maik_score"] = pd.to_numeric(df["maik_score"], errors="coerce") 
    df["marktwert"] = pd.to_numeric(df["marktwert"], errors="coerce")
    df["punkte"] = pd.to_numeric(df["punkte"], errors="coerce")

    df["marktwert_mio"] = df["marktwert"] / 1_000_000
    df["value"] = df["maik_score"] / df["marktwert_mio"]

    return df, last_update


df, last_update = load_data()

# -----------------------
# Sidebar
# -----------------------
st.sidebar.header("Filter")

search = st.sidebar.text_input("Spieler suchen")

team = st.sidebar.multiselect(
    "Team",
    sorted(df.team.dropna().unique())
)

position = st.sidebar.multiselect(
    "Position",
    sorted(df.position.dropna().unique())
)

minimum_maik_score = st.sidebar.number_input(
    "Mindest-MAIK-Punkte",
    min_value=0,
    value=0,
    step=100,
    format="%d",
)

only_startelf = st.sidebar.checkbox("Nur Startelf", True)

# -----------------------
# Filter anwenden
# -----------------------
view = df.copy()

if search:
    view = view[view.spieler.str.contains(search, case=False, na=False)]

if team:
    view = view[view.team.isin(team)]

if position:
    view = view[view.position.isin(position)]

if minimum_maik_score > 0:
    view = view[view.maik_score >= minimum_maik_score]

if only_startelf:
    view = view[view.startelf == True]

# -----------------------
# KPIs
# -----------------------
if pd.notna(last_update):
    st.caption(f"Letztes Pipeline-Update: {last_update.strftime('%d.%m.%Y %H:%M UTC')}")
else:
    st.caption("Kein `retrieved_at`-Datum in der CSV gefunden")

c1, c2, c3 = st.columns(3)
c1.metric("Spieler", len(view))
c2.metric("Ø MAIK", round(view.maik_score.mean(), 1))
c3.metric("Ø Marktwert", f"{view.marktwert_mio.mean():.1f} Mio")

st.divider()

# -----------------------
# Tabelle
# -----------------------
st.subheader("Bargain Finder")

show = view.sort_values(
    "value",
    ascending=False
)[[
    "spieler", "team", "position",
    "maik_score", "marktwert",
    "punkte", "startelf", "url"
]]

st.dataframe(
    show,
    use_container_width=True,
    hide_index=True,
    column_config={
        "marktwert": st.column_config.NumberColumn(
            "Marktwert",
            format="%.0f €"
        ),
        "maik_score": st.column_config.NumberColumn(
            "MAIK",
            format="%.1f"
        ),
        "url": st.column_config.LinkColumn(
            "LigaInsider"
        )
    }
)

st.divider()

# -----------------------
# Chart 1
# -----------------------
st.subheader("Top 20 Value-Spieler")

top = view.nlargest(20, "value").sort_values("value")

fig = px.bar(
    top,
    x="value",
    y="spieler",
    orientation="h",
    color="position",
    labels={"value": "MAIK / Mio Marktwert", "spieler": ""}
)

st.plotly_chart(fig, use_container_width=True)

# -----------------------
# Chart 2
# -----------------------
st.subheader("MAIK vs Marktwert")

fig = px.scatter(
    view,
    x="marktwert_mio",
    y="maik_score",
    color="position",
    hover_name="spieler",
    labels={
        "marktwert_mio": "Marktwert (Mio €)",
        "maik_score": "MAIK"
    }
)

st.plotly_chart(fig, use_container_width=True)

# -----------------------
# Chart 3
# -----------------------
st.subheader("Teamqualität")

team_df = (
    view.groupby("team", as_index=False)
    .agg(
        maik=("maik_score", "mean"),
        spieler=("spieler", "count")
    )
    .sort_values("maik", ascending=False)
)

fig = px.bar(
    team_df,
    x="team",
    y="maik",
    color="maik",
    labels={"maik": "Ø MAIK", "team": ""}
)

st.plotly_chart(fig, use_container_width=True)