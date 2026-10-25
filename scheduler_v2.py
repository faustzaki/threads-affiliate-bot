"""
scheduler_v2.py — Cron cycle dengan modul baru (quality gate, angle picker, dst).

GANTI scheduler.py. Yang berubah:

LAMA (scheduler.py):
  - random.sample tanpa memory -> 87% duplikat
  - gak ada quality gate
  - gak kirim gambar ke poster
  - gak ada anti double-post
  - notif cuma di terminal

BARU (scheduler_v2.py):
  - angle_picker: history filter + 40 angle + tema harian
  - quality_gate: tolak caption jelek sebelum dikirim
  - image_pool: rotasi gambar adil
  - publish_guard: anti double-post + publish_unknown
  - notifier: notif Telegram jelas
  - poster: FIXED (image_path beneran dikirim)

Alur tetap SAMA:
  1. Cron generate 2 opsi draft
  2. Kirim ke Telegram buat approval
  3. Lo balas "post 1" / "post 2"
  4. Posting + notif

Cara pakai:
  python scheduler_v2.py Siang
  python scheduler_v2.py Malam
  python scheduler_v2.py --post 1
  python scheduler_v2.py --status
"""

import json
import sqlite3
import sys
import urllib.request
from pathlib import Path
from datetime import datetime, timezone, timedelta

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, NINEROUTER_URL, NINEROUTER_KEY, DEFAULT_MODEL

import angle_picker
import image_pool
import notifier
import publish_guard as pg
from poster import post_to_threads, PostResult
from quality_gate import run_quality_gate
from style_engine import StyleDNA, check_ai_tells

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "affiliate_content.db"
WIB = timezone(timedelta(hours=7))

# ─────────────────────────────────────────────────────────────
# ROTASI PROBABILISTIK (bukan jadwal tetap)
# ─────────────────────────────────────────────────────────────

# Bobot peluang, BUKAN jadwal. Tiap run acak berdasarkan ini.
MODE_WEIGHTS = {
    "text_only":    0.40,
    "random_image": 0.30,
    "affiliate":    0.30,
}

# Peluang skip total (manusia juga gak selalu posting)
SKIP_CHANCE = 0.10

# Auto-post threshold: text-only yang skornya bagus langsung posting
AUTO_POST_MIN_SCORE = 90
AUTO_POST_MAX_AI = 0


def pick_mode(avoid_repeat=None):
    """
    Pilih mode probabilistik, dengan guard biar gak 3x sama berturut-turut.
    avoid_repeat: list mode terakhir (max 2) buat dicek.
    """
    import random
    modes = list(MODE_WEIGHTS.keys())
    weights = list(MODE_WEIGHTS.values())

    for _ in range(10):   # max 10 percobaan
        pick = random.choices(modes, weights=weights, k=1)[0]
        # kalau 2 terakhir sama dengan pick, coba lagi
        if avoid_repeat and len(avoid_repeat) >= 2:
            if avoid_repeat[-1] == avoid_repeat[-2] == pick:
                continue
        return pick

    # fallback kalau gagal terus
    return random.choices(modes, weights=weights, k=1)[0]


def get_recent_modes(limit=2):
    """
    Ambil mode N post terakhir dari DB.
    Mode disimpan di kolom `slot` dengan format 'siang|text_only'.
    """
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT slot FROM cron_proposals
            WHERE status IN ('posted', 'pending')
              AND slot LIKE '%|%'
            ORDER BY id DESC LIMIT ?
        """, (limit,))
        rows = cur.fetchall()
        conn.close()
        out = []
        for (s,) in rows:
            if '|' in (s or ''):
                out.append(s.split('|')[1])
        return list(reversed(out))
    except Exception:
        return []


def should_skip():
    """10% peluang skip — biar gak keliatan robot."""
    import random
    return random.random() < SKIP_CHANCE


# ─────────────────────────────────────────────────────────────
# DB
# ─────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
    CREATE TABLE IF NOT EXISTS cron_proposals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        day_number INTEGER,
        slot TEXT,
        opt1_text TEXT,
        opt2_text TEXT,
        opt1_reply TEXT,
        opt2_reply TEXT,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    return conn


def already_ran_today(slot):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, status FROM cron_proposals
        WHERE lower(slot) = lower(?)
          AND date(created_at, '+7 hours') = date('now', '+7 hours')
    """, (slot,))
    row = cur.fetchone()
    conn.close()
    return row


