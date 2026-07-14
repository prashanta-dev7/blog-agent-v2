# IMAGE_REQUIREMENTS.md — Product Image Matching & WordPress Publishing
## Feature: Auto-match PID images to blog sections + full WordPress publish

---

## Context

Read CLAUDE.md and REQUIREMENTS.md first. This file specifies:
1. Product image matching and insertion into blog sections
2. Featured image handling with resizing via ImageKit
3. Full Yoast SEO meta fields on WordPress publish
4. Prompt caching implementation across the pipeline
5. One-time product embedding pre-computation script

---

## Architecture Overview

```
ONE-TIME OFFLINE STEP (run once when catalogue changes):
  product_info.csv (1,806 products)
    → set OPENAI_API_KEY in terminal
    → python embed_products.py
    → products_with_embeddings.json

AT BLOG GENERATION TIME (client-side):
  Each blog section text
    → OpenAI embeddings API (text-embedding-3-small) → section embedding
    → cosine similarity vs all PID embeddings (pure JS, free)
    → top PID match per section
    → image URL transformed via ImageKit for correct dimensions
    → upload to WordPress media library
    → insert <figure> with PDP link into section HTML
    → set featured image (first matched PID, resized)
    → publish post with full Yoast SEO fields
```

**OpenAI is used twice:**
1. Once offline via embed_products.py — ~$0.002 total for 1,806 PIDs
2. Once per blog at generation time — ~6 calls, ~$0.00004 total per blog

**Claude handles all writing. OpenAI handles all embeddings.**

---

## Part 1 — Source Data Format

### product_info.csv (the actual file, 1,806 rows)

4 columns:
- `productID` — numeric PID (e.g. 123181)
- `productTitle` — product name (e.g. "Ivory Pure Banarasi Silk Saree")
- `image_urls` — comma-separated AZA CDN URLs with ImageKit `tr:w-450` transform
- `neuralens_processed_data` — nested JSON array with all product attributes

**Important:** Standard CSV parsers (pandas, csv module) fail on this file
because `neuralens_processed_data` contains commas inside nested JSON.
The script below reads it line-by-line and parses the JSON manually.

### neuralens_processed_data structure

Each product has a JSON array with one `global` entry containing:
- `description` — single sentence product description
- `keywords` — semantic tags (e.g. "banarasi saree", "Heritage Revival")
- `attributes` — list of attribute objects, each with `display_name` and `value`

Key attributes extracted from `attributes`:
- `Occasions` / `Occasion` — e.g. ["Wedding", "Festive"]
- `Style Genre` — e.g. ["Indian"]
- `Components` — e.g. ["Saree", "Blouse"]
- `Noteworthy Feature` — e.g. ["Intricate resham woven detail"]
- `Fabric` — e.g. ["Silk"]
- `Color` — e.g. ["Off White"]
- `Pattern` — e.g. ["Solid"]
- `Type of Work` — e.g. ["Embroidery"]
- `Short Description` — concise product summary
- `Pattern Style` — e.g. ["Banarasi"]
- `Embellishment Style` — e.g. ["Resham Embroidery"]
- `Border Style` — e.g. ["Zari Border"]
- `Neckline Style`, `Sleeve Style`, `Fit` — garment specifics

### PDP URL construction

Use PID twice — redirects to correct PDP automatically:
```
https://www.samyuktasinghania.com/products/{pid}/{pid}
```

### Image URL format

Raw from CSV:
```
https://static3.azafashions.com/tr:w-450/uploads/product_gallery/xxx.jpg
```

For featured image (swap ImageKit transform):
```
https://static3.azafashions.com/tr:w-1200,h-800,c-maintain_ratio/uploads/product_gallery/xxx.jpg
```

---

## Part 2 — Pre-Computation Script (embed_products.py)

### How to provide the OpenAI API key

Set as environment variable in terminal before running.
Never written to any file, never committed to the repo.

**Mac / Linux:**
```bash
export OPENAI_API_KEY="sk-..."
python embed_products.py
```

**Windows (Command Prompt):**
```cmd
set OPENAI_API_KEY=sk-...
python embed_products.py
```

**Windows (PowerShell):**
```powershell
$env:OPENAI_API_KEY = "sk-..."
python embed_products.py
```

Re-run only when the product catalogue changes.

