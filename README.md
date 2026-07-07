# Feedback Agent

A free **social-listening tool for product teams**. Track a brand across every
channel customers talk on, analyze the conversation automatically, and get a
prioritized roadmap for the week.

## Sources

| Channel | How |
|---|---|
| **Reddit** | Search discussions, optionally per subreddit (JSON, RSS and archive fallbacks) |
| **Hacker News** | Stories and comments via the Algolia search API |
| **Bluesky** | Public post search via the AppView API |
| **Google News** | Press and media mentions via the news RSS feed |
| **Stack Overflow** | Developer questions via the Stack Exchange API |
| **Google Play** | Live app reviews by package id (e.g. `com.spotify.music`) |
| **App Store** | Live app reviews via Apple's public RSS feed (numeric app id) |
| **Excel / CSV upload** | Any feedback export. Columns are auto-detected |

All sources are free and need no API keys.

## Analysis

Every mention is scored for **sentiment** (VADER, runs locally), tagged with
**pain themes** (Bugs & Crashes, Performance, UI/UX, Pricing & Billing, Login &
Account, Feature Requests, Customer Support, Ads & Notifications) and mapped to
a **customer-journey stage** (Awareness, Solution Search, Comparison, Purchase
Decision, Experience & Advocacy).

**Dashboard**: KPI cards (mentions 28d with trend, avg sentiment 0-100,
negative share, avg rating, channels tracked), customer journey funnel,
pain-theme map, sentiment over time, mentions by source.

**Weekly Roadmap**: the headline feature for product managers. Pain themes are
ranked by volume x negativity x recency and turned into a prioritized Mon-Fri
plan (P0/P1/P2, suggested owner, evidence quotes). An optional AI step polishes
it into a day-by-day plan with quick wins and a watch list.

**Mentions**: a social-listening feed with source badges, journey stage, pain
tags and 0-100 sentiment per mention. Filter, search, export to CSV.

Design: light UI, Inter typeface, card-based layout.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy for free (Streamlit Community Cloud)

1. Push this folder to a **public GitHub repo**
2. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with GitHub
3. **New app**, pick the repo, main file `app.py`, **Deploy**
4. *(Optional)* In app **Settings > Secrets**, add:
   ```toml
   ANTHROPIC_API_KEY = "sk-ant-..."
   ```
   to enable the AI-polished roadmap without pasting a key each time.

You get a permanent public URL like `https://<your-app>.streamlit.app`, free forever.

## Tech

Python · Streamlit · pandas · Plotly · VADER sentiment · google-play-scraper ·
Apple RSS · Reddit JSON/RSS · HN Algolia · Bluesky AppView · Google News RSS ·
Stack Exchange API
