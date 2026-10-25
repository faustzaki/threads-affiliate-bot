import datetime
import json
import sqlite3
import urllib.request
from pathlib import Path
from config import NINEROUTER_URL, NINEROUTER_KEY, DEFAULT_MODEL, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "affiliate_content.db"

WARMUP_START_DATE = datetime.date(2026, 10, 18)

def get_current_day():
    today = datetime.date.today()
    delta = (today - WARMUP_START_DATE).days + 1
    return max(1, delta)

def get_db():
    conn = sqlite3.connect(DB_PATH)
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

def generate_warmup_options(day: int, slot: str) -> dict:
    from generator import ANGLES_SIANG, ANGLES_MALAM, FORMAT_STYLES, LENGTHS, HOOKS, extract_content_from_resp
    import random

    angles_pool = ANGLES_MALAM if slot.lower() == "malam" else ANGLES_SIANG
    angle1, angle2 = random.sample(angles_pool, 2)
    fmt1, fmt2 = random.sample(FORMAT_STYLES, 2)
    len1, len2 = random.sample(LENGTHS, 2)
    hook1, hook2 = random.sample(HOOKS, 2)

    if slot.lower() == "malam":
        time_context = (
            "KONTEKS WAKTU: MALAM HARI (Jam santai kos/rumah, 19:00 - 22:30 WIB).\n"
            "TOPIK WAJIB BERNUANSA MALAM: Baru balik kos/rumah abis macet-macetan jalanan, mandi air anget, rebahan kasur ganti celana gombrang/daster ternyaman, "
            "scrolling toko oren sebelum tidur (compare rating toko tengah malam tapi checkout jedai/kunciran), nonton mukbang mie pedes pas laper malam, "
            "skincare malam, atau dilema 'besok ngantor/kuliah pake baju apa ya' padahal baju selemari penuh.\n"
            "DILARANG KERAS: Membahas panas terik matahari siang bolong, keluar makan siang, atau jam kantor siang."
        )
    else:
        time_context = (
            "KONTEKS WAKTU: SIANG HARI (Jam istirahat makan siang / kerja kampus, 11:30 - 14:00 WIB).\n"
            "TOPIK WAJIB BERNUANSA SIANG: Panas matahari terik pas keluar cari makan siang, baju gerah dan lepek, "
            "celana kulot/loose pants yang ga begah buat duduk lama di kantor/kelas, kemeja ga gampang kusut kena helm/ojol, "
            "food coma & ngantuk berat jam 2 siang di meja kerja butuh es kopi/es teh manis segar, atau adu nasib menu makan siang.\n"
            "DILARANG KERAS: Membahas begadang ampe subuh, rebahan kasur malam hari, atau overthinking sebelum tidur."
        )

    prompt = f"""Kamu adalah cewek Gen Z Indonesia yang aktif curhat di Threads.
Buatkan 2 OPSI postingan organik Threads tanpa link untuk pemanasan hari ke-{day}.

{time_context}

ATURAN ANTI-TEMPLATE & ANTI-BOT (WAJIB DIPATUHI):
1. JANGAN JADIKAN SEPERTI TEMPLATE:
   - DILARANG memaksakan kata klise seperti 'in this economy', 'war is over', 'trapped heat', atau 'flowy' di setiap postingan! Gunakan bahasa percakapan cewek asli yang spontan, santai, dan bervariasi.
   - JANGAN selalu buka dengan 'YA ALLAHHH' atau 'kalian sadar ga sih'. Buat pembuka yang segar, ceplas-ceplos, atau langsung ke cerita.
2. VARIASI TOPIK & FORMAT: Opsi 1 dan Opsi 2 HARUS memiliki gaya dan vibe yang kontras (misal: satu ceplas-ceplos dialog singkat, satu lagi curhat observasi santai).
3. VARIASI EMOTICON: Maksimal 1 emoticon, atau bahkan TANPA EMOT sama sekali jika gaya tulisannya sarkas/datar/deadpan. Bebas gunakan variasi: 🫠, 😭, 💀, 🥹, wkwk, kwkwk, zzzz.
4. Gaya: Dominan huruf kecil (lowercase). Singkatan santai (pdhl, bgt, lgsg, co, sm, kyk, gausa, nyari, bat).
5. TANPA LINK SAMA SEKALI (zero link).
6. DILARANG kata-kata bot: "racun shopee", "wajib checkout", "spill racun", "link di bio", "murce bgt say".

KONFIGURASI OPSI:
- Opsi 1: Format [{fmt1}], sudut pandang [{angle1}], panjang [{len1}], gaya pembuka [{hook1}].
- Opsi 2: Format [{fmt2}], sudut pandang [{angle2}], panjang [{len2}], gaya pembuka [{hook2}].

Kembalikan HANYA format JSON murni:
{{
  "opt1": "teks opsi 1",
  "opt2": "teks opsi 2"
}}"""

    payload = json.dumps({
        "model": DEFAULT_MODEL,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.92
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{NINEROUTER_URL}/chat/completions",
        data=payload,
        headers={"Authorization": f"Bearer {NINEROUTER_KEY}", "Content-Type": "application/json"}
    )

    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8")
        text = extract_content_from_resp(raw)

        import re
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        return json.loads(text)

def run_cron_cycle(slot_name: str = "Siang", force: bool = False):
    day = get_current_day()
    conn = get_db()

    cur = conn.cursor()
    if not force:
        cur.execute("""
        SELECT id FROM cron_proposals
        WHERE lower(slot) = lower(?) AND date(created_at, '+7 hours') = date('now', '+7 hours')
        """, (slot_name,))
        existing = cur.fetchone()
        if existing:
            print(f"[*] Slot {slot_name} sudah dijalankan hari ini (Prop ID: {existing[0]}). Skip.")
            conn.close()
            return

    if day <= 7:
        # FASE PEMANASAN (WARM-UP)
        print(f"[*] Menjalankan Cron: Hari ke-{day}/7 (Pemanasan - {slot_name})")
        opts = generate_warmup_options(day, slot_name)
        opt1 = opts.get("opt1", "")
        opt2 = opts.get("opt2", "")

        from generator import build_warmup_image_prompt
        img_info = build_warmup_image_prompt(opt1, slot=slot_name)

        cur = conn.cursor()
        cur.execute("""
        INSERT INTO cron_proposals (day_number, slot, opt1_text, opt2_text, status)
        VALUES (?, ?, ?, ?, 'pending')
        """, (day, slot_name, opt1, opt2))
        prop_id = cur.lastrowid
        conn.commit()

        if img_info and img_info.get("prompt"):
            ref_badge = img_info.get("ref_note", "Pakai Foto Referensi")
            prompt_block = (
                f"📸 <b>PROMPT GAMBAR NANO BANANA:</b>\n"
                f"💡 <i>Instruksi: {ref_badge}</i>\n"
                f"<code>{img_info['prompt']}</code>\n\n"
            )
        else:
            prompt_block = "💬 <i>Format: Post murni teks (tanpa gambar) untuk variasi natural feed.</i>\n\n"

        # Format pesan Telegram
        message = (
            f"🧵 <b>[PEMANASAN HARI {day}/7] DRAFT THREADS ({slot_name.upper()})</b>\n\n"
            f"<i>Fase pemanasan akun: Nol link affiliate agar reputasi akun naik.</i>\n\n"
            f"1️⃣ <b>Opsi 1:</b>\n"
            f"<code>{opt1}</code>\n\n"
            f"2️⃣ <b>Opsi 2:</b>\n"
            f"<code>{opt2}</code>\n\n"
            f"{prompt_block}"
            f"👉 <b>Cara Post Otomatis:</b>\n"
            f"Balas dengan <code>post 1</code> atau <code>post 2</code> untuk langsung diterbitkan ke Threads."
        )
    else:
        # FASE AFFILIATE (HARI 8+)
        print(f"[*] Menjalankan Cron: Hari ke-{day} (Fase Affiliate - {slot_name})")
        from generator import generate_threads_copy
        from db import get_next_product_to_post

        prod = get_next_product_to_post()
        if not prod:
            prod = {
                "id": None,
                "name": "Loose Pants Celana Kulot Highwaist Linen",
                "price": "Rp55.000",
                "highlights": "cuttingan rapi, bahan jatuh, adem, aman buat paha besar",
                "link": "https://s.shopee.co.id/9zycTvmkpq"
            }

        sample_product = prod
        res = generate_threads_copy(
            product_name=sample_product["name"],
            price=sample_product["price"],
            highlights=sample_product["highlights"],
            affiliate_link=sample_product["link"]
        )
        opt1_main = res.get("main_post", "")
        opt1_reply = res.get("reply_post", "")
        img_prompt = res.get("image_prompt", "")

        cur = conn.cursor()
        cur.execute("""
        INSERT INTO cron_proposals (day_number, slot, opt1_text, opt1_reply, status)
        VALUES (?, ?, ?, ?, 'pending')
        """, (day, slot_name, opt1_main, opt1_reply))
        prop_id = cur.lastrowid
        conn.commit()

        message = (
            f"👗 <b>[AFFILIATE HARI {day}] DRAFT PRODUK ({slot_name.upper()})</b>\n\n"
            f"📦 <b>Produk:</b> {sample_product['name']} (~{sample_product['price']})\n\n"
            f"📝 <b>POST UTAMA:</b>\n"
            f"<code>{opt1_main}</code>\n\n"
            f"💬 <b>REPLY TOKO (Affiliate):</b>\n"
            f"<code>{opt1_reply}</code>\n\n"
            f"📸 <b>PROMPT GAMBAR NANO BANANA:</b>\n"
            f"💡 <i>Instruksi: Tanpa Referensi — Muka Ketutup HP</i>\n"
            f"<code>{img_prompt}</code>\n\n"
            f"👉 <b>Cara Post Otomatis:</b>\n"
            f"Balas dengan <code>post affiliate</code> untuk langsung publish main post + reply link ke Threads."
        )

    # Kirim ke Telegram
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode())
        print(f"[✓] Draft dikirim ke Telegram (Prop ID: {prop_id}), Status: {data.get('ok')}")

    conn.close()

    # Otomatis acak jadwal slot ini untuk hari berikutnya (anti-bot footprint)
    randomize_next_schedule(slot_name)

