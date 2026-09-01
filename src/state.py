"""ชั้นเก็บ state ถาวร — ไฟล์ local (ค่าเริ่มต้น) หรือ Supabase (เมื่อตั้ง env ครบ).

ปัญหาที่แก้:
  Render free tier ใช้ filesystem แบบ **ephemeral** — container restart เมื่อไร ไฟล์ใน data/
  หายหมด ผลคือ: ทีมโดนแจ้ง Discord เรื่องเดิมซ้ำ (alerts_sent หาย) · label ที่ทีมแก้เองหายเกลี้ยง
  (overrides หาย) · คลัง "อ่านแล้ว" หาย · จ่าย Apify/Claude ซ้ำเพราะ cache หาย

ทำไมเลือก Supabase:
  - Postgres ฟรี 500MB (state ทั้งหมดของโปรเจกต์นี้ < 1MB) ไม่มีค่ารายเดือน
  - มี PostgREST มาให้ → เรียกผ่าน urllib ธรรมดาได้ **ไม่ต้องเพิ่ม dependency**
    ตรงกับแนวทางเดิมที่ยิง Apify/Anthropic ด้วย stdlib ล้วน (ดู requirements.txt)

สัญญาของโมดูลนี้ — จงใจให้ "เหมือนอ่าน/เขียนไฟล์" เพื่อให้จุดเรียกใช้แทบไม่ต้องแก้:
    data = read_json(STORE, default={})
    write_json(STORE, data, indent=1)
key ใน Supabase มาจากชื่อไฟล์ (STORE.stem) เช่น data/overrides.json → key "overrides"
→ เทสที่สลับ STORE ไปไฟล์ temp ยังทำงานเหมือนเดิม (โหมดไฟล์) โดยไม่ต้องแก้อะไร

ตั้งค่าผ่าน env (ดู .env.example):
  SUPABASE_URL            https://<project-ref>.supabase.co
  SUPABASE_SERVICE_KEY    Secret key (sb_secret_... — ชื่อเดิมคือ service_role) ต้อง bypass RLS ได้
                          เพราะตาราง app_state เปิด RLS แบบไม่มี policy · อยู่ฝั่ง server เท่านั้น
                          **ห้ามใช้ Publishable key (anon เดิม)** — จะอ่านไม่ได้สักแถว
  SUPABASE_TABLE          ชื่อตาราง (ค่าเริ่มต้น app_state) — schema อยู่ที่ docs/supabase_schema.sql
  STATE_BACKEND           auto (ค่าเริ่มต้น) | file | supabase
  STATE_NAMESPACE         prefix ของ key — แยก staging/production ใน project เดียวกัน
  STATE_CACHE_TTL_SEC     กัน read ยิงเน็ตทุกครั้งที่หน้าเว็บ poll (ค่าเริ่มต้น 30 วินาที)

**ล้มเหลวแล้วต้องไม่พังทั้งระบบ**: ต่อ Supabase ไม่ได้ → คืนค่าที่ cache ไว้ (ถ้ามี) ไม่งั้นคืน
default แล้วเขียน log — พฤติกรรมเท่ากับ "ไฟล์หาย" ซึ่งทุกจุดที่เรียกรับมือได้อยู่แล้ว
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

from .env import ssl_context

TABLE_DEFAULT = "app_state"
CACHE_TTL_DEFAULT = 30       # วินาที
TIMEOUT = 8                  # วินาที — ช้ากว่านี้ถือว่าล่ม ไม่ให้รอบตรวจ/หน้าเว็บค้างตาม
WRITE_RETRIES = 2            # เขียนพลาด = ข้อมูลหาย → ลองใหม่ (เจอ 5xx/เน็ตสะดุด)
READ_RETRIES = 0             # อ่านพลาดมีของสำรอง (cache) → อย่าให้คนที่เปิดหน้าเว็บรอนาน
OUTAGE_BACKOFF = 20          # วินาที — Supabase ล่มแล้วพักการ "อ่าน" ไว้ก่อน (ดู _OUTAGE_UNTIL)

# key ทั้งหมดที่ระบบใช้ (ชื่อ = stem ของไฟล์เดิมใน data/) — CLI ข้างล่างใช้ตอน push/pull
KEYS = ("overrides", "archive", "alerts_sent", "monitor_latest", "monitor_history",
        "llm_cache", "post_urls_cache")

_CACHE: dict[str, tuple[float, str]] = {}    # key → (เวลาที่อ่านมา, ตัว JSON ดิบ)
_CACHE_LOCK = threading.Lock()
_LOG_ONCE: set[str] = set()

# วงจรตัดตอน: Supabase ล่มทีนึงมักล่มยาว ไม่ใช่แค่ request เดียว — ถ้าปล่อยให้ทุก read ไปรอ
# timeout เอง หน้าเว็บที่ poll ทุก 5 วิจะค้างสะสมกันเป็นแถว (แต่ละ read บล็อกได้ถึง TIMEOUT วิ)
# → ล่มแล้วพัก "การอ่าน" ไว้ OUTAGE_BACKOFF วิ ระหว่างนั้นเสิร์ฟจาก cache ทันที
# **ไม่พักการเขียน** — เขียนพลาดคือข้อมูลหาย ยอมช้ากว่ายอมหาย
_OUTAGE_UNTIL = 0.0


# ───────────────────────── config ─────────────────────────

def _int_env(key: str, default: int) -> int:
    try:
        return int(str(os.environ.get(key, "")).strip() or default)
    except ValueError:
        return default


def _clean_url(raw: str) -> str:
    """รับ URL ได้ทั้ง 2 แบบที่ Dashboard โชว์ — คืนเฉพาะ origin.

    หน้า Settings > Data API โชว์เป็น "https://<ref>.supabase.co/rest/v1" (มี path ติดมา)
    แต่หน้าอื่น/เอกสารเก่าโชว์เป็น "https://<ref>.supabase.co" เฉย ๆ
    ถ้าไม่ตัดให้ จะต่อ path ซ้ำเป็น /rest/v1/rest/v1/... แล้วได้ 404 PGRST125 ที่อ่านไม่ออกว่าพลาดตรงไหน
    """
    url = (raw or "").strip().rstrip("/")
    for suffix in ("/rest/v1", "/rest"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
    return url.rstrip("/")


def config() -> dict:
    """อ่าน env ทุกครั้งที่เรียก — เปลี่ยนค่าแล้วไม่ต้อง restart ตอน dev/test
    (แบบเดียวกับ monitor.config() / alerts.config())."""
    url = _clean_url(os.environ.get("SUPABASE_URL", ""))
    key = (os.environ.get("SUPABASE_SERVICE_KEY", "")
           or os.environ.get("SUPABASE_KEY", "")).strip()
    mode = os.environ.get("STATE_BACKEND", "").strip().lower() or "auto"

    if mode == "file":
        use_supabase = False
    elif mode == "supabase":
        use_supabase = True          # ตั้งใจบังคับ — ถ้า env ไม่ครบให้ error ดัง ๆ ตอนใช้จริง
    else:
        use_supabase = bool(url and key)

    return {
        "backend": "supabase" if use_supabase else "file",
        "url": url,
        "key": key,
        "table": os.environ.get("SUPABASE_TABLE", "").strip() or TABLE_DEFAULT,
        "namespace": os.environ.get("STATE_NAMESPACE", "").strip(),
        "cache_ttl": max(0, _int_env("STATE_CACHE_TTL_SEC", CACHE_TTL_DEFAULT)),
    }


def backend() -> str:
    return config()["backend"]


def status() -> dict:
    """สรุปให้ /api/health — พอให้รู้ว่า state รอดตอน restart ไหม โดยไม่หลุด secret ออกไป."""
    cfg = config()
    out = {"backend": cfg["backend"], "persistent": cfg["backend"] == "supabase"}
    if cfg["backend"] == "supabase":
        out["table"] = cfg["table"]
        if cfg["namespace"]:
            out["namespace"] = cfg["namespace"]
    return out


def key_for(path: Path | str, cfg: dict | None = None) -> str:
    """data/overrides.json → "overrides" (+ prefix ถ้าตั้ง STATE_NAMESPACE)."""
    cfg = cfg or config()
    stem = Path(path).stem
    return f"{cfg['namespace']}:{stem}" if cfg["namespace"] else stem


def _log(msg: str, once_key: str = "") -> None:
    """เขียน log แบบไม่ท่วม — error เดิมซ้ำ ๆ (เช่นเน็ตล่ม) พิมพ์ครั้งเดียวพอ."""
    if once_key:
        if once_key in _LOG_ONCE:
            return
        _LOG_ONCE.add(once_key)
    print(f"[state] {msg}", flush=True)


# ───────────────────────── Supabase (PostgREST ผ่าน urllib) ─────────────────────────

class SupabaseError(RuntimeError):
    pass


def _headers(cfg: dict, extra: dict | None = None) -> dict:
    h = {
        "apikey": cfg["key"],
        "Authorization": f"Bearer {cfg['key']}",
        "Content-Type": "application/json",
    }
    h.update(extra or {})
    return h


def _call(cfg: dict, method: str, path: str, body: Any = None,
          extra_headers: dict | None = None, retries: int = WRITE_RETRIES) -> bytes:
    global _OUTAGE_UNTIL
    if not (cfg["url"] and cfg["key"]):
        raise SupabaseError("ยังไม่ได้ตั้ง SUPABASE_URL / SUPABASE_SERVICE_KEY")

    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(f"{cfg['url']}/rest/v1/{path}", data=data,
                                 headers=_headers(cfg, extra_headers), method=method)
    last = ""
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=ssl_context()) as r:
                out = r.read()
                _OUTAGE_UNTIL = 0.0        # ต่อติดแล้ว → เลิกพัก
                return out
        except urllib.error.HTTPError as e:
            detail = (e.read() or b"")[:200].decode("utf-8", "replace")
            # 4xx = ตั้งค่าผิด (key ผิด / ยังไม่ได้สร้างตาราง) — ลองใหม่ก็ได้ผลเดิม
            # และไม่ใช่ "ล่ม" ด้วย จึงไม่ตั้ง backoff (ไม่งั้นจะกลบ error จริงไปทั้งชุด)
            if e.code < 500:
                raise SupabaseError(f"Supabase ตอบ {e.code}: {detail}") from e
            last = f"{e.code}: {detail}"
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            last = str(e)
        if attempt < retries:
            time.sleep(0.5 * (attempt + 1))
    _OUTAGE_UNTIL = time.time() + OUTAGE_BACKOFF
    raise SupabaseError(f"ต่อ Supabase ไม่ได้: {last}")


def _remote_get(cfg: dict, key: str) -> Optional[str]:
    """คืนตัว JSON ดิบของ value (None = ยังไม่มีแถวนี้)."""
    q = urllib.parse.urlencode({"key": f"eq.{key}", "select": "value", "limit": "1"})
    rows = json.loads(_call(cfg, "GET", f"{cfg['table']}?{q}", retries=READ_RETRIES) or b"[]")
    if not rows:
        return None
    return json.dumps(rows[0].get("value"), ensure_ascii=False)


def _remote_put(cfg: dict, key: str, value: Any) -> None:
    """upsert แถวเดียว — resolution=merge-duplicates ให้ POST ทับของเดิมได้ตาม primary key."""
    _call(cfg, "POST", cfg["table"],
          body=[{"key": key, "value": value}],
          extra_headers={"Prefer": "resolution=merge-duplicates,return=minimal"})


def _remote_delete(cfg: dict, key: str) -> None:
    _call(cfg, "DELETE", f"{cfg['table']}?{urllib.parse.urlencode({'key': f'eq.{key}'})}",
          extra_headers={"Prefer": "return=minimal"})


def ping() -> dict:
    """เช็กว่าต่อได้จริงและตารางมีอยู่ — ใช้ตอนตั้งค่าครั้งแรก/ตรวจสุขภาพ."""
    cfg = config()
    if cfg["backend"] != "supabase":
        return {"ok": True, "backend": "file"}
    t0 = time.time()
    _call(cfg, "GET", f"{cfg['table']}?{urllib.parse.urlencode({'select': 'key', 'limit': '1'})}",
          retries=READ_RETRIES)
    return {"ok": True, "backend": "supabase", "table": cfg["table"],
            "ms": int((time.time() - t0) * 1000)}


# ───────────────────────── cache ─────────────────────────
# เก็บเป็น "ตัว JSON ดิบ" ไม่ใช่ object — read แต่ละครั้ง parse ใหม่ได้ก้อนของตัวเอง
# จุดเรียกใช้แทบทุกที่ทำ read-modify-write (data = load(); data[k] = v; _write(data))
# ถ้าคืน object ตัวเดียวกันจาก cache แล้ว write ล้มเหลว cache จะเพี้ยนตามการแก้ที่ยังไม่ลง DB

def _cache_get(key: str, ttl: int) -> Optional[str]:
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
    if not hit:
        return None
    ts, raw = hit
    return raw if (time.time() - ts) < ttl else None


def _cache_stale(key: str) -> Optional[str]:
    """ค่าที่ cache ไว้แม้หมดอายุ — ใช้ประคองตอน Supabase ล่ม ดีกว่าคืนค่าว่าง."""
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
    return hit[1] if hit else None


def _cache_put(key: str, raw: str) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (time.time(), raw)


def invalidate(path: Path | str | None = None) -> None:
    """ทิ้ง cache (ทั้งหมด หรือเฉพาะ key เดียว) — เทส/CLI ใช้บังคับให้อ่านจากต้นทางใหม่.

    ⚠️ ทิ้งของสำรองที่ใช้ประคองตอน Supabase ล่มไปด้วย — จึงไม่ควรเรียกจากโค้ดรันไทม์
    """
    global _OUTAGE_UNTIL
    _OUTAGE_UNTIL = 0.0
    with _CACHE_LOCK:
        if path is None:
            _CACHE.clear()
        else:
            _CACHE.pop(key_for(path), None)


# ───────────────────────── API ที่จุดอื่นเรียกใช้ ─────────────────────────

def read_json(path: Path | str, default: Any = None) -> Any:
    """อ่าน state 1 ก้อน. อ่านไม่ได้/ยังไม่มี → คืน default (ไม่ raise)."""
    cfg = config()
    if cfg["backend"] == "file":
        try:
            val = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default
        return default if val is None else val   # ให้เท่ากับฝั่ง Supabase: null = ยังไม่มีค่า

    key = key_for(path, cfg)
    raw = _cache_get(key, cfg["cache_ttl"])
    if raw is None and time.time() < _OUTAGE_UNTIL:
        raw = _cache_stale(key)             # กำลังล่มอยู่ → อย่าไปรอ timeout ซ้ำอีก
        if raw is None:
            return default
    if raw is None:
        try:
            raw = _remote_get(cfg, key)
            if raw is None:
                _cache_put(key, "null")     # ยังไม่มีแถว = ข้อเท็จจริงหนึ่ง ควร cache ด้วย
                return default
            _cache_put(key, raw)
        except SupabaseError as e:
            _log(f"อ่าน '{key}' ไม่ได้ ({e}) — ใช้ค่าที่จำไว้ใน memory แทน", once_key=f"read:{key}")
            raw = _cache_stale(key)
            if raw is None:
                return default
    try:
        val = json.loads(raw)
    except json.JSONDecodeError:
        return default
    return default if val is None else val


def write_json(path: Path | str, data: Any, *, indent: int | None = None) -> bool:
    """เขียน state 1 ก้อน. คืน False ถ้าเขียนไม่ลง (ระบบต้องไปต่อได้ด้วย state ใน memory)."""
    cfg = config()
    if cfg["backend"] == "file":
        p = Path(path)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            # เขียนไฟล์ชั่วคราวแล้ว rename — crash กลางคันจะไม่เหลือ JSON พังไว้ให้อ่านรอบหน้า
            tmp = p.with_suffix(p.suffix + ".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=indent), encoding="utf-8")
            os.replace(tmp, p)
            return True
        except OSError:
            return False      # ดิสก์ read-only → ทำงานต่อด้วย state ใน memory (เหมือนเดิม)

    key = key_for(path, cfg)
    try:
        _remote_put(cfg, key, data)
        _cache_put(key, json.dumps(data, ensure_ascii=False))
        return True
    except SupabaseError as e:
        _log(f"เขียน '{key}' ไม่สำเร็จ ({e}) — รอบหน้าจะลองใหม่", once_key=f"write:{key}")
        return False


def delete(path: Path | str) -> bool:
    cfg = config()
    if cfg["backend"] == "file":
        try:
            Path(path).unlink()
            return True
        except OSError:
            return False
    key = key_for(path, cfg)
    try:
        _remote_delete(cfg, key)
        _cache_put(key, "null")
        return True
    except SupabaseError as e:
        _log(f"ลบ '{key}' ไม่สำเร็จ ({e})")
        return False


# ───────────────────────── CLI: ตั้งค่าครั้งแรก / ย้ายข้อมูล / สำรอง ─────────────────────────
#   python3 -m src.state            เช็กว่าต่อ Supabase ได้ไหม + มีอะไรอยู่ในนั้นบ้าง
#   python3 -m src.state --push     อัปไฟล์ใน data/*.json ขึ้น Supabase (ย้ายของเดิมขึ้นครั้งแรก)
#   python3 -m src.state --pull     ดึงจาก Supabase ลงไฟล์ data/*.json (สำรอง/ถอยกลับโหมดไฟล์)

if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from src.env import load_dotenv

    load_dotenv()
    ROOT = Path(__file__).resolve().parent.parent
    DATA = ROOT / "data"
    mode = (sys.argv[1] if len(sys.argv) > 1 else "").lstrip("-")

    cfg = config()
    if cfg["backend"] != "supabase":
        print("❌ ยังไม่ได้ตั้ง SUPABASE_URL / SUPABASE_SERVICE_KEY (หรือตั้ง STATE_BACKEND=file ไว้)")
        print("   ตอนนี้ระบบเก็บ state ลงไฟล์ data/*.json ซึ่งหายตอน container restart บน Render")
        print("   วิธีตั้ง: ดู .env.example หัวข้อ 'เก็บ state ถาวรด้วย Supabase'")
        raise SystemExit(1)

    print(f"🗄  Supabase · {cfg['url']} · ตาราง {cfg['table']}"
          + (f" · namespace {cfg['namespace']}" if cfg["namespace"] else ""))
    try:
        print(f"✅ ต่อได้ ({ping()['ms']} ms)\n")
    except SupabaseError as e:
        print(f"❌ {e}\n")
        print("   ถ้าเป็น 404/42P01 = ยังไม่ได้สร้างตาราง → เอา docs/supabase_schema.sql "
              "ไปวางใน Supabase > SQL Editor > Run")
        raise SystemExit(1)

    if mode == "push":
        for k in KEYS:
            f = DATA / f"{k}.json"
            if not f.exists():
                print(f"  –  {k:<18} ไม่มีไฟล์ในเครื่อง ข้าม")
                continue
            try:
                val = json.loads(f.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                print(f"  ❌ {k:<18} ไฟล์เสีย ({e}) ข้าม")
                continue
            n = len(val) if isinstance(val, (dict, list)) else 1
            print(f"  {'✅' if write_json(f, val) else '❌'} {k:<18} {n} รายการ")
        print("\nเสร็จ — ตั้ง SUPABASE_URL / SUPABASE_SERVICE_KEY บน Render แล้ว deploy ได้เลย")

    elif mode == "pull":
        DATA.mkdir(parents=True, exist_ok=True)
        for k in KEYS:
            f = DATA / f"{k}.json"
            val = read_json(f, default=None)
            if val is None:
                print(f"  –  {k:<18} ยังไม่มีใน Supabase ข้าม")
                continue
            f.write_text(json.dumps(val, ensure_ascii=False, indent=1), encoding="utf-8")
            n = len(val) if isinstance(val, (dict, list)) else 1
            print(f"  ✅ {k:<18} {n} รายการ → {f.relative_to(ROOT)}")
        print("\nเสร็จ — ไฟล์ใน data/ ตรงกับ Supabase แล้ว (มี PII อยู่ข้างใน ห้ามขึ้น git)")

    else:
        for k in KEYS:
            val = read_json(DATA / f"{k}.json", default=None)
            if val is None:
                print(f"  –  {k:<18} (ยังไม่มี)")
            else:
                n = len(val) if isinstance(val, (dict, list)) else 1
                print(f"  ✅ {k:<18} {n} รายการ")
        print("\n--push = อัปไฟล์ในเครื่องขึ้น · --pull = ดึงลงไฟล์")
