# AZA Content Intelligence Desk + AI Blog Writer

An end-to-end content intelligence and AI-powered blog generation system built for [AZA Fashions](https://www.azafashions.com), India's largest premium ethnic wear retailer.

**Two core products:**
1. **Research Dashboard** (`index.html`) — Real-time content intelligence from 36+ editorial sources and 67 Instagram accounts
2. **Blog Writer** (`writer.html`) — AI-powered blog generation with product image matching and WordPress publishing

Used daily by the AZA editorial and content teams.

---

## What It Does

### Part 1: Content Research Dashboard (index.html)

The content team needs to know: what are competitors publishing, what is the industry talking about, and what are readers searching for?

- **Websites Tab** — Tracks posts from 20 competitor brands, 15 industry publications, and AZA's own blogs. Each article is scored for fashion relevance, classified into AZA's six editorial categories, and given a suggested content angle via Claude AI.
- **Google Trends Tab** — Live trend charts for AZA's tracked keyword portfolio (India and US markets separately). Keywords pull from a managed Google Sheet; top keywords load immediately with Google Trends embed widgets.
- **Instagram Tab** — Latest posts from 67 tracked fashion media, bridal, runway, and commentary accounts. Captions and hashtags are extracted and fully searchable. One-click blog idea generation from any post.

### Part 2: AI Blog Writer (writer.html)

Turns a shortlisted content idea into a publish-ready blog post with product images in 90 seconds.

**Full Pipeline:**
1. **Brief Builder** — Analyzes source material, generates SEO-optimized brief (title, outline, keywords, flags)
2. **Blog Writer** — Writes full post in Samyukta Singhania's voice with streaming text preview
3. **Editorial Review** — Checks for brand violations, rates voice authenticity (1–10 score)
4. **Rewrite** — Fixes violations if needed (only runs if score < 6 or violations found)

**Product Image Matching** — Automatically matches blog sections to products from AZA's 1,804-product catalogue via OpenAI embeddings + cosine similarity. User approves/skips matches, images are uploaded to WordPress and inserted as figures.

**WordPress Publishing** — Creates post draft with:
- Matched product images as clickable figures with PDP links
- Featured image (first approved match, resized to 1200×800)
- Yoast SEO fields (title, meta description, keywords)
- Post slug and excerpt

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│ GitHub Actions (cron)                                   │
├─────────────────────────────────────────────────────────┤
│ fetch_feeds.py     → feed.json (articles, trends)       │
│ scrape_instagram.py → ig_posts.json (IG posts)         │
│ embed_products.py   → products_with_embeddings.json     │
└─────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────┐
│ Browser (GitHub Pages)                                  │
├─────────────────────────────────────────────────────────┤
│ index.html (Research Dashboard)                         │
│   → Claude AI (idea generation, brand checking)         │
│   ↓                                                     │
│ writer.html (Blog Writer Pipeline)                      │
│   → Claude AI (4-stage pipeline, prompt caching)        │
│   → OpenAI (product image embedding)                    │
│   → WordPress REST API (media upload, post creation)    │
└─────────────────────────────────────────────────────────┘
```

**No backend. No build step. No framework.** Entire frontend is client-side HTML + vanilla JS. All computation happens in Python at scrape time or in the browser at render time.

---

## Technical Stack

| Component | Technology |
|---|---|
| **Research Dashboard** | Vanilla JS, single-file HTML, GitHub Pages |
| **Blog Writer Pipeline** | Claude AI (Haiku + Sonnet), prompt caching |
| **Product Embeddings** | OpenAI text-embedding-3-small (1536-dim vectors) |
| **Image Matching** | Cosine similarity (pure JavaScript, no API) |
| **WordPress Integration** | REST API (media upload, post creation, Yoast SEO) |
| **Featured Image Sizing** | ImageKit URL transforms |
| **Feed Scraping** | Python 3, feedparser, BeautifulSoup, requests |
| **Instagram Scraping** | Playwright (async, headless Chromium) |
| **Scheduling** | GitHub Actions (cron) |
| **Deployment** | GitHub Pages (frontend) + GitHub Actions (backend) |

---

## How the Blog Writer Works

### Stage 1: Brief Builder (Claude Haiku, temp 0.3)

**Input:** Topic title + content angle + source material

**Output:** JSON brief with:
- SEO-optimized title and slug
- Meta description (140–165 characters)
- Content outline (3–8 sections)
- Key points and SEO keywords
- Factual flags for verification

**Example Output:**
```json
{
  "title": "Why Banarasi Silk Remains Timeless",
  "slug": "banarasi-silk-timeless",
  "meta_description": "Banarasi silk's heritage, craftsmanship, and why luxury fashion brands champion it.",
  "outline": [
    { "section": "Heritage & Craft", "notes": "500-year history of Banarasi weaving..." },
    { "section": "What Makes It Different", "notes": "Weight, zari work, silk quality..." },
    { "section": "How to Wear It Today", "notes": "Modern styling beyond traditional occasions..." }
  ],
  "seo_keywords": ["Banarasi silk saree", "Indian silk weaving", "luxury sarees"],
  "flags": ["Verify: Banarasi weaving is 500+ years old"]
}
```

### Stage 2: Blog Writer (Claude Sonnet, temp 0.8, streaming)

**Input:** Brief + brand guidelines + writing skill rules

**Output:** Full markdown blog post in Samyukta Singhania's voice

**Stream:** Text appears in real-time as it's generated

**Constraints:**
- No em-dashes (—) — use commas or periods instead
- No opening questions/statistics — start with a scene or opinion
- Long-form only: max 3 H2 subheadings, editorial style
- No call-to-action or "only time will tell" closing

**Example:** 800–1500 word post with specific details, personal opinions, and brand-aligned voice.

### Stage 3: Editorial Review (Claude Haiku, temp 0.2)

**Input:** Draft + brand context + brief

**Output:** Violation JSON with:
- Brand voice score (1–10, with calibration rules)
- Specific violations (banned words, rhythm, AI tells)
- SEO readiness checks (keyword placement, heading structure)
- Suggested title alternatives
- `needs_rewrite` flag

**Scoring:**
- 5 = competent but generic
- 6 = recognizably Samyukta's domain
- 7 = good — specific person with opinions
- 8+ = strong — distinctive voice, genuine POV

If score < 6 or violations found, auto-triggers Stage 4.

### Stage 4: Rewrite (Claude Sonnet, temp 0.5)

**Input:** Draft + violation report (only if `needs_rewrite: true`)

**Output:** Corrected markdown (fixes only violations, preserves voice)

**Non-Rewritable:** Doesn't run if Stage 3 score ≥ 6 and no violations.

---

## Product Image Matching

### Pre-Computation (embed_products.py)

One-time setup: Embeds all 1,804 products in AZA's catalogue.

```bash
python embed_products.py \
  --input product_info.csv \
  --output products_with_embeddings.json
```

**Output:** products_with_embeddings.json
```json
[
  {
    "pid": 123181,
    "title": "Ivory Pure Banarasi Silk Saree",
    "images": ["https://static3.azafashions.com/tr:w-450/...jpg"],
    "pdp_url": "https://www.samyuktasinghania.com/products/123181/123181",
    "description": "Pure mulberry silk with traditional zari work...",
    "keywords": ["saree", "banarasi", "silk", "wedding"],
    "embedding": [0.002, -0.051, 0.088, ...]  // 1536 dimensions
  },
  ...
]
```

**Cost:** ~$0.004 (one-time)

### Client-Side Matching (writer.html)

1. **Upload catalogue** — File picker loads products_with_embeddings.json (in-memory, never persisted)
2. **Generate blog** — Runs 4-stage pipeline
3. **Match sections** — For each blog section:
   - Embed section text via OpenAI (1536-dim vector)
   - Calculate cosine similarity against all 1,804 product embeddings
   - Return top 3 matches + scores
   - Flag if best match score < 0.35 (NO_MATCH_THRESHOLD)
4. **Approve/skip** — User manually reviews matches and approves images to include
5. **Publish** — Approved images uploaded to WordPress, inserted as figures

**Cost per blog:** ~$0.00004 (6 OpenAI calls, ~0.00001 per call)

### Featured Image Processing

- **Dimensions:** 1200×800px (configurable in settings)
- **Transform:** ImageKit URL rewrite — `tr:w-450` → `tr:w-1200,h-800,c-maintain_ratio`
- **Source:** First approved matched product image
- **Inserted:** As post featured image in WordPress

---

## WordPress Publishing Workflow

1. **Image Upload**
   - For each approved match: `uploadImageToWP(imageUrl, filename, altText)`
   - Stores media_id and media_url in match result

2. **HTML Assembly**
   - Parse blog sections (marked by `## H2` headings)
   - For each section with approved match: insert `<figure>` block
   - Figure includes: image, alt text, PDP link, clickable product title

3. **Post Creation**
   - POST to `/wp-json/wp/v2/posts` with:
     - `title` (from brief or selected alternative)
     - `content` (full HTML with figures)
     - `slug` (SEO-friendly, from brief)
     - `excerpt` (meta description, 140–165 chars)

4. **Featured Image**
   - Update post with `featured_media: media_id` (first approved match)

5. **Yoast SEO**
   - `_yoast_wpseo_title` — SEO title
   - `_yoast_wpseo_metadesc` — Meta description
   - `_yoast_wpseo_focuskw` — Primary keyword
   - `_yoast_wpseo_keywordsynonyms` — Secondary keywords (JSON)

**Non-Blocking Failures:** All steps except post creation can fail without blocking. Post still publishes if images don't upload or featured image fails.

---

## Prompt Caching

All Claude API calls use prompt caching to reduce costs and latency.

```javascript
callClaudeWithCaching({
  model: 'claude-haiku-4-5',
  temperature: 0.3,
  stageInstructions: `...`,
  userMessage: `...`
})
```

**Cached blocks:**
- BRAND_GUIDE (Samyukta Singhania's voice, values, brand pillars)
- WRITING_SKILL (grammar, style, banned words, structure rules)

**Cache behavior:**
- Stage 1 (Brief): cache write (~20KB prompt)
- Stages 2–4 (Draft, Review, Rewrite): cache reads
- Cache stats logged to browser console: `cache_creation_input_tokens`, `cache_read_input_tokens`

**Cost reduction:** ~26% per blog (standard Sonnet pricing), ~36% with introductory pricing (until Aug 31, 2026)

---

## Settings Panel

**Anthropic API Key**
- Used for all Claude calls (Brief → Draft → Review → Rewrite)
- Stored in `sessionStorage` (survives refresh, cleared on tab close)
- Never logged or sent anywhere except api.anthropic.com

**OpenAI API Key**
- Used for product image embedding (~$0.00004 per blog)
- Same sessionStorage handling as Anthropic key

**WordPress Credentials**
- Site URL: `https://www.samyuktasinghania.com/blog` (configurable)
- Username: Application username
- App Password: 24-character application password (not account password)
- Used for media upload, post creation, featured image, Yoast SEO

**Product Catalogue**
- File picker to upload `products_with_embeddings.json`
- Shows product count on load
- Stored in-memory only (never persisted or sent to API)

**Featured Image Dimensions**
- Width, height in pixels (default 1200×800)
- Used in `getFeaturedImageUrl()` for ImageKit transform

---

## Project Structure

```
blog_topics_new/
├── .github/workflows/
│   ├── fetch_feeds.yml      # Daily RSS + HTML feed aggregation
│   └── scrape_instagram.yml # 3x daily Instagram scraping
├── fetch_feeds.py            # Feed aggregator with HTML fallback
├── scrape_instagram.py       # Playwright Instagram scraper
├── embed_products.py         # Pre-computes product embeddings
├── index.html                # Research dashboard (GitHub Pages)
├── writer.html               # Blog writer pipeline (GitHub Pages)
├── brand_guide.md            # Samyukta Singhania brand voice
├── writing_skill.md          # Grammar, style, brand rules
├── feed.json                 # Generated: articles, trends, keywords
├── ig_posts.json             # Generated: Instagram posts
├── products_with_embeddings.json  # Generated: 1,804 products
├── CLAUDE.md                 # AI-generation instructions
├── IMAGE_REQUIREMENTS.md     # Product image matching spec
├── REQUIREMENTS.md           # WordPress publishing spec
└── README.md                 # This file
```

---

## Setup

### Prerequisites

- GitHub account (for Actions + Pages)
- Google AI API key (for research dashboard idea generation) — [Get key](https://aistudio.google.com/app/apikey)
- Anthropic API key (for blog writer) — [Get key](https://console.anthropic.com)
- OpenAI API key (for product embeddings) — [Get key](https://platform.openai.com/api-keys)
- WordPress site with REST API enabled (for blog publishing) — www.samyuktasinghania.com/blog or your site
- WordPress application password (not account password) — [Generate](https://wordpress.com/support/application-passwords/)
- Instagram cookies exported from [Cookie-Editor](https://chrome.google.com/webstore/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm) for Instagram scraping

### 1. Clone the Repository

```bash
git clone https://github.com/prashantapurkayastha/blog_topics_new.git
cd blog_topics_new
```

### 2. Configure GitHub Actions Secrets

Go to **Settings → Secrets and variables → Actions** and add:

| Secret | Value | Purpose |
|---|---|---|
| `INSTAGRAM_COOKIES` | JSON cookie array | Instagram scraping |

### 3. Configure Keyword Google Sheet

Create a published Google Sheet with two tabs (Keywords_IN, Keywords_US), each with columns: `Keyword`, `Keyword Type`, `Category`, `Search Volume`, `Active`.

Publish each tab as CSV and update URLs in `fetch_feeds.py`.

### 4. Enable GitHub Pages

Go to **Settings → Pages → Source** and select `main` branch, root directory.

### 5. Pre-Compute Product Embeddings (One-Time)

```bash
export OPENAI_API_KEY="sk-..."
python embed_products.py \
  --input product_info.csv \
  --output products_with_embeddings.json
```

Commit `products_with_embeddings.json` to repo.

### 6. Run Workflows

Go to **Actions** and run both workflows manually once. After that, they run on schedule:
- `fetch_feeds.yml` — daily at 9 AM IST
- `scrape_instagram.yml` — 3x daily (9 AM, 1 PM, 5 PM IST)

### 7. Open the Dashboard

- **Research Dashboard:** `https://{your-github-username}.github.io/blog_topics_new/`
- **Blog Writer:** Open dashboard, click "Write Blog" on any article or Instagram post

To use the blog writer, paste your API keys when prompted:
1. **Anthropic key** (for blog generation pipeline)
2. **OpenAI key** (for product image embedding)
3. **WordPress credentials** (for publishing)

---

## Tracked Sources

### Competitor Brands (20+)
Kalki Fashion, Pernia's Pop-Up Shop, Utsav Fashion, FabIndia, House of Indya, Manyavar, BIBA, Anita Dongre, Sabyasachi, Torani, Lashkaraa, Libas, MissMalini Style, South India Fashion, Saree.com, Koskii, Panash India, Indian Cloth Store, and others.

### Industry Publications (15+)
Vogue India, Vogue US, Elle India, Grazia India, Harper's Bazaar, Business of Fashion, Who What Wear, Fashionista, India Today Fashion, Tag-Walk, Lyst, The Blonde Salad, The Sartorialist, FashionBeans, Fashion Gone Rogue.

### Instagram Accounts (67+)
Fashion media (Vogue India, BOF, WWD, Elle India, GQ India, Bazaar India), runway coverage (Vogue Runway, Archived Runway, L'Officiel), bridal content (Brides Today, Wedding Vows, Wedding Affair), commentary (Diet Prada, DietsAbya, Check the Tag, Fashion Law Journal), and style accounts.

---

## Cost Summary

| Item | Frequency | Cost |
|---|---|---|
| **embed_products.py** — 1,804 products | Once | ~$0.004 |
| **Brief Builder** (Haiku, cache write) | Per blog | ~$0.019 |
| **Draft Writer** (Sonnet, cache read, streaming) | Per blog | ~$0.026 |
| **Editorial Review** (Haiku, cache read) | Per blog | ~$0.009 |
| **Rewrite Agent** (Sonnet, cache read, if needed) | Per blog | ~$0.030 |
| **Product embedding** (OpenAI, 6 sections) | Per blog | ~$0.00004 |
| **WordPress media upload** | Per image | Free |
| **Total per blog** (all stages, with caching) | | **~$0.068** |
| **With intro pricing** (until Aug 31, 2026) | | **~$0.050** |

**Volume projections:**
- 10 blogs/month: ~$0.68 (or ~$0.50 with intro pricing)
- 30 blogs/month: ~$2.05 (or ~$1.50 with intro pricing)

---

## Key Implementation Details

### Why Prompt Caching?

BRAND_GUIDE and WRITING_SKILL are ~20KB of context used across all 4 stages. Caching them means:
- Stage 1: writes to cache once
- Stages 2–4: read from cache (5 free read-back requests, ~10% token savings each)
- Net: 26% cost reduction per blog

### Why Dual Scraping (RSS + HTML)?

Many fashion brands publish blogs on Shopify (clean Atom feeds) or custom CMS (broken or no feeds). HTML scraping as fallback ensures coverage regardless of brand's engineering setup.

### Why Product Embeddings Pre-Computed?

Computing embeddings at publish time (per-blog) costs ~$0.001 per section × 6 sections = $0.006/blog. Pre-computing once costs ~$0.004 total, then every blog pays only for matching (free cosine similarity in JS).

### Why WordPress REST API?

Direct API calls avoid: WordPress admin page slowness, user login friction, iframe sandbox issues. REST API with application passwords is fast and secure.

### Why No Backend?

Infrastructure cost, deployment friction, and operational complexity add up. For an internal tool used by a content team, client-side simplicity wins. All computation happens in Python (scraping, embeddings) or browser (pipeline, matching).

---

## Known Limitations

**Feed scraper fragility:**
- RSS feeds can disappear or break (brand redesigns)
- HTML scraping depends on CSS selectors (can break on site redesign)
- Workaround: monitor workflow failures, add/remove sources

**Instagram cookie expiry:**
- Instagram session cookies expire every few weeks
- When expired, scraper exits cleanly and preserves last good data
- Workaround: update GitHub secret when scraper fails

**Featured image dimensions fixed:**
- WordPress doesn't resample images to exact dimensions
- Featured image still displays correct aspect ratio
- Workaround: manually crop in WordPress Media Library if needed

**No draft auto-save:**
- If browser closes during pipeline run, work is lost
- Workaround: pipeline is fast (~90 sec), run in dedicated browser tab

**Product catalogue size:**
- Matching against 1,804 products takes ~6 OpenAI calls (one per section)
- Cost is still negligible (~$0.00004), but could be optimized with vector DB cache

---

## Support & Contribution

For bugs, feature requests, or questions:
1. Check existing GitHub issues
2. Open a new issue with:
   - What you were trying to do
   - What happened
   - What you expected
   - Relevant logs/screenshots

For contributions, please maintain:
- No new dependencies (keep it vanilla JS)
- Backward compatibility with existing feeds/posts
- Clear commit messages

---

## License

Created for AZA Fashions. Internal use only.

---

**Last updated:** July 14, 2026 | **Status:** All 23 build steps complete, production-ready
