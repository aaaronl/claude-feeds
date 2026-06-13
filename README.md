# Claude / Anthropic RSS feeds

Self-hosted, $0 RSS feeds for two sites that don't publish their own:

- **Claude Blog** — https://claude.com/blog
- **Anthropic Newsroom** — https://www.anthropic.com/news

A scheduled GitHub Action scrapes each index page, writes RSS 2.0 files into
`docs/`, and GitHub Pages serves them for free. No third-party service, no
subscription, no account beyond GitHub.

## How it works

`generate_feeds.py` matches posts by **URL pattern** (not by CSS classes, which
the sites can rename), and accumulates every post it has ever seen in
`docs/state.json`. Each feed is rebuilt from that state, so a single failed or
rate-limited scrape never empties an existing feed — it just adds nothing new
that run.

Output files (all in `docs/`):

| File | Purpose |
|------|---------|
| `claude-blog.xml` | RSS feed for the Claude blog |
| `anthropic-news.xml` | RSS feed for the Anthropic newsroom |
| `index.html` | A small landing page linking both feeds |
| `state.json` | Accumulated post history (don't edit by hand) |

## Setup (works entirely from the GitHub website, iPad included)

1. **Create a repo.** github.com → New repository → name it e.g. `claude-feeds`,
   make it **Public** (Pages is free for public repos), → Create.

2. **Add two files.** Use **Add file → Create new file** for each:
   - `generate_feeds.py` — paste the script.
   - `.github/workflows/build-feeds.yml` — typing that path in the filename box
     creates the folders automatically; paste the workflow.

3. **Run it once.** Repo → **Actions** tab → *Build RSS feeds* →
   **Run workflow**. After ~1 minute it commits a new `docs/` folder.

4. **Turn on Pages.** Repo → **Settings → Pages** → *Source:* **Deploy from a
   branch** → Branch: **main**, Folder: **/docs** → Save. Give it a minute.

5. **Subscribe.** Your URLs (replace `USER`/`REPO`):
   - `https://USER.github.io/REPO/claude-blog.xml`
   - `https://USER.github.io/REPO/anthropic-news.xml`
   - Landing page: `https://USER.github.io/REPO/`

   Paste a feed URL into NetNewsWire, Reeder, Inoreader, etc.

## Notes

- **Schedule:** every 6 hours (`cron: "0 */6 * * *"`). Change the cron line to
  adjust. GitHub may delay scheduled runs by a few minutes under load.
- **Dormancy:** GitHub auto-disables scheduled workflows after ~60 days with no
  repo activity. If feeds go stale, open Actions and hit *Run workflow* (or push
  any commit) to re-enable.
- **Run locally** instead of/in addition to CI:
  `pip install requests beautifulsoup4 && python generate_feeds.py`
  (writes to `docs/`; set `OUT_DIR=somewhere` to change that).
- **If a site changes layout** and a feed stops gaining new items, the URL
  patterns in `SITES` (top of `generate_feeds.py`) are the only thing likely to
  need a tweak. Existing items remain in the feed regardless.
- Unofficial; not affiliated with Anthropic.
