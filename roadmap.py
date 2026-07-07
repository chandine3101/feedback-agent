"""Weekly roadmap builder for product managers.

Turns analyzed feedback into a prioritized Monday-Friday action plan.
Works fully offline (heuristic engine); an optional AI step can polish it.
"""

from __future__ import annotations

import re

import pandas as pd

from analysis import THEMES

# What to actually do about each pain theme, and who usually owns it.
ACTION_PLAYBOOK = {
    "Bugs & Crashes": ("Triage the most-reported crashes, reproduce the top 3, ship a hotfix", "Engineering"),
    "Performance": ("Profile the slow screens users name; set a loading-time budget", "Engineering"),
    "UI / UX": ("Run a 30-min usability review of the flows users call confusing", "Design"),
    "Pricing & Billing": ("Audit billing complaints for double charges; clarify the pricing page", "Product + Finance"),
    "Login & Account": ("Investigate auth/OTP failures end-to-end; add a fallback login path", "Engineering"),
    "Feature Requests": ("Groom the top requested features into the backlog; reply to requesters", "Product"),
    "Customer Support": ("Clear the support backlog; write macros for the 3 most common issues", "Support"),
    "Ads & Notifications": ("Review ad load & notification frequency; add user controls", "Product"),
    "Other": ("Read through unclassified feedback and label recurring topics", "Product"),
}

_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


def build_roadmap(df: pd.DataFrame, max_items: int = 6) -> list[dict]:
    """Rank pain themes into a prioritized weekly plan.

    Priority score = volume x pain: mentions weighted by how negative the theme is,
    with a recency boost for themes trending worse in the last 7 days of data.
    """
    items = []
    dated = df.dropna(subset=["date"]).copy()
    if not dated.empty:
        dated["date"] = pd.to_datetime(dated["date"], utc=True, errors="coerce")
        cutoff = dated["date"].max() - pd.Timedelta(days=7)

    for theme in ACTION_PLAYBOOK:
        mask = df["themes"].str.contains(re.escape(theme), na=False)
        sub = df[mask]
        if len(sub) == 0 or theme == "Other":
            continue

        mentions = len(sub)
        neg_share = float((sub["sentiment_label"] == "Negative").mean())
        avg_sent = float(sub["sentiment"].mean())

        recent_boost = 1.0
        trend = ""
        if not dated.empty:
            dsub = dated[dated["themes"].str.contains(re.escape(theme), na=False)]
            recent = int((dsub["date"] > cutoff).sum())
            earlier = max(len(dsub) - recent, 0)
            if recent > earlier:
                recent_boost, trend = 1.3, "rising"
            elif recent < earlier:
                trend = "cooling"

        score = mentions * (0.4 + neg_share) * recent_boost

        # Two most negative representative quotes
        quotes = (sub.nsmallest(2, "sentiment")["text"]
                  .map(lambda t: str(t)[:220]).tolist())

        action, owner = ACTION_PLAYBOOK[theme]
        items.append({
            "theme": theme,
            "score": score,
            "mentions": mentions,
            "neg_share": neg_share,
            "avg_sentiment100": int(round((avg_sent + 1) * 50)),
            "trend": trend,
            "action": action,
            "owner": owner,
            "quotes": quotes,
        })

    items.sort(key=lambda x: x["score"], reverse=True)
    items = items[:max_items]

    # Assign priorities and spread across the week: P0 early, P2 late.
    for i, item in enumerate(items):
        item["priority"] = "P0" if i < 2 else ("P1" if i < 4 else "P2")
        item["day"] = _DAYS[min(i, len(_DAYS) - 1)]
    return items


# --------------------------------------------------------------- AI roadmap

AI_MODEL = "claude-opus-4-8"

AI_SYSTEM = """You are a pragmatic senior product manager. You receive customer
feedback data (statistics, theme breakdown, and raw samples) plus a draft
heuristic roadmap. Produce THE roadmap for next week as markdown:

## This Week's Focus
One sentence: the single most important thing to move.

## Monday - Friday Plan
A day-by-day plan. Each day: a bold headline task with priority tag (P0/P1/P2),
owner suggestion, 1-2 sentences of what to do and the evidence (quote real
feedback briefly). Front-load P0 work. Friday should include a review/measure slot.

## Quick Wins (< 1 day each)
3 bullet items.

## Watch List
Things not urgent yet but trending: 2-3 bullets.

Ground every item in the supplied data; never invent problems. Be concrete and
brief. A PM should be able to paste this into their planning doc as-is.
Do not use em dashes anywhere in your output."""


def generate_ai_roadmap(df: pd.DataFrame, heuristic_items: list[dict], api_key: str) -> str:
    """Ask the model to turn the data + draft plan into a polished weekly roadmap."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)

    draft = "\n".join(
        f"- [{it['priority']}] {it['theme']}: {it['mentions']} mentions, "
        f"{it['neg_share']:.0%} negative, trend={it['trend'] or 'flat'} -> {it['action']} ({it['owner']})"
        for it in heuristic_items
    )
    sample = df.nsmallest(60, "sentiment")
    quotes = "\n".join(
        f"[{r['source']} sent={r['sentiment100']}] {str(r['text'])[:300]}"
        for _, r in sample.iterrows()
    )
    prompt = (
        f"Total items: {len(df)} | Sentiment split: {df['sentiment_label'].value_counts().to_dict()}\n\n"
        f"DRAFT HEURISTIC ROADMAP\n{draft}\n\n"
        f"MOST NEGATIVE FEEDBACK SAMPLE\n{quotes}\n\n"
        "Write next week's roadmap."
    )

    with client.messages.stream(
        model=AI_MODEL,
        max_tokens=4000,
        thinking={"type": "adaptive"},
        system=AI_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        response = stream.get_final_message()

    return next((b.text for b in response.content if b.type == "text"), "No response.")
