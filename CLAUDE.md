# CLAUDE.md — Samyukta Singhania Blog Writer
## AI-Powered Content Pipeline: Research → Brief → Draft → Review → Rewrite → Docx

---

## Project Overview

An extension of the existing `blog_topics` dashboard that adds a fully automated
blog writing pipeline. User opens `writer.html` from within the research dashboard,
selects a shortlisted topic, and the system produces a publish-ready `.docx` file.
No human writing involved. You are acting as Samyukta Singhania's content writer.

**Guiding principle**: One orchestrator, four sequential stages with two specialised
agents (Writer + Reviewer), one human decision point (topic selection). Everything
else is automated.

**MVP scope**: Fully client-side. No backend. No GitHub Actions for blog generation.
Browser → Anthropic API → docx download. Ship this first, harden later.

---

## Architecture

```
blog_topics/
├── index.html           # Existing research dashboard — migrated from Gemini to Claude
├── writer.html          # New: Blog writing pipeline
├── ig_posts.json        # Shared data — Instagram posts
├── feed.json            # Shared data — editorial articles
├── brand_guide.md       # Samyukta Singhania brand voice — loaded via fetch()
├── writing_skill.md     # Combined human writing rules — loaded via fetch()
├── CLAUDE.md            # This file
└── .github/
    └── workflows/       # Existing scrapers only — do not touch
```

**How the two pages connect**: `index.html` gets a "Write Blog" button next to each
shortlisted topic. Clicking it opens `writer.html?topic=<encoded_topic_data>` in a
new tab, pre-loading the selected topic + source posts/articles.

---

## API Configuration

**Model allocation:**

| Stage | Model | Temp | Reason |
|---|---|---|---|
| index.html — idea generation | claude-haiku-4-5 | 0.5 | Fast, cheap, ideas don't need Sonnet |
| Stage 1 — Brief Builder | claude-haiku-4-5 | 0.3 | Structured JSON, analytical |
| Stage 2 — Blog Writer Agent | claude-sonnet-4-6 | 0.8 | Quality matters, voice-driven |
| Stage 3 — Editorial Review Agent | claude-haiku-4-5 | 0.2 | Fast checklist enforcement |
| Stage 4 — Rewrite Agent | claude-sonnet-4-6 | 0.5 | Targeted fixes only |

**Key management — MVP approach:**
- Single settings panel (gear icon, top right) in both `index.html` and `writer.html`
- User pastes `ANTHROPIC_API_KEY` once per session
- Stored in `sessionStorage` — survives refresh, cleared on tab close
- Never logged, never sent anywhere except `api.anthropic.com`
- Key field: password input type (masked)
- If key is missing when API call attempted: settings panel opens automatically

**Every API call must include this header:**
```javascript
"anthropic-dangerous-direct-browser-access": "true"
```

**Standard fetch wrapper (use for all calls):**
```javascript
const callClaude = async ({ model, temperature, system, userMessage, stream = false }) => {
  const response = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-api-key": sessionStorage.getItem("ANTHROPIC_API_KEY"),
      "anthropic-version": "2023-06-01",
      "anthropic-dangerous-direct-browser-access": "true"
    },
    body: JSON.stringify({
      model,
      max_tokens: 4096,
      temperature,
      system,
      stream,
      messages: [{ role: "user", content: userMessage }]
    })
  });
  if (!response.ok) throw new Error(`API error: ${response.status}`);
  const data = await response.json();
  return data.content[0].text;
};
```

---

## Latency Optimisations

### index.html — Idea Generation

**Batch all source material into a single API call.**
Do not make one call per post or per article. Send all source material in one
prompt and ask for all ideas in a single structured JSON response.

```javascript
// WRONG — sequential calls
for (const post of posts) {
  const ideas = await generateIdeas(post); // N network round trips
}

// CORRECT — single batched call
const allIdeas = await generateAllIdeas(posts); // 1 network round trip
```

Use `claude-haiku-4-5` for idea generation — it is 5x faster than Sonnet for
this task and the quality difference is negligible for topic ideas.

### writer.html — Pre-load files immediately

Load `brand_guide.md` and `writing_skill.md` the moment `writer.html` opens —
not when the user clicks "Write Blog." They should be in memory before the user
has finished reading State 1.

```javascript
// Run immediately on page load — do not await user interaction
let brandGuide, writingSkill;
(async () => {
  [brandGuide, writingSkill] = await Promise.all([
    fetch('brand_guide.md').then(r => r.text()),
    fetch('writing_skill.md').then(r => r.text())
  ]);
})();
```

