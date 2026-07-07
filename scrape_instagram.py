#!/usr/bin/env python3
"""
AZA Instagram Scraper — Production CI Version

Ported from the Colab notebook for unattended GitHub Actions execution.
Reads cookies from the INSTAGRAM_COOKIES env var (a JSON string exported
from Cookie-Editor in Chrome). Writes ig_posts.json to the repo root.

Exit codes:
  0  — success, fresh data written
  1  — fatal config error (missing cookies, malformed JSON)
  2  — scrape ran but harvested too few posts (likely login wall / IP block);
       existing ig_posts.json is preserved so the dashboard doesn't go blank
"""

import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

# ── Config ──────────────────────────────────────────────────────────────
ACCOUNTS = [
    "a2z_fashionmag", "anothermagazine", "archivedrunway", "bazaaraustralia",
    "bazaarindia", "bof", "bollywoodwomencloset", "bridestodayin",
    "brownfashiongal", "checkthetag", "cnnstyle", "coveteur", "cultmag",
    "culturecircle_", "dazed", "diamond_world_magazine", "diet_prada",
    "dietsabya", "elleindia", "elleusa", "esquireindia", "fashionispsychology",
    "fashionlawjournal", "feminaindia", "goodonyou_app", "gqindia", "graziauk",
    "harpersbazaarus", "hellomag", "highsnobietystyle", "houseofsartorial",
    "hypebae", "hypebeast", "idivaofficial", "instylemagazine",
    "lifestyleasiaindia", "lofficielitalia", "lofficielusa", "luxuriousbymm",
    "manifest.ind", "nytstyle", "opulentstylings", "outlandermagazine",
    "shethepeoplenews", "spreeh.in", "stylecartel", "stylistelixir",
    "the.estd", "thecitizensposte", "thefashionobserve", "thenodmag",
    "thevofashion", "veronicatuckerthelabel", "vogue.adria", "voguebeauty",
    "voguebusiness", "vogueindia", "voguemagazine", "voguerunway",
    "vogueshopping", "voguesingapore", "weddingaffairofficial",
    "weddingvows.in", "who_wore_what_when", "whowhatwear", "womenculture.co",
    "wwd",
]

POSTS_PER_ACCOUNT = 6
PARALLEL_BROWSERS = 3       # safe concurrency — IG flags higher
DELAY_BETWEEN_POSTS = 1.5   # seconds between individual post pages
ACCOUNT_TIMEOUT = 180       # hard cap per account (seconds) so a stuck
                            # account can't hang the whole workflow

# Sanity threshold: if we get fewer posts than this, treat the run as
# failed and refuse to overwrite the existing ig_posts.json. Tuned to be
# generous — partial scrapes (some accounts blocked) still get through,
# but a wholesale login-wall failure does not.
MIN_POSTS_FOR_SUCCESS = 50

POST_LINK_SELECTORS = [
    "article a[href*='/p/']",
    "a[href*='/p/']",
    "main a[href*='/p/']",
]

OUTPUT_PATH = Path("ig_posts.json")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


# ── Cookie loading ──────────────────────────────────────────────────────
def load_cookies():
    """Read cookies from INSTAGRAM_COOKIES env var (JSON-encoded)."""
    raw = os.environ.get("INSTAGRAM_COOKIES", "").strip()
    if not raw:
        print("FATAL: INSTAGRAM_COOKIES env var is empty or missing.")
        print("       Set it as a GitHub Actions secret with the JSON")
        print("       export from the Cookie-Editor Chrome extension.")
        sys.exit(1)

    try:
        raw_cookies = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"FATAL: INSTAGRAM_COOKIES is not valid JSON: {e}")
        sys.exit(1)

    if not isinstance(raw_cookies, list):
        print("FATAL: INSTAGRAM_COOKIES must be a JSON array of cookie objects.")
        sys.exit(1)

    # Same normalisation as the notebook — Playwright is strict about
    # the sameSite values and rejects negative/zero expires.
    cookies = []
    for c in raw_cookies:
        same_site = c.get("sameSite", "Lax")
        if same_site not in ("Strict", "Lax", "None"):
            same_site = "Lax"
        cookie = {
            "name": c.get("name", ""),
            "value": c.get("value", ""),
            "domain": c.get("domain", ".instagram.com"),
            "path": c.get("path", "/"),
            "sameSite": same_site,
        }
        exp = c.get("expirationDate") or c.get("expires")
        if isinstance(exp, (int, float)) and exp > 0:
            cookie["expires"] = int(exp)
        if c.get("httpOnly"):
            cookie["httpOnly"] = True
        if c.get("secure"):
            cookie["secure"] = True
        cookies.append(cookie)

    # Sanity check — without sessionid, every request will hit the login
    # wall. Fail fast rather than burn 45 minutes scraping nothing.
    has_sessionid = any(c["name"] == "sessionid" and c["value"] for c in cookies)
    if not has_sessionid:
        print("FATAL: No 'sessionid' cookie found. Re-export from a")
        print("       logged-in Instagram session and update the secret.")
        sys.exit(1)

    print(f"Loaded {len(cookies)} cookies (sessionid present)")
    return cookies