### Script

```python
# embed_products.py
# Reads product_info.csv, extracts attributes from neuralens_processed_data,
# generates OpenAI embeddings, saves products_with_embeddings.json
#
# Usage:
#   export OPENAI_API_KEY="sk-..."
#   python embed_products.py
#
# Input:  product_info.csv  (1,806 products)
# Output: products_with_embeddings.json
# Cost:   ~$0.002 total for 1,806 PIDs

import json
import os
import re
import argparse
from openai import OpenAI

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

SKIP_ATTRIBUTES = {
    'Component Count', 'Gender', 'Image Type', 'No of Component',
    'Size Details', 'Fit', 'Visible Items not included',
    'Care Instruction', 'Disclaimer', 'Component Attributes'
}

def parse_csv_line(line):
    """
    Parse one CSV line from product_info.csv.
    Cannot use standard CSV parser — neuralens_processed_data contains
    commas inside nested JSON which breaks standard parsers.

    Format: productID,productTitle,"image_urls","neuralens_json"
    """
    line = line.strip()
    if not line:
        return None

    # Extract productID (everything before first comma)
    first_comma = line.index(',')
    pid = line[:first_comma].strip()

    rest = line[first_comma + 1:]

    # Extract productTitle (may or may not be quoted)
    if rest.startswith('"'):
        title_end = rest.index('",', 1)
        title = rest[1:title_end]
        rest = rest[title_end + 2:]
    else:
        title_end = rest.index(',')
        title = rest[:title_end]
        rest = rest[title_end + 1:]

    # Extract image_urls (quoted, comma-separated URLs inside quotes)
    if rest.startswith('"'):
        # Find the closing quote before the JSON blob
        # JSON starts with ,"[{ so find that pattern
        json_marker = rest.find('","[{')
        if json_marker == -1:
            json_marker = rest.find(',"[{')
            image_str = rest[1:json_marker]
            json_raw = rest[json_marker + 2:]
        else:
            image_str = rest[1:json_marker]
            json_raw = rest[json_marker + 2:]
    else:
        comma_pos = rest.index(',"[{')
        image_str = rest[:comma_pos]
        json_raw = rest[comma_pos + 1:]

    # Clean image URLs
    images = [u.strip().strip('"') for u in image_str.split(',') if 'azafashions' in u]

    # Clean JSON — strip surrounding quotes and trailing chars
    json_raw = json_raw.strip()
    if json_raw.startswith('"'):
        json_raw = json_raw[1:]
    if json_raw.endswith('"'):
        json_raw = json_raw[:-1]

    return pid, title, images, json_raw


def extract_attributes(neuralens_raw):
    """Parse neuralens JSON and extract display-worthy attributes."""
    try:
        data = json.loads(neuralens_raw)
        global_entry = next(
            (d for d in data if d.get('key') == 'global'),
            data[0] if data else {}
        )

        result = {
            'description': global_entry.get('description', ''),
            'keywords':    global_entry.get('keywords', []),
            'attributes':  {}
        }

        for attr in global_entry.get('attributes', []):
            display_name = attr.get('display_name') or attr.get('key', '')
            if display_name in SKIP_ATTRIBUTES:
                continue
            val = attr.get('value', [])
            if not val:
                continue
            if isinstance(val, list):
                val = [str(v) for v in val if v and str(v).strip()]
            if val:
                result['attributes'][display_name] = val

        return result

    except Exception as e:
        return {'description': '', 'keywords': [], 'attributes': {}, 'error': str(e)}


def build_embedding_text(pid, title, attrs):
    """
    Build rich embedding string from all available product attributes.
    This is what gets embedded — the richer it is, the better the matching.
    """
    parts = [title]

    desc = attrs.get('description', '')
    if desc:
        parts.append(desc)

    # Add each attribute as "Key: value1, value2"
    priority_keys = [
        'Short Description', 'Occasions', 'Occasion', 'Style Genre',
        'Components', 'Noteworthy Feature', 'Fabric', 'Color', 'Pattern',
        'Type of Work', 'Pattern Style', 'Embellishment Style', 'Border Style',
        'Neckline Style', 'Sleeve Style'
    ]

    # Priority attributes first
    attrs_dict = attrs.get('attributes', {})
    for key in priority_keys:
        if key in attrs_dict:
            val = attrs_dict[key]
            parts.append(f"{key}: {', '.join(val)}")

    # Remaining attributes
    for key, val in attrs_dict.items():
        if key not in priority_keys:
            parts.append(f"{key}: {', '.join(val)}")

    # Keywords last (semantic enrichment)
    keywords = attrs.get('keywords', [])
    if keywords:
        parts.append(f"Keywords: {', '.join(keywords[:12])}")

    return '. '.join(p for p in parts if p.strip())


def embed_batch(texts):
    """Call OpenAI embeddings API for a batch of texts."""
    resp = client.embeddings.create(
        model='text-embedding-3-small',
        input=texts
    )
    return [r.embedding for r in resp.data]


def run(input_path, output_path):
    print(f"Reading {input_path}...")

    products = []
    errors   = []

    with open(input_path, 'r', encoding='utf-8', errors='replace') as f:
        lines = f.readlines()

    # Skip header
    for i, line in enumerate(lines[1:], start=2):
        try:
            parsed = parse_csv_line(line)
            if not parsed:
                continue
            pid, title, images, json_raw = parsed
            attrs = extract_attributes(json_raw)

            if 'error' in attrs:
                errors.append(f"Line {i} PID {pid}: {attrs['error']}")
                continue

            embedding_text = build_embedding_text(pid, title, attrs)

            products.append({
                'pid':            pid,
                'title':          title,
                'images':         images,
                'description':    attrs['description'],
                'keywords':       attrs['keywords'],
                'attributes':     attrs['attributes'],
                'pdp_url':        f'https://www.samyuktasinghania.com/products/{pid}/{pid}',
                'embedding_text': embedding_text,
                'embedding':      None   # filled below
            })

        except Exception as e:
            errors.append(f"Line {i}: {e}")

    print(f"Parsed {len(products)} products ({len(errors)} errors)")
    if errors[:5]:
        print("First errors:", errors[:5])

    # Generate embeddings in batches of 100
    print(f"\nGenerating embeddings...")
    texts      = [p['embedding_text'] for p in products]
    BATCH_SIZE = 100
    all_embeddings = []

    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i:i + BATCH_SIZE]
        embs  = embed_batch(batch)
        all_embeddings.extend(embs)
        print(f"  {min(i + BATCH_SIZE, len(texts))}/{len(products)} done")

    for p, emb in zip(products, all_embeddings):
        p['embedding'] = emb

    with open(output_path, 'w') as f:
        json.dump(products, f)

    total_tokens = sum(len(t.split()) for t in texts)
    cost = (total_tokens / 1_000_000) * 0.02
    print(f"\nDone. Saved {len(products)} products to {output_path}")
    print(f"Estimated cost: ~${cost:.4f}")
    print(f"File size: ~{len(json.dumps(products)) // 1024 // 1024}MB")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input',  default='product_info.csv')
    parser.add_argument('--output', default='products_with_embeddings.json')
    args = parser.parse_args()
    run(args.input, args.output)
```