def randomize_next_schedule(slot: str):
    import subprocess
    import random
    
    JOB_ID_SIANG = "3e03e57512e7"
    JOB_ID_MALAM = "0bfe006bb1f4"

    try:
        if slot.lower() == "siang":
            # Siang slot acak jadwal Malam hari ini (19:10 to 20:45 WIB)
            r = random.randint(0, 95)
            if r <= 49:
                hr = 19
                mn = 10 + r
            else:
                hr = 20
                mn = r - 50
            cron_expr = f"{mn} {hr} * * *"
            res = subprocess.run(["hermes", "cron", "edit", "--schedule", cron_expr, JOB_ID_MALAM], capture_output=True, text=True)
            print(f"[✓] Auto-randomized tonight's Malam schedule: {cron_expr} ({hr:02d}:{mn:02d} WIB)")

        elif slot.lower() == "malam":
            # Malam slot acak jadwal Siang besok (11:45 to 13:10 WIB)
            r = random.randint(0, 85)
            if r <= 14:
                hr = 11
                mn = 45 + r
            elif r <= 74:
                hr = 12
                mn = r - 15
            else:
                hr = 13
                mn = r - 75
            cron_expr = f"{mn} {hr} * * *"
            res = subprocess.run(["hermes", "cron", "edit", "--schedule", cron_expr, JOB_ID_SIANG], capture_output=True, text=True)
            print(f"[✓] Auto-randomized tomorrow's Siang schedule: {cron_expr} ({hr:02d}:{mn:02d} WIB)")
    except Exception as e:
        print(f"[!] Warning: Gagal randomize schedule: {e}")

