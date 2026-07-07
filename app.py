"""Feedback Agent: a social-listening tool that gives product managers
a weekly roadmap.

Tracks a brand across Reddit, Hacker News, Bluesky, Google News and
Stack Overflow, pulls app reviews from Google Play and the App Store,
accepts Excel/CSV uploads, analyzes sentiment, pain themes and journey
stage locally (no paid APIs), and turns it all into a prioritized
Monday-Friday action plan.

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
.block-container { padding-top: 2.2rem; }
h1, h2, h3 { letter-spacing: -0.02em; }

.app-title { font-size: 26px; font-weight: 800; color: #111827; letter-spacing: -0.03em; }
.app-sub   { font-size: 14px; color: #6b7280; margin-top: 2px; }
.logo-mark { display:inline-block; width: 12px; height: 12px; border-radius: 3px;
             background: #2563eb; margin-right: 10px; }

.side-label { font-size: 11px; font-weight: 700; color: #9ca3af;
              text-transform: uppercase; letter-spacing: 0.08em; margin: 10px 0 2px 0; }

.card {
    background: #ffffff; border: 1px solid #e5e7eb; border-radius: 12px;
    padding: 20px 24px; margin-bottom: 12px;
}
.section-title { font-size: 17px; font-weight: 700; color: #111827; margin-bottom: 2px; }
.section-cap   { font-size: 13px; color: #6b7280; margin-bottom: 8px; }

.kpi-label { font-size: 11px; font-weight: 700; color: #6b7280;
             text-transform: uppercase; letter-spacing: 0.07em; }
.kpi-value { font-size: 32px; font-weight: 800; color: #111827; line-height: 1.25; }
.kpi-sub   { font-size: 13px; color: #6b7280; }
.kpi-up    { color: #15803d; font-weight: 600; }
.kpi-down  { color: #dc2626; font-weight: 600; }

.pill {
    display: inline-block; padding: 2px 10px; border-radius: 999px;
    font-size: 12px; font-weight: 500; background: #eff6ff; color: #1d4ed8;
    border: 1px solid #bfdbfe; margin: 2px 4px 2px 0; white-space: nowrap;
}
.src-badge {
    display: inline-block; padding: 2px 9px; border-radius: 6px;
    font-size: 12px; font-weight: 600; white-space: nowrap;
}
.sent-num { font-family: 'JetBrains Mono', ui-monospace, monospace !important;
            font-weight: 700; font-size: 15px; }

.mention-row { border-bottom: 1px solid #f3f4f6; padding: 14px 4px; }
.mention-row:last-child { border-bottom: none; }
.mention-title { font-weight: 600; font-size: 15px; color: #111827; }
.mention-body  { font-size: 13px; color: #6b7280; margin-top: 3px; line-height: 1.5; }
.mention-meta  { font-size: 12px; color: #9ca3af; }
.mention-meta a { color: #2563eb; text-decoration: none; }

.prio { display: inline-block; padding: 2px 10px; border-radius: 6px;
        font-size: 12px; font-weight: 700; color: white; }
.prio-P0 { background: #dc2626; }
.prio-P1 { background: #d97706; }
.prio-P2 { background: #2563eb; }
.day-chip { display: inline-block; padding: 2px 10px; border-radius: 6px;
            font-size: 12px; font-weight: 600; background: #f3f4f6; color: #374151; }
.quote { border-left: 3px solid #e5e7eb; padding: 4px 12px; margin: 8px 0 0 0;
         font-size: 13px; color: #6b7280; font-style: italic; line-height: 1.5; }

.empty-step { display: flex; gap: 14px; align-items: baseline; padding: 10px 0;
              border-bottom: 1px solid #f3f4f6; }
.empty-step:last-child { border-bottom: none; }
.step-num { min-width: 26px; height: 26px; border-radius: 999px; background: #eff6ff;
            color: #1d4ed8; font-weight: 700; font-size: 13px; text-align: center;
            line-height: 26px; }
</style>
""", unsafe_allow_html=True)

