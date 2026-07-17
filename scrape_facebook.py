#!/usr/bin/env python3
"""Crisis Radar — ตัวดึงคอมเมนต์ Facebook จริง (รัน local).

ดึง → normalize เป็น fixture schema → (option) รัน pipeline ต่อทันที

ตัวอย่าง:
  # 1) เตรียม token ก่อน
  export APIFY_TOKEN=xxxx

  # 2) ดึงเฉพาะเพจ public (demo ปลอดภัยสุด) 30 คอมเมนต์/โพสต์ แล้วรัน pipeline เลย
  python scrape_facebook.py --method apify --only page --max-posts 10 --max-comments 30 --run

  # 3) ดูโครง raw item ตัวแรก (ไว้แก้ field mapping ถ้า actor เปลี่ยน)
  python scrape_facebook.py --method apify --only page --inspect

  # 4) รวมกลุ่มด้วย (ต้องเป็นสมาชิก + ใส่ cookie — ดู docs/SCRAPING.md)
  FB_COOKIES_JSON=fb_cookies.json python scrape_facebook.py --method apify --run

  # 5) ไม่มีงบ Apify → ใช้ Playwright + session ตัวเอง (เฉพาะเพจ)
  python scrape_facebook.py --method playwright --only page --run

ผลลัพธ์: data/facebook_live_<brand>.json  (เอาไปใช้ต่อ: python run_demo.py --fixture <ไฟล์นั้น>)
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from src.env import load_dotenv

ROOT = Path(__file__).parent
TARGETS_FILE = ROOT / "data" / "targets.json"
load_dotenv()   # อ่าน APIFY_TOKEN / FB_COOKIES_JSON จาก .env (ถ้ามี)


def load_cookies() -> list | None:
    path = os.environ.get("FB_COOKIES_JSON")
    if path and Path(path).exists():
        return json.loads(Path(path).read_text(encoding="utf-8"))
    return None


def scrape_apify(targets, cfg, args) -> list[dict]:
    from src.sources.facebook_apify import ApifyFacebookScraper
    scraper = ApifyFacebookScraper(cookies=load_cookies())
    all_comments: list[dict] = []
    for t in targets:
        if t["type"] == "group" and not scraper.cookies:
            print(f"  [ข้าม] {t['name']} — กลุ่ม private ต้องใส่ FB_COOKIES_JSON ก่อน")
            continue
        all_comments += scraper.scrape_target(t, args.max_posts, args.max_comments)
    return all_comments


def scrape_playwright(targets, cfg, args) -> list[dict]:
    from src.sources.facebook_playwright import scrape_page_comments
    all_comments: list[dict] = []
    for i, t in enumerate(targets, 1):
        print(f"  [playwright] {t['name']} …")
        all_comments += scrape_page_comments(t["url"], post_id=f"{t['type']}_{i}",
                                             headless=not args.show)
    return all_comments


def inspect_apify(targets, args) -> None:
    """ดึง raw item ตัวแรกมาโชว์ ไว้ตรวจ/ปรับ field mapping."""
    from src.sources.facebook_apify import ApifyFacebookScraper, COMMENTS_ACTOR
    scraper = ApifyFacebookScraper(cookies=load_cookies())
    urls = scraper.get_post_urls(targets[0]["url"], 1)
    if not urls:
        print("ไม่เจอโพสต์ — เพจอาจต้อง cookie หรือ actor เปลี่ยน input"); return
    raw = scraper._run(COMMENTS_ACTOR, {"startUrls": [{"url": urls[0]}], "resultsLimit": 1})
    print("RAW comment item ตัวแรก (คีย์ที่มี):")
    print(json.dumps(raw[0] if raw else {}, ensure_ascii=False, indent=2)[:1500])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--method", choices=["apify", "playwright"], default="apify")
    ap.add_argument("--only", choices=["page", "group", "all"], default="all",
                    help="เลือกดึงเฉพาะเพจ / กลุ่ม / ทั้งหมด")
    ap.add_argument("--max-posts", type=int, default=10)
    ap.add_argument("--max-comments", type=int, default=30)
    ap.add_argument("--inspect", action="store_true", help="ดู raw item ตัวแรก (แก้ field mapping)")
    ap.add_argument("--show", action="store_true", help="playwright: เปิด browser ให้เห็น (ไม่ headless)")
    ap.add_argument("--run", action="store_true", help="รัน pipeline ต่อทันทีหลัง scrape")
    args = ap.parse_args()

    cfg = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
    brand = cfg["brand"]
    targets = cfg["targets"]
    if args.only != "all":
        targets = [t for t in targets if t["type"] == args.only]

    if args.inspect:
        inspect_apify(targets, args); return

    print(f"[scrape] method={args.method} · เป้าหมาย {len(targets)} · brand={brand}")
    comments = scrape_apify(targets, cfg, args) if args.method == "apify" else scrape_playwright(targets, cfg, args)
    print(f"[scrape] รวม {len(comments)} คอมเมนต์")

    out = {
        "_note": f"LIVE scrape ({args.method}) — ดิบก่อน mask PII (mask ตอนเข้า pipeline)",
        "page": cfg.get("page_name", brand),
        "page_id": cfg.get("page_id", brand),
        "brand": brand,
        "comments": comments,
    }
    out_path = ROOT / "data" / f"facebook_live_{brand}.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[scrape] เขียน {out_path}")

    if args.run and comments:
        from run_demo import run_pipeline
        print("\n[pipeline] รันต่อบน data จริง…\n")
        run_pipeline(out_path, brand=brand)
    elif args.run:
        print("[pipeline] ไม่มีคอมเมนต์ให้รัน — เช็ก token/cookie/selector")


if __name__ == "__main__":
    main()