def save_proposal(slot, opt1, opt2, reply1=None, reply2=None,
                  image_path=None, mode="text_only"):
    conn = get_db()
    cur = conn.cursor()
    # simpan mode di kolom slot: "siang|text_only"
    slot_with_mode = f"{slot}|{mode}"
    cur.execute("""
        INSERT INTO cron_proposals
        (day_number, slot, opt1_text, opt2_text, opt1_reply, opt2_reply, status)
        VALUES (0, ?, ?, ?, ?, ?, 'pending')
    """, (slot_with_mode, opt1, opt2, reply1, reply2))
    pid = cur.lastrowid
    conn.commit()

    if image_path:
        conn.execute("""
            INSERT INTO publish_log (proposal_id, post_type, image_path, status)
            VALUES (?, ?, ?, 'queued')
        """, (pid, mode, image_path))
        conn.commit()
    conn.close()
    return pid


def get_pending():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, opt1_text, opt2_text, opt1_reply, opt2_reply, slot
        FROM cron_proposals WHERE status = 'pending'
        ORDER BY id DESC LIMIT 1
    """)
    row = cur.fetchone()
    conn.close()
    return row


# ─────────────────────────────────────────────────────────────
# GENERATE TEKS
# ─────────────────────────────────────────────────────────────

def generate_text(slot, mode, dna):
    """Generate caption via LLM dengan DNA style."""
    theme = angle_picker.theme_for_day()
    angles = angle_picker.pick_angles(slot, n=2, prefer_theme=theme, verbose=False)

    if not angles:
        return None

    angle_desc = " | ".join(a[1] for a in angles)

    if mode == "affiliate":
        from db import get_next_product_to_post
        prod = get_next_product_to_post()
        if not prod:
            return None

        prompt = f"""Kamu content creator Threads Indonesia yang jujur dan santai.

PRODUK: {prod['name']} ({prod['price']})
DETAIL: {prod['highlights']}

{dna.to_prompt()}

ATURAN KETAT:
1. Gaya STYLING/PAMER, BUKAN review pengalaman (lo belum beli)
2. DILARANG: "udah gue pake X minggu", "beneran adem", "wajib checkout"
3. BOLEH: saran matching, deskripsi bahan dari data produk
4. Tanpa link di caption (link masuk reply)
5. Tanpa em-dash (—)
6. Huruf kecil dominan

Buat 2 opsi berbeda. Format JSON murni:
{{"opt1": "...", "opt2": "..."}}"""
        return _call_llm(prompt), prod
    else:
        prompt = f"""Kamu cewek Gen Z Indonesia yang curhat di Threads.

ANGLE (pilih salah satu, jangan campur):
{angle_desc}

{dna.to_prompt()}

ATURAN:
1. Bahasa percakapan santai, huruf kecil dominan
2. Tanpa em-dash (—)
3. Tanpa kata bot: "racun shopee", "wajib checkout", "link di bio"
4. Tanpa link sama sekali
5. Panjang sesuai DNA di atas