def post_selected_proposal(option_num: int = 1) -> bool:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
    SELECT id, opt1_text, opt2_text, opt1_reply, opt2_reply
    FROM cron_proposals
    WHERE status = 'pending'
    ORDER BY id DESC LIMIT 1
    """)
    row = cur.fetchone()
    if not row:
        print("[!] Tidak ada draft pending di database.")
        conn.close()
        return False

    prop_id, opt1_text, opt2_text, opt1_reply, opt2_reply = row
    if option_num == 1:
        main_text = opt1_text
        reply_text = opt1_reply
    else:
        main_text = opt2_text
        reply_text = opt2_reply

    print(f"[*] Posting pilihan {option_num} (Prop ID: {prop_id})...")
    from poster import post_to_threads
    success = post_to_threads(main_text=main_text, reply_text=reply_text)

    if success:
        cur.execute("UPDATE cron_proposals SET status = 'posted' WHERE id = ?", (prop_id,))
        conn.commit()
        # Jika postingan affiliate (ada reply_text), update rotasi di database catalog
        if reply_text and "s.shopee.co.id" in reply_text:
            try:
                from db import DB_PATH
                import sqlite3
                conn_cat = sqlite3.connect(DB_PATH)
                conn_cat.execute("""
                UPDATE affiliate_catalog
                SET post_count = post_count + 1, last_posted_at = CURRENT_TIMESTAMP
                WHERE instr(?, affiliate_link) > 0
                """, (reply_text,))
                conn_cat.commit()
                conn_cat.close()
                print("[✓] Rotasi katalog diperbarui di database!")
            except Exception as e:
                print(f"[!] Warning update catalog: {e}")
        print(f"[✓] Berhasil mempublikasikan opsi {option_num} ke Threads!")

    conn.close()
    return success

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == "--post":
        opt = int(sys.argv[2])
        post_selected_proposal(opt)
    else:
        slot = sys.argv[1] if len(sys.argv) > 1 else "Siang"
        force = "--force" in sys.argv
        run_cron_cycle(slot, force=force)
