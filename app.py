"""Feedback Agent: a free social-listening tool that gives product managers
a weekly roadmap.

Pulls customer feedback from Excel/CSV uploads, Google Play, the App Store,
and Reddit; analyzes sentiment, pain themes, and customer-journey stage
locally (no paid APIs); and turns it into a prioritized Mon-Fri action plan.

Run locally:   streamlit run app.py
Deploy free:   https://share.streamlit.io  (Streamlit Community Cloud)
"""

import html
import os
from datetime import datetime, timezone

import pandas as pd
import plotly.express as px
import streamlit as st

import sources
from analysis import (JOURNEY_ORDER, add_journey, add_sentiment, add_themes,
                      journey_summary, theme_summary, top_terms)
from roadmap import build_roadmap

st.set_page_config(page_title="Feedback Agent", page_icon="📡", layout="wide")

# ------------------------------------------------------------------ styling

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

html, body, [class*="css"], [data-testid="stAppViewContainer"] * {
    font-family: 'Inter', -apple-system, sans-serif !important;
}
/* keep Streamlit's icon glyphs on their icon font */
[data-testid="stIconMaterial"], [data-testid="stExpanderToggleIcon"],
.material-symbols-rounded, [class*="material-symbols"],
[data-testid="stAppViewContainer"] [data-testid="stIconMaterial"] * {
    font-family: 'Material Symbols Rounded' !important;
}
[data-testid="stAppViewContainer"] { background: #fafafa; }
[data-testid="stSidebar"] { background: #ffffff; border-right: 1px solid #e5e7eb; }
h1, h2, h3 { letter-spacing: -0.02em; }

.card {
    background: #ffffff; border: 1px solid #e5e7eb; border-radius: 12px;
    padding: 20px 24px; margin-bottom: 12px;
}
.kpi-label { font-size: 12px; font-weight: 600; color: #6b7280;
             text-transform: uppercase; letter-spacing: 0.06em; }
.kpi-value { font-size: 34px; font-weight: 800; color: #111827; line-height: 1.2; }
.kpi-sub   { font-size: 13px; color: #6b7280; }
.kpi-up    { color: #15803d; font-weight: 600; }
.kpi-down  { color: #dc2626; font-weight: 600; }

.pill {
    display: inline-block; padding: 2px 10px; border-radius: 999px;
    font-size: 12px; font-weight: 500; background: #eff6ff; color: #1d4ed8;
    border: 1px solid #bfdbfe; margin-right: 4px; white-space: nowrap;
}
.sent-num { font-family: 'JetBrains Mono', ui-monospace, monospace !important;
            font-weight: 700; font-size: 15px; }

.mention-row { border-bottom: 1px solid #f3f4f6; padding: 14px 4px; }
.mention-title { font-weight: 600; font-size: 15px; color: #111827; }
.mention-body  { font-size: 13px; color: #6b7280; margin-top: 3px; }
.mention-meta  { font-size: 12px; color: #9ca3af; }

.prio { display: inline-block; padding: 2px 10px; border-radius: 6px;
        font-size: 12px; font-weight: 700; color: white; }
.prio-P0 { background: #dc2626; }
.prio-P1 { background: #d97706; }
.prio-P2 { background: #2563eb; }
.day-chip { display: inline-block; padding: 2px 10px; border-radius: 6px;
            font-size: 12px; font-weight: 600; background: #f3f4f6; color: #374151; }
.quote { border-left: 3px solid #e5e7eb; padding: 4px 12px; margin: 6px 0;
         font-size: 13px; color: #6b7280; font-style: italic; }
</style>
""", unsafe_allow_html=True)

FUNNEL_COLORS = {
    "Awareness": "#8b1538", "Solution Search": "#e11d48", "Comparison": "#b08968",
    "Purchase Decision": "#16a34a", "Experience & Advocacy": "#2563eb",
    "Unclassified": "#94a3b8",
}


def sent_color(v: int) -> str:
    return "#dc2626" if v < 40 else ("#d97706" if v < 70 else "#16a34a")


def rel_time(ts) -> str:
    if pd.isna(ts):
        return "-"
    ts = pd.to_datetime(ts, utc=True, errors="coerce")
    if pd.isna(ts):
        return "-"
    days = (datetime.now(timezone.utc) - ts).days
    if days <= 0:
        return "today"
    if days < 30:
        return f"{days}d ago"
    return f"{days // 30}mo ago"


# ------------------------------------------------------------------ state

if "feedback" not in st.session_state:
    st.session_state.feedback = pd.DataFrame(columns=sources.COLUMNS)
if "ai_roadmap" not in st.session_state:
    st.session_state.ai_roadmap = None


def add_data(df: pd.DataFrame, label: str):
    if df.empty:
        st.sidebar.warning(f"{label}: no feedback found.")
        return
    df = add_journey(add_themes(add_sentiment(df)))
    combined = pd.concat([st.session_state.feedback, df], ignore_index=True)
    combined = combined.drop_duplicates(subset=["source", "text"], keep="first")
    st.session_state.feedback = combined
    st.session_state.ai_roadmap = None  # stale after new data
    st.sidebar.success(f"{label}: +{len(df)} items (total {len(combined)})")


# ------------------------------------------------------------------ sidebar

st.sidebar.title("📡 Feedback Agent")
st.sidebar.caption("Social listening for product teams. Pull feedback from anywhere, get a roadmap for the week.")

with st.sidebar.expander("📄 Upload Excel / CSV", expanded=True):
    st.caption("Any file with a feedback/review text column. Date, rating and author columns are auto-detected.")
    uploaded = st.file_uploader("Choose file", type=["xlsx", "xls", "csv"], label_visibility="collapsed")
    if uploaded and st.button("Import file", use_container_width=True):
        try:
            add_data(sources.load_upload(uploaded), "Upload")
        except Exception as e:
            st.error(f"Could not read file: {e}")

with st.sidebar.expander("▶️ Google Play reviews"):
    gp_id = st.text_input("App package id", placeholder="com.spotify.music",
                          help="From the Play Store URL: play.google.com/store/apps/details?id=<this>")
    gp_count = st.slider("How many reviews", 50, 500, 200, 50)
    if st.button("Pull Google Play", use_container_width=True, disabled=not gp_id):
        with st.spinner("Fetching Google Play reviews…"):
            try:
                add_data(sources.fetch_google_play(gp_id, gp_count), "Google Play")
            except Exception as e:
                st.error(f"Google Play error: {e}")

with st.sidebar.expander("🍎 App Store reviews"):
    as_id = st.text_input("App numeric id", placeholder="324684580",
                          help="The number in the App Store URL: apps.apple.com/us/app/…/id<this>")
    as_country = st.text_input("Country code", value="us", max_chars=2)
    if st.button("Pull App Store", use_container_width=True, disabled=not as_id):
        with st.spinner("Fetching App Store reviews…"):
            try:
                add_data(sources.fetch_app_store(as_id, as_country.lower()), "App Store")
            except Exception as e:
                st.error(f"App Store error: {e}")

with st.sidebar.expander("👽 Reddit discussions"):
    rd_query = st.text_input("Search query", placeholder="Spotify app")
    rd_sub = st.text_input("Limit to subreddit (optional)", placeholder="spotify")
    if st.button("Pull Reddit", use_container_width=True, disabled=not rd_query):
        with st.spinner("Searching Reddit…"):
            try:
                add_data(sources.fetch_reddit(rd_query, subreddit=rd_sub), "Reddit")
            except Exception as e:
                st.error(f"Reddit error: {e}")

st.sidebar.divider()
if st.sidebar.button("🗑️ Clear all data", use_container_width=True):
    st.session_state.feedback = pd.DataFrame(columns=sources.COLUMNS)
    st.session_state.ai_roadmap = None
    st.rerun()

# ------------------------------------------------------------------ main

df = st.session_state.feedback

st.title("📡 Feedback Agent")

if df.empty:
    st.info(
        "**Get started**: pull in customer feedback from the sidebar.\n\n"
        "- 📄 Upload an **Excel/CSV** export of customer feedback\n"
        "- ▶️ Pull live reviews from **Google Play** (e.g. `com.spotify.music`)\n"
        "- 🍎 Pull live reviews from the **App Store** (e.g. `324684580`)\n"
        "- 👽 Search **Reddit** discussions about your product\n\n"
        "You'll get a dashboard, a mentions feed, and a prioritized roadmap for the week."
    )
    st.stop()

tab_dash, tab_roadmap, tab_mentions = st.tabs(
    ["📊 Dashboard", "🗺️ Weekly Roadmap", "💬 Mentions"])

# ------------------------------------------------------------------ dashboard

with tab_dash:
    main_col, kpi_col = st.columns([2.8, 1])

    with kpi_col:
        # Mentions delta: last 28d vs previous 28d (when dates exist)
        dated = df.dropna(subset=["date"]).copy()
        delta_html = ""
        if not dated.empty:
            dts = pd.to_datetime(dated["date"], utc=True, errors="coerce").dropna()
            now = datetime.now(timezone.utc)
            last28 = int((dts > now - pd.Timedelta(days=28)).sum())
            prev28 = int(((dts <= now - pd.Timedelta(days=28)) &
                          (dts > now - pd.Timedelta(days=56))).sum())
            diff = last28 - prev28
            cls = "kpi-up" if diff >= 0 else "kpi-down"
            arrow = "↑" if diff >= 0 else "↓"
            delta_html = f'<div class="kpi-sub"><span class="{cls}">{arrow} {diff:+d}</span> vs prev 28d</div>'
            mentions_val = last28
        else:
            mentions_val = len(df)

        avg100 = int(df["sentiment100"].mean())
        neg_share = (df["sentiment_label"] == "Negative").mean()
        ratings = pd.to_numeric(df["rating"], errors="coerce")
        rating_str = f"{ratings.mean():.2f} ★" if ratings.notna().any() else "-"

        st.markdown(f"""
<div class="card"><div class="kpi-label">Mentions · 28d</div>
<div class="kpi-value">{mentions_val}</div>{delta_html}</div>
<div class="card"><div class="kpi-label">Avg Sentiment</div>
<div class="kpi-value" style="color:{sent_color(avg100)}">{avg100}</div>
<div class="kpi-sub">0-100 scale</div></div>
<div class="card"><div class="kpi-label">Negative Share</div>
<div class="kpi-value">{neg_share:.0%}</div>
<div class="kpi-sub">of all mentions</div></div>
<div class="card"><div class="kpi-label">Avg Rating</div>
<div class="kpi-value">{rating_str}</div>
<div class="kpi-sub">store reviews</div></div>
""", unsafe_allow_html=True)

    with main_col:
        st.subheader("Customer Journey Funnel")
        st.caption("Where your mentions sit across the customer journey.")
        js = journey_summary(df)
        fig = px.bar(js, x="count", y="stage", orientation="h", text="count",
                     color="stage", color_discrete_map=FUNNEL_COLORS,
                     category_orders={"stage": JOURNEY_ORDER})
        fig.update_traces(textposition="inside", textfont=dict(color="white", size=13),
                          hovertemplate="%{y}: %{x}<extra></extra>")
        fig.update_layout(template="plotly_white", showlegend=False, height=320,
                          margin=dict(t=8, l=0, r=0, b=0),
                          yaxis=dict(autorange="reversed", title=""),
                          xaxis=dict(title=""), font=dict(family="Inter"),
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)

        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Pain themes")
            ts = theme_summary(df)
            if not ts.empty:
                fig = px.bar(ts, x="mentions", y="theme", orientation="h",
                             color="avg_sentiment",
                             color_continuous_scale=["#dc2626", "#d1d5db", "#16a34a"],
                             range_color=[-0.6, 0.6])
                fig.update_layout(template="plotly_white", height=330,
                                  yaxis=dict(autorange="reversed", title=""),
                                  xaxis=dict(title="mentions"),
                                  margin=dict(t=8, l=0, r=0, b=0),
                                  coloraxis_colorbar_title="sent.",
                                  font=dict(family="Inter"),
                                  paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig, use_container_width=True)
        with c2:
            st.subheader("Sentiment over time")
            if len(dated) > 5:
                dated["date"] = pd.to_datetime(dated["date"], utc=True, errors="coerce")
                weekly = (dated.dropna(subset=["date"]).set_index("date").sort_index()
                               .groupby(pd.Grouper(freq="W"))["sentiment100"]
                               .agg(["mean", "count"]).reset_index())
                weekly = weekly[weekly["count"] > 0]
                fig = px.line(weekly, x="date", y="mean", markers=True,
                              labels={"mean": "avg sentiment"})
                fig.add_hline(y=50, line_dash="dot", line_color="#9ca3af")
                fig.update_traces(line_color="#2563eb")
                fig.update_layout(template="plotly_white", height=330,
                                  margin=dict(t=8, l=0, r=0, b=0),
                                  yaxis=dict(range=[0, 100], title="avg sentiment"),
                                  xaxis=dict(title=""), font=dict(family="Inter"),
                                  paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.caption("Not enough dated feedback yet.")

        st.subheader("Top words in negative feedback")
        terms = top_terms(df, "Negative", 15)
        if terms:
            tdf = pd.DataFrame(terms, columns=["word", "count"])
            fig = px.bar(tdf, x="word", y="count", color_discrete_sequence=["#dc2626"])
            fig.update_layout(template="plotly_white", height=260,
                              margin=dict(t=8, l=0, r=0, b=0), font=dict(family="Inter"),
                              xaxis=dict(title=""), yaxis=dict(title=""),
                              paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No negative feedback 🎉")

# ------------------------------------------------------------------ roadmap

with tab_roadmap:
    st.subheader("🗺️ Your roadmap for the week")
    st.caption("Pain themes ranked by volume x negativity x recency, turned into a Mon-Fri plan. "
               "P0 = do first. Built automatically from the feedback you pulled.")

    items = build_roadmap(df)
    if not items:
        st.info("Not enough themed feedback yet to build a roadmap. Pull more data.")
    else:
        for it in items:
            trend_badge = ""
            if it["trend"] == "rising":
                trend_badge = ' · <span class="kpi-down">▲ rising</span>'
            elif it["trend"] == "cooling":
                trend_badge = ' · <span class="kpi-up">▼ cooling</span>'
            quotes_html = "".join(
                f'<div class="quote">“{html.escape(q)}”</div>' for q in it["quotes"])
            st.markdown(f"""
<div class="card">
  <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
    <span class="prio prio-{it['priority']}">{it['priority']}</span>
    <span class="day-chip">{it['day']}</span>
    <span style="font-weight:700; font-size:16px;">{html.escape(it['theme'])}</span>
    <span class="kpi-sub">{it['mentions']} mentions · {it['neg_share']:.0%} negative ·
    sentiment <span class="sent-num" style="color:{sent_color(it['avg_sentiment100'])}">{it['avg_sentiment100']}</span>{trend_badge}</span>
  </div>
  <div style="margin-top:10px; font-size:14px;">
    <b>Do:</b> {html.escape(it['action'])} &nbsp;·&nbsp; <b>Owner:</b> {html.escape(it['owner'])}
  </div>
  {quotes_html}
</div>
""", unsafe_allow_html=True)

    st.divider()
    st.subheader("✨ AI-polished roadmap (optional)")
    st.caption("With an API key, the plan above is rewritten into a day-by-day roadmap "
               "with quick wins and a watch list, ready to paste into your planning doc.")

    try:
        secret_key = st.secrets.get("ANTHROPIC_API_KEY", "")
    except Exception:
        secret_key = ""
    default_key = os.environ.get("ANTHROPIC_API_KEY", "") or secret_key
    api_key = st.text_input("API key", value=default_key, type="password",
                            help="Get one at console.anthropic.com, or set ANTHROPIC_API_KEY in Streamlit secrets.")

    if st.button("Generate AI roadmap", type="primary", disabled=not (api_key and items)):
        from roadmap import generate_ai_roadmap
        with st.spinner("Planning your week… (can take a minute)"):
            try:
                st.session_state.ai_roadmap = generate_ai_roadmap(df, items, api_key)
            except Exception as e:
                st.error(f"AI roadmap failed: {e}")

    if st.session_state.ai_roadmap:
        st.markdown(st.session_state.ai_roadmap)
        st.download_button("⬇️ Download roadmap (markdown)",
                           st.session_state.ai_roadmap.encode("utf-8"),
                           file_name="weekly_roadmap.md", mime="text/markdown")

# ------------------------------------------------------------------ mentions

with tab_mentions:
    st.subheader("Mentions")
    st.caption("Every tracked mention from your sources, newest first.")

    f1, f2, f3, f4 = st.columns(4)
    src_filter = f1.multiselect("Source", sorted(df["source"].unique()))
    sent_filter = f2.multiselect("Sentiment", ["Negative", "Neutral", "Positive"])
    theme_options = sorted({t.strip() for ts in df["themes"] for t in ts.split(",")})
    theme_filter = f3.multiselect("Pain theme", theme_options)
    journey_filter = f4.multiselect("Journey stage", JOURNEY_ORDER)
    search = st.text_input("Search text", placeholder="e.g. crash, refund, dark mode…")

    view = df
    if src_filter:
        view = view[view["source"].isin(src_filter)]
    if sent_filter:
        view = view[view["sentiment_label"].isin(sent_filter)]
    if theme_filter:
        view = view[view["themes"].apply(lambda ts: any(t in ts for t in theme_filter))]
    if journey_filter:
        view = view[view["journey"].isin(journey_filter)]
    if search:
        view = view[view["text"].str.contains(search, case=False, na=False)]

    view = view.sort_values("date", ascending=False, na_position="last")
    st.caption(f"{len(view)} of {len(df)} mentions")

    SOURCE_ICON = {"Google Play": "▶️", "App Store": "🍎", "Reddit": "👽", "Upload": "📄"}
    rows_html = []
    for _, r in view.head(100).iterrows():
        text = str(r["text"])
        title = html.escape(text[:90] + ("…" if len(text) > 90 else ""))
        body = html.escape(text[90:340] + ("…" if len(text) > 340 else "")) if len(text) > 90 else ""
        pains = "".join(f'<span class="pill">{html.escape(t.strip())}</span>'
                        for t in str(r["themes"]).split(",") if t.strip() and t.strip() != "Other")
        s100 = int(r["sentiment100"])
        rating = f" · {int(r['rating'])}★" if pd.notna(r.get("rating")) else ""
        link = f' · <a href="{html.escape(str(r["url"]))}" target="_blank">open</a>' if str(r.get("url", "")).startswith("http") else ""
        body_html = f'<div class="mention-body">{body}</div>' if body else ''
        # single-line HTML: indented lines inside st.markdown become code blocks
        rows_html.append(
            '<div class="mention-row">'
            '<div style="display:flex; justify-content:space-between; gap:16px;">'
            '<div style="flex:1; min-width:0;">'
            f'<div class="mention-title">{title}</div>{body_html}'
            f'<div class="mention-meta" style="margin-top:6px;">'
            f"{SOURCE_ICON.get(r['source'], '💬')} {html.escape(str(r['source']))}{rating}"
            f" · {html.escape(str(r['journey']))}{link}</div></div>"
            '<div style="text-align:right; flex-shrink:0;">'
            f'<span class="sent-num" style="color:{sent_color(s100)}">{s100}</span>'
            f'<div class="mention-meta">{rel_time(r["date"])}</div>'
            f'<div style="margin-top:6px; max-width:240px;">{pains}</div>'
            '</div></div></div>')
    st.markdown(f'<div class="card">{"".join(rows_html)}</div>', unsafe_allow_html=True)
    if len(view) > 100:
        st.caption("Showing newest 100. Download the full set below.")

    st.download_button(
        "⬇️ Download as CSV",
        view.to_csv(index=False).encode("utf-8"),
        file_name="feedback_export.csv",
        mime="text/csv",
    )