### writer.html — Stream Stage 2

Use streaming for Stage 2 (Blog Writer Agent) so the user sees text appearing
immediately rather than waiting for the full draft. Set `stream: true` and handle
the SSE stream. This dramatically reduces perceived latency even if total time
is similar.

Stage 1, 3, 4 do not need streaming — they are fast (Haiku) or targeted (Stage 4).

---

## The Four-Stage Pipeline

### Stage 1 — Brief Builder
**Model:** claude-haiku-4-5 | **Temp:** 0.3

**System prompt:**
```
You are an editorial director building a content brief for the Samyukta Singhania blog.

BRAND GUIDE:
{brandGuide}

WRITING SKILL:
{writingSkill}

Your job: analyse the source material and produce a structured JSON brief.
Return ONLY valid JSON. No preamble, no explanation, no markdown fences.
```

**User message:** Topic title + angle + source captions/excerpts + blog type (short/long)

**Output — strict JSON:**
```json
{
  "title": "Working title, SEO-aware, max 12 words",
  "slug": "url-friendly-slug-max-6-words",
  "meta_description": "150-160 characters exactly",
  "target_length": "short|long",
  "angle": "Single declarative sentence — the specific take",
  "reader_need": "What the reader gets — information, inspiration, or validation",
  "outline": [
    { "section": "Section heading", "notes": "What this covers and why" }
  ],
  "key_points": ["Concrete point 1", "Concrete point 2"],
  "seo_keywords": ["primary keyword", "secondary keyword 1", "secondary keyword 2"],
  "sourced_from": ["URL or post ID of source material"],
  "flags": ["Specific claim that needs fact-checking before publish"]
}
```

**Validation:**
- `outline`: 3–5 items for short-form, 5–8 for long-form
- `angle`: declarative sentence, not a question
- `meta_description`: 140–165 chars — retry once if outside range
- `flags`: must name any designer names, prices, dates, statistics, collection names
- JSON parse failure: retry once with stricter instruction

---

### Stage 2 — Blog Writer Agent
**Model:** claude-sonnet-4-6 | **Temp:** 0.8 | **Stream:** true

This agent has ONE job: write in Samyukta's voice. It does not self-review.
It does not anticipate corrections. It writes freely.

**System prompt:**
```
You are Samyukta Singhania — a luxury Indian fashion designer based in Jaipur,
writing a blog post in your own voice for your personal blog.

BRAND GUIDE (your voice, your values, your reader):
{brandGuide}

WRITING SKILL (the craft rules your writing follows):
{writingSkill}

CONTENT BRIEF (what you are writing today):
{briefJSON}

Write the full blog post now.
Return ONLY the blog text in plain markdown.
Do not add "Here is the blog post:" or any preamble.
Start directly with the title as # H1, then the body.
Nothing before the title. Nothing after the last sentence.

ABSOLUTE RULES — these cannot be broken:
- Never use em-dashes (—). If you want one, restructure the sentence.
  Use a comma, a period, or start a new sentence instead.
- Never start with a question, a statistic, or "In today's world"
- Never end with a call to action or "only time will tell"
- Short-form: no subheadings, flowing prose only
- Long-form: maximum 3 subheadings, editorial style
```

**Output:** Raw markdown string. Title as # H1. Subheadings as ## H2 (long-form only).

---

### Stage 3 — Editorial Review Agent
**Model:** claude-haiku-4-5 | **Temp:** 0.2

This agent has ONE job: find violations. It does NOT rewrite anything.
It reads the draft and returns a structured violation report only.

Keeping review and rewrite separate means:
- The reviewer is ruthless — it has no responsibility for fixing anything
- The rewriter is precise — it has a specific list of exactly what to fix
- The original voice from Stage 2 is preserved everywhere Stage 3 didn't flag

**System prompt:**
```
You are a strict copy editor reviewing a blog post for the Samyukta Singhania brand.
Your ONLY job is to find violations. Do NOT rewrite anything. Do NOT suggest improvements.
Find violations, report them precisely, and stop.

BRAND GUIDE:
{brandGuide}

WRITING SKILL (the rules to enforce):
{writingSkill}

ORIGINAL BRIEF:
{briefJSON}

DRAFT TO REVIEW:
{draftMarkdown}

Return ONLY valid JSON. No preamble, no explanation, no markdown fences.
```

