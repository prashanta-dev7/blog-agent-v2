# AZA Content Intelligence Desk

A real-time content research dashboard built for [AZA Fashions](https://www.azafashions.com), one of India's largest premium ethnic wear retailers. The system monitors 36 editorial sources, 67 Instagram accounts, and a live keyword portfolio across IN/US markets — and turns that signal into actionable blog ideas using Gemini AI.

Used daily by the AZA content team.

---

## What It Does

The content team at a fashion brand needs to know three things before writing a blog post: what are competitors publishing, what is the industry talking about, and what are readers actually searching for. Answering all three previously meant opening 20+ browser tabs and manually stitching together a picture. This dashboard automates the entire intelligence layer.

**Websites tab** — Tracks posts from AZA's own blogs, 20 direct competitor brands (Kalki, Manyavar, BIBA, Sabyasachi, Anita Dongre, and others), and 15 industry publications (Vogue India/US, Harper's Bazaar, Business of Fashion). Each article is scored for fashion relevance, classified into one of six editorial categories, and given a suggested AZA-specific content angle. One click generates three ready-to-brief blog post ideas via Gemini.

**Google Trends tab** — Shows live trend charts for AZA's entire tracked keyword portfolio (IN and US markets separately). Keywords and search volumes are pulled live from a managed Google Sheet — the editorial team can update the keyword list without touching code. The top keywords auto-load with Google Trends embed widgets; everything else loads on demand to keep the page fast.

**Instagram tab** — Shows the latest posts from 67 tracked accounts across fashion media, bridal content, runway coverage, and commentary accounts (Diet Prada, DietsAbya, Vogue Runway, BOF, WWD, and others). Captions, image alt text, and hashtags are extracted and searchable. The same Gemini "Generate Blog Ideas" button works here too, with a prompt tuned for Instagram signals.

---

## Architecture

```
GitHub Actions (cron)
├── fetch_feeds.py     → feed.json        (articles, trends, keyword charts)
└── scrape_instagram.py → ig_posts.json  (IG posts with captions + hashtags)

GitHub Pages (index.html)
└── fetches both JSONs at runtime, renders everything client-side
```

No backend. No build step. No framework. The entire frontend is a single HTML file with vanilla JS. All computation happens either in Python at scrape time or in the browser at render time.

This architecture was a deliberate choice: zero infrastructure to maintain, instant deployment via GitHub Pages, and the data artifacts (`feed.json`, `ig_posts.json`) are version-controlled alongside the code.

---

## Technical Stack

| Layer | Technology |
|---|---|
| Scraping | Python 3, `feedparser`, `BeautifulSoup`, `requests` |
| Instagram | Playwright (async, Chromium, headless) |
| Scheduling | GitHub Actions (cron) |
| AI | Gemini 2.5 Flash via `generativelanguage.googleapis.com` |
| Frontend | Vanilla JS, single-file HTML, GitHub Pages |
| Keyword data | Google Sheets (published CSV, live pull at scrape time) |
| Trend charts | Google Trends Embed API |

---

## How the Feed Scraper Works

`fetch_feeds.py` (v5.2) runs two fetch strategies per source and merges the results.

**Primary: RSS/Atom feed parsing.** Every source has one or more feed URLs. The script fetches and parses them with `feedparser`, applies a 60-day recency filter, extracts published dates across multiple date field formats (`published`, `updated`, `created`), and builds a normalised article object.

**Fallback: HTML scraping.** When feeds are absent or partial, the script fetches the source's listing page(s) and runs a CSS selector cascade (`article a`, `h1 a`, `h2 a`, `.post a`, `.card a`, and others) to extract article links. Each candidate URL is validated against a `looks_like_post_url()` function that checks for known bad path patterns (`/products/`, `/collections/`, `/cart`, `/wp-content/`, image extensions) and requires the URL to contain blog-like path segments or a date pattern (`/2024/05/`).

**Content classification** happens at scrape time, not render time:

- `score_fashion()` — counts keyword matches across 44 fashion terms (saree, lehenga, couture, banarasi, kanjeevaram, etc.)
- `detect_category()` — maps each article to one of six AZA editorial categories (Bridal & Wedding, Celebrity Style, Designer Spotlight, Art & Craft, Trend Alert, Occasion Dressing) by scoring keyword overlap
- `suggest_angle()` — generates a draft content angle using title keyword patterns (e.g. a title containing "spotted" or "airport" gets "Get the Look: How to Style This Celebrity Trend the AZA Way")

