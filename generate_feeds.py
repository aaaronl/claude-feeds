#!/usr/bin/env python3
"""Build unofficial RSS feeds for the Claude blog and the Anthropic newsroom.

Design goals:
  * Robust to layout changes - posts are matched by URL pattern, not by CSS
    classes that the sites can rename at any time.
  * Self-healing - every seen post is accumulated in docs/state.json, and each
    feed is rebuilt from that state. A single failed or blocked scrape therefore
    never empties an existing feed; it just adds nothing new that run.
  * No database, no paid service - output is plain files written to docs/, which
    GitHub Pages serves for free.

Dependencies: requests, beautifulsoup4  (html.parser, no lxml needed).
"""
import datetime as dt
import json
import os
import re
import sys
from xml.sax.saxutils import escape

import requests
from bs4 import BeautifulSoup

OUT_DIR = os.environ.get("OUT_DIR", "docs")
MAX_ITEMS = 30
TIMEOUT = 30
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

SITES = [
    {
        "key": "claude-blog",
        "name": "Claude Blog",
        "home": "https://claude.com/blog",
        "site": "https://claude.com",
        "out": "claude-blog.xml",
        "desc": "Unofficial feed of posts from the Claude blog (claude.com/blog).",
        "link_re": re.compile(
            r"^https://claude\.com/blog/(?!category/)[a-z0-9][a-z0-9-]+/?$", re.I
        ),
    },
    {
        "key": "anthropic-news",
        "name": "Anthropic Newsroom",
        "home": "https://www.anthropic.com/news",
        "site": "https://www.anthropic.com",
        "out": "anthropic-news.xml",
        "desc": "Unofficial feed of posts from the Anthropic newsroom (anthropic.com/news).",
        "link_re": re.compile(
            r"^https://www\.anthropic\.com/(news|research)/[a-z0-9][a-z0-9-]+/?$", re.I
        ),
    },
]

DATE_RE = re.compile(r"([A-Z][a-z]+ \d{1,2}, \d{4})")
NAV_NOISE = re.compile(
    r"^(read more|read the post|learn more|see more|view more|try claude|contact sales)$",
    re.I,
)
# Category labels that some cards prepend to the title text. Only stripped when
# the title also starts with a date, so clean heading titles are never touched.
CATEGORY_RE = re.compile(
    r"^(product announcements?|enterprise ai|claude code|societal impacts|"
    r"announcements?|product|policy|interpretability|research|company|"
    r"education|alignment|agents)\b[\s:\u2013-]*",
    re.I,
)


def now_utc():
    return dt.datetime.now(dt.timezone.utc)


def iso(d):
    return d.astimezone(dt.timezone.utc).isoformat()