SOURCE_COLORS = {
    "Google Play": "#16a34a", "App Store": "#0f172a", "Reddit": "#ff4500",
    "Hacker News": "#f26522", "Bluesky": "#1185fe", "Google News": "#7c3aed",
    "Stack Overflow": "#f48024", "Upload": "#64748b",
}

FUNNEL_COLORS = {
    "Awareness": "#8b1538", "Solution Search": "#e11d48", "Comparison": "#b08968",
    "Purchase Decision": "#16a34a", "Experience & Advocacy": "#2563eb",
    "Unclassified": "#94a3b8",
}

SOCIAL_SOURCES = ["Reddit", "Hacker News", "Bluesky", "Google News", "Stack Overflow"]


def src_badge(name: str) -> str:
    c = SOURCE_COLORS.get(name, "#64748b")
    return (f'<span class="src-badge" style="background:{c}14; color:{c}; '
            f'border:1px solid {c}33">{html.escape(name)}</span>')


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


def section(title: str, caption: str):
    st.markdown(f'<div class="section-title">{title}</div>'
                f'<div class="section-cap">{caption}</div>', unsafe_allow_html=True)


# ------------------------------------------------------------------ state

if "feedback" not in st.session_state:
    st.session_state.feedback = pd.DataFrame(columns=sources.COLUMNS)
if "ai_roadmap" not in st.session_state:
    st.session_state.ai_roadmap = None


def ingest(df: pd.DataFrame) -> int:
    """Analyze and merge new feedback; returns number of new rows kept."""
    if df.empty:
        return 0
    df = add_journey(add_themes(add_sentiment(df)))
    before = len(st.session_state.feedback)
    combined = pd.concat([st.session_state.feedback, df], ignore_index=True)
    combined = combined.drop_duplicates(subset=["source", "text"], keep="first")
    st.session_state.feedback = combined
    st.session_state.ai_roadmap = None  # stale after new data
    return len(combined) - before


# ------------------------------------------------------------------ sidebar

st.sidebar.markdown(
    '<div style="padding: 4px 0 10px 0;">'
    '<span class="logo-mark"></span>'
    '<span style="font-size:19px; font-weight:800; color:#111827;">Feedback Agent</span>'
    '<div class="app-sub">Social listening for product teams</div></div>',
    unsafe_allow_html=True)

st.sidebar.markdown('<div class="side-label">Track a brand</div>', unsafe_allow_html=True)
keyword = st.sidebar.text_input("Brand or product keyword", placeholder="e.g. Notion",
                                label_visibility="collapsed")
picked = st.sidebar.multiselect("Social sources", SOCIAL_SOURCES,
                                default=["Reddit", "Hacker News", "Bluesky", "Google News"])
with st.sidebar.expander("Search options"):
    rd_sub = st.text_input("Limit Reddit to subreddit (optional)", placeholder="notion")
    per_source = st.slider("Max mentions per source", 25, 100, 50, 25)

if st.sidebar.button("Pull social mentions", type="primary",
                     use_container_width=True, disabled=not (keyword and picked)):
    fetchers = {
        "Reddit": lambda: sources.fetch_reddit(keyword, per_source, rd_sub),
        "Hacker News": lambda: sources.fetch_hackernews(keyword, per_source),
        "Bluesky": lambda: sources.fetch_bluesky(keyword, per_source),
        "Google News": lambda: sources.fetch_google_news(keyword, per_source),
        "Stack Overflow": lambda: sources.fetch_stackoverflow(keyword, per_source),
    }
    results, failures = [], []
    with st.spinner("Listening across sources..."):
        for name in picked:
            try:
                n = ingest(fetchers[name]())
                results.append(f"{name} {n}")
            except Exception:
                failures.append(name)
    st.sidebar.success("New mentions: " + ", ".join(results))
    if failures:
        st.sidebar.warning("No data from: " + ", ".join(failures))

