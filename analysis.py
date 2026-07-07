"""Local (free, no-API-key) analysis: sentiment scoring and theme detection."""

from __future__ import annotations

import re
from collections import Counter

import pandas as pd
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

_analyzer = SentimentIntensityAnalyzer()

# Theme keyword map: a hit on any keyword tags the feedback with that theme.
THEMES = {
    "Bugs & Crashes": [
        "bug", "crash", "crashes", "freeze", "frozen", "broken", "error",
        "glitch", "not working", "doesn't work", "doesnt work", "fails", "failed",
    ],
    "Performance": [
        "slow", "lag", "laggy", "loading", "takes forever", "battery", "drain",
        "memory", "heavy", "speed", "fast", "performance", "hang",
    ],
    "UI / UX": [
        "ui", "ux", "design", "interface", "layout", "confusing", "hard to use",
        "intuitive", "navigation", "dark mode", "theme", "font", "button",
    ],
    "Pricing & Billing": [
        "price", "pricing", "expensive", "subscription", "billing", "charged",
        "refund", "payment", "pay", "free trial", "cost", "money",
    ],
    "Login & Account": [
        "login", "log in", "sign in", "signin", "password", "account", "otp",
        "verification", "logout", "logged out", "authentication", "2fa",
    ],
    "Feature Requests": [
        "feature", "wish", "would be nice", "please add", "add support", "missing",
        "should have", "need option", "request", "suggestion", "hope you",
    ],
    "Customer Support": [
        "support", "customer service", "no response", "contacted", "help center",
        "ticket", "reply", "respond", "service team",
    ],
    "Ads & Notifications": [
        "ads", "advert", "ad ", "notification", "spam", "popup", "pop-up",
        "annoying", "intrusive",
    ],
}

_STOPWORDS = set("""
a an and are as at be but by for from has have i if in is it its of on or so
that the this to was were will with you your app very just really would can
get got dont don't do does did im i'm not no me my we they he she them their
there than then when what who how why all any some out up about after also
been being had more most other only own too s t can will don should now
""".split())


# Customer journey stages: keyword heuristics, checked in order.
JOURNEY_STAGES = {
    "Awareness": [
        "what is", "just heard", "heard about", "saw an ad", "anyone know",
        "just found", "discovered", "never heard", "is this the app",
    ],
    "Solution Search": [
        "looking for", "recommend me", "any recommendation", "best app for",
        "need an app", "suggestions for", "how do i", "is there an app",
        "any app that", "what app",
    ],
    "Comparison": [
        " vs ", "versus", "compared to", "better than", "alternative to",
        "alternatives", "switch from", "switching from", "instead of",
        "or should i use", "competitor",
    ],
    "Purchase Decision": [
        "worth it", "should i buy", "should i get", "free trial", "about to subscribe",
        "thinking of buying", "before i pay", "is premium worth", "upgrade to",
    ],
    "Experience & Advocacy": [
        "been using", "i use it", "i've used", "i have used", "love this",
        "hate this", "uninstalled", "cancelled", "canceled", "my experience",
        "recommend it", "would recommend", "stopped using",
    ],
}

JOURNEY_ORDER = list(JOURNEY_STAGES.keys()) + ["Unclassified"]

# Sources that are inherently first-hand product experience.
_EXPERIENCE_SOURCES = {"Google Play", "App Store"}


def add_sentiment(df: pd.DataFrame) -> pd.DataFrame:
    """Add sentiment (-1..1 compound), a 0-100 score, and a P/N/N label."""
    df = df.copy()
    scores = df["text"].astype(str).map(lambda t: _analyzer.polarity_scores(t[:2000])["compound"])
    df["sentiment"] = scores
    df["sentiment100"] = ((scores + 1) * 50).round().astype(int)
    df["sentiment_label"] = pd.cut(
        scores, bins=[-1.01, -0.05, 0.05, 1.01],
        labels=["Negative", "Neutral", "Positive"],
    )
    return df


def add_journey(df: pd.DataFrame) -> pd.DataFrame:
    """Tag each item with a customer-journey stage."""
    df = df.copy()

    def detect(row) -> str:
        low = " " + str(row["text"]).lower() + " "
        for stage, kws in JOURNEY_STAGES.items():
            if any(k in low for k in kws):
                return stage
        # A store review with a rating is first-hand experience by definition
        if row["source"] in _EXPERIENCE_SOURCES or pd.notna(row.get("rating")):
            return "Experience & Advocacy"
        return "Unclassified"

    df["journey"] = df.apply(detect, axis=1)
    return df


def journey_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Counts + share per journey stage, in funnel order."""
    counts = df["journey"].value_counts()
    total = max(len(df), 1)
    rows = [{
        "stage": s,
        "count": int(counts.get(s, 0)),
        "share": counts.get(s, 0) / total,
    } for s in JOURNEY_ORDER]
    return pd.DataFrame(rows)


def add_themes(df: pd.DataFrame) -> pd.DataFrame:
    """Tag each feedback item with matching themes (comma-separated string)."""
    df = df.copy()

    def detect(text: str) -> str:
        low = " " + str(text).lower() + " "
        hits = [theme for theme, kws in THEMES.items() if any(k in low for k in kws)]
        return ", ".join(hits) if hits else "Other"

    df["themes"] = df["text"].map(detect)
    return df


def theme_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Per-theme counts and average sentiment, sorted by volume."""
    rows = []
    for theme in list(THEMES.keys()) + ["Other"]:
        mask = df["themes"].str.contains(re.escape(theme), na=False)
        sub = df[mask]
        if len(sub) == 0:
            continue
        rows.append({
            "theme": theme,
            "mentions": len(sub),
            "avg_sentiment": round(float(sub["sentiment"].mean()), 3),
            "negative_share": round(float((sub["sentiment_label"] == "Negative").mean()), 3),
        })
    return pd.DataFrame(rows).sort_values("mentions", ascending=False).reset_index(drop=True)


def top_terms(df: pd.DataFrame, label: str = "Negative", n: int = 15) -> list[tuple[str, int]]:
    """Most frequent meaningful words in feedback with the given sentiment label."""
    texts = df.loc[df["sentiment_label"] == label, "text"].astype(str)
    counter: Counter = Counter()
    for t in texts:
        words = re.findall(r"[a-zA-Z']{3,}", t.lower())
        counter.update(w for w in words if w not in _STOPWORDS)
    return counter.most_common(n)