# ── Scrape helpers (lifted from the notebook) ───────────────────────────
def extract_shortcode(url):
    m = re.search(r"/p/([A-Za-z0-9_-]+)", url)
    return m.group(1) if m else None


async def find_post_links(page, n):
    for sel in POST_LINK_SELECTORS:
        try:
            await page.wait_for_selector(sel, timeout=8000)
            hrefs = await page.eval_on_selector_all(
                sel,
                "els => [...new Set(els.map(e => e.href).filter(h => h.includes('/p/')))]",
            )
            if hrefs:
                return hrefs[:n]
        except Exception:
            continue
    # fallback: any /p/ link on the page
    try:
        hrefs = await page.eval_on_selector_all(
            "a[href]",
            "els => [...new Set(els.map(e => e.href).filter(h => /\\/p\\/[A-Za-z0-9_-]+/.test(h)))]",
        )
        return hrefs[:n] if hrefs else []
    except Exception:
        return []


async def get_post_details(page, href):
    await page.goto(href, wait_until="domcontentloaded", timeout=25000)
    await asyncio.sleep(DELAY_BETWEEN_POSTS)

    # expand truncated caption
    for sel in [
        'span[role="button"]:has-text("more")',
        'span:has-text("… more")',
        'span:has-text("more")',
    ]:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible():
                await btn.click()
                await asyncio.sleep(0.5)
                break
        except Exception:
            pass

    # caption
    caption = ""
    try:
        candidates = await page.eval_on_selector_all(
            'span[class*="x193iq5w"]',
            "els => els.map(el => el.innerText.trim()).filter(t => t.length > 30)",
        )
        if candidates:
            raw = max(candidates, key=len)
            skip = re.compile(
                r"^(vogueindia|diet_prada|dietsabya|Edited|Follow|Verified|\d+[wdhm]|•|\xa0)$",
                re.IGNORECASE,
            )
            clean = [
                l.strip()
                for l in raw.splitlines()
                if l.strip()
                and not skip.match(l.strip())
                and not re.match(r"^[\w.]+$", l.strip())
            ]
            caption = "\n".join(clean).strip()
    except Exception:
        pass

    # image alt text
    alt_text = ""
    try:
        alts = await page.eval_on_selector_all(
            "img.x5yr21d.xu96u03.x10l6tqk.x13vifvy.x87ps6o.xh8yej3",
            "els => els.map(el => el.getAttribute('alt')).filter(a => a && a.length > 20)",
        )
        if alts:
            alt_text = alts[0]
    except Exception:
        pass

    # post date
    post_date = ""
    try:
        post_date = await page.eval_on_selector(
            "time[datetime]", "el => el.getAttribute('datetime')"
        ) or ""
    except Exception:
        pass

    hashtags = re.findall(r"#\w+", caption)
    return {
        "post_id": extract_shortcode(href),
        "url": href,
        "caption": caption,
        "alt_text": alt_text,
        "hashtags": hashtags,
        "date": post_date,
    }