### Expected output structure (products_with_embeddings.json)

```json
[{
  "pid":         "123181",
  "title":       "Ivory Pure Banarasi Silk Saree",
  "images":      ["https://static3.azafashions.com/tr:w-450/uploads/...jpg"],
  "description": "Ivory Pure Banarasi silk saree featuring intricate resham woven detail",
  "keywords":    ["banarasi saree", "silk saree", "ivory saree", "Heritage Revival"],
  "attributes": {
    "Occasions":           ["Wedding", "Festive"],
    "Style Genre":         ["Indian"],
    "Components":          ["Saree"],
    "Noteworthy Feature":  ["Intricate resham woven detail", "Elegant border design"],
    "Fabric":              ["Silk"],
    "Color":               ["Off White"],
    "Pattern Style":       ["Banarasi"],
    "Embellishment Style": ["Resham Embroidery"],
    "Border Style":        ["Zari Border"]
  },
  "pdp_url":        "https://www.samyuktasinghania.com/products/123181/123181",
  "embedding_text": "Ivory Pure Banarasi Silk Saree. Ivory Pure Banarasi silk saree...",
  "embedding":      [0.023, -0.045, 0.112, ...]
}]
```

---

## Part 3 — Client-Side Matching (writer.html)

### Load catalogue via file picker

