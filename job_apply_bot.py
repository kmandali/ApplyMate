import asyncio
import json
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse, parse_qs

from playwright.async_api import async_playwright, Page, Locator

# ==============================
# EDIT THIS SECTION
# ==============================
CONFIG = {
    "email": "youremail@gmail.com",
    "phone": "+1 555 555 555",
    "first_name": "FiirstName",
    "last_name": "LastName",
    "linkedin": "https://www.linkedin.com/in/yourname/",
    "website": "https://your-site.com",
    "city": "San Francisco",
    "state": "CA",
    "country": "United States",
    "work_authorization": "Yes",
    "requires_visa_sponsorship": "No",
    "years_of_experience": "7",
    "resume_path": "./resume.pdf",
    "cover_letter_path": "./cover_letter.pdf",  # optional
    "job_links": [
        "https://www.linkedin.com/jobs/search/?currentJobId=",
        "https://www.linkedin.com/jobs/search/?currentJobId",
        "https://www.linkedin.com/jobs/search/?currentJobId,
        "https://www.joblinks",
    ],
    # Modes:
    # review   -> fills what it can, then pauses for you to inspect and submit
    # cautious -> attempts next/apply/submit only on very high-confidence buttons
    "mode": "review",
    # If true, uses existing Chrome profile so you stay logged in.
    "use_persistent_profile": True,
    # Change this to your local Chrome user-data dir.
    # Mac default path. For Windows use: r"~\AppData\Local\Google\Chrome\User Data"
    # For Linux use: "~/.config/google-chrome"
    "chrome_user_data_dir": os.path.expanduser("~/Library/Application Support/Google/Chrome"),
    # Slow motion helps with debugging.
    "slow_mo_ms": 150,
    # How long to wait for pages/elements.
    "timeout_ms": 12000,
}

# ==============================
# UTILITIES
# ==============================

def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def exists(path: str) -> bool:
    return bool(path) and Path(path).expanduser().exists()


FIELD_MAP = {
    "first name": lambda c: c["first_name"],
    "given name": lambda c: c["first_name"],
    "last name": lambda c: c["last_name"],
    "family name": lambda c: c["last_name"],
    "full name": lambda c: f"{c['first_name']} {c['last_name']}",
    "name": lambda c: f"{c['first_name']} {c['last_name']}",
    "email": lambda c: c["email"],
    "phone": lambda c: c["phone"],
    "mobile": lambda c: c["phone"],
    "linkedin": lambda c: c["linkedin"],
    "website": lambda c: c["website"],
    "portfolio": lambda c: c["website"],
    "city": lambda c: c["city"],
    "state": lambda c: c["state"],
    "country": lambda c: c["country"],
    "work authorization": lambda c: c["work_authorization"],
    "authorized to work": lambda c: c["work_authorization"],
    "visa": lambda c: c["requires_visa_sponsorship"],
    "sponsorship": lambda c: c["requires_visa_sponsorship"],
    "experience": lambda c: c["years_of_experience"],
    "years of experience": lambda c: c["years_of_experience"],
}


async def safe_text(locator: Locator) -> str:
    try:
        return (await locator.inner_text()).strip()
    except Exception:
        return ""


async def try_fill(locator: Locator, value: str) -> bool:
    try:
        await locator.scroll_into_view_if_needed()
        await locator.fill("")
        await locator.fill(value)
        return True
    except Exception:
        return False


async def try_check(locator: Locator) -> bool:
    try:
        await locator.scroll_into_view_if_needed()
        await locator.check()
        return True
    except Exception:
        try:
            await locator.click()
            return True
        except Exception:
            return False


async def click_first(page: Page, selectors: List[str]) -> bool:
    for sel in selectors:
        try:
            locator = page.locator(sel).first
            if await locator.count() > 0:
                await locator.scroll_into_view_if_needed()
                await locator.click(timeout=2000)
                return True
        except Exception:
            pass
    return False


def normalize_job_url(url: str) -> str:
    parsed = urlparse(url)

    if "linkedin.com" in parsed.netloc and "/jobs/search/" in parsed.path:
        current_job_id = parse_qs(parsed.query).get("currentJobId", [None])[0]
        if current_job_id:
            return f"https://www.linkedin.com/jobs/view/{current_job_id}/"

    return url