st.sidebar.markdown('<div class="side-label">App store reviews</div>', unsafe_allow_html=True)
with st.sidebar.expander("Google Play and App Store"):
    gp_id = st.text_input("Google Play package id", placeholder="com.notion.id",
                          help="From the Play Store URL: play.google.com/store/apps/details?id=<this>")
    as_id = st.text_input("App Store numeric id", placeholder="1232780281",
                          help="The number in the App Store URL: apps.apple.com/us/app/.../id<this>")
    as_country = st.text_input("Country code", value="us", max_chars=2)
    if st.button("Pull app reviews", use_container_width=True, disabled=not (gp_id or as_id)):
        msgs, fails = [], []
        with st.spinner("Fetching app reviews..."):
            if gp_id:
                try:
                    msgs.append(f"Google Play {ingest(sources.fetch_google_play(gp_id, 200))}")
                except Exception:
                    fails.append("Google Play")
            if as_id:
                try:
                    msgs.append(f"App Store {ingest(sources.fetch_app_store(as_id, as_country.lower()))}")
                except Exception:
                    fails.append("App Store")
        if msgs:
            st.success("New reviews: " + ", ".join(msgs))
        if fails:
            st.warning("No data from: " + ", ".join(fails))

st.sidebar.markdown('<div class="side-label">Import</div>', unsafe_allow_html=True)
with st.sidebar.expander("Upload Excel / CSV"):
    st.caption("Any file with a feedback or review text column. Date, rating and author are auto-detected.")
    uploaded = st.file_uploader("Choose file", type=["xlsx", "xls", "csv"],
                                label_visibility="collapsed")
    if uploaded and st.button("Import file", use_container_width=True):
        try:
            n = ingest(sources.load_upload(uploaded))
            st.success(f"Imported {n} items")
        except Exception as e:
            st.error(f"Could not read file: {e}")

st.sidebar.divider()
df = st.session_state.feedback
st.sidebar.caption(f"{len(df)} mentions collected")
if st.sidebar.button("Clear all data", use_container_width=True):
    st.session_state.feedback = pd.DataFrame(columns=sources.COLUMNS)
    st.session_state.ai_roadmap = None
    st.rerun()

# ------------------------------------------------------------------ header

st.markdown(
    '<div style="margin-bottom: 14px;">'
    '<span class="logo-mark" style="width:14px;height:14px;"></span>'
    '<span class="app-title">Feedback Agent</span>'
    '<div class="app-sub">Listen everywhere your customers talk. Know exactly what to build next.</div>'
    '</div>', unsafe_allow_html=True)

if df.empty:
    st.markdown(f"""
<div class="card" style="max-width:720px;">
  <div class="section-title">Start listening in three steps</div>
  <div class="empty-step"><div class="step-num">1</div><div>
    <b>Track a brand</b> - type a product keyword in the sidebar and pull mentions from
    Reddit, Hacker News, Bluesky, Google News and Stack Overflow.</div></div>
  <div class="empty-step"><div class="step-num">2</div><div>
    <b>Add app reviews</b> - pull live reviews from Google Play
    (e.g. <code>com.spotify.music</code>) and the App Store (e.g. <code>324684580</code>).</div></div>
  <div class="empty-step"><div class="step-num">3</div><div>
    <b>Or upload your own</b> - drop in any Excel/CSV export of customer feedback,
    support tickets or NPS comments.</div></div>
  <div class="section-cap" style="margin-top:12px;">Every mention is scored for sentiment,
  tagged with pain themes and mapped to a customer-journey stage. No API keys needed.</div>
</div>""", unsafe_allow_html=True)
    st.stop()

tab_dash, tab_roadmap, tab_mentions = st.tabs(["Dashboard", "Weekly Roadmap", "Mentions"])

# ------------------------------------------------------------------ dashboard

