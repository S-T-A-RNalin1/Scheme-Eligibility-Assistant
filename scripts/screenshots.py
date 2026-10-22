"""Capture UI screenshots for the report and slides (needs the server on :8000 and Microsoft Edge).

File names decide figure order and captions: screen_<n>_<caption_words>.png
"""
import time
from datetime import date, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).absolute().parent.parent
IMG = ROOT / "docs" / "img"
BASE = "http://127.0.0.1:8000"
creds = dict(line.strip().split("=", 1) for line in (ROOT / ".env.demo").read_text().splitlines() if "=" in line)
STILL = ("document.documentElement.style.scrollBehavior='auto';"
         "document.querySelectorAll('.reveal').forEach(e => e.classList.add('in'));"
         "document.querySelectorAll('.login-card, .rec, .res, .msg, .hero-inner').forEach(e => e.style.animation = 'none');")


def settle(pg, ms=500):
    pg.evaluate(STILL)
    pg.wait_for_timeout(ms)


def at(pg, selector, offset=78):
    pg.evaluate(f"scrollTo(0, document.querySelector('{selector}').getBoundingClientRect().top + scrollY - {offset})")
    pg.wait_for_timeout(450)


def hide_toast(pg):
    pg.evaluate("document.getElementById('toast') && document.getElementById('toast').classList.add('hidden')")


def ask(pg, q):
    n = pg.locator(".msg.bot").count()
    pg.fill("#chat-q", q)
    pg.click("#chat-form button")
    pg.wait_for_function(f"(() => {{ const m = document.querySelectorAll('.msg.bot')[{n}]; return m && !m.textContent.includes('Searching'); }})()",
                         timeout=20000)
    pg.wait_for_timeout(2600)


PROFILE_TEXT = {"age": "29", "annual_income": "90000"}
PROFILE_SEL = {"state": "Assam", "is_bpl": "true", "occupation": "weaver", "is_citizen": "true",
               "is_income_tax_payer": "false", "gender": "female"}

for old in IMG.glob("screen_*.png"):
    old.unlink()

with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge", headless=True)
    pg = b.new_page(viewport={"width": 1360, "height": 860}, device_scale_factor=1.25)

    pg.goto(BASE + "/")
    pg.wait_for_selector("#f-age")
    pg.evaluate("localStorage.clear()")
    pg.goto(BASE + "/")
    pg.wait_for_selector("#f-age")
    settle(pg, 700)
    pg.screenshot(path=str(IMG / "screen_1_home_page.png"))

    # Login page (citizen tab), then register a citizen
    pg.goto(BASE + "/login?next=/%23tracker")
    pg.wait_for_selector(".role-tabs")
    settle(pg)
    pg.screenshot(path=str(IMG / "screen_2_separate_citizen_and_admin_login.png"))
    pg.click(".mode[data-mode=register]")
    pg.fill("#lg-name", "Meena Das"); pg.fill("#lg-email", f"meena{int(time.time())}@example.com"); pg.fill("#lg-pass", "password123")
    pg.click("#lg-submit")
    pg.wait_for_url("**/#tracker")
    pg.wait_for_selector("#f-age")
    settle(pg)

    # Eligibility results with ranked recommendations
    for k, v in PROFILE_TEXT.items():
        pg.fill(f"#f-{k}", v)
    for k, v in PROFILE_SEL.items():
        pg.select_option(f"#f-{k}", v)
    pg.click("#profile-form button[type=submit]")
    pg.wait_for_selector("#recs .rec [data-save]")
    settle(pg, 1000)
    for i in range(2):
        pg.locator("#recs .rec").nth(i).locator("[data-save]").click()
        pg.wait_for_timeout(700)
    hide_toast(pg)
    at(pg, "#recs", 74)
    pg.screenshot(path=str(IMG / "screen_3_recommendations_and_results.png"))

    # Grounded answers
    at(pg, "#ask")
    ask(pg, "Am I eligible for Atal Pension Yojana?")
    ask(pg, "atal yojna")
    pg.evaluate("document.getElementById('chat-log').scrollTop = 0")
    at(pg, "#ask")
    pg.screenshot(path=str(IMG / "screen_4_grounded_answers.png"))

    # Application tracker: tick a document, mark applied, deadline in 2 days
    pg.wait_for_selector("#tr-list .app-card")
    card = pg.locator("#tr-list .app-card").last
    slug = card.get_attribute("data-app")
    card.locator("[data-doc]").first.check(); pg.wait_for_timeout(700)
    card = pg.locator(f'#tr-list .app-card[data-app="{slug}"]')
    card.locator("[data-a-status]").select_option("applied"); pg.wait_for_timeout(700)
    card = pg.locator(f'#tr-list .app-card[data-app="{slug}"]')
    card.locator("[data-a-deadline]").fill((date.today() + timedelta(days=2)).isoformat())
    card.locator("[data-a-deadline]").dispatch_event("change"); pg.wait_for_timeout(1000)
    hide_toast(pg)
    at(pg, "#tracker")
    pg.screenshot(path=str(IMG / "screen_5_application_tracker.png"))

    # Grievance
    pg.evaluate("loadGrievances()")
    pg.wait_for_selector("#grv-app:not(.hidden)")
    pg.wait_for_timeout(500)
    pg.fill("#grv-scheme", "Atal Pension Yojana")
    pg.select_option("#grv-category", "application_status")
    pg.fill("#grv-subject", "Application not processed")
    pg.fill("#grv-desc", "I submitted my APY application at the bank two months ago and have had no response.")
    pg.click("#grv-form button")
    pg.wait_for_selector("#grv-list .grv")
    pg.wait_for_timeout(600)
    ticket = pg.locator("#grv-list .grv").first.get_attribute("data-ticket")
    pg.locator("#grv-list .grv details").first.evaluate("d => d.open = true")
    hide_toast(pg)
    at(pg, "#grievances")
    pg.screenshot(path=str(IMG / "screen_6_grievance_portal.png"))

    # Admin: coverage gap analytics, grievance queue
    pg.click("#logout-btn"); pg.wait_for_timeout(600)
    pg.goto(BASE + "/login?role=admin")
    pg.wait_for_selector("#lg-email")
    pg.fill("#lg-email", "admin@example.org"); pg.fill("#lg-pass", creds["admin@example.org"])
    pg.click("#lg-submit")
    pg.wait_for_url("**/admin")
    pg.wait_for_selector("#cov-regions table")
    pg.wait_for_selector("#cov-map path.leaflet-interactive", timeout=20000)
    pg.wait_for_timeout(2500)
    settle(pg)
    at(pg, ".cov-cols", 74)
    pg.wait_for_timeout(800)
    pg.screenshot(path=str(IMG / "screen_7_coverage_gap_analytics_admin.png"))

    card = pg.locator(f'#gq-list .grv[data-ticket="{ticket}"]')
    card.locator("details").evaluate("d => d.open = true")
    card.locator("[data-gq-status]").select_option("resolved")
    card.locator("[data-gq-note]").fill("Bank confirmed your enrolment; your PRAN has been issued.")
    card.locator("[data-gq-save]").click()
    pg.wait_for_timeout(1300)
    pg.locator(f'#gq-list .grv[data-ticket="{ticket}"] details').evaluate("d => d.open = true")
    hide_toast(pg)
    at(pg, "#grievance-queue")
    pg.screenshot(path=str(IMG / "screen_8_grievance_queue_admin.png"))
    b.close()
print("screenshots saved to", IMG)
