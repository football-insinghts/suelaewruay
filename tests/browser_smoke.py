"""Optional local browser QA using an existing Edge installation; no API calls."""
from pathlib import Path
from getpass import getpass
import os
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dist"
OUT.mkdir(exist_ok=True)
MEMBER_PASSWORD = os.getenv("ZANI_TEST_MEMBER_PASSWORD") or getpass("Member password for local browser QA: ")


def enter_history(page):
    page.get_by_label("ประวัติ: เก่าสุด → ล่าสุด", exact=True).fill("1 2 0 7 1 8 2 8 6 4 9 7 9 6 6 5 5 4 8 8 8")
    page.get_by_label("ประวัติ: เก่าสุด → ล่าสุด", exact=True).press("Tab")
    page.get_by_role("button", name="ยืนยันประวัติ", exact=True).click()


def login(page):
    expect(page.get_by_label("รหัสผ่าน", exact=True)).to_be_visible(timeout=30000)
    page.get_by_label("รหัสผ่าน", exact=True).fill(MEMBER_PASSWORD)
    page.get_by_role("button", name="เข้าสู่ระบบ →", exact=True).click()
    expect(page.get_by_role("heading", name="อ่านประวัติ · เทียบสูตร · วางแผน")).to_be_visible(timeout=30000)
    expect(page.get_by_label("Gemini API key ใหม่", exact=True)).to_have_count(0)
    expect(page.get_by_label("Gemini model", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="หลังบ้าน", exact=True)).to_have_count(0)
    # Deterministic smoke checks use local formulas, without making any paid API request.
    ai_toggle = page.get_by_role("switch", name="ให้ AI ช่วยเลือกจาก 5 สูตรอันดับแรก")
    if ai_toggle.is_enabled():
        ai_toggle.uncheck()

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1200})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto("http://127.0.0.1:8502", wait_until="domcontentloaded")
    login(page)
    expect(page.get_by_role("heading", name="อ่านประวัติ · เทียบสูตร · วางแผน")).to_be_visible(timeout=30000)
    enter_history(page)
    expect(page.get_by_text("ยืนยันแล้ว 21 งวด", exact=False)).to_be_visible()
    page.get_by_role("button", name="วิเคราะห์สูตรและคำนวณ 20 งวด →", exact=True).click()
    expect(page.get_by_role("button", name="☰", exact=True)).to_be_visible(timeout=30000)
    expect(page.get_by_text("03 / PLAN & EVIDENCE", exact=True)).to_have_count(0)
    expect(page.get_by_role("tab")).to_have_count(0)
    expect(page.get_by_text("อันดับหนึ่งจากผลทดสอบย้อนหลัง", exact=True)).to_be_visible()
    expect(page.locator(".recommend-name")).to_have_text("เว้น 1-7-9")
    expect(page.locator(".analysis-result-footer")).to_contain_text("สูตร: 34")
    page.locator(".st-key-analysis-panel").screenshot(path=str(OUT / "preview-analysis-desktop.png"))
    expect(page.locator(".st-key-bankroll-panel")).to_have_count(0)
    expect(page.get_by_label("ทุนเริ่มต้น (บาท)", exact=True)).not_to_be_visible()
    expect(page.get_by_text("มีข้อมูลทดสอบเพียง", exact=False)).to_have_count(0)
    page.get_by_role("button", name="☰", exact=True).click()
    page.get_by_label("เงินต่อเลข (บาท)", exact=True).fill("10")
    page.get_by_label("เงินต่อเลข (บาท)", exact=True).press("Tab")
    expect(page.locator(".st-key-bankroll-menu-content")).to_contain_text("รวม 7 เลข = 7.00 บาทต่อรอบ")
    expect(page.get_by_label("ทุนเริ่มต้น (บาท)", exact=True)).to_have_value("1000.00")
    expect(page.get_by_label("อัตราจ่ายรวมทุนของเลขที่ถูก (เท่า)", exact=True)).to_have_count(0)
    page.get_by_role("button", name="บันทึก", exact=True).click()
    expect(page.locator(".st-key-bankroll-menu-content")).to_contain_text("รวม 7 เลข = 70.00 บาทต่อรอบ")
    expect(page.locator(".st-key-bankroll-menu-content")).to_contain_text("+29.00 บาท")
    expect(page.locator(".st-key-bankroll-menu-content")).not_to_contain_text("แนะนำพัก")
    expect(page.locator(".st-key-bankroll-menu-content")).not_to_contain_text("เงินลงที่แนะนำ")
    page.locator(".st-key-bankroll-menu-content").screenshot(path=str(OUT / "preview-bankroll-desktop.png"))
    page.keyboard.press("Escape")
    expect(page.locator(".st-key-bankroll-menu-content")).not_to_be_visible()
    page.get_by_test_id("stMain").evaluate("element => element.scrollTop = 0")
    page.screenshot(path=str(OUT / "preview-desktop.png"), full_page=True)
    page.get_by_role("heading", name="กระดานประวัติผล", exact=True).scroll_into_view_if_needed()
    page.screenshot(path=str(OUT / "preview-desktop-road.png"))
    page.get_by_role("button", name="0", exact=True).click()
    expect(page.get_by_text("ยืนยันแล้ว 22 งวด", exact=False)).to_be_visible()
    expect(page.get_by_label("ประวัติ: เก่าสุด → ล่าสุด", exact=True)).to_have_value("1 2 0 7 1 8 2 8 6 4 9 7 9 6 6 5 5 4 8 8 8 0")
    expect(page.get_by_text("บันทึกตรวจผลใหม่หลังวิเคราะห์", exact=True)).to_be_visible()
    page.get_by_role("button", name="วิเคราะห์สูตรและคำนวณ 20 งวด →", exact=True).click()
    expect(page.get_by_text("ผลงวดล่าสุด 0", exact=True)).to_be_visible()
    # Verify custom future assumptions update the plan without becoming real history.
    page.get_by_test_id("stSelectbox").click()
    page.get_by_role("option", name="กำหนดผลสมมติ 19 งวดเอง", exact=True).click()
    page.get_by_label("ผลสมมติ 19 ตัว — ไม่ใช่ผลทำนาย").fill("1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9")
    page.get_by_label("ผลสมมติ 19 ตัว — ไม่ใช่ผลทำนาย").press("Tab")
    page.get_by_role("button", name="วิเคราะห์สูตรและคำนวณ 20 งวด →", exact=True).click()
    expect(page.locator(".st-key-bankroll-panel")).to_have_count(0)
    expect(page.get_by_text("ยืนยันแล้ว 22 งวด", exact=False)).to_be_visible()
    # Test CSV download content from the actual browser button.
    with page.expect_download() as download_info:
        page.get_by_role("button", name="ดาวน์โหลดบันทึกผลใหม่", exact=True).click()
    download = download_info.value
    download.save_as(str(OUT / "browser-live-results.csv"))
    import csv
    with (OUT / "browser-live-results.csv").open(encoding="utf-8-sig", newline="") as handle:
        log = list(csv.DictReader(handle))
    assert len(log) == 1
    assert log[0]["ผลจริง"] == "0"
    assert log[0]["งวด"] == "22"
    mobile = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True, device_scale_factor=1)
    mobile.on("pageerror", lambda error: errors.append(str(error)))
    mobile.goto("http://127.0.0.1:8502", wait_until="domcontentloaded")
    login(mobile)
    expect(mobile.get_by_role("heading", name="อ่านประวัติ · เทียบสูตร · วางแผน")).to_be_visible(timeout=30000)
    enter_history(mobile)
    mobile.get_by_role("button", name="วิเคราะห์สูตรและคำนวณ 20 งวด →", exact=True).click()
    expect(mobile.get_by_role("tab")).to_have_count(0)
    expect(mobile.get_by_text("บันทึกตรวจผลใหม่หลังวิเคราะห์", exact=True)).to_be_visible()
    expect(mobile.locator(".st-key-bankroll-panel")).to_have_count(0)
    mobile.locator(".st-key-analysis-panel").screenshot(path=str(OUT / "preview-analysis-mobile.png"))
    mobile.get_by_role("button", name="☰", exact=True).click()
    expect(mobile.get_by_label("ทุนเริ่มต้น (บาท)", exact=True)).to_be_visible()
    mobile.get_by_label("ทุนเริ่มต้น (บาท)", exact=True).fill("2500")
    mobile.get_by_role("button", name="บันทึก", exact=True).click()
    expect(mobile.locator(".st-key-bankroll-menu-content")).to_contain_text("ทุนเริ่มต้น 2,500 บาท")
    mobile.locator(".st-key-bankroll-menu-content").screenshot(path=str(OUT / "preview-bankroll-mobile.png"))
    mobile.keyboard.press("Escape")
    mobile.get_by_test_id("stMain").evaluate("element => element.scrollTop = 0")
    mobile.screenshot(path=str(OUT / "preview-mobile.png"))
    mobile.get_by_role("button", name="0", exact=True).scroll_into_view_if_needed()
    mobile.screenshot(path=str(OUT / "preview-mobile-road.png"))
    digit_boxes = [mobile.get_by_role("button", name=str(digit), exact=True).bounding_box() for digit in range(10)]
    assert len({round(box['y']) for box in digit_boxes}) == 2, "Mobile number entry should use two rows"
    overflow = mobile.evaluate("document.documentElement.scrollWidth > window.innerWidth")
    assert not overflow, "Mobile page has horizontal overflow"
    assert not errors, errors
    print("Browser QA passed: desktop, manual history, actual 0, custom scenario, live-results CSV, hidden plan section, mobile, no JS errors")
    browser.close()
