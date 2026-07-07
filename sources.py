"""Data source connectors: Excel/CSV upload, Google Play, App Store, Reddit.

Every connector returns a pandas DataFrame with the unified schema:
    source, date, rating, text, author, url
(rating is None where the source has no ratings, e.g. Reddit)
"""

from __future__ import annotations

import html as html_lib
import re
from datetime import datetime, timezone

import pandas as pd
import requests

COLUMNS = ["source", "date", "rating", "text", "author", "url"]

USER_AGENT = "feedback-agent/1.0 (product feedback research tool)"


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=COLUMNS)


# ---------------------------------------------------------------- Excel / CSV

def load_upload(file) -> pd.DataFrame:
    """Load an uploaded Excel/CSV file and map its columns to the unified schema.

    Column detection is fuzzy: it looks for likely names for the feedback text,
    date, rating and author columns.
    """
    name = file.name.lower()
    if name.endswith(".csv"):
        df = pd.read_csv(file)
    else:
        df = pd.read_excel(file)

    if df.empty:
        return _empty()

    cols = {c.lower().strip(): c for c in df.columns}

    def find(*candidates):
        for cand in candidates:
            for low, orig in cols.items():
                if cand in low:
                    return orig
        return None

    text_col = find("feedback", "review", "comment", "text", "message", "description", "body")
    date_col = find("date", "time", "created", "submitted")
    rating_col = find("rating", "stars", "score", "nps")
    author_col = find("author", "user", "name", "customer", "email")

    if text_col is None:
        # fall back to the first object-dtype column with the longest strings
        obj_cols = [c for c in df.columns if df[c].dtype == object]
        if not obj_cols:
            return _empty()
        text_col = max(obj_cols, key=lambda c: df[c].astype(str).str.len().mean())

    out = pd.DataFrame({
        "source": "Upload",
        "date": pd.to_datetime(df[date_col], errors="coerce") if date_col else pd.NaT,
        "rating": pd.to_numeric(df[rating_col], errors="coerce") if rating_col else None,
        "text": df[text_col].astype(str),
        "author": df[author_col].astype(str) if author_col else "",
        "url": "",
    })
    out = out[out["text"].str.strip().str.len() > 2]
    return out.reset_index(drop=True)


# ---------------------------------------------------------------- Google Play

def fetch_google_play(app_id: str, count: int = 200, lang: str = "en", country: str = "us") -> pd.DataFrame:
    """Fetch recent reviews from Google Play. app_id e.g. 'com.spotify.music'."""
    from google_play_scraper import Sort, reviews

    results, _ = reviews(
        app_id.strip(),
        lang=lang,
        country=country,
        sort=Sort.NEWEST,
        count=count,
    )
    if not results:
        return _empty()

    rows = [{
        "source": "Google Play",
        "date": r.get("at"),
        "rating": r.get("score"),
        "text": r.get("content") or "",
        "author": r.get("userName") or "",
        "url": f"https://play.google.com/store/apps/details?id={app_id.strip()}",
    } for r in results]
    df = pd.DataFrame(rows, columns=COLUMNS)
    return df[df["text"].str.strip().str.len() > 2].reset_index(drop=True)


# ------------------------------------------------------------------ App Store

def fetch_app_store(app_id: str, country: str = "us", pages: int = 4) -> pd.DataFrame:
    """Fetch recent reviews via Apple's public RSS feed. app_id is the numeric id
    from the App Store URL, e.g. 324684580 for Spotify."""
    app_id = re.sub(r"\D", "", str(app_id))
    rows = []
    for page in range(1, pages + 1):
        url = (f"https://itunes.apple.com/{country}/rss/customerreviews/"
               f"page={page}/id={app_id}/sortby=mostrecent/json")
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
            resp.raise_for_status()
            entries = resp.json().get("feed", {}).get("entry", [])
        except Exception:
            break
        # first entry on page 1 is app metadata, not a review
        for e in entries:
            if "im:rating" not in e:
                continue
            title = e.get("title", {}).get("label", "")
            body = e.get("content", {}).get("label", "")
            date_raw = e.get("updated", {}).get("label")
            rows.append({
                "source": "App Store",
                "date": pd.to_datetime(date_raw, errors="coerce"),
                "rating": pd.to_numeric(e["im:rating"].get("label"), errors="coerce"),
                "text": f"{title}. {body}".strip(". "),
                "author": e.get("author", {}).get("name", {}).get("label", ""),
                "url": f"https://apps.apple.com/{country}/app/id{app_id}",
            })
        if not entries:
            break
    df = pd.DataFrame(rows, columns=COLUMNS) if rows else _empty()
    return df.reset_index(drop=True)


# --------------------------------------------------------------------- Reddit

_BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def fetch_reddit(query: str, limit: int = 100, subreddit: str = "") -> pd.DataFrame:
    """Search Reddit posts, no API key needed.

    Tries three free endpoints in order, since Reddit rate-limits/blocks
    unauthenticated JSON on some networks:
      1. reddit.com JSON search
      2. reddit.com RSS search (official, rarely blocked)
      3. PullPush archive API
    """
    sub = subreddit.strip().lstrip("r/").strip("/")

    for fetcher in (_reddit_json, _reddit_rss, _reddit_pullpush):
        try:
            df = fetcher(query, limit, sub)
            if not df.empty:
                return df
        except Exception:
            continue
    return _empty()


def _reddit_json(query: str, limit: int, sub: str) -> pd.DataFrame:
    if sub:
        base = f"https://www.reddit.com/r/{sub}/search.json"
        params = {"q": query, "sort": "new", "limit": min(limit, 100), "restrict_sr": "1"}
    else:
        base = "https://www.reddit.com/search.json"
        params = {"q": query, "sort": "new", "limit": min(limit, 100)}

    resp = requests.get(base, params=params, headers={"User-Agent": _BROWSER_UA}, timeout=15)
    resp.raise_for_status()
    children = resp.json().get("data", {}).get("children", [])

    rows = []
    for c in children:
        d = c.get("data", {})
        text = (d.get("title", "") + ". " + (d.get("selftext") or "")).strip(". ")
        if len(text.strip()) <= 2:
            continue
        rows.append({
            "source": "Reddit",
            "date": datetime.fromtimestamp(d.get("created_utc", 0), tz=timezone.utc),
            "rating": None,
            "text": text[:3000],
            "author": d.get("author", ""),
            "url": "https://www.reddit.com" + d.get("permalink", ""),
        })
    return pd.DataFrame(rows, columns=COLUMNS) if rows else _empty()


