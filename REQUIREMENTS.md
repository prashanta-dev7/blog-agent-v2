# REQUIREMENTS.md — WordPress Publishing Integration
## Feature: Publish to WordPress Draft from writer.html

---

## Context

This document extends `CLAUDE.md`. Read `CLAUDE.md` first for the full project
architecture. This file specifies the WordPress publishing feature only.

The blog writing pipeline already produces:
- A corrected markdown draft (from Stage 3)
- A structured JSON brief (from Stage 1) containing title, slug, meta description,
  SEO keywords, and factual flags

This feature takes that output and publishes it directly to WordPress as a draft
at the click of a button in State 3 of `writer.html`.

---

## WordPress Environment

- **Site:** `https://ssblog.azaonline.in` (QA/staging)
- **Type:** Self-hosted WordPress
- **REST API:** Enabled and confirmed working
- **SEO Plugin:** Yoast Premium — active, REST API fields available
- **Auth method:** WordPress Application Passwords (WP 5.6+)
- **Default publish status:** `draft` — hardcoded, never changes, never "publish"

---

## One-Time Setup (user does this, not the code)

The user generates a WordPress Application Password from their WP admin:

```
wp-admin → Users → Profile → Application Passwords
→ Name: "blog_writer_tool"
→ Click: Add New Application Password
→ Copy the generated password (shown once only)
```

This produces credentials in the format: `wordpress_username:xxxx xxxx xxxx xxxx`

---

## Credentials Management

Store WordPress credentials in `sessionStorage` alongside the existing Anthropic key.
Same pattern, same settings panel (gear icon, top right).

Add three new fields to the settings panel:

```
── WordPress ──────────────────────────────
Site URL      [https://ssblog.azaonline.in   ]
Username      [                              ]
App Password  [                         ••••]  ← password input type
```

- Site URL defaults to `https://ssblog.azaonline.in` — pre-filled, user can change
- All three stored in `sessionStorage` as `WP_SITE_URL`, `WP_USERNAME`, `WP_APP_PASSWORD`
- Never committed, never logged, cleared on tab close
- If any WordPress credential is missing when "Publish to WordPress Draft" is clicked,
  open settings panel automatically with a "WordPress credentials required" message

---

## Dependencies

Add `marked.js` via CDN for Markdown → HTML conversion.
Add to `<head>` of `writer.html`:

```html
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
```

No other new dependencies. The WordPress REST API is called directly via `fetch()`.

---

## The Publish Function