async def label_for_input(page: Page, input_el: Locator) -> str:
    try:
        input_id = await input_el.get_attribute("id")
        if input_id:
            label = page.locator(f'label[for="{input_id}"]').first
            if await label.count() > 0:
                txt = await safe_text(label)
                if txt:
                    return txt
    except Exception:
        pass

    try:
        parent_label = input_el.locator("xpath=ancestor::label[1]").first
        if await parent_label.count() > 0:
            txt = await safe_text(parent_label)
            if txt:
                return txt
    except Exception:
        pass

    for attr in ["aria-label", "placeholder", "name"]:
        try:
            val = await input_el.get_attribute(attr)
            if val:
                return val
        except Exception:
            pass
    return ""


async def fill_common_inputs(page: Page, config: Dict[str, str]) -> Dict[str, int]:
    filled = 0
    seen = 0

    text_like = page.locator(
        'input:not([type="hidden"]):not([type="file"]):not([type="checkbox"]):not([type="radio"]), textarea'
    )
    count = await text_like.count()

    for i in range(count):
        el = text_like.nth(i)
        seen += 1
        try:
            disabled = await el.get_attribute("disabled")
            readonly = await el.get_attribute("readonly")
            value = await el.input_value()
            if disabled is not None or readonly is not None or value.strip():
                continue
        except Exception:
            continue

        label = normalize(await label_for_input(page, el))
        if not label:
            continue

        chosen_value: Optional[str] = None
        for key, getter in FIELD_MAP.items():
            if key in label:
                chosen_value = getter(config)
                break

        if chosen_value:
            ok = await try_fill(el, chosen_value)
            if ok:
                filled += 1
                log(f'Filled field "{label}"')

    return {"seen": seen, "filled": filled}


async def upload_documents(page: Page, config: Dict[str, str]) -> int:
    uploads = 0
    file_inputs = page.locator('input[type="file"]')
    count = await file_inputs.count()

    for i in range(count):
        el = file_inputs.nth(i)
        label = normalize(await label_for_input(page, el))
        target = None

        if any(k in label for k in ["resume", "cv"]):
            if exists(config["resume_path"]):
                target = str(Path(config["resume_path"]).expanduser())
        elif "cover" in label:
            if exists(config["cover_letter_path"]):
                target = str(Path(config["cover_letter_path"]).expanduser())
        elif count == 1 and exists(config["resume_path"]):
            target = str(Path(config["resume_path"]).expanduser())

        if target:
            try:
                await el.set_input_files(target)
                uploads += 1
                log(f"Uploaded file to: {label or 'unlabeled file input'}")
            except Exception:
                pass

    return uploads


async def select_common_options(page: Page, config: Dict[str, str]) -> int:
    changed = 0

    # Selects
    selects = page.locator("select")
    for i in range(await selects.count()):
        el = selects.nth(i)
        label = normalize(await label_for_input(page, el))
        try:
            if "country" in label:
                await el.select_option(label=config["country"])
                changed += 1
            elif "work authorization" in label or "authorized" in label:
                await el.select_option(label=config["work_authorization"])
                changed += 1
            elif "sponsorship" in label or "visa" in label:
                await el.select_option(label=config["requires_visa_sponsorship"])
                changed += 1
        except Exception:
            pass

    # Radios / checkboxes where wording is obvious.
    radio_and_checkbox = page.locator('input[type="radio"], input[type="checkbox"]')
    for i in range(await radio_and_checkbox.count()):
        el = radio_and_checkbox.nth(i)
        label = normalize(await label_for_input(page, el))
        if not label:
            continue
        want_yes = False
        want_no = False

        if "authorized" in label or "work authorization" in label:
            want_yes = normalize(config["work_authorization"]) in {"yes", "true"}
        elif "visa" in label or "sponsorship" in label:
            want_yes = normalize(config["requires_visa_sponsorship"]) in {"yes", "true"}
            want_no = not want_yes
        else:
            continue

        try:
            if want_yes and any(x in label for x in ["yes", "true"]):
                if await try_check(el):
                    changed += 1
            elif want_no and any(x in label for x in ["no", "false"]):
                if await try_check(el):
                    changed += 1
        except Exception:
            pass

    return changed


async def maybe_start_application(page: Page) -> bool:
    selectors = [
        'button:has-text("Easy Apply")',
        'button:has-text("Apply")',
        'a:has-text("Apply")',
        'a:has-text("Apply for this job")',
        'button:has-text("Apply for this job")',
        'button:has-text("Submit Application")',
        'a:has-text("Apply now")',
        'button:has-text("Apply now")',
        'a:has-text("Apply to Job")',
        'button:has-text("Apply to Job")',
    ]
    clicked = await click_first(page, selectors)
    if clicked:
        log("Opened application flow.")
        await page.wait_for_timeout(2000)
    return clicked


