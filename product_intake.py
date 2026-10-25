"""
product_intake.py — Terima produk dari lo, olah otomatis.

JAWABAN PERTANYAAN: "gua stokin di folder atau kirim ke lu?"

DUA-DUANYA BISA:

  Opsi A — Kirim URL via chat (paling cepat, 1 produk)
    Lo: "https://shopee.co.id/Produk-i.123.456 | Nama | Harga | detail"
    Gua: olah langsung, masuk katalog

  Opsi B — Stok di file (batch, banyak produk)
    Lo: isi data/products_inbox.json
    Gua: proses semua sekaligus

  Opsi C — CSV export dari dashboard affiliate
    Lo: download CSV dari Shopee Affiliate
    Gua: baca + ranking by komisi

FREKUENSI: kapan aja lo mau. Gak harus rutin.
  - Minimal 5 produk aktif di katalog
  - Kalau stok < 3, gua kasih warning
  - Idealnya tambah 5 produk baru tiap 2 minggu

Cara pakai:
  python product_intake.py --template        # bikin file template
  python product_intake.py --add "url|nama|harga|detail|kategori"
  python product_intake.py --process         # proses products_inbox.json
  python product_intake.py --import-csv FILE # dari export affiliate
  python product_intake.py --status          # stok katalog
"""

import argparse
import csv
import json
import re
import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

import affiliate_link

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "affiliate_content.db"
DATA_DIR = BASE_DIR / "data"
INBOX_FILE = DATA_DIR / "products_inbox.json"
WIB = timezone(timedelta(hours=7))

AFFILIATE_ID = "11342632100"   # ID lo

CATEGORIES = ["bawahan", "atasan", "hijab", "rumahan", "outer", "aksesoris"]


# ─────────────────────────────────────────────────────────────
# TEMPLATE
# ─────────────────────────────────────────────────────────────

def cmd_template():
    """Bikin file template kosong buat lo isi."""
    DATA_DIR.mkdir(exist_ok=True)

    if INBOX_FILE.exists():
        print(f"[!] File udah ada: {INBOX_FILE}")
        print("    Hapus dulu kalau mau bikin baru, atau edit langsung.")
        return 1

    template = {
        "_petunjuk": [
            "Isi array 'products' dengan produk dari Shopee.",
            "Ambil URL: buka produk di app Shopee → Share → Copy Link",
            "Atau dari desktop: copy dari address bar",
            "Kategori: bawahan, atasan, hijab, rumahan, outer, aksesoris",
            "Hapus produk dari array setelah diproses (otomatis).",
        ],
        "products": [
            {
                "url": "https://shopee.co.id/Nama-Produk-i.123456.789012",
                "nama": "Nama produk yang jelas",
                "harga": "Rp59.000",
                "detail": "bahan linen, cuttingan longgar, pinggang karet",
                "kategori": "bawahan",
            }
        ],
    }

    INBOX_FILE.write_text(json.dumps(template, indent=2, ensure_ascii=False),
                          encoding="utf-8")
    print(f"\n✅ Template dibuat: {INBOX_FILE}")
    print(f"\nIsi file itu, lalu jalankan:")
    print(f"  python product_intake.py --process")
    return 0


# ─────────────────────────────────────────────────────────────
# TAMBAH 1 PRODUK (via CLI)
# ─────────────────────────────────────────────────────────────

def cmd_add(raw):
    """
    Format: url|nama|harga|detail|kategori
    Contoh:
    https://shopee.co.id/X-i.1.2|Kulot Linen|Rp59.000|bahan linen|bawahan
    """
    parts = [p.strip() for p in raw.split("|")]
    if len(parts) < 3:
        print("[!] Format salah. Pakai: url|nama|harga|detail|kategori")
        print("    Minimal: url|nama|harga")
        return 1

    url = parts[0]
    nama = parts[1]
    harga = parts[2]
    detail = parts[3] if len(parts) > 3 else ""
    kategori = parts[4] if len(parts) > 4 else "bawahan"

    if kategori not in CATEGORIES:
        print(f"[!] Kategori '{kategori}' gak dikenal. Pilih: {', '.join(CATEGORIES)}")
        return 1

    return _insert_product(url, nama, harga, detail, kategori)