```javascript
let productCatalogue = null;

document.getElementById('catalogue-upload').addEventListener('change', async (e) => {
  const text = await e.target.files[0].text();
  productCatalogue = JSON.parse(text);
  document.getElementById('catalogue-status').textContent =
    `${productCatalogue.length} products loaded ✓`;
  console.log(`Catalogue loaded: ${productCatalogue.length} products`);
});
```

### Embed a blog section (OpenAI API)

```javascript
const embedText = async (text) => {
  const r = await fetch('https://api.openai.com/v1/embeddings', {
    method: 'POST',
    headers: {
      'Content-Type':  'application/json',
      'Authorization': `Bearer ${sessionStorage.getItem('OPENAI_API_KEY')}`
    },
    body: JSON.stringify({
      model: 'text-embedding-3-small',
      input: text.slice(0, 2000)
    })
  });
  const d = await r.json();
  return d.data[0].embedding;
};
```

### Cosine similarity (pure JS — free, no API)

```javascript
const cosineSim = (a, b) => {
  let dot = 0, na = 0, nb = 0;
  for (let i = 0; i < a.length; i++) {
    dot += a[i] * b[i];
    na  += a[i] * a[i];
    nb  += b[i] * b[i];
  }
  return dot / (Math.sqrt(na) * Math.sqrt(nb));
};
```

### Match each section to top PIDs

```javascript
const NO_MATCH_THRESHOLD = 0.35;

const matchSection = async (sectionText, catalogue) => {
  const sectionEmb = await embedText(sectionText);

  const scored = catalogue
    .map(p => ({ product: p, score: cosineSim(sectionEmb, p.embedding) }))
    .sort((a, b) => b.score - a.score)
    .slice(0, 3);

  return {
    matched:    scored[0].score >= NO_MATCH_THRESHOLD,
    flagged:    scored[0].score <  NO_MATCH_THRESHOLD,
    candidates: scored,
    best:       scored[0]
  };
};

const matchAllSections = async (sections, catalogue) => {
  const results = [];
  for (const section of sections) {
    const { matched, flagged, candidates, best } = await matchSection(
      section.text, catalogue
    );
    results.push({
      section_heading: section.heading,
      section_text:    section.text,
      matched,
      flagged,
      best_pid:    best.product.pid,
      best_score:  best.score,
      best_image:  best.product.images[0],
      pdp_url:     best.product.pdp_url,
      product:     best.product,
      candidates,
      approved:    false
    });
  }
  return results;
};
```

---

## Part 4 — Featured Image

### Resize via ImageKit (no canvas, no CORS)

```javascript
const getFeaturedImageUrl = (originalUrl, width, height) => {
  return originalUrl.replace(
    /tr:[^/]+/,
    `tr:w-${width},h-${height},c-maintain_ratio`
  );
};
```

Example:
```
Input:  https://static3.azafashions.com/tr:w-450/uploads/product_gallery/xxx.jpg
Output: https://static3.azafashions.com/tr:w-1200,h-800,c-maintain_ratio/uploads/product_gallery/xxx.jpg
```

### Which PID becomes the featured image

First section with `matched: true` and `approved: true`, using `images[0]`.
If all sections are skipped or flagged: show warning in UI.

### Default dimensions

1200 x 800px. Stored in sessionStorage, editable in settings.

---

## Part 5 — WordPress Media Upload

```javascript
const uploadImageToWP = async (imageUrl, filename, altText) => {
  const siteUrl     = sessionStorage.getItem('WP_SITE_URL');
  const credentials = btoa(
    `${sessionStorage.getItem('WP_USERNAME')}:${sessionStorage.getItem('WP_APP_PASSWORD')}`
  );

  const imgResp = await fetch(imageUrl);
  const blob    = await imgResp.blob();

  const form = new FormData();
  form.append('file', blob, filename);
  form.append('alt_text', altText);

  const r = await fetch(`${siteUrl}/wp-json/wp/v2/media`, {
    method: 'POST',
    headers: {
      'Authorization':       `Basic ${credentials}`,
      'Content-Disposition': `attachment; filename="${filename}"`
    },
    body: form
  });

  if (!r.ok) throw new Error(`Media upload failed: ${r.status}`);
  const media = await r.json();
  return { media_id: media.id, media_url: media.source_url };
};
```

