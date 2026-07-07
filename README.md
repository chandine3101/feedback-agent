# 📡 Feedback Agent

A free **social-listening tool for product teams**. Pull customer feedback from
anywhere it lives, analyze it automatically, and get a prioritized roadmap for
the week.

## What it does

| Source | How |
|---|---|
| 📄 **Excel / CSV upload** | Drop in any feedback export. Columns are auto-detected |
| ▶️ **Google Play** | Live reviews by app package id (e.g. `com.spotify.music`) |
| 🍎 **App Store** | Live reviews via Apple's public RSS feed (numeric app id) |
| 👽 **Reddit** | Search discussions about your product, optionally per subreddit |

Every item is scored for **sentiment** (VADER, runs locally, no API key),
tagged with **pain themes** (Bugs & Crashes, Performance, UI/UX, Pricing &
Billing, Login & Account, Feature Requests, Customer Support, Ads &
Notifications) and classified into a **customer-journey stage** (Awareness,
Solution Search, Comparison, Purchase Decision, Experience & Advocacy).

**📊 Dashboard**: KPI cards (mentions 28d, avg sentiment 0-100, negative share,
avg rating), customer journey funnel, pain-theme map, sentiment over time.

**🗺️ Weekly Roadmap**: the headline feature for product managers. Pain themes
are ranked by volume x negativity x recency and turned into a prioritized
Mon-Fri plan (P0/P1/P2, suggested owner, evidence quotes). An optional AI step
polishes it into a day-by-day plan with quick wins and a watch list.

**💬 Mentions**: a social-listening feed of every mention with source, journey
stage, pain tags and 0-100 sentiment. Filter, search, export to CSV.

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
Apple RSS · Reddit JSON API
