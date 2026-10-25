"""
affiliate_flow.py — Alur lengkap: LINK -> GAMBAR -> POST.

Kenyataan yang harus diterima:
  Shopee MEMBLOKIR scraping (verified: og:image gak ada, kena anti-bot).
  Jadi gambar produk TIDAK bisa diambil otomatis dari URL.

Alur yang works:

  ┌─────────────────────────────────────────────────────────────┐
  │ TAHAP 1: INPUT PRODUK (lo, 1 menit per produk)             │
  │                                                             │
  │   python affiliate_flow.py add \                            │
  │     --url "https://shopee.co.id/Produk-i.123.456" \         │
  │     --nama "Kulot Linen" \                                  │
  │     --harga "Rp59.000" \                                    │
  │     --detail "bahan linen, cuttingan jatuh"                 │
  │                                                             │
  │   -> Link affiliate otomatis dibuat                         │
  │   -> Prompt gambar otomatis dibuat                          │
  │   -> Produk masuk katalog dengan status "perlu_gambar"      │
  └─────────────────────────────────────────────────────────────┘
                            ↓
  ┌─────────────────────────────────────────────────────────────┐
  │ TAHAP 2: GENERATE GAMBAR (lo, pakai prompt yang dikasih)   │
  │                                                             │
  │   Script kasih prompt siap pakai. Lo paste ke Nano Banana.  │
  │   Simpan hasil ke: media/inbox/affiliate/{product_id}/      │
  └─────────────────────────────────────────────────────────────┘
                            ↓
  ┌─────────────────────────────────────────────────────────────┐
  │ TAHAP 3: CAPTION (otomatis via vision)                     │
  │                                                             │
  │   python affiliate_flow.py caption --product-id 6           │
  │   -> Baca gambar, tulis caption styling yang nyambung       │
  └─────────────────────────────────────────────────────────────┘
                            ↓
  ┌─────────────────────────────────────────────────────────────┐
  │ TAHAP 4: POST (otomatis)                                   │
  │                                                             │
  │   python affiliate_flow.py post --product-id 6              │
  │   -> Post ke Threads + link di reply + notif Telegram       │
  └─────────────────────────────────────────────────────────────┘
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

import affiliate_link
import image_pool
import notifier
import publish_guard as pg
from poster import post_to_threads, PostResult
from quality_gate import run_quality_gate
from style_engine import StyleDNA

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "affiliate_content.db"
WIB = timezone(timedelta(hours=7))

# ─────────────────────────────────────────────────────────────
# PROMPT GAMBAR AFFILIATE
# ─────────────────────────────────────────────────────────────

# Template prompt berdasarkan kategori produk
IMAGE_PROMPTS = {
    "bawahan": (
        "close-up photo of a hand pulling the fabric of {nama_warna} wide-leg pants, "
        "showing the linen texture and how it stretches, no face, no person, "
        "flat lay on white bedsheet, natural window light, "
        "authentic smartphone photo, slight grain, real fabric wrinkles"
    ),
    "atasan": (
        "close-up photo of {nama_warna} linen shirt fabric held up by two hands, "
        "showing the weave texture and drape, no face, no person, "
        "neutral background, soft natural daylight, "
        "authentic smartphone photo, real fabric detail"
    ),
    "hijab": (
        "close-up photo of {nama_warna} jersey pashmina fabric draped over a hand, "
        "showing the soft texture and how it falls, no face, no person, "
        "white background, natural window light, authentic smartphone photo"
    ),
    "rumahan": (
        "close-up photo of {nama_warna} crinkle fabric set laid flat, "
        "showing the wrinkle texture and material quality, no person, "
        "on white bedsheet, natural daylight, authentic smartphone photo"
    ),
    "outer": (
        "close-up photo of {nama_warna} knit cardigan fabric, "
        "hand touching the knit texture to show softness, no face, no person, "
        "warm indoor light, authentic smartphone photo, real fabric detail"
    ),
}

# Warna yang sering muncul — buat deteksi dari nama produk
COLOR_WORDS = {
    "beige": "beige", "cream": "cream", "putih": "white", "hitam": "black",
    "navy": "navy", "abu": "grey", "coklat": "brown", "hijau": "green",
    "sage": "sage green", "dusty": "dusty pink", "pink": "pink",
    "biru": "blue", "kuning": "yellow", "maroon": "maroon",
}


def detect_color(text):
    """Deteksi warna dari nama produk."""
    low = text.lower()
    for k, v in COLOR_WORDS.items():
        if k in low:
            return v
    return "neutral"


def build_image_prompt(product_name, highlights, category):
    """
    Bikin prompt gambar affiliate.

    Prinsip: TANPA MUKA, close-up produk, realistis, gak ketara AI.
    """
    warna = detect_color(product_name + " " + highlights)
    template = IMAGE_PROMPTS.get(category, IMAGE_PROMPTS["bawahan"])

    prompt = template.format(nama_warna=warna)

    # tambahan dari highlights
    return (
        f"{prompt}. "
        f"Product: {product_name}. "
        f"Details to show: {highlights}. "
        f"--ar 3:4 --no 3d render, cgi, plastic skin, text, watermark, logo, face, person"
    )


# ─────────────────────────────────────────────────────────────
# DB
# ─────────────────────────────────────────────────────────────

def ensure_catalog_columns():
    """Tambah kolom baru kalau belum ada."""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(affiliate_catalog)")
    cols = {r[1] for r in cur.fetchall()}

    new_cols = {
        "image_prompt": "TEXT",
        "image_status": "TEXT DEFAULT 'perlu_gambar'",
        "caption": "TEXT",
        "tema": "TEXT DEFAULT 'fashion'",
    }
    for col, typ in new_cols.items():
        if col not in cols:
            cur.execute(f"ALTER TABLE affiliate_catalog ADD COLUMN {col} {typ}")
            print(f"[db] kolom '{col}' ditambahkan")

    conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────────────
# TAHAP 1: ADD PRODUK
# ─────────────────────────────────────────────────────────────

def cmd_add(url, nama, harga, detail, category, affiliate_id, sub_id="threads"):
    """Tambah produk baru + generate link affiliate + prompt gambar."""
    ensure_catalog_columns()

    # validasi & ekstrak
    pid_info = affiliate_link.extract_product_id(url)
    if not pid_info:
        print(f"[!] Gak bisa ekstrak product ID dari URL: {url}")
        print("    Format harus: shopee.co.id/Nama-Produk-i.{shop_id}.{item_id}")
        return 1

    print(f"\n=== TAMBAH PRODUK ===")
    print(f"  Nama      : {nama}")
    print(f"  Harga     : {harga}")
    print(f"  Shop ID   : {pid_info['shop_id']}")
    print(f"  Item ID   : {pid_info['item_id']}")
    print(f"  Kategori  : {category}")

    # generate link affiliate
    if affiliate_id:
        link = affiliate_link.build_link(
            affiliate_link.normalize_url(url), affiliate_id, sub_id)
        print(f"  Link aff  : {link[:80]}...")
    else:
        link = ""
        print(f"  ⚠️  Link aff: KOSONG (--affiliate-id belum diisi)")
        print(f"      Produk tetap ditambah, tapi lo harus update link nanti")

    # generate prompt gambar
    prompt = build_image_prompt(nama, detail, category)
    print(f"\n  📸 PROMPT GAMBAR:")
    print(f"  {prompt}")

    # simpan ke DB
    conn = sqlite3.connect(DB_PATH, timeout=30)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO affiliate_catalog
        (product_name, price, highlights, origin_url, affiliate_link,
         category, image_prompt, image_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'perlu_gambar')
    """, (nama, harga, detail, url, link, category, prompt))
    new_id = cur.lastrowid
    conn.commit()
    conn.close()

    print(f"\n✅ Produk ditambah dengan ID {new_id}")
    print(f"\n{'='*65}")
    print(f"  LANGKAH BERIKUTNYA")
    print(f"{'='*65}")
    print(f"  1. Generate gambar pakai prompt di atas")
    print(f"  2. Simpan ke: media/inbox/affiliate/{new_id:02d}/")
    print(f"  3. Jalankan: python affiliate_flow.py caption --product-id {new_id}")
    print(f"  4. Jalankan: python affiliate_flow.py post --product-id {new_id}")
    return 0