def rfc822(d):
    return d.astimezone(dt.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")


def parse_human_date(text):
    """Pull a 'May 28, 2026' style date out of a blob of text, if present."""
    m = DATE_RE.search(text or "")
    if not m:
        return None
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return dt.datetime.strptime(m.group(1), fmt).replace(tzinfo=dt.timezone.utc)
        except ValueError:
            continue
    return None


def clean_title(text):
    """Normalise whitespace and undo the title-repeated-twice pattern that the
    card markup on both sites produces."""
    t = re.sub(r"\s+", " ", (text or "")).strip()
    n = len(t)
    if n and n % 2 == 0 and t[: n // 2].strip() == t[n // 2 :].strip():
        t = t[: n // 2].strip()
    return t


def strip_prefixes(title):
    """If a title literally starts with a date (the inline date+category+title
    card pattern), strip the leading date and a following category label."""
    t = (title or "").strip()
    m = DATE_RE.match(t)
    if not m:
        return t
    t = t[m.end() :].lstrip(" \u2013-:\u00a0")
    return CATEGORY_RE.sub("", t, count=1).strip()


def extract_title(a):
    """Prefer a heading inside the link/card; fall back to link text."""
    h = a.find(["h1", "h2", "h3", "h4", "h5", "h6"])
    if h and h.get_text(strip=True):
        return strip_prefixes(clean_title(h.get_text(" ", strip=True)))
    label = a.get("aria-label") or a.get_text(" ", strip=True)
    return strip_prefixes(clean_title(label))


def scrape(site, html_text=None):
    """Return {url: {'title':..., 'date': datetime|None}} for a site's index."""
    if html_text is None:
        r = requests.get(site["home"], headers={"User-Agent": UA}, timeout=TIMEOUT)
        r.raise_for_status()
        html_text = r.text
    soup = BeautifulSoup(html_text, "html.parser")
    found = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith("/"):
            href = site["site"] + href
        href = href.split("#")[0].split("?")[0]
        if not site["link_re"].match(href):
            continue
        url = href.rstrip("/")
        label = extract_title(a)
        if NAV_NOISE.match(label or ""):
            label = ""
        # Date: look in the link, then walk up a few parents (the card wrapper).
        date = parse_human_date(a.get_text(" ", strip=True))
        node = a
        for _ in range(3):
            if date:
                break
            node = node.parent
            if node is None:
                break
            date = parse_human_date(node.get_text(" ", strip=True))
        rec = found.get(url)
        if rec is None:
            found[url] = {"title": label, "date": date}
        else:
            if len(label) > len(rec["title"]):
                rec["title"] = label
            if rec["date"] is None and date is not None:
                rec["date"] = date
    return found


def load_state(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def build_feed(site, items):
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">',
        "<channel>",
        f"<title>{escape(site['name'])}</title>",
        f"<link>{escape(site['home'])}</link>",
        f"<description>{escape(site['desc'])}</description>",
        "<language>en-us</language>",
        f"<lastBuildDate>{rfc822(now_utc())}</lastBuildDate>",
        "<generator>github-actions-rss</generator>",
    ]
    for it in items:
        parts += [
            "<item>",
            f"<title>{escape(it['title'] or it['url'])}</title>",
            f"<link>{escape(it['url'])}</link>",
            f'<guid isPermaLink="true">{escape(it["url"])}</guid>',
            f"<pubDate>{rfc822(it['pub'])}</pubDate>",
            "</item>",
        ]
    parts += ["</channel>", "</rss>"]
    return "\n".join(parts)


def items_from_state(state_for_site):
    items = []
    for url, rec in state_for_site.items():
        pub_iso = rec.get("date") or rec.get("first_seen")
        try:
            pub = dt.datetime.fromisoformat(pub_iso)
        except (TypeError, ValueError):
            pub = now_utc()
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=dt.timezone.utc)
        items.append({"url": url, "title": rec.get("title"), "pub": pub})
    items.sort(key=lambda x: x["pub"], reverse=True)
    return items[:MAX_ITEMS]


def write_index(summary):
    rows = "\n".join(
        f'<li><a href="{site["out"]}">{escape(site["name"])}</a>'
        f'<span class="meta">{count} items &middot; '
        f'<a href="{escape(site["home"])}">source</a></span></li>'
        for site, count in summary
    )
    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Claude / Anthropic RSS feeds</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font: 16px/1.6 -apple-system, system-ui, sans-serif;
         max-width: 38rem; margin: 4rem auto; padding: 0 1.25rem; }}
  h1 {{ font-size: 1.4rem; margin-bottom: .25rem; }}
  p.sub {{ color: #8a8a8a; margin-top: 0; }}
  ul {{ list-style: none; padding: 0; }}
  li {{ display: flex; justify-content: space-between; align-items: baseline;
       gap: 1rem; padding: .9rem 0; border-bottom: 1px solid #8884; }}
  .meta {{ color: #8a8a8a; font-size: .8rem; white-space: nowrap; }}
  footer {{ margin-top: 2rem; color: #8a8a8a; font-size: .8rem; }}
</style></head>
<body>
<h1>Claude &amp; Anthropic feeds</h1>
<p class="sub">Unofficial RSS, rebuilt automatically from the public index pages. Paste a link into your reader.</p>
<ul>
{rows}
</ul>
<p class="sub">Updated {escape(rfc822(now_utc()))}.</p>
<footer>Generated by a scheduled GitHub Action. Not affiliated with Anthropic.</footer>
</body></html>
"""
    with open(os.path.join(OUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(doc)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    state_path = os.path.join(OUT_DIR, "state.json")
    state = load_state(state_path)
    summary = []
    ts = iso(now_utc())
    for site in SITES:
        st = state.setdefault(site["key"], {})
        new_count = 0
        try:
            found = scrape(site)
        except Exception as e:  # noqa: BLE001 - keep prior state on any failure
            print(f"[warn] {site['name']}: scrape failed: {e}", file=sys.stderr)
            found = {}
        for url, info in found.items():
            rec = st.get(url)
            if rec is None:
                st[url] = {
                    "title": info["title"],
                    "first_seen": ts,
                    "date": iso(info["date"]) if info["date"] else None,
                }
                new_count += 1
            else:
                if info["title"] and len(info["title"]) > len(rec.get("title", "")):
                    rec["title"] = info["title"]
                if not rec.get("date") and info["date"]:
                    rec["date"] = iso(info["date"])
        items = items_from_state(st)
        with open(os.path.join(OUT_DIR, site["out"]), "w", encoding="utf-8") as f:
            f.write(build_feed(site, items))
        summary.append((site, len(items)))
        print(f"[ok] {site['name']}: {len(items)} items in feed ({new_count} new)")
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    write_index(summary)


if __name__ == "__main__":
    main()