---

## Part 6 — HTML Assembly with Product Figures

```javascript
const buildSectionHTML = (sectionMarkdown, matchResult) => {
  let html = marked.parse(sectionMarkdown);

  if (matchResult.approved && matchResult.media_url) {
    const figure = `
<figure class="wp-block-image aligncenter">
  <a href="${matchResult.pdp_url}" target="_blank" rel="noopener noreferrer">
    <img src="${matchResult.media_url}" alt="${matchResult.product.title}" />
  </a>
  <figcaption>
    <a href="${matchResult.pdp_url}" target="_blank" rel="noopener noreferrer">
      ${matchResult.product.title}
    </a>
  </figcaption>
</figure>`;

    if (html.includes('</h2>')) {
      html = html.replace('</h2>', `</h2>${figure}`);
    } else {
      html = figure + html;
    }
  }

  return html;
};
```

---

## Part 7 — Full Yoast SEO Fields

```javascript
const updateYoastSEO = async (postId, brief, credentials, siteUrl) => {
  const r = await fetch(`${siteUrl}/wp-json/wp/v2/posts/${postId}`, {
    method: 'POST',
    headers: {
      'Content-Type':  'application/json',
      'Authorization': `Basic ${credentials}`
    },
    body: JSON.stringify({
      meta: {
        _yoast_wpseo_title:    brief.title,
        _yoast_wpseo_metadesc: brief.meta_description,
        _yoast_wpseo_focuskw:  brief.seo_keywords[0],

        _yoast_wpseo_keywordsynonyms: JSON.stringify(
          brief.seo_keywords.slice(1).map(kw => ({ keyword: kw, synonyms: '' }))
        ),

        _yoast_wpseo_opengraph_title:       brief.title,
        _yoast_wpseo_opengraph_description: brief.meta_description,
        _yoast_wpseo_twitter_title:         brief.title,
        _yoast_wpseo_twitter_description:   brief.meta_description,

        _yoast_wpseo_schema_article_type: 'BlogPosting',
        _yoast_wpseo_schema_page_type:    'WebPage',

        _yoast_wpseo_is_cornerstone: brief.target_length === 'long' ? '1' : '0',
        _yoast_wpseo_canonical:      ''
      }
    })
  });

  if (!r.ok) console.warn('Yoast SEO update failed:', await r.json());
};
```

After building, verify fields:
```
GET /wp-json/yoast/v1/get_head?url=<post_preview_url>
```

---

## Part 8 — Prompt Caching

```javascript
const callClaudeWithCaching = async ({
  model, temperature, brandGuide, writingSkill,
  stageInstructions, userMessage, stream = false
}) => {
  const systemBlocks = [];

  if (brandGuide) {
    systemBlocks.push({
      type: 'text',
      text: 'BRAND GUIDE:\n' + brandGuide,
      cache_control: { type: 'ephemeral' }
    });
  }
  if (writingSkill) {
    systemBlocks.push({
      type: 'text',
      text: 'WRITING SKILL:\n' + writingSkill,
      cache_control: { type: 'ephemeral' }
    });
  }
  systemBlocks.push({ type: 'text', text: stageInstructions });

  const response = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: {
      'Content-Type':                            'application/json',
      'x-api-key':                               sessionStorage.getItem('ANTHROPIC_API_KEY'),
      'anthropic-version':                       '2023-06-01',
      'anthropic-beta':                          'prompt-caching-2024-07-31',
      'anthropic-dangerous-direct-browser-access': 'true'
    },
    body: JSON.stringify({
      model, max_tokens: 4096, temperature, stream,
      system:   systemBlocks,
      messages: [{ role: 'user', content: userMessage }]
    })
  });

  if (!response.ok) throw new Error(`API error: ${response.status}`);
  if (stream) return response;

  const data = await response.json();
  console.log('Cache stats:', {
    writes: data.usage?.cache_creation_input_tokens,
    reads:  data.usage?.cache_read_input_tokens,
    normal: data.usage?.input_tokens
  });
  return data.content[0].text;
};
```

---

## Part 9 — Settings Panel