# ─────────────────────────────────────────────────────────────
# TAHAP 2: LIHAT PROMPT
# ─────────────────────────────────────────────────────────────

def cmd_prompt(product_id=None):
    """Tampilkan prompt gambar buat produk yang belum ada gambarnya."""
    ensure_catalog_columns()
    conn = sqlite3.connect(DB_PATH, timeout=30)
    cur = conn.cursor()

    if product_id:
        cur.execute("""
            SELECT id, product_name, price, highlights, category, image_prompt, image_status
            FROM affiliate_catalog WHERE id = ?
        """, (product_id,))
    else:
        cur.execute("""
            SELECT id, product_name, price, highlights, category, image_prompt, image_status
            FROM affiliate_catalog
            WHERE image_status = 'perlu_gambar'
            ORDER BY id
        """)

    rows = cur.fetchall()
    conn.close()

    if not rows:
        print("[✓] Semua produk udah punya gambar")
        return 0

    for pid, name, price, detail, cat, prompt, status in rows:
        print(f"\n{'='*65}")
        print(f"  PRODUK #{pid}: {name} ({price})")
        print(f"  Kategori: {cat} | Status: {status}")
        print(f"{'='*65}")
        print(f"\n📸 PROMPT (paste ke Nano Banana / generator lo):\n")
        print(prompt)
        print(f"\n💾 Simpan hasil ke: media/inbox/affiliate/{pid:02d}/")
        print(f"   (buat foldernya dulu, taruh 1-3 gambar)")

    return 0


