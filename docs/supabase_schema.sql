-- Crisis Radar — ตาราง state ถาวร (แทนไฟล์ data/*.json ที่หายตอน container restart)
--
-- วิธีใช้: Supabase Dashboard > SQL Editor > New query > วางทั้งไฟล์นี้ > Run
--
-- ทำไม 1 ตาราง key-value ไม่ normalize:
--   ของที่เก็บคือ "ก้อน state ของแอป" 7 ก้อน ไม่ใช่ข้อมูลที่ต้อง query/join/รายงาน
--   (โค้ดอ่านทั้งก้อนแล้วเขียนกลับทั้งก้อนอยู่แล้ว — ดู src/state.py)
--   normalize เป็นตารางต่อ entity = เพิ่มงาน migration ทุกครั้งที่ field เปลี่ยน โดยไม่ได้อะไรกลับมา
--   ถ้าวันหนึ่งอยากทำรายงานย้อนหลังจริง ๆ ค่อยแตก view/ตารางจาก jsonb ทีหลังได้

create table if not exists public.app_state (
  key        text primary key,
  value      jsonb       not null,
  updated_at timestamptz not null default now()
);

comment on table public.app_state is
  'Crisis Radar runtime state — 1 แถวต่อ 1 ไฟล์เดิมใน data/ (overrides, archive, alerts_sent, monitor_latest, monitor_history, llm_cache, post_urls_cache)';

-- อัปเดตเวลาให้เองทุกครั้งที่เขียนทับ — ใช้ดูว่า state ตัวไหนนิ่งไปนานผิดปกติ (ระบบพัง?)
create or replace function public.app_state_touch()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end $$;

drop trigger if exists app_state_touch on public.app_state;
create trigger app_state_touch
  before update on public.app_state
  for each row execute function public.app_state_touch();

-- ── ความปลอดภัย ──────────────────────────────────────────────────────────────
-- ข้างในมี PII: คอมเมนต์จริง + comment_id ของ Facebook (ระบุตัวคนย้อนได้)
-- เปิด RLS แล้ว **ไม่สร้าง policy เลย** = anon key และ authenticated อ่านไม่ได้เลยแม้แต่แถวเดียว
-- server เข้าถึงผ่าน service_role key ซึ่ง bypass RLS ตามการออกแบบของ Supabase
-- → ห้ามเอา service_role key ไปไว้ฝั่ง frontend เด็ดขาด (มันคือ key ที่ผ่านทุกด่าน)
alter table public.app_state enable row level security;

revoke all on public.app_state from anon, authenticated;