**Live keyword loading** pulls two Google Sheets tabs (India and US keyword portfolios) as CSVs at runtime. The loader detects the header row dynamically — it scans for a row containing both `keyword` and `active` columns, making it resilient to teams adding rows above the header. Active keywords are sorted by search volume, and the top 50 from each market go into `feed.json`.

**Output:** A single `feed.json` with up to 800 deduplicated articles (sorted by tier, then date), up to 20 Google Trends RSS signals, and the keyword portfolio with pre-computed Trends URLs.

---

## How the Instagram Scraper Works

`scrape_instagram.py` uses Playwright in headless Chromium mode, authenticated via real browser cookies injected from a GitHub Actions secret.

**Cookie handling:** The scraper reads `INSTAGRAM_COOKIES` from the environment — a JSON array exported from the Cookie-Editor Chrome extension. On startup it validates the JSON, normalises `sameSite` values to what Playwright accepts, and checks for a valid `sessionid` cookie. If it's missing, the script exits with code 1 rather than running 45 minutes into a login wall.

**Concurrency:** Three browsers run in parallel (`asyncio.Semaphore(3)`). Instagram flags higher parallelism. Each account gets a hard timeout of 180 seconds via `asyncio.wait_for()` so a stuck account can't hang the workflow.

**Per-account flow:**
1. Navigate to `instagram.com/{handle}/`
2. Check for login redirect (URL or page title contains "login")
3. Extract post links using a selector cascade with `/p/` URL pattern matching
4. For each post: navigate to the post page, expand truncated captions, extract caption text (targeting `span[class*="x193iq5w"]` with noise filtering), image alt text (from Instagram's generated alt on media elements), post date from `time[datetime]`, and hashtags via regex

**Quality gate:** If fewer than 50 posts are harvested across all accounts, the script exits with code 2 and *does not overwrite* the existing `ig_posts.json`. This matters: on days when Instagram blocks the scraper wholesale (expired cookies, IP rate limiting), the dashboard still shows the previous successful run's data rather than going blank. The content team never sees an empty Instagram tab from a failed scrape.

---

## Content Intelligence Features

### Three-Tier Source Model

| Tier | Sources | Purpose |
|---|---|---|
| `owned` | AZA Blog, AZA Magazine | Track own publishing cadence |
| `competitor` | 20 Indian fashion brands | Spot gaps and opportunities |
| `industry` | 15 global/Indian publications | Catch macro trend signals |

Competitor articles are visually flagged in the dashboard and ranked above industry content in the default sort.

### Six AZA Editorial Categories

The classifier maps every article and IG post to one of:

- **Bridal & Wedding** — lehenga, trousseau, shaadi, mehendi
- **Celebrity Style** — bollywood, airport looks, red carpet
- **Designer Spotlight** — collection launches, couture, collaborations
- **Art & Craft** — handloom, embroidery, artisan heritage, block print
- **Trend Alert** — seasonal forecasts, style guides, edits
- **Occasion Dressing** — Diwali, Navratri, Eid, reception dressing

### Gemini Blog Idea Generation

Each article and Instagram post card has a **Generate Blog Ideas** button that calls Gemini 2.5 Flash with a context-specific prompt:

- For articles: title + AZA content angle + editorial category → 3 blog ideas with headlines and one-line briefs
- For Instagram posts: handle + caption + image alt text + hashtags → 3 blog ideas referencing the specific IG signal

The API key is entered by the user in the dashboard header (a password field) and held in `window._oaiKey`. It never touches a server. `thinkingBudget: 0` keeps latency low for this use case.

### Keyword Trend Charts

The Google Trends tab renders live embed widgets for the full keyword portfolio. Top 10 keywords per market auto-load with staggered timing (400ms between each) to avoid rate limiting the embed API. All other keywords load on click. A "Load more" button paginates at 20 cards to keep initial render fast.

---

## Engineering Notes

**Why dual fetch (RSS + HTML)?** Several fashion brands publish blogs on Shopify, which generates clean Atom feeds. Others use custom CMS setups with broken or absent feeds. HTML scraping as a fallback means source coverage doesn't depend on whether a brand's engineering team set up RSS correctly.

**Why validate URLs so aggressively?** HTML scraping from listing pages picks up navigation links, product links, and category pages alongside actual posts. The `looks_like_post_url()` function runs a blocklist check (product/collection/cart paths, image extensions, known non-post patterns) and a passlist check (blog path segments, year/month date patterns) before an article is included. Without this, the dataset fills up with `/collections/bridal-lehenga` URLs.

**Why commit the JSON artifacts to the repo?** This was a deliberate trade-off. A CDN or object storage bucket would be cleaner at scale, but for an internal tool running on GitHub Actions, keeping `feed.json` and `ig_posts.json` in the repo means the dashboard works immediately on any branch, with zero additional infrastructure, and the data history is version-controlled for free.

**Why not use a framework for the frontend?** The dashboard has no build step and no `node_modules`. Deployment is a git push. The HTML file opens directly from disk for testing. For a tool used internally by a content team — not a public product — the operational simplicity of a single file outweighs anything a framework would add.

**Why Gemini 2.5 Flash with `thinkingBudget: 0`?** The Generate Blog Ideas feature is used on-demand during a content team's research session. Latency matters more than depth. Flash with thinking disabled returns in under two seconds and the output quality is sufficient for idea generation (not final copy).

---

## Setup

### 1. Fork the Repository

```bash
git clone https://github.com/prashantapurkayastha/blog_topics.git
cd blog_topics
```

### 2. Configure GitHub Secrets

Go to **Settings → Secrets and variables → Actions** and add:

| Secret | Value |
|---|---|
| `INSTAGRAM_COOKIES` | JSON cookie array exported from [Cookie-Editor](https://chrome.google.com/webstore/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm) while logged into Instagram |

To export cookies: install Cookie-Editor → log into instagram.com in Chrome → open the extension → Export (JSON format) → copy the output.

### 3. Configure the Keyword Google Sheet

The script expects a published Google Sheet with two tabs:

- **Keywords_IN** — columns: `Keyword`, `Keyword Type`, `Category`, `Search Volume`, `Active` (TRUE/FALSE)
- **Keywords_US** — same structure

Publish each tab as CSV (**File → Share → Publish to web → CSV**) and update the `SHEET_KEYWORDS_IN` and `SHEET_KEYWORDS_US` URLs in `fetch_feeds.py`.

### 4. Enable GitHub Pages

Go to **Settings → Pages → Source** and select `main` branch, root directory.

### 5. Run the Workflow

Go to **Actions** and run the feed refresh workflow manually once. After that, it runs on the configured cron schedule.

### 6. Open the Dashboard

Navigate to `https://{your-username}.github.io/blog_topics/`

To use Gemini blog idea generation, get a [Google AI Studio API key](https://aistudio.google.com/app/apikey) and paste it into the key field in the dashboard header.

---

## Project Structure

```
blog_topics/
├── .github/
│   └── workflows/         # GitHub Actions workflow files
├── fetch_feeds.py          # RSS + HTML feed aggregator (v5.2)
├── scrape_instagram.py     # Playwright Instagram scraper
├── index.html              # Single-file dashboard (GitHub Pages)
├── feed.json               # Generated: website articles, trends, keywords
└── ig_posts.json           # Generated: Instagram posts with captions
```

---

## Tracked Sources

### Competitor Brands (20)
Kalki Fashion, Pernia's Pop-Up Shop, Utsav Fashion, FabIndia, House of Indya, Manyavar, BIBA, Anita Dongre, Sabyasachi, Torani, Lashkaraa, Libas, MissMalini Style, South India Fashion, Saree.com, Koskii, Panash India, Indian Cloth Store, and others.

### Industry Publications (15)
Vogue India, Vogue US, Elle India, Grazia India, Harper's Bazaar, Business of Fashion, Who What Wear, Fashionista, India Today Fashion, Tag-Walk, Lyst, The Blonde Salad, The Sartorialist, FashionBeans, Fashion Gone Rogue.

### Instagram Accounts (67)
Fashion media (Vogue India, BOF, WWD, Elle India, GQ India, Bazaar India), runway coverage (Vogue Runway, Archived Runway, L'Officiel), bridal content (Brides Today, Wedding Vows, Wedding Affair), commentary (Diet Prada, DietsAbya, Check the Tag, Fashion Law Journal), style accounts, and sustainability/culture accounts.

---

## Known Limitations

**Instagram cookie expiry.** Instagram session cookies expire periodically — roughly every few weeks. When this happens, the scraper exits cleanly with code 2 and preserves the last good dataset, but the Instagram tab stops refreshing until the secret is updated. A workflow failure notification via email or Slack would close this gap.

**Instagram selector fragility.** Caption extraction targets `span[class*="x193iq5w"]`, an obfuscated class Instagram ships with its frontend. These classes change when Instagram deploys a new build. The scraper has fallback logic, but caption extraction may degrade silently after an Instagram frontend update.

**`feed.json` growth.** Committing the data artifact to the repo means the repo grows with every workflow run. At current article counts (~800 per run), this is negligible, but worth migrating to a CDN or R2 bucket if the data volume grows significantly.

**No historical data.** Each run overwrites the previous `feed.json`. There's no trend-over-time view of which competitors posted more or less. Adding a timestamped archive would enable that analysis.