async def scrape_one_account(handle, cookies, semaphore, results, progress):
    async with semaphore:
        try:
            await asyncio.wait_for(
                _scrape_one_account_inner(handle, cookies, results),
                timeout=ACCOUNT_TIMEOUT,
            )
        except asyncio.TimeoutError:
            print(f"  ⚠️  @{handle} timed out after {ACCOUNT_TIMEOUT}s")
            results.setdefault(handle, [])

        progress["done"] += 1
        total = progress["total"]
        done = progress["done"]
        pct = int(done / total * 100)
        bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
        n = len(results.get(handle, []))
        print(f"[{bar}] {pct}%  @{handle} — {n} posts  ({done}/{total})")


async def _scrape_one_account_inner(handle, cookies, results):
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True, args=["--no-sandbox"]
        )
        context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 900},
        )
        await context.add_cookies(cookies)
        page = await context.new_page()

        posts = []
        try:
            await page.goto(
                f"https://www.instagram.com/{handle}/",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            await asyncio.sleep(2)

            title = await page.title()
            if "login" in page.url.lower() or "Log in" in title:
                print(f"  ⚠️  @{handle} — login wall, skipping")
            else:
                hrefs = await find_post_links(page, POSTS_PER_ACCOUNT)
                for href in hrefs:
                    try:
                        post = await get_post_details(page, href)
                        posts.append(post)
                    except Exception as e:
                        print(f"  ⚠️  {href}: {e}")
                results[handle] = posts
        except Exception as e:
            print(f"  ⚠️  @{handle} failed: {e}")
            results.setdefault(handle, [])
        finally:
            await context.close()
            await browser.close()


async def scrape_all(accounts, cookies):
    semaphore = asyncio.Semaphore(PARALLEL_BROWSERS)
    results = {}
    progress = {"done": 0, "total": len(accounts)}

    print(
        f"Starting scrape of {len(accounts)} accounts "
        f"({PARALLEL_BROWSERS} in parallel)...\n"
    )
    tasks = [
        scrape_one_account(handle, cookies, semaphore, results, progress)
        for handle in accounts
    ]
    await asyncio.gather(*tasks)
    return results


# ── Output ──────────────────────────────────────────────────────────────
def build_ig_posts_payload(results):
    ig_posts = []
    for handle, posts in results.items():
        for post in posts:
            date_display = ""
            if post["date"]:
                try:
                    dt = datetime.fromisoformat(post["date"].replace("Z", "+00:00"))
                    date_display = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                except Exception:
                    date_display = post["date"]
            ig_posts.append({
                "handle": handle,
                "post_id": post["post_id"],
                "url": post["url"],
                "caption": post["caption"],
                "alt_text": post["alt_text"],
                "hashtags": post["hashtags"],
                "date": date_display,
            })

    return {
        "scraped_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_posts": len(ig_posts),
        "accounts": len(results),
        "posts": ig_posts,
    }


# ── Main ────────────────────────────────────────────────────────────────
async def main():
    cookies = load_cookies()

    start = datetime.now(timezone.utc)
    print(f"Started at {start:%H:%M} UTC\n")

    results = await scrape_all(ACCOUNTS, cookies)

    elapsed = datetime.now(timezone.utc) - start
    payload = build_ig_posts_payload(results)
    total = payload["total_posts"]
    accounts_with_posts = sum(1 for v in results.values() if v)

    mins = int(elapsed.total_seconds() // 60)
    secs = int(elapsed.total_seconds() % 60)
    print(f"\nDone in {mins}m {secs}s")
    print(f"   {total} posts from {accounts_with_posts}/{len(results)} accounts")

    # Quality gate — refuse to overwrite a good ig_posts.json with a
    # near-empty one. This is what protects the dashboard on the days
    # Instagram blocks us wholesale.
    if total < MIN_POSTS_FOR_SUCCESS:
        print(
            f"\nFAILED: only {total} posts harvested "
            f"(threshold: {MIN_POSTS_FOR_SUCCESS})."
        )
        print("Likely cause: cookies expired, login wall, or IP block.")
        print("Existing ig_posts.json left untouched.")
        sys.exit(2)

    OUTPUT_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nWrote {OUTPUT_PATH} ({total} posts)")


if __name__ == "__main__":
    asyncio.run(main())