Buat 2 opsi berbeda. Format JSON murni:
{{"opt1": "...", "opt2": "..."}}"""
        return _call_llm(prompt), None


def _call_llm(prompt):
    """
    Panggil LLM. Kalau gagal, return None biar caller bisa fallback.
    """
    try:
        payload = json.dumps({
            "model": DEFAULT_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.92,
        }).encode()

        req = urllib.request.Request(
            f"{NINEROUTER_URL}/chat/completions",
            data=payload,
            headers={"Authorization": f"Bearer {NINEROUTER_KEY}",
                     "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = resp.read().decode("utf-8")
    except Exception as e:
        print(f"[llm] gagal konek: {type(e).__name__}: {str(e)[:100]}")
        return None

    # ekstrak JSON
    import re
    if raw.strip().startswith("{"):
        try:
            d = json.loads(raw)
            if "choices" in d:
                raw = d["choices"][0]["message"]["content"]
        except Exception:
            pass

    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────
# FALLBACK CAPTIONS — dipakai kalau LLM mati
# ─────────────────────────────────────────────────────────────

FALLBACK_FILE = BASE_DIR / "data" / "fallback_captions.json"


def load_fallback_captions(slot, mode):
    """
    Ambil 2 caption manual yang belum pernah dipakai.

    Format file:
    {
      "siang": [{"opt1": "...", "opt2": "...", "used": false}, ...],
      "malam": [...]
    }
    """
    if not FALLBACK_FILE.exists():
        return None

    try:
        data = json.loads(FALLBACK_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None

    pool = data.get(slot, [])
    unused = [x for x in pool if not x.get("used")]
    if not unused:
        return None

    pick = unused[0]
    # tandai udah dipakai
    pick["used"] = True
    pick["used_at"] = datetime.now(WIB).isoformat()
    FALLBACK_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                             encoding="utf-8")

    return {"opt1": pick.get("opt1", ""), "opt2": pick.get("opt2", "")}


def cmd_fallback_status():
    if not FALLBACK_FILE.exists():
        print("[!] Belum ada fallback captions")
        return 1
    data = json.loads(FALLBACK_FILE.read_text(encoding="utf-8"))
    print(f"\n{'='*55}")
    print(f"  STOK CAPTION MANUAL")
    print(f"{'='*55}")
    for slot in ["siang", "malam"]:
        pool = data.get(slot, [])
        unused = sum(1 for x in pool if not x.get("used"))
        print(f"  {slot:6}: {unused}/{len(pool)} tersedia")
    print(f"\n  File: {FALLBACK_FILE}")
    return 0


# ─────────────────────────────────────────────────────────────
# SIKLUS UTAMA
# ─────────────────────────────────────────────────────────────

def run_cycle(slot="Siang", force=False, force_approval=False, auto_slot=False):
    slot_norm = "siang" if slot.lower().startswith("s") else "malam"

    print(f"\n{'='*65}")
    print(f"  CYCLE {slot.upper()} — {datetime.now(WIB).strftime('%d %b %H:%M')}")
    print(f"{'='*65}")

    # cek udah jalan hari ini?
    # auto_slot = dipanggil cron_wrapper yang udah ngatur jadwal sendiri,
    # jadi gak perlu cek per-slot (bisa 2-3 post sehari)
    if not force and not auto_slot:
        existing = already_ran_today(slot)
        if existing:
            print(f"[skip] Slot {slot} udah jalan hari ini (ID {existing[0]}, status {existing[1]})")
            return 0

    # recovery post nyangkut
    n = pg.recover_stale()
    if n:
        print(f"[recovery] {n} post nyangkut -> publish_unknown")

    # SKIP acak 10% — biar gak keliatan robot
    if not force and should_skip():
        print(f"[skip] Skip acak (10% chance) — hari ini gak posting {slot}")
        return 0

    # tentukan mode secara PROBABILISTIK, bukan rotasi hari
    # + guard: jangan 3x mode sama berturut-turut
    # + GATE: hanya mode yang stoknya siap
    recent = get_recent_modes(2)
    mode = pick_mode(avoid_repeat=recent)

    # GATE STOK — cek apa yang boleh jalan
    try:
        import cek_stok as _stok
        allowed = _stok.allowed_modes()
    except Exception as e:
        print(f"[gate] gagal cek stok: {e} -> anggap text_only aja")
        allowed = ["text_only"]

    if mode not in allowed:
        print(f"[gate] mode '{mode}' gak boleh (stok kosong) -> fallback ke text_only")
        mode = "text_only"

    print(f"[mode] {mode} (probabilistik) | 2 terakhir: {recent or '-'} | allowed: {allowed}")

    # DNA style — deterministik per slot+tanggal
    seed_id = datetime.now(WIB).toordinal() * 2 + (0 if slot_norm == "siang" else 1)
    dna = StyleDNA.for_post(seed_id)
    print(f"[style] {dna}")

    # pilih gambar kalau mode butuh
    image_path = None
    if mode == "random_image":
        picked = image_pool.pick_next(slot=slot_norm, kind="random")
        if picked:
            image_path = picked["path"]
            print(f"[gambar] {picked['rel']} (used {picked['used']}x)")
        else:
            print(f"[gambar] pool {slot_norm} kosong -> fallback text-only")
            mode = "text_only"

    # generate
    print(f"[gen] generate caption...")
    try:
        opts, prod = generate_text(slot_norm, mode, dna)
    except Exception as e:
        print(f"[error] generate gagal: {e}")
        opts, prod = None, None

    # FALLBACK: kalau LLM mati, pakai caption manual dari file
    if not opts:
        print("[fallback] LLM gak tersedia — pakai caption manual")
        opts = load_fallback_captions(slot_norm, mode)
        if not opts:
            print("[error] Gak ada caption manual juga. Berhenti.")
            notifier._send(
                "⚠️ <b>Cron gagal generate</b>\n\n"
                "LLM (9router) gak nyala, dan gak ada caption fallback.\n"
                "Cek: <code>curl http://127.0.0.1:20128/v1/models</code>"
            )
            return 1
        if mode == "affiliate":
            from db import get_next_product_to_post
            prod = get_next_product_to_post()

    opt1 = (opts.get("opt1") or "").strip()
    opt2 = (opts.get("opt2") or "").strip()

    if not opt1 or not opt2:
        print("[error] LLM gak ngasih caption valid")
        return 1

    # quality gate — tolak kalau jelek
    is_aff = (mode == "affiliate")
    reply_link = prod["link"] if (is_aff and prod) else None

    q1 = run_quality_gate(opt1, reply_link, mode, is_aff)
    q2 = run_quality_gate(opt2, reply_link, mode, is_aff)

    ai1, _ = check_ai_tells(opt1)
    ai2, _ = check_ai_tells(opt2)

    print(f"\n[gate] Opsi 1: {q1.score}/100 AI:{ai1} {'✅' if q1.passed else '❌'}")
    if not q1.passed:
        for r in q1.reasons: print(f"         ❌ {r}")
    print(f"[gate] Opsi 2: {q2.score}/100 AI:{ai2} {'✅' if q2.passed else '❌'}")
    if not q2.passed:
        for r in q2.reasons: print(f"         ❌ {r}")

    if not q1.passed and not q2.passed:
        print("\n[!] Kedua opsi ditolak quality gate. Gak dikirim ke Telegram.")
        notifier.notify_quality_rejected(0, mode, q1.reasons + q2.reasons)
        return 2

    # ── AUTO-POST kalau kualitas tinggi ──
    # Syarat: text-only (no image, no affiliate), skor >= 90, AI score 0
    best_opt, best_score, best_ai = (opt1, q1.score, ai1) if q1.score >= q2.score else (opt2, q2.score, ai2)

    auto_ok = (
        mode == "text_only"
        and not image_path
        and not reply_link
        and best_score >= AUTO_POST_MIN_SCORE
        and best_ai <= AUTO_POST_MAX_AI
    )

    if auto_ok and not force_approval:
        print(f"\n[auto-post] Skor {best_score}/100, AI {best_ai} -> langsung posting!")
        pid = save_proposal(slot_norm, best_opt, best_opt, None, None, None, mode)

        def do_post():
            return post_to_threads(main_text=best_opt, reply_text=None, image_path=None)

        result = pg.safe_publish(pid, do_post, mode, None)
        print(f"[auto-post] {result}")

        if result.kind == PostResult.POSTED:
            notifier.notify_posted(
                post_no=pid, post_type="random",
                caption_preview=best_opt,
                has_image=False,
                threads_url=result.url,
            )
            print("[✓] Auto-post sukses + notif terkirim")
            return 0
        elif result.kind == PostResult.FAILED:
            notifier.notify_failed(pid, "random", result.message)
            return 1
        else:
            notifier.notify_unknown(pid, "random", result.message)
            return 3

    # Kalau gak lolos auto-post, kirim ke Telegram buat approval
    if auto_ok and force_approval:
        print(f"\n[manual] Skor tinggi ({best_score}) tapi force_approval aktif -> kirim ke Telegram")
    else:
        print(f"\n[manual] Skor {best_score}/100 (butuh >= {AUTO_POST_MIN_SCORE} buat auto-post) -> kirim ke Telegram")

    # simpan
    pid = save_proposal(slot_norm, opt1, opt2,
                        reply_link if is_aff else None,
                        reply_link if is_aff else None,
                        image_path, mode)

    # kirim Telegram
    send_approval(pid, slot_norm, mode, opt1, opt2, q1, q2, ai1, ai2,
                  prod, image_path, dna)

    print(f"\n[✓] Proposal ID {pid} terkirim ke Telegram")
    return 0


def send_approval(pid, slot, mode, opt1, opt2, q1, q2, ai1, ai2,
                  prod, image_path, dna):
    mode_label = {
        "text_only": "TEXT-ONLY",
        "random_image": "RANDOM + GAMBAR",
        "affiliate": "AFFILIATE",
    }[mode]

    lines = [
        f"🧵 <b>DRAFT {slot.upper()} — {mode_label}</b>",
        f"<i>ID {pid} · {dna.signature()}</i>",
        "",
    ]

    if prod:
        lines.append(f"🛍️ <b>{prod['name']}</b> — {prod['price']}")
        lines.append("")

    if image_path:
        lines.append(f"🖼️ Gambar: <code>{Path(image_path).name}</code>")
        lines.append("")

    # opsi 1
    badge1 = "✅" if q1.passed else "❌"
    lines.append(f"1️⃣ <b>Opsi 1</b> {badge1} <i>({q1.score}/100 · AI {ai1})</i>")
    lines.append(f"<code>{opt1}</code>")
    lines.append("")

    # opsi 2
    badge2 = "✅" if q2.passed else "❌"
    lines.append(f"2️⃣ <b>Opsi 2</b> {badge2} <i>({q2.score}/100 · AI {ai2})</i>")
    lines.append(f"<code>{opt2}</code>")
    lines.append("")

    if prod:
        lines.append(f"🔗 Link (masuk reply): {prod['link']}")
        lines.append("")

    lines.append("👉 Balas <code>post 1</code> atau <code>post 2</code>")
    lines.append("👉 Atau <code>skip</code> buat buang draft ini")

    notifier._send("\n".join(lines))


# ─────────────────────────────────────────────────────────────
# POSTING (setelah approval)
# ─────────────────────────────────────────────────────────────

def post_selected(option_num):
    row = get_pending()
    if not row:
        print("[!] Gak ada draft pending")
        return 1

    pid, opt1, opt2, rep1, rep2, slot = row
    if option_num == 1:
        text, reply = opt1, rep1
    else:
        text, reply = opt2, rep2

    if not text:
        print(f"[!] Opsi {option_num} kosong")
        return 1

    # cari gambar dari publish_log
    conn = pg.get_db()
    cur = conn.cursor()
    cur.execute("SELECT image_path FROM publish_log WHERE proposal_id = ? LIMIT 1", (pid,))
    r = cur.fetchone()
    conn.close()
    image_path = r[0] if r and r[0] else None

    post_type = "affiliate" if reply else "random"

    print(f"\n[*] Posting opsi {option_num} (ID {pid})")
    print(f"    tipe  : {post_type}")
    print(f"    gambar: {image_path or 'tidak ada'}")

    # quality gate final
    qr = run_quality_gate(text, reply, post_type, bool(reply))
    if not qr.passed:
        print(f"[!] Ditolak gate: {qr.reasons}")
        notifier.notify_quality_rejected(pid, post_type, qr.reasons)
        return 2

    def do_post():
        return post_to_threads(main_text=text, reply_text=reply,
                               image_path=image_path)

    result = pg.safe_publish(pid, do_post, post_type, image_path)
    print(f"[hasil] {result}")

    # notif
    if result.kind == PostResult.POSTED:
        if image_path:
            image_pool.mark_used(image_path, result.url)
            # LIFECYCLE: kalau gambar udah habis masa pakai -> pindah arsip
            kind = "affiliate" if post_type == "affiliate" else "random"
            retired, reason = image_pool.retire_if_exhausted(image_path, kind=kind)
            if retired:
                print(f"[arsip] gambar {reason}")
        if post_type == "affiliate":
            # update rotasi katalog
            from db import mark_product_posted
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cur = conn.cursor()
            cur.execute("""UPDATE affiliate_catalog
                           SET post_count = post_count + 1,
                               last_posted_at = CURRENT_TIMESTAMP
                           WHERE instr(?, affiliate_link) > 0""", (reply,))
            conn.commit()
            conn.close()

        notifier.notify_posted(
            post_no=pid, post_type=post_type,
            caption_preview=text,
            has_image=bool(image_path),
            link_in_reply=bool(reply),
            threads_url=result.url,
        )
        return 0

    elif result.kind == PostResult.FAILED:
        notifier.notify_failed(pid, post_type, result.message,
                               image_path=image_path)
        return 1
    else:
        notifier.notify_unknown(pid, post_type, result.message)
        return 3


def cmd_status():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, slot, status, substr(opt1_text,1,50), created_at
        FROM cron_proposals
        WHERE date(created_at, '+7 hours') >= date('now', '-2 days', '+7 hours')
        ORDER BY id DESC LIMIT 10
    """)
    rows = cur.fetchall()
    conn.close()

    print(f"\n{'='*75}")
    print(f"  STATUS CRON (2 hari terakhir)")
    print(f"{'='*75}\n")
    print(f"  {'ID':>3} {'Slot':7} {'Status':16} {'Caption':40}")
    print(f"  {'-'*72}")
    for pid, slot, status, prev, _ in rows:
        print(f"  {pid:>3} {slot:7} {status:16} {(prev or '')[:40]}")

    print(f"\n  Pool: {image_pool.stats()}")

    unver = pg.get_unverified_posts()
    if unver:
        print(f"\n  ⚠️ {len(unver)} post perlu cek manual (publish_unknown)")

    print(f"\n  Angle pool health:")
    for s in ["siang", "malam"]:
        h = angle_picker.pool_health(s)
        print(f"    {s:6}: {h['fresh']}/{h['total']} fresh — cukup {h['days_left']} hari {h['status']}")
    return 0