```
-- Anthropic ------------------------------------------
API Key      [sk-ant-...                        ****]

-- OpenAI (product image matching) -------------------
API Key      [sk-...                            ****]
             Used for embedding blog sections
             (~$0.00004 per blog, ~6 calls)

-- WordPress -----------------------------------------
Site URL     [https://ssblog.azaonline.in          ]
Username     [                                     ]
App Password [                                ****]

-- Product Catalogue ----------------------------------
[ Upload products_with_embeddings.json ]
Status: 1,806 products loaded ✓

-- Featured Image -------------------------------------
Width  [1200]   Height  [800]   px
```

SessionStorage keys:
- ANTHROPIC_API_KEY
- OPENAI_API_KEY
- WP_SITE_URL, WP_USERNAME, WP_APP_PASSWORD
- FEATURED_IMAGE_WIDTH (default 1200)
- FEATURED_IMAGE_HEIGHT (default 800)
- Product catalogue: memory only

---

## Part 10 — State 3 UI: Product Images Section

```
-- Product Images -----------------------------------------------

[ Upload products_with_embeddings.json ]
[ Match Product Images ]

Section 1: "The Art of the Weave"
  [thumbnail] Ivory Pure Banarasi Silk Saree (123181)
  Score: 0.74    [Approve ✓]  [Skip]

Section 2: "Colour and Occasion"
  [thumbnail] ⚠ No strong match (score: 0.28)
  Closest: Black Printed Dhoti Pant (211667)
  [Use anyway]  [Skip]

Featured image: Ivory Pure Banarasi Silk Saree — 1200×800px ✓

Publish flow:
  [✓] Uploading Section 1 image...
  [✓] Uploading featured image...
  [✓] Creating draft post...
  [✓] Setting featured image...
  [✓] Updating Yoast SEO...
  ✅ Draft created — [Preview ↗]  [Edit in WordPress ↗]
```

---

## Part 11 — Build Order (append after CLAUDE.md step 12)

13. embed_products.py — build using the script in Part 2. Test with first
    10 rows of product_info.csv. Confirm:
    - Parsing handles the nested JSON correctly
    - embedding_text is rich (title + description + attributes + keywords)
    - Output JSON has valid 1536-dim embedding arrays
    - pdp_url uses PID twice (samyuktasinghania.com/products/{pid}/{pid})

14. Settings panel — add OpenAI key, catalogue file picker, featured image
    dimension fields. Log product count on load. Confirm 1,806 products load.

15. embedText() — wire OpenAI call. Test with one section, confirm array
    length is 1536.

16. cosineSim() + matchSection() — test with mock section text.
    Log top 3 matches and scores. Verify rankings make sense.

17. matchAllSections() — run against all sections of a generated blog.
    Inspect results in console. Tune NO_MATCH_THRESHOLD if needed.

18. Match results UI — render per-section cards in State 3 with
    thumbnail, score, Approve / Skip / Use anyway. Block Publish
    until all flagged sections resolved.

19. WordPress media upload — test uploadImageToWP() with one image.
    Confirm it appears in WordPress Media Library.

20. Featured image — test getFeaturedImageUrl() transform. Confirm
    the transformed URL loads correctly in browser before uploading.

21. HTML assembly — build full post HTML with figures. Inspect in
    browser, check figure insertion after </h2>.

22. Full publish flow — wire all steps: media → post → featured
    image → Yoast. Test on QA site (ssblog.azaonline.in).

23. Prompt caching — replace all callClaude() with callClaudeWithCaching().
    Confirm cache stats appear in console.

---

## Cost Summary

| Item | Frequency | Cost |
|---|---|---|
| embed_products.py — 1,806 PIDs | Once | ~$0.004 |
| OpenAI — embed 6 sections | Per blog | ~$0.00004 |
| Claude Stage 1 Brief (Haiku, cache write) | Per blog | ~$0.019 |
| Claude Stage 2 Draft (Sonnet, cache read) | Per blog | ~$0.026 |
| Claude Stage 3 Review (Haiku, cache read) | Per blog | ~$0.009 |
| Claude Stage 4 Rewrite (Sonnet, cache read) | If needed | ~$0.030 |
| WordPress media upload | Per image | Free |
| **Total per blog (all stages, with caching)** | | **~$0.068** |
| **Until Aug 31 2026 (introductory Sonnet pricing)** | | **~$0.050** |
| **10 blogs/month** | | **~$0.68** |
| **30 blogs/month** | | **~$2.05** |