# ─────────────────────────────────────────────────────────────
# TAHAP 3: GENERATE CAPTION
# ─────────────────────────────────────────────────────────────

def cmd_caption(product_id, caption=None, dry_run=False):
    """
    Generate/isi caption untuk produk.

    Kalau --caption dikasih: pakai itu.
    Kalau tidak: tampilkan template yang harus diisi agent (vision).
    """
    ensure_catalog_columns()
    conn = sqlite3.connect(DB_PATH, timeout=30)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, product_name, price, highlights, category, affiliate_link
        FROM affiliate_catalog WHERE id = ?
    """, (product_id,))
    row = cur.fetchone()
    conn.close()

    if not row:
        print(f"[!] Produk ID {product_id} gak ada")
        return 1

    pid, name, price, detail, cat, link = row

    # cek gambar ada atau belum
    img_dir = image_pool.AFFILIATE_DIR / f"{pid:02d}_produk"
    has_image = img_dir.exists() and any(
        f.suffix.lower() in image_pool.IMG_EXT for f in img_dir.glob("*")
    )

    print(f"\n=== CAPTION PRODUK #{pid} ===")
    print(f"  Nama    : {name}")
    print(f"  Harga   : {price}")
    print(f"  Detail  : {detail}")
    print(f"  Gambar  : {'✅ ada' if has_image else '❌ belum ada'}")

    if caption:
        # validasi quality gate
        qr = run_quality_gate(caption, link, "affiliate", is_affiliate=True)
        print(f"\n[*] Quality Gate:\n{qr}")
        if not qr.passed:
            print("\n[!] Caption ditolak. Revisi dulu.")
            return 2

        if dry_run:
            print(f"\n[DRY-RUN] Caption valid, gak disimpan")
            return 0

        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.execute("UPDATE affiliate_catalog SET caption = ? WHERE id = ?",
                     (caption, pid))
        conn.commit()
        conn.close()
        print(f"\n✅ Caption disimpan")
        return 0

    # kalau gak ada caption: kasih instruksi ke agent
    print(f"\n{'='*65}")
    print(f"  CAPTION BELUM ADA — perlu dibuat dari gambar")
    print(f"{'='*65}")

    if not has_image:
        print(f"\n⚠️  Gambar belum ada. Alurnya:")
        print(f"  1. python affiliate_flow.py prompt --product-id {pid}")
        print(f"  2. Generate gambar pakai prompt itu")
        print(f"  3. Simpan ke: media/inbox/affiliate/{pid:02d}/")
        print(f"  4. Ulangi command ini")
        return 1

    # kasih info buat agent vision
    images = [f for f in img_dir.glob("*") if f.suffix.lower() in image_pool.IMG_EXT]
    print(f"\n📸 Gambar tersedia ({len(images)}):")
    for im in images:
        print(f"   {im}")

    dna = StyleDNA.for_post(pid)
    print(f"\n🎨 DNA Style untuk produk ini: {dna}")
    print(f"\n{dna.to_prompt()}")

    print(f"\n{'='*65}")
    print(f"  PROMPT BUAT AGENT (copy ke Hermes):")
    print(f"{'='*65}")
    print(f"""
