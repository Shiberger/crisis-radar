"""ดึงคอมเมนต์ Facebook ด้วย Playwright + session login ของคุณเอง (fallback ฟรี).

⚠️ ข้อจำกัดที่ต้องรู้ (เขียนตรง ๆ):
  - เปราะ: FB เปลี่ยน DOM/selector บ่อย → ต้องคอยปรับ selector
  - ผิด ToS ของ FB ถ้าใช้เชิงอัตโนมัติหนัก ๆ → ใช้เฉพาะ prototype ปริมาณน้อย
  - ต้องมี session ที่ล็อกอินแล้ว (storage_state.json) — อย่าฝัง user/pass ในโค้ด

วิธีเตรียม session (ทำครั้งเดียว):
  python -m playwright install chromium
  python - <<'PY'
  from playwright.sync_api import sync_playwright
  with sync_playwright() as p:
      b = p.chromium.launch(headless=False)
      ctx = b.new_context()
      page = ctx.new_page(); page.goto("https://www.facebook.com/login")
      input("ล็อกอินในหน้าต่างที่เปิด แล้วกด Enter ที่นี่...")
      ctx.storage_state(path="fb_state.json")   # เก็บ session
  PY

จากนั้น scrape:  scrape_page_comments(url, storage_state="fb_state.json")

แนะนำ: ใช้ Apify (facebook_apify.py) เป็นหลัก. Playwright ไว้เผื่อไม่มีงบ Apify.
"""
from __future__ import annotations

import hashlib
import time
from datetime import datetime


def _cid(text: str, i: int) -> str:
    return "c_" + hashlib.sha1(f"{i}:{text}".encode("utf-8")).hexdigest()[:10]


def scrape_page_comments(
    url: str,
    storage_state: str = "fb_state.json",
    max_scrolls: int = 8,
    headless: bool = True,
    post_id: str = "pw_1",
) -> list[dict]:
    """คืน list ของ comment dict (fixture schema). best-effort — ตรวจ selector ก่อนใช้จริง."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise ImportError("ต้อง `pip install playwright` และ `python -m playwright install chromium`") from e

    comments: list[dict] = []
    seen: set[str] = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context(storage_state=storage_state, locale="th-TH")
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(4)

        # เลื่อนหน้าเพื่อโหลดคอมเมนต์เพิ่ม
        for _ in range(max_scrolls):
            page.mouse.wheel(0, 3000)
            time.sleep(2)
            # พยายามกด "ดูความคิดเห็นเพิ่มเติม" (ข้อความอาจเปลี่ยนตามภาษา)
            for label in ("ดูความคิดเห็นเพิ่มเติม", "View more comments", "ดูเพิ่มเติม"):
                try:
                    page.get_by_text(label, exact=False).first.click(timeout=1500)
                    time.sleep(1)
                except Exception:
                    pass

        # ดึงกล่องคอมเมนต์ — FB ใช้ role=article ซ้อน. heuristic: เก็บ text ที่ยาวพอ
        # NOTE: selector นี้อาจต้องปรับตามโครง DOM ปัจจุบันของ FB
        blocks = page.query_selector_all('div[role="article"]')
        for i, b in enumerate(blocks):
            try:
                txt = (b.inner_text() or "").strip()
            except Exception:
                continue
            # กรอง: ยาวพอ + ไม่ซ้ำ (ตัด header/ปุ่ม)
            body = txt.split("\n")[-1].strip() if txt else ""
            if len(body) < 4 or body in seen:
                continue
            seen.add(body)
            comments.append({
                "comment_id": _cid(body, i),
                "post_id": post_id,
                "author": (txt.split("\n")[0].strip() or "unknown")[:60],
                "text": body,
                "created_at": datetime.now().isoformat(),
                "reach": 0,   # Playwright ดึง like count ยาก — ตั้ง 0 (Apify ได้ครบกว่า)
            })
        browser.close()

    return comments