def _insert_product(url, nama, harga, detail, kategori):
    """Insert 1 produk ke katalog + generate link affiliate."""
    pid_info = affiliate_link.extract_product_id(url)
    if not pid_info:
        print(f"[!] URL gak valid: {url}")
        print("    Format harus: shopee.co.id/Nama-i.{shop_id}.{item_id}")
        return 1

    # cek duplikat
    conn = sqlite3.connect(DB_PATH, timeout=30)
    cur = conn.cursor()
    cur.execute("SELECT id, product_name FROM affiliate_catalog WHERE origin_url = ?", (url,))
    existing = cur.fetchone()
    if existing:
        print(f"[skip] Produk udah ada (ID {existing[0]}: {existing[1]})")
        conn.close()
        return 0

    # generate link
    try:
        link = affiliate_link.build_link(
            affiliate_link.normalize_url(url), AFFILIATE_ID, "threads")
    except Exception as e:
        print(f"[!] Gagal bikin link: {e}")
        conn.close()
        return 1

    # generate prompt gambar
    from affiliate_flow import build_image_prompt
    prompt = build_image_prompt(nama, detail, kategori)

    cur.execute("""
        INSERT INTO affiliate_catalog
        (product_name, price, highlights, origin_url, affiliate_link,
         category, image_prompt, image_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'perlu_gambar')
    """, (nama, harga, detail, url, link, kategori, prompt))
    new_id = cur.lastrowid
    conn.commit()
    conn.close()

    print(f"✅ [{new_id}] {nama} ({harga})")
    print(f"   link : {link[:75]}...")
    print(f"   simpan gambar ke: media/inbox/affiliate/{new_id:02d}/")
    return 0


# ─────────────────────────────────────────────────────────────
# PROSES BATCH
# ─────────────────────────────────────────────────────────────

def cmd_process():
    """Proses semua produk di products_inbox.json."""
    if not INBOX_FILE.exists():
        print(f"[!] File gak ada: {INBOX_FILE}")
        print("    Jalankan dulu: python product_intake.py --template")
        return 1

    data = json.loads(INBOX_FILE.read_text(encoding="utf-8"))
    products = data.get("products", [])

    if not products:
        print("[!] Array 'products' kosong")
        return 1

    print(f"\n{'='*60}")
    print(f"  PROSES {len(products)} PRODUK")
    print(f"{'='*60}\n")

    ok = skip = fail = 0
    done = []

    for i, p in enumerate(products, 1):
        url = p.get("url", "").strip()
        nama = p.get("nama", "").strip()
        harga = p.get("harga", "").strip()
        detail = p.get("detail", "").strip()
        kat = p.get("kategori", "bawahan").strip()

        print(f"[{i}/{len(products)}] {nama or url[:40]}")

        if not url or not nama:
            print("   ❌ URL atau nama kosong")
            fail += 1
            continue

        r = _insert_product(url, nama, harga, detail, kat)
        if r == 0:
            # cek apakah skip atau sukses
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cur = conn.cursor()
            cur.execute("SELECT id FROM affiliate_catalog WHERE origin_url = ?", (url,))
            if cur.fetchone():
                done.append(url)
            conn.close()
            ok += 1
        else:
            fail += 1
        print()

    # hapus yang udah diproses dari inbox
    remaining = [p for p in products if p.get("url") not in done]
    data["products"] = remaining
    INBOX_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                          encoding="utf-8")

    print(f"{'='*60}")
    print(f"  HASIL: {ok} sukses, {fail} gagal, {len(remaining)} sisa di inbox")
    print(f"{'='*60}")
    return 0


# ─────────────────────────────────────────────────────────────
# IMPORT CSV (dari dashboard affiliate)
# ─────────────────────────────────────────────────────────────