async def maybe_advance(page: Page, mode: str) -> int:
    if mode != "cautious":
        return 0

    steps = 0
    for _ in range(4):
        clicked = await click_first(
            page,
            [
                'button:has-text("Next")',
                'button:has-text("Continue")',
                'button:has-text("Review")',
                'button:has-text("Submit")',
                'button:has-text("Submit Application")',
            ],
        )
        if not clicked:
            break
        steps += 1
        log("Advanced application flow.")
        await page.wait_for_timeout(1500)
        await fill_common_inputs(page, CONFIG)
        await upload_documents(page, CONFIG)
        await select_common_options(page, CONFIG)
    return steps


async def ensure_page(context, page: Optional[Page] = None) -> Page:
    try:
        if page and not page.is_closed():
            return page
    except Exception:
        pass
    return await context.new_page()


async def handle_job(context, page: Page, url: str, config: Dict[str, str]):
    normalized_url = normalize_job_url(url)
    result = {
        "url": url,
        "normalized_url": normalized_url,
        "opened_application": False,
        "filled_fields": 0,
        "uploads": 0,
        "option_changes": 0,
        "advance_steps": 0,
        "status": "unknown",
    }

    page = await ensure_page(context, page)
    log(f"Opening {normalized_url}")
    await page.goto(normalized_url, wait_until="domcontentloaded", timeout=config["timeout_ms"])
    await page.wait_for_timeout(2500)

    result["opened_application"] = await maybe_start_application(page)
    fill_stats = await fill_common_inputs(page, config)
    result["filled_fields"] = fill_stats["filled"]
    result["uploads"] = await upload_documents(page, config)
    result["option_changes"] = await select_common_options(page, config)
    result["advance_steps"] = await maybe_advance(page, config["mode"])

    if config["mode"] == "review":
        result["status"] = "ready_for_review"
        log("Paused for manual review. Submit it yourself after checking.")
        input("Press Enter to continue to the next job... ")
    else:
        result["status"] = "attempted_autofill"
        await page.wait_for_timeout(1500)

    return result, page


async def build_browser(p):
    headless = False
    if CONFIG["use_persistent_profile"]:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=CONFIG["chrome_user_data_dir"],
            headless=headless,
            slow_mo=CONFIG["slow_mo_ms"],
        )
        page = context.pages[0] if context.pages else await context.new_page()
        return context, page
    else:
        browser = await p.chromium.launch(headless=headless, slow_mo=CONFIG["slow_mo_ms"])
        context = await browser.new_context()
        page = await context.new_page()
        return context, page


async def main() -> None:
    missing = []
    if not exists(CONFIG["resume_path"]):
        missing.append("resume_path")
    if CONFIG.get("cover_letter_path") and CONFIG["cover_letter_path"] and not exists(CONFIG["cover_letter_path"]):
        log("cover_letter_path does not exist; continuing without it.")

    if missing:
        raise FileNotFoundError(f"Missing required files/config: {', '.join(missing)}")

    results = []
    async with async_playwright() as p:
        context, page = await build_browser(p)
        try:
            for link in CONFIG["job_links"]:
                try:
                    result, page = await handle_job(context, page, link, CONFIG)
                    results.append(result)
                except Exception as e:
                    log(f"Error on {link}: {e}")
                    results.append({"url": link, "status": f"error: {e}"})
                    try:
                        page = await ensure_page(context, page)
                    except Exception:
                        pass
        finally:
            out = Path("job_apply_results.json")
            out.write_text(json.dumps(results, indent=2))
            log(f"Saved run results to {out.resolve()}")
            log("Run complete.")
            try:
                if page and not page.is_closed():
                    input("Press Enter to close the browser and exit... ")
            except Exception:
                pass


if __name__ == "__main__":
    asyncio.run(main())

"""
HOW TO USE
==========
1) Install Python 3.10+.
2) Install Playwright:
   pip install playwright
   playwright install chromium
3) Put your resume PDF in the same folder and update CONFIG.
4) Add the job links you want in CONFIG['job_links'].
5) Log in manually to LinkedIn / the ATS once if needed.
6) Run:
   python job_apply_bot.py

NOTES
=====
- This script is intentionally conservative. "review" mode fills data and pauses before submission.
- Different ATS systems (Greenhouse, Lever, Workday, Ashby, LinkedIn Easy Apply) have different HTML, so some forms will need custom selectors.
- Many sites use anti-bot checks, CAPTCHAs, custom widgets, or dynamic questions. Expect to handle those manually.
- For a safer workflow, keep auto-submit OFF until you've tested on a few roles.
- You should only use this where the application answers are truthful and reviewed by you.
"""