def _reddit_rss(query: str, limit: int, sub: str) -> pd.DataFrame:
    import xml.etree.ElementTree as ET

    if sub:
        base = f"https://www.reddit.com/r/{sub}/search.rss"
        params = {"q": query, "sort": "new", "restrict_sr": "1"}
    else:
        base = "https://www.reddit.com/search.rss"
        params = {"q": query, "sort": "new"}

    resp = requests.get(base, params=params, headers={"User-Agent": _BROWSER_UA}, timeout=15)
    resp.raise_for_status()
    ns = {"a": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(resp.content)

    rows = []
    for entry in root.findall("a:entry", ns)[:limit]:
        title = entry.findtext("a:title", "", ns)
        content_html = entry.findtext("a:content", "", ns)
        # strip HTML tags and collapse whitespace
        body = re.sub(r"<[^>]+>", " ", content_html)
        body = re.sub(r"\s+", " ", body).replace("submitted by", "").strip()
        author_el = entry.find("a:author/a:name", ns)
        link_el = entry.find("a:link", ns)
        rows.append({
            "source": "Reddit",
            "date": pd.to_datetime(entry.findtext("a:updated", None, ns), errors="coerce"),
            "rating": None,
            "text": f"{title}. {body}".strip(". ")[:3000],
            "author": (author_el.text if author_el is not None else "").lstrip("/u/"),
            "url": link_el.get("href", "") if link_el is not None else "",
        })
    return pd.DataFrame(rows, columns=COLUMNS) if rows else _empty()


def _reddit_pullpush(query: str, limit: int, sub: str) -> pd.DataFrame:
    params = {"q": query, "size": min(limit, 100), "sort": "desc", "sort_type": "created_utc"}
    if sub:
        params["subreddit"] = sub
    resp = requests.get("https://api.pullpush.io/reddit/search/submission/",
                        params=params, headers={"User-Agent": _BROWSER_UA}, timeout=25)
    resp.raise_for_status()
    data = resp.json().get("data", [])

    rows = []
    for d in data:
        text = (d.get("title", "") + ". " + (d.get("selftext") or "")).strip(". ")
        if len(text.strip()) <= 2 or text.strip() in ("[removed]", "[deleted]"):
            continue
        rows.append({
            "source": "Reddit",
            "date": datetime.fromtimestamp(d.get("created_utc", 0), tz=timezone.utc),
            "rating": None,
            "text": text[:3000],
            "author": d.get("author", ""),
            "url": "https://www.reddit.com" + (d.get("permalink") or ""),
        })
    return pd.DataFrame(rows, columns=COLUMNS) if rows else _empty()


# ---------------------------------------------------------------- Hacker News

def fetch_hackernews(query: str, limit: int = 100) -> pd.DataFrame:
    """Search Hacker News stories and comments via the free Algolia API."""
    resp = requests.get(
        "https://hn.algolia.com/api/v1/search_by_date",
        params={"query": query, "tags": "(story,comment)", "hitsPerPage": min(limit, 100)},
        headers={"User-Agent": USER_AGENT}, timeout=20,
    )
    resp.raise_for_status()
    hits = resp.json().get("hits", [])

    rows = []
    for h in hits:
        title = h.get("title") or ""
        body = h.get("story_text") or h.get("comment_text") or ""
        body = re.sub(r"<[^>]+>", " ", body)
        text = html_lib.unescape(f"{title}. {body}").strip(". ")
        text = re.sub(r"\s+", " ", text)
        if len(text.strip()) <= 2:
            continue
        rows.append({
            "source": "Hacker News",
            "date": pd.to_datetime(h.get("created_at"), utc=True, errors="coerce"),
            "rating": None,
            "text": text[:3000],
            "author": h.get("author", ""),
            "url": f"https://news.ycombinator.com/item?id={h.get('objectID')}",
        })
    return pd.DataFrame(rows, columns=COLUMNS) if rows else _empty()


# ---------------------------------------------------------------- Google News

def fetch_google_news(query: str, limit: int = 50) -> pd.DataFrame:
    """Press and media mentions via the free Google News RSS feed."""
    import xml.etree.ElementTree as ET

    resp = requests.get(
        "https://news.google.com/rss/search",
        params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"},
        headers={"User-Agent": _BROWSER_UA}, timeout=20,
    )
    resp.raise_for_status()
    root = ET.fromstring(resp.content)

    rows = []
    for item in root.findall(".//item")[:limit]:
        title = html_lib.unescape(item.findtext("title", "") or "")
        outlet = item.findtext("source", "") or ""
        if len(title.strip()) <= 2:
            continue
        rows.append({
            "source": "Google News",
            "date": pd.to_datetime(item.findtext("pubDate", None), utc=True, errors="coerce"),
            "rating": None,
            "text": title[:3000],
            "author": outlet,
            "url": item.findtext("link", "") or "",
        })
    return pd.DataFrame(rows, columns=COLUMNS) if rows else _empty()


# -------------------------------------------------------------------- Bluesky

def fetch_bluesky(query: str, limit: int = 100) -> pd.DataFrame:
    """Search public Bluesky posts via the free public AppView API."""
    posts = []
    for host in ("https://api.bsky.app", "https://public.api.bsky.app"):
        try:
            resp = requests.get(
                f"{host}/xrpc/app.bsky.feed.searchPosts",
                params={"q": query, "limit": min(limit, 100), "sort": "latest"},
                headers={"User-Agent": _BROWSER_UA}, timeout=20,
            )
            resp.raise_for_status()
            posts = resp.json().get("posts", [])
            if posts:
                break
        except Exception:
            continue

    rows = []
    for p in posts:
        record = p.get("record", {})
        text = re.sub(r"\s+", " ", record.get("text") or "").strip()
        if len(text) <= 2:
            continue
        handle = p.get("author", {}).get("handle", "")
        rkey = (p.get("uri") or "").rsplit("/", 1)[-1]
        rows.append({
            "source": "Bluesky",
            "date": pd.to_datetime(record.get("createdAt") or p.get("indexedAt"),
                                   utc=True, errors="coerce"),
            "rating": None,
            "text": text[:3000],
            "author": handle,
            "url": f"https://bsky.app/profile/{handle}/post/{rkey}" if handle and rkey else "",
        })
    return pd.DataFrame(rows, columns=COLUMNS) if rows else _empty()


# --------------------------------------------------------------- Stack Overflow

def fetch_stackoverflow(query: str, limit: int = 50) -> pd.DataFrame:
    """Search Stack Overflow questions via the free Stack Exchange API."""
    resp = requests.get(
        "https://api.stackexchange.com/2.3/search/advanced",
        params={"order": "desc", "sort": "creation", "q": query,
                "site": "stackoverflow", "pagesize": min(limit, 100), "filter": "withbody"},
        headers={"User-Agent": USER_AGENT}, timeout=25,
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])

    rows = []
    for it in items:
        title = html_lib.unescape(it.get("title") or "")
        body = re.sub(r"<[^>]+>", " ", it.get("body") or "")
        text = html_lib.unescape(f"{title}. {body}").strip(". ")
        text = re.sub(r"\s+", " ", text)
        if len(text.strip()) <= 2:
            continue
        rows.append({
            "source": "Stack Overflow",
            "date": datetime.fromtimestamp(it.get("creation_date", 0), tz=timezone.utc),
            "rating": None,
            "text": text[:3000],
            "author": it.get("owner", {}).get("display_name", ""),
            "url": it.get("link", ""),
        })
    return pd.DataFrame(rows, columns=COLUMNS) if rows else _empty()