def cmd_import_csv(filepath):
    """
    Import dari export Shopee Affiliate (Kreatif → Tampilan Produk → download).

    Format CSV biasanya: product_name, product_shortlink, price, commission...
    """
    p = Path(filepath)
    if not p.exists():
        print(f"[!] File gak ada: {p}")
        return 1

    rows = []
    try:
        with open(p, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except Exception as e:
        print(f"[!] Gagal baca CSV: {e}")
        return 1

    print(f"\n[+] {len(rows)} baris ditemukan")
    if rows:
        print(f"    Kolom: {list(rows[0].keys())[:8]}")

    # coba tebak kolom
    def find_col(row, candidates):
        for k in row.keys():
            kl = k.lower().replace(" ", "_")
            for c in candidates:
                if c in kl:
                    return k
        return None

    if not rows:
        return 1

    sample = rows[0]
    col_name = find_col(sample, ["product_name", "nama", "item_name", "title"])
    col_link = find_col(sample, ["product_shortlink", "shortlink", "link", "url"])
    col_price = find_col(sample, ["price", "harga"])
    col_comm = find_col(sample, ["commission", "komisi", "rate"])

    print(f"\n    nama  : {col_name}")
    print(f"    link  : {col_link}")
    print(f"    harga : {col_price}")
    print(f"    komisi: {col_comm}")

    if not col_name:
        print("\n[!] Gak bisa deteksi kolom nama produk. Cek header CSV.")
        return 1

    # sortir by komisi kalau ada
    if col_comm:
        def parse_comm(v):
            try:
                return float(re.sub(r'[^\d.]', '', str(v)) or 0)
            except Exception:
                return 0
        rows.sort(key=lambda r: parse_comm(r.get(col_comm, 0)), reverse=True)
        print(f"\n    [sorted] diurutkan by komisi tertinggi")

    # simpan ke inbox
    products = []
    for r in rows[:50]:   # max 50
        nama = (r.get(col_name) or "").strip()
        link = (r.get(col_link) or "").strip() if col_link else ""
        price = (r.get(col_price) or "").strip() if col_price else ""
        comm = (r.get(col_comm) or "").strip() if col_comm else ""

        if not nama or not link:
            continue

        # kalau link-nya sudah affiliate (an_redir), ekstrak origin
        if "an_redir" in link:
            import urllib.parse
            m = re.search(r'origin_link=([^&]+)', link)
            if m:
                link = urllib.parse.unquote(m.group(1))

        products.append({
            "url": link,
            "nama": nama[:100],
            "harga": price,
            "detail": f"komisi {comm}" if comm else "",
            "kategori": "bawahan",
        })

    data = {"products": products}
    INBOX_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                          encoding="utf-8")

    print(f"\n✅ {len(products)} produk disimpan ke {INBOX_FILE.name}")
    print(f"\n   Langkah berikut:")
    print(f"   1. Review file itu, betulkan kategori")
    print(f"   2. python product_intake.py --process")
    return 0


# ─────────────────────────────────────────────────────────────
# STATUS
# ─────────────────────────────────────────────────────────────

def cmd_status():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, product_name, price, category,
               CASE WHEN caption IS NOT NULL AND caption != '' THEN 1 ELSE 0 END,
               CASE WHEN image_status = 'siap' THEN 1 ELSE 0 END,
               post_count
        FROM affiliate_catalog ORDER BY id
    """)
    rows = cur.fetchall()
    conn.close()

    print(f"\n{'='*80}")
    print(f"  STOK PRODUK")
    print(f"{'='*80}\n")
    print(f"  {'ID':>3} {'Produk':36} {'Kategori':10} {'Cap':5} {'Gbr':5} {'Post':>4}")
    print(f"  {'-'*76}")

    by_cat = {}
    for pid, name, price, cat, has_cap, has_img, pc in rows:
        print(f"  {pid:>3} {name[:36]:36} {(cat or '-'):10} "
              f"{'✅' if has_cap else '❌':5} {'✅' if has_img else '❌':5} {pc or 0:>4}")
        by_cat[cat or '-'] = by_cat.get(cat or '-', 0) + 1

    # stok per kategori
    print(f"\n  Stok per kategori:")
    for cat, n in sorted(by_cat.items(), key=lambda x: -x[1]):
        warn = "  ⚠️ kurang" if n < 2 else ""
        print(f"    {cat:12}: {n}{warn}")

    total = len(rows)
    ready = sum(1 for r in rows if r[4] and r[5])
    print(f"\n  Total produk  : {total}")
    print(f"  Siap dipost   : {ready}")

    if total < 5:
        print(f"\n  ⚠️  Stok < 5. Tambah produk biar rotasi gak monoton.")
        print(f"      python product_intake.py --template")
    if ready < 3:
        print(f"  ⚠️  Cuma {ready} produk siap. Butuh gambar + caption.")

    return 0


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Terima & olah produk dari lo")
    ap.add_argument("--template", action="store_true", help="Bikin file template")
    ap.add_argument("--add", help="Tambah 1 produk: url|nama|harga|detail|kategori")
    ap.add_argument("--process", action="store_true", help="Proses products_inbox.json")
    ap.add_argument("--import-csv", help="Import dari export Shopee Affiliate")
    ap.add_argument("--status", action="store_true", help="Stok produk")
    args = ap.parse_args()

    if args.template:
        return cmd_template()
    if args.add:
        return cmd_add(args.add)
    if args.process:
        return cmd_process()
    if args.import_csv:
        return cmd_import_csv(args.import_csv)
    if args.status:
        return cmd_status()

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