```javascript
const publishToWordPress = async (brief, correctedDraftMarkdown) => {

  const siteUrl    = sessionStorage.getItem('WP_SITE_URL');
  const username   = sessionStorage.getItem('WP_USERNAME');
  const appPassword = sessionStorage.getItem('WP_APP_PASSWORD');

  // Basic auth — Application Password format
  const credentials = btoa(`${username}:${appPassword}`);

  // Convert markdown to clean HTML
  const htmlContent = marked.parse(correctedDraftMarkdown);

  // Build post payload
  const payload = {
    title:   brief.title,
    content: htmlContent,
    status:  "draft",                    // HARDCODED — never change this
    slug:    brief.slug,
    excerpt: brief.meta_description,
  };

  // Publish to WordPress REST API
  const response = await fetch(`${siteUrl}/wp-json/wp/v2/posts`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Basic ${credentials}`
    },
    body: JSON.stringify(payload)
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.message || `WordPress API error: ${response.status}`);
  }

  const post = await response.json();

  // After post is created, update Yoast SEO fields separately
  await updateYoastFields(post.id, brief, credentials, siteUrl);

  return {
    postId:     post.id,
    previewUrl: post.link,              // draft preview URL
    editUrl:    `${siteUrl}/wp-admin/post.php?post=${post.id}&action=edit`
  };
};
```

---

## Yoast Premium SEO Fields

After the post is created, update Yoast fields via a second REST API call.
Yoast Premium exposes its fields through the WordPress REST API.

```javascript
const updateYoastFields = async (postId, brief, credentials, siteUrl) => {

  await fetch(`${siteUrl}/wp-json/wp/v2/posts/${postId}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Basic ${credentials}`
    },
    body: JSON.stringify({
      meta: {
        // Yoast Premium meta fields
        _yoast_wpseo_title:           brief.title,
        _yoast_wpseo_metadesc:        brief.meta_description,
        _yoast_wpseo_focuskw:         brief.seo_keywords[0],

        // Yoast Premium — related keyphrases (secondary keywords)
        _yoast_wpseo_keywordsynonyms: JSON.stringify(
          brief.seo_keywords.slice(1).map(kw => ({ keyword: kw, synonyms: "" }))
        ),
      }
    })
  });
  // Non-blocking — if Yoast update fails, the post still exists
  // Log the error but do not throw
};
```

**Note on Yoast field names:** These are the standard Yoast meta key names. If
fields do not save correctly after building, inspect the REST API response from
`/wp-json/yoast/v1/get_head?url=<post_url>` to confirm field names for this
specific Yoast Premium version. Do not assume field names — verify against the
live API.

---

## Error Handling

Handle these specific failure cases:

| Error | Cause | User message |
|---|---|---|
| 401 Unauthorized | Wrong username or app password | "WordPress credentials incorrect — check settings" |
| 403 Forbidden | User role doesn't have publish rights | "WordPress user doesn't have permission to create posts" |
| 404 Not Found | Wrong site URL or REST API disabled | "Could not reach WordPress — check site URL" |
| 500 Server Error | WordPress server error | "WordPress returned a server error — try again" |
| Network error | No connection | "Could not connect to WordPress — check your connection" |
| Yoast update fails | Non-blocking | Log to console only, do not show error to user |

On any error: show error message inline below the publish button. Keep the
"Publish to WordPress Draft" button active so the user can retry.

---

## UI Changes to State 3

**Before publish** — two buttons side by side:

```
┌─────────────────────┐  ┌──────────────────────────────────┐
│   Download Docx     │  │  Publish to WordPress Draft  →   │
└─────────────────────┘  └──────────────────────────────────┘
```

**While publishing** — button shows inline spinner:

```
┌─────────────────────┐  ┌──────────────────────────────────┐
│   Download Docx     │  │  ⟳  Publishing...                │
└─────────────────────┘  └──────────────────────────────────┘
```

**After successful publish** — replace publish button with confirmation:

```
┌─────────────────────┐
│   Download Docx     │
└─────────────────────┘

✅ Draft created in WordPress

[Preview Draft ↗]    [Edit in WordPress ↗]
```

Both links open in a new tab.
`Preview Draft` → `post.link`
`Edit in WordPress` → `wp-admin/post.php?post={id}&action=edit`

The user can still download the docx after publishing. Both actions are independent.

---

## What Does NOT Get Published

Do not include in the WordPress post payload:

- The review report (brand voice score, AI tells, factual flags) — internal only
- The meta information block from the docx (slug, keywords line) — Yoast handles this
- Any markdown formatting syntax — `marked.parse()` converts it before sending
- The "Factual flags to verify" section — stays in the docx only

---

## Scope Constraints

- Status is always `draft` — no UI option to change this
- No scheduled publishing in this version
- No category or tag assignment in this version — user sets these in WP editor
- No featured image — user adds this in WP editor
- No revision history or publish log
- The QA site (`ssblog.azaonline.in`) is the only target — no multi-site support

---

## Verification Step Before Building

Before writing any code, confirm the REST API and auth work by running this in
the browser console on any page of the tool:

```javascript
// Test 1 — REST API reachable
fetch('https://ssblog.azaonline.in/wp-json/wp/v2/posts?per_page=1')
  .then(r => r.json())
  .then(data => console.log('REST API OK:', data))
  .catch(e => console.error('REST API failed:', e));

// Test 2 — Auth works (run after getting app password)
const creds = btoa('YOUR_USERNAME:YOUR_APP_PASSWORD');
fetch('https://ssblog.azaonline.in/wp-json/wp/v2/users/me', {
  headers: { 'Authorization': `Basic ${creds}` }
})
  .then(r => r.json())
  .then(data => console.log('Auth OK, logged in as:', data.name))
  .catch(e => console.error('Auth failed:', e));
```

Both must pass before proceeding. If Test 1 fails, check `.htaccess` and REST API
settings in WordPress. If Test 2 fails, regenerate the Application Password.