Baca gambar produk ini: {images[0]}

Info produk:
  Nama  : {name}
  Harga : {price}
  Detail: {detail}

Tulis caption Threads gaya STYLING/PAMER (bukan review — gue belum beli):
- Fokus: cara matching, kenapa cocok, detail bahan yang keliatan di foto
- JANGAN klaim pengalaman pake ("udah gue pake 2 minggu")
- JANGAN klaim kualitas absolut ("beneran adem", "gak melar")
- Ikuti DNA style di atas

Simpan hasil:
  python affiliate_flow.py caption --product-id {pid} --caption "hasil caption"
""")
    return 0


# ─────────────────────────────────────────────────────────────
# TAHAP 4: POST
# ─────────────────────────────────────────────────────────────

def cmd_post(product_id=None, text_only=True, dry_run=False):
    """Post affiliate ke Threads."""
    ensure_catalog_columns()

    conn = sqlite3.connect(DB_PATH, timeout=30)
    cur = conn.cursor()
    if product_id:
        cur.execute("""
            SELECT id, product_name, price, affiliate_link, caption, image_status
            FROM affiliate_catalog WHERE id = ?
        """, (product_id,))
    else:
        cur.execute("""
            SELECT id, product_name, price, affiliate_link, caption, image_status
            FROM affiliate_catalog
            WHERE caption IS NOT NULL AND caption != ''
            ORDER BY post_count ASC, last_posted_at ASC
            LIMIT 1
        """)
    row = cur.fetchone()
    conn.close()

    if not row:
        print("[!] Gak ada produk dengan caption siap pakai")
        print("    Jalankan: python affiliate_flow.py caption --product-id N")
        return 1

    pid, name, price, link, caption, img_status = row

    if not link:
        print(f"[!] Produk #{pid} gak punya link affiliate")
        print(f"    Update dulu: python affiliate_link.py --update --affiliate-id XXX")
        return 1

    # cek gambar
    image_path = None
    if not text_only:
        picked = image_pool.pick_next(slot=f"{pid:02d}_produk", kind="affiliate")
        if picked:
            image_path = picked["path"]
            print(f"[*] Gambar: {picked['rel']}")

    print(f"\n=== POST AFFILIATE #{pid} ===")
    print(f"  Produk  : {name}")
    print(f"  Harga   : {price}")
    print(f"  Gambar  : {image_path or 'tidak ada (text-only)'}")
    print(f"  Link    : {link[:70]}...")

    # quality gate final
    qr = run_quality_gate(caption, link, "affiliate", is_affiliate=True)
    print(f"\n[*] Quality Gate:\n{qr}")
    if not qr.passed:
        notifier.notify_quality_rejected(pid, "affiliate", qr.reasons)
        return 2

    if dry_run:
        print(f"\n[DRY-RUN] Caption:\n{caption}")
        print(f"[DRY-RUN] Reply: {link}")
        return 0

    # posting
    conn = pg.get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO cron_proposals (day_number, slot, opt1_text, opt1_reply, status)
        VALUES (0, 'affiliate', ?, ?, 'pending')
    """, (caption, link))
    prop_id = cur.lastrowid
    conn.commit()
    conn.close()

    def do_post():
        return post_to_threads(main_text=caption, reply_text=link,
                               image_path=image_path)

    result = pg.safe_publish(prop_id, do_post, "affiliate", image_path)
    print(f"\n[*] Hasil: {result}")

    if result.kind == PostResult.POSTED:
        if image_path:
            image_pool.mark_used(image_path, result.url)
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.execute("""
            UPDATE affiliate_catalog
            SET post_count = post_count + 1, last_posted_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (pid,))
        conn.commit()
        conn.close()

        notifier.notify_posted(
            post_no=prop_id, post_type="affiliate",
            product=name, price=price,
            has_image=bool(image_path), link_in_reply=True,
            threads_url=result.url,
        )
        print("[✓] Sukses + notif terkirim")
        return 0

    elif result.kind == PostResult.FAILED:
        notifier.notify_failed(prop_id, "affiliate", result.message,
                               product=name, image_path=image_path)
        return 1
    else:
        notifier.notify_unknown(prop_id, "affiliate", result.message, product=name)
        return 3


# ─────────────────────────────────────────────────────────────
# STATUS
# ─────────────────────────────────────────────────────────────

def cmd_status():
    ensure_catalog_columns()
    conn = sqlite3.connect(DB_PATH, timeout=30)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, product_name, price, image_status,
               CASE WHEN caption IS NOT NULL AND caption != '' THEN 1 ELSE 0 END,
               CASE WHEN affiliate_link IS NOT NULL AND affiliate_link != '' THEN 1 ELSE 0 END,
               post_count
        FROM affiliate_catalog ORDER BY id
    """)
    rows = cur.fetchall()
    conn.close()

    print(f"\n{'='*80}")
    print(f"  STATUS KATALOG AFFILIATE")
    print(f"{'='*80}\n")
    print(f"  {'ID':>3} {'Produk':35} {'Harga':10} {'Gbr':5} {'Cap':5} {'Link':5} {'Post':4}")
    print(f"  {'-'*75}")

    for pid, name, price, img_st, has_cap, has_link, pcount in rows:
        img_icon = "✅" if img_st == "siap" else "❌"
        cap_icon = "✅" if has_cap else "❌"
        link_icon = "✅" if has_link else "❌"
        print(f"  {pid:>3} {name[:35]:35} {price or '-':10} "
              f"{img_icon:5} {cap_icon:5} {link_icon:5} {pcount or 0:4}")

    # ringkasan
    total = len(rows)
    ready = sum(1 for r in rows if r[4] and r[5])
    need_img = sum(1 for r in rows if r[3] != "siap")
    no_link = sum(1 for r in rows if not r[5])

    print(f"\n  Total produk   : {total}")
    print(f"  Siap dipost    : {ready}")
    print(f"  Perlu gambar   : {need_img}")
    print(f"  Link kosong    : {no_link}")

    if no_link:
        print(f"\n  ⚠️  {no_link} produk tanpa link affiliate = TIDAK DAPAT KOMISI")
        print(f"      Fix: python affiliate_link.py --update --affiliate-id ID_LO")

    return 0


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Alur affiliate: link -> gambar -> caption -> post")
    sub = ap.add_subparsers(dest="cmd", required=True)

    # add
    p_add = sub.add_parser("add", help="Tambah produk baru")
    p_add.add_argument("--url", required=True, help="URL produk Shopee")
    p_add.add_argument("--nama", required=True)
    p_add.add_argument("--harga", required=True)
    p_add.add_argument("--detail", default="", help="Detail/highlight produk")
    p_add.add_argument("--kategori", default="bawahan",
                       choices=list(IMAGE_PROMPTS.keys()))
    p_add.add_argument("--affiliate-id", help="ID Shopee Affiliate lo")
    p_add.add_argument("--sub-id", default="threads")

    # prompt
    p_prompt = sub.add_parser("prompt", help="Lihat prompt gambar")
    p_prompt.add_argument("--product-id", type=int)

    # caption
    p_cap = sub.add_parser("caption", help="Isi/generate caption")
    p_cap.add_argument("--product-id", type=int, required=True)
    p_cap.add_argument("--caption", help="Caption final")
    p_cap.add_argument("--dry-run", action="store_true")

    # post
    p_post = sub.add_parser("post", help="Post ke Threads")
    p_post.add_argument("--product-id", type=int)
    p_post.add_argument("--text-only", action="store_true", default=True)
    p_post.add_argument("--with-image", action="store_true")
    p_post.add_argument("--dry-run", action="store_true")

    # status
    sub.add_parser("status", help="Status katalog")

    args = ap.parse_args()

    if args.cmd == "add":
        return cmd_add(args.url, args.nama, args.harga, args.detail,
                       args.kategori, args.affiliate_id, args.sub_id)
    if args.cmd == "prompt":
        return cmd_prompt(args.product_id)
    if args.cmd == "caption":
        return cmd_caption(args.product_id, args.caption, args.dry_run)
    if args.cmd == "post":
        return cmd_post(args.product_id, not args.with_image, args.dry_run)
    if args.cmd == "status":
        return cmd_status()
    return 0


if __name__ == "__main__":
    sys.exit(main())