def cmd_simulate(n=100):
    """Simulasi rotasi 100 hari — buktiin gak keliatan bot."""
    import random
    print(f"\n{'='*60}")
    print(f"  SIMULASI {n} POST — distribusi mode & skip")
    print(f"{'='*60}\n")

    counts = {"text_only": 0, "random_image": 0, "affiliate": 0, "skip": 0}
    history = []
    for _ in range(n):
        if should_skip():
            counts["skip"] += 1
            history.append("skip")
        else:
            m = pick_mode(avoid_repeat=history[-2:])
            counts[m] += 1
            history.append(m)

    print(f"  {'Mode':16} {'Jumlah':>7} {'%':>7}  {'Target':>8}")
    print(f"  {'-'*44}")
    for mode, target in [("text_only", 40), ("random_image", 30), ("affiliate", 30)]:
        pct = counts[mode] / n * 100
        print(f"  {mode:16} {counts[mode]:>7} {pct:>6.1f}%  {target:>7}%")
    print(f"  {'skip':16} {counts['skip']:>7} {counts['skip']/n*100:>6.1f}%  {'10':>7}%")
    print(f"\n  Total: {n} run")

    # cek apakah ada pola berulang
    print(f"\n  {'='*44}")
    print(f"  TES ANTI-POLA: 20 run berturut-turut")
    print(f"  {'='*44}")
    seq = []
    hist = []
    for _ in range(20):
        if should_skip():
            seq.append("S")
            hist.append("skip")
        else:
            m = pick_mode(avoid_repeat=hist[-2:])
            seq.append({"text_only": "T", "random_image": "G", "affiliate": "A"}[m])
            hist.append(m)
    print(f"  {''.join(seq)}")
    print(f"  (T=text, G=gambar, A=affiliate, S=skip)")

    # cek ada pola berulang yang beneran (bukan sekadar kebetulan statistik)
    # Random sejati memang punya pengulangan 3-huruf sesekali. Yang bahaya:
    # pola PANJANG berulang, atau pola sama berturut-turut.
    print(f"\n  ANALISIS POLA:")
    # 1. ada 3 mode sama berturut-turut?
    triples = 0
    for i in range(len(seq)-2):
        if seq[i] == seq[i+1] == seq[i+2]:
            triples += 1
    # 2. ada siklus pendek berulang (ABAB / ABCABC)?
    cycles = 0
    for plen in (2, 3, 4):
        for i in range(len(seq) - plen*2):
            if seq[i:i+plen] == seq[i+plen:i+plen*2]:
                cycles += 1

    print(f"    3 sama berturut-turut : {triples}  {'✅' if triples == 0 else '⚠️'}")
    print(f"    Siklus pendek berulang: {cycles}  {'✅' if cycles <= 2 else '⚠️'}")

    # 3. bandingkan dengan random sejati
    import random as _r
    true_random = [_r.choice("TGA") for _ in range(len(seq))]
    tr_dupes = len([1 for i in range(len(true_random)-2)
                    if len(set(true_random[i:i+3])) < 3])
    our_dupes = len([1 for i in range(len(seq)-2)
                     if len(set(seq[i:i+3])) < 3])
    print(f"    Pola 3-huruf (ada yang sama): kita {our_dupes}, random sejati {tr_dupes}")

    verdict = triples == 0 and cycles <= 2
    print(f"\n  {'✅ RANDOM — gak keliatan bot' if verdict else '⚠️ Perlu dicek'}")
    return 0


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]

    if not args:
        print(__doc__)
        return 0

    if args[0] == "--post":
        return post_selected(int(args[1]))
    if args[0] == "--status":
        return cmd_status()
    if args[0] == "--fallback":
        return cmd_fallback_status()
    if args[0] == "--simulate":
        return cmd_simulate()
    if args[0] == "--force":
        slot = args[1] if len(args) > 1 else "Siang"
        return run_cycle(slot, force=True, force_approval="--approval" in args,
                         auto_slot="--auto-slot" in args)

    slot = args[0]
    force = "--force" in args
    return run_cycle(slot, force=force, force_approval="--approval" in args,
                     auto_slot="--auto-slot" in args)


if __name__ == "__main__":
    sys.exit(main())