with tab_dash:
    main_col, kpi_col = st.columns([2.8, 1])

    with kpi_col:
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
            arrow = "&#8593;" if diff >= 0 else "&#8595;"
            delta_html = f'<div class="kpi-sub"><span class="{cls}">{arrow} {diff:+d}</span> vs prev 28d</div>'
            mentions_val = last28
        else:
            mentions_val = len(df)

        avg100 = int(df["sentiment100"].mean())
        neg_share = (df["sentiment_label"] == "Negative").mean()
        ratings = pd.to_numeric(df["rating"], errors="coerce")
        rating_str = f"{ratings.mean():.2f}" if ratings.notna().any() else "-"
        n_sources = df["source"].nunique()

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
<div class="card"><div class="kpi-label">Sources</div>
<div class="kpi-value">{n_sources}</div>
<div class="kpi-sub">channels tracked</div></div>
""", unsafe_allow_html=True)

    with main_col:
        section("Customer Journey Funnel",
                "Where your mentions sit across the customer journey.")
        js = journey_summary(df)
        fig = px.bar(js, x="count", y="stage", orientation="h", text="count",
                     color="stage", color_discrete_map=FUNNEL_COLORS,
                     category_orders={"stage": JOURNEY_ORDER})
        fig.update_traces(textposition="inside", textfont=dict(color="white", size=13),
                          hovertemplate="%{y}: %{x}<extra></extra>")
        fig.update_layout(template="plotly_white", showlegend=False, height=300,
                          margin=dict(t=8, l=0, r=0, b=0),
                          yaxis=dict(autorange="reversed", title=""),
                          xaxis=dict(title=""), font=dict(family="Inter"),
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)

        c1, c2 = st.columns(2)
        with c1:
            section("Pain themes", "What people complain about, colored by sentiment.")
            ts = theme_summary(df)
            if not ts.empty:
                fig = px.bar(ts, x="mentions", y="theme", orientation="h",
                             color="avg_sentiment",
                             color_continuous_scale=["#dc2626", "#d1d5db", "#16a34a"],
                             range_color=[-0.6, 0.6])
                fig.update_layout(template="plotly_white", height=300,
                                  yaxis=dict(autorange="reversed", title=""),
                                  xaxis=dict(title=""),
                                  margin=dict(t=8, l=0, r=0, b=0),
                                  coloraxis_colorbar_title="",
                                  font=dict(family="Inter"),
                                  paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig, use_container_width=True)
        with c2:
            section("Sentiment over time", "Weekly average, 0-100. Above 50 is positive.")
            if len(dated) > 5:
                dated["date"] = pd.to_datetime(dated["date"], utc=True, errors="coerce")
                weekly = (dated.dropna(subset=["date"]).set_index("date").sort_index()
                               .groupby(pd.Grouper(freq="W"))["sentiment100"]
                               .agg(["mean", "count"]).reset_index())
                weekly = weekly[weekly["count"] > 0]
                fig = px.line(weekly, x="date", y="mean", markers=True)
                fig.add_hline(y=50, line_dash="dot", line_color="#9ca3af")
                fig.update_traces(line_color="#2563eb")
                fig.update_layout(template="plotly_white", height=300,
                                  margin=dict(t=8, l=0, r=0, b=0),
                                  yaxis=dict(range=[0, 100], title=""),
                                  xaxis=dict(title=""), font=dict(family="Inter"),
                                  paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.caption("Not enough dated feedback yet.")

        c3, c4 = st.columns(2)
        with c3:
            section("Mentions by source", "Which channels your customers talk on.")
            sc = df["source"].value_counts().reset_index()
            sc.columns = ["source", "count"]
            fig = px.bar(sc, x="count", y="source", orientation="h",
                         color="source", color_discrete_map=SOURCE_COLORS)
            fig.update_layout(template="plotly_white", showlegend=False, height=280,
                              yaxis=dict(autorange="reversed", title=""),
                              xaxis=dict(title=""), margin=dict(t=8, l=0, r=0, b=0),
                              font=dict(family="Inter"),
                              paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, use_container_width=True)
        with c4:
            section("Top words in negative feedback", "The vocabulary of complaints.")
            terms = top_terms(df, "Negative", 12)
            if terms:
                tdf = pd.DataFrame(terms, columns=["word", "count"])
                fig = px.bar(tdf, x="word", y="count", color_discrete_sequence=["#dc2626"])
                fig.update_layout(template="plotly_white", height=280,
                                  margin=dict(t=8, l=0, r=0, b=0), font=dict(family="Inter"),
                                  xaxis=dict(title=""), yaxis=dict(title=""),
                                  paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.caption("No negative feedback found.")

# ------------------------------------------------------------------ roadmap

with tab_roadmap:
    section("Your roadmap for the week",
            "Pain themes ranked by volume x negativity x recency, turned into a Mon-Fri plan. "
            "P0 = do first. Built automatically from the mentions you pulled.")

    items = build_roadmap(df)
    if not items:
        st.info("Not enough themed feedback yet to build a roadmap. Pull more data.")
    else:
        for it in items:
            trend_badge = ""
            if it["trend"] == "rising":
                trend_badge = ' · <span class="kpi-down">rising</span>'
            elif it["trend"] == "cooling":
                trend_badge = ' · <span class="kpi-up">cooling</span>'
            quotes_html = "".join(
                f'<div class="quote">"{html.escape(q)}"</div>' for q in it["quotes"])
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
    section("AI-polished roadmap (optional)",
            "With an API key, the plan above is rewritten into a day-by-day roadmap "
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
        with st.spinner("Planning your week... (can take a minute)"):
            try:
                st.session_state.ai_roadmap = generate_ai_roadmap(df, items, api_key)
            except Exception as e:
                st.error(f"AI roadmap failed: {e}")

    if st.session_state.ai_roadmap:
        st.markdown(st.session_state.ai_roadmap)
        st.download_button("Download roadmap (markdown)",
                           st.session_state.ai_roadmap.encode("utf-8"),
                           file_name="weekly_roadmap.md", mime="text/markdown")

# ------------------------------------------------------------------ mentions

with tab_mentions:
    section("Mentions", "Every tracked mention from your sources, newest first.")

    f1, f2, f3, f4 = st.columns(4)
    src_filter = f1.multiselect("Source", sorted(df["source"].unique()))
    sent_filter = f2.multiselect("Sentiment", ["Negative", "Neutral", "Positive"])
    theme_options = sorted({t.strip() for ts in df["themes"] for t in ts.split(",")})
    theme_filter = f3.multiselect("Pain theme", theme_options)
    journey_filter = f4.multiselect("Journey stage", JOURNEY_ORDER)
    search = st.text_input("Search text", placeholder="e.g. crash, refund, pricing...")

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

    rows_html = []
    for _, r in view.head(100).iterrows():
        text = str(r["text"])
        title = html.escape(text[:90] + ("..." if len(text) > 90 else ""))
        body = html.escape(text[90:340] + ("..." if len(text) > 340 else "")) if len(text) > 90 else ""
        pains = "".join(f'<span class="pill">{html.escape(t.strip())}</span>'
                        for t in str(r["themes"]).split(",") if t.strip() and t.strip() != "Other")
        s100 = int(r["sentiment100"])
        rating = f" · {int(r['rating'])} stars" if pd.notna(r.get("rating")) else ""
        author = f" · {html.escape(str(r['author'])[:30])}" if str(r.get("author", "")).strip() else ""
        link = (f' · <a href="{html.escape(str(r["url"]))}" target="_blank">open</a>'
                if str(r.get("url", "")).startswith("http") else "")
        body_html = f'<div class="mention-body">{body}</div>' if body else ''
        # single-line HTML: indented lines inside st.markdown become code blocks
        rows_html.append(
            '<div class="mention-row">'
            '<div style="display:flex; justify-content:space-between; gap:16px;">'
            '<div style="flex:1; min-width:0;">'
            f'<div class="mention-title">{title}</div>{body_html}'
            f'<div class="mention-meta" style="margin-top:7px;">'
            f"{src_badge(r['source'])}&nbsp; {html.escape(str(r['journey']))}{rating}{author}{link}</div></div>"
            '<div style="text-align:right; flex-shrink:0;">'
            f'<span class="sent-num" style="color:{sent_color(s100)}">{s100}</span>'
            f'<div class="mention-meta">{rel_time(r["date"])}</div>'
            f'<div style="margin-top:6px; max-width:240px;">{pains}</div>'
            '</div></div></div>')
    st.markdown(f'<div class="card">{"".join(rows_html)}</div>', unsafe_allow_html=True)
    if len(view) > 100:
        st.caption("Showing newest 100. Download the full set below.")

    st.download_button(
        "Download as CSV",
        view.to_csv(index=False).encode("utf-8"),
        file_name="feedback_export.csv",
        mime="text/csv",
    )