**Output — strict JSON:**
```json
{
  "brand_voice_score": 7,
  "brand_voice_rationale": "One honest sentence — do not inflate",
  "em_dashes_found": ["exact sentence containing —"],
  "banned_words_found": [{ "word": "word", "context": "sentence it appeared in" }],
  "rhythm_violations": ["quote the 3+ consecutive same-length sentences"],
  "opening_violation": false,
  "closing_violation": false,
  "ai_tells": ["specific phrase that reads as AI-generated"],
  "seo_readiness": {
    "primary_keyword_in_title": true,
    "primary_keyword_in_first_100_words": true,
    "meta_description_length": 155,
    "heading_structure": "pass"
  },
  "factual_flags": ["claim to verify — carried from brief"],
  "suggested_title_alternatives": ["Alt title 1", "Alt title 2"],
  "needs_rewrite": true
}
```

**`needs_rewrite` logic:**
- `true` if: any em-dashes found, any banned words found, any rhythm violations,
  opening or closing violation, brand_voice_score < 6, or 2+ ai_tells found
- `false` if: no violations found and score ≥ 6
- If `needs_rewrite` is false: skip Stage 4 entirely, go straight to output

**Score calibration (enforce strictly in prompt):**
- 5 = competent but generic, could be any Indian fashion brand
- 6 = recognisably Samyukta's domain, some personality present
- 7 = good — sounds like a specific person with opinions
- 8 = strong — distinctive voice, specific details, genuine point of view
- 9–10 = reserved; do not assign unless truly exceptional

---

### Stage 4 — Rewrite Agent
**Model:** claude-sonnet-4-6 | **Temp:** 0.5

Only runs if Stage 3 sets `needs_rewrite: true`.

This agent has ONE job: fix exactly what Stage 3 flagged. Nothing else.
It does not improve unflagged sections. It does not expand. It does not reimagine.
Fix and stop.

**System prompt:**
```
You are a precise copy editor making targeted fixes to a blog post.
You have a violation report that lists exactly what is wrong.
Fix ONLY what is listed in the violation report.
Do not change anything that is not listed.
Do not improve unflagged sections.
Do not change the voice, tone, or any sentence not mentioned in the report.
Fix and stop.

VIOLATION REPORT:
{reviewJSON}

ORIGINAL DRAFT:
{draftMarkdown}

Return ONLY the corrected blog post in plain markdown.
Same format as the input — title as # H1, body as paragraphs.
No preamble. No explanation of what you changed. Just the corrected draft.
```

**Fixes applied in priority order:**
1. Remove every em-dash — replace with comma, period, or restructured sentence
2. Replace every banned word with a natural alternative
3. Fix rhythm violations — vary sentence length in flagged passages
4. Fix opening if flagged
5. Fix closing if flagged
6. Remove AI tells from flagged phrases

**Auto-retry rule:**
- If Stage 3 score < 6: re-run Stage 2 with the review JSON appended as context.
  Show "Polishing draft (attempt 2/2)..." in UI. Maximum 2 attempts total.
  Do not retry a third time regardless of score.

---

## Post-Processing (JavaScript — runs after Stage 4, before docx)

This is a deterministic safety net. No matter what the model generates,
these transforms run on the final text before any output.

```javascript
const postProcess = (text) => {
  return text
    // Remove all em-dashes — deterministic guarantee
    .replace(/([^.!?\n])\s*—\s*(?=[a-z])/g, '$1, ')   // mid-sentence lowercase → comma
    .replace(/([^.!?\n])\s*—\s*(?=[A-Z])/g, '$1. ')   // mid-sentence uppercase → period
    .replace(/—/g, ',')                                  // catch any remaining

    // Normalise smart quotes to standard
    .replace(/[\u2018\u2019]/g, "'")
    .replace(/[\u201C\u201D]/g, '"')

    // Remove double spaces
    .replace(/ {2,}/g, ' ')

    // Trim trailing whitespace from lines
    .split('\n').map(line => line.trimEnd()).join('\n');
};
```

---

## UI Design (writer.html)

**Visual style:** Match `index.html` exactly — same fonts, colours, spacing.

**State 1 — Topic Loaded**
- Read-only: topic title, source account/article, 2–3 lines of source text
- Single toggle: Short-form (300–500w) / Long-form (800–1500w)
- Single button: "Write Blog" — disabled if API key not set
- Empty state if no URL params: instructions to use "Write Blog" from dashboard

**State 2 — Pipeline Running**
Four steps with status indicators:

```
[●] Building brief...          ← spinner → checkmark
[●] Writing draft...           ← streaming text visible here
[ ] Reviewing...
[ ] Finalising...              ← only shown if needs_rewrite is true
```

- Show estimated time: "~45 sec" short-form, "~90 sec" long-form
- Stage 2 shows streaming text as it arrives — user sees draft being written live
- "Finalising" step shown/hidden dynamically based on needs_rewrite

**State 3 — Complete**
- Brand voice score: colour-coded (< 6 amber, 6–7 green, 8+ deep green)
- SEO readiness: pass/fail per check
- Factual flags: listed in amber — "Verify before publishing"
- First 200 words preview of final draft
- Two title options: original + best alternative from review
- Primary button: "Download Docx"
- Secondary button: "Publish to WordPress Draft →"
- Tertiary button: "Regenerate" — reruns Stages 2–4, keeps the brief

**Error handling:**
- API key missing: open settings panel, show "API key required"
- Stage 1 JSON parse fail: retry once, then "Try again" button
- Any stage API failure: show which stage failed, "Retry from here" button
- Network error: "Check connection and retry"

---

## Docx Output

Generate client-side using `docxtemplater` + `pizzip`.
Add via CDN — no npm build step.

**Document structure:**
1. Title — Heading 1, 24pt
2. Meta block (italic, 10pt, grey):
   `Slug: {slug} | Keywords: {keywords} | {meta_description}`
3. Horizontal rule
4. Blog body — Normal style, 12pt, line spacing 1.5
   - Long-form subheadings: Heading 2
   - No bold in body except proper nouns on first mention
   - No bullet points in body
5. Horizontal rule
6. Review notes (italic, 10pt):
   - Brand voice score: {score}/10 — {rationale}
   - Factual flags: bulleted list

**Filename:** `blog-YYYY-MM-DD-{slug}.docx`

---

## Topic Data Schema (URL params)

```javascript
// index.html — encoding
const topicData = {
  title: "The topic title or blog idea",
  source_type: "instagram|article",
  source_handle: "@vogueindia or publication name",
  source_url: "https://...",
  source_text: "Caption or excerpt (max 500 chars)",
  generated_angle: "The angle from the research dashboard"
};
window.open(`writer.html?topic=${btoa(JSON.stringify(topicData))}`, '_blank');

// writer.html — decoding
const topicData = JSON.parse(atob(new URLSearchParams(location.search).get('topic')));
```

---

## Build Order for Claude Code

Build strictly in this sequence. Test each step before moving to the next.

1. **Migrate `index.html`** — replace Gemini with Claude (Haiku). Batch all idea
   generation into a single API call. Add settings panel with API key (sessionStorage).
   Confirm idea generation works and is noticeably faster than before.

2. **Build `writer.html` shell** — UI only, no API calls. Mock topic in State 1.
   Mock output in State 3. Four-step progress in State 2. Get layout right first.

3. **Wire file loading** — `brand_guide.md` and `writing_skill.md` loaded via
   `Promise.all()` immediately on page init. Log to console to confirm.

4. **Wire Stage 1** — Brief Builder. Parse JSON. Show brief summary in console.

5. **Wire Stage 2** — Blog Writer Agent with streaming. Show live text in State 2.

6. **Wire Stage 3** — Editorial Review Agent. Parse violation JSON. Log report.

7. **Wire Stage 4** — Rewrite Agent. Conditional on `needs_rewrite`. Apply
   `postProcess()` to final output regardless.

8. **Render State 3** — brand voice score, SEO checks, flags, preview, title options.

9. **Wire docx generation** — test download opens cleanly in Word.

10. **Wire auto-retry** — score < 6 triggers Stage 2 rerun with review context.

11. **Wire "Write Blog" button in index.html** — encode topic data, open writer.html.

12. **Wire WordPress publish button** — per REQUIREMENTS.md.

---

## What NOT to Build in This Version

- No WordPress publishing beyond what REQUIREMENTS.md specifies
- No saved drafts or session history — stateless
- No image generation or suggestions
- No multi-user or auth
- No GitHub Actions for blog generation
- Do not touch `.github/workflows/` — scrapers must keep running

---

## Success Criteria

- Idea generation in `index.html` completes in under 10 seconds
- Short-form blog generates end-to-end in under 90 seconds
- Brand voice score averages 7+ across 5 test runs
- Zero em-dashes in any final output (postProcess is the guarantee)
- Zero banned vocabulary in final output
- Docx opens cleanly in Word, uploads to WordPress without reformatting
- Factual flags appear for every piece containing designer names or statistics
