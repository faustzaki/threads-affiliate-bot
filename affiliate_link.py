"""
affiliate_link.py — Generate link affiliate Shopee TANPA API.

Rumus resmi dari Shopee Help Center Indonesia:
https://help.shopee.co.id/10/article/184879

Format:
  https://s.shopee.co.id/an_redir?origin_link={URL_ENCODED}&affiliate_id={ID}&sub_id={SUB}

Jadi lo TIDAK perlu API Shopee Open Platform. Cuma butuh:
  - affiliate_id (dari dashboard Shopee Affiliate lo)
  - URL produk asli

Cara dapat affiliate_id:
  1. Daftar di https://affiliate.shopee.co.id
  2. Login -> menu Akun/Profil
  3. Cari "Affiliate ID" (biasanya angka, contoh: 12345678)

Cara dapat URL produk:
  - Buka produk di Shopee -> Share -> Copy Link
  - Atau dari desktop, copy dari address bar
"""

import urllib.parse
import sqlite3
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "affiliate_content.db"
WIB = timezone(timedelta(hours=7))


def build_link(origin_url, affiliate_id, sub_id="threads"):
    """
    Bikin link affiliate Shopee tanpa API.

    Args:
        origin_url: URL produk Shopee asli
        affiliate_id: ID affiliate lo (angka)
        sub_id: tracking (bebas, maks 5 segmen dipisah '-')

    Returns:
        str: link affiliate siap pakai
    """
    if not origin_url or not affiliate_id:
        raise ValueError("origin_url dan affiliate_id wajib diisi")

    # validasi domain
    if not re.search(r'shopee\.co\.id|shope\.ee', origin_url):
        raise ValueError(f"Bukan URL Shopee: {origin_url}")

    # encode URL
    enc = urllib.parse.quote(origin_url, safe="")

    return (f"https://s.shopee.co.id/an_redir?origin_link={enc}"
            f"&affiliate_id={affiliate_id}&sub_id={sub_id}")


def extract_product_id(url):
    """
    Ambil product ID dari URL Shopee.
    Format: shopee.co.id/Nama-Produk-i.{shop_id}.{item_id}
    """
    m = re.search(r'-i\.(\d+)\.(\d+)', url)
    if m:
        return {"shop_id": m.group(1), "item_id": m.group(2)}
    m = re.search(r'/product/(\d+)/(\d+)', url)
    if m:
        return {"shop_id": m.group(1), "item_id": m.group(2)}
    return None


def normalize_url(url):
    """Bersihin URL dari tracking param yang gak perlu."""
    url = re.sub(r'[?&](?:utm_[a-z_]+|fbclid|gclid|gads_t_sig|sp_atk|smtt)=[^&]*', '', url)
    return url.rstrip('?&')


# ─────────────────────────────────────────────────────────────
# INTEGRASI DB
# ─────────────────────────────────────────────────────────────

def update_catalog_links(affiliate_id, sub_id_prefix="threads", dry_run=False):
    """
    Update semua link di catalog pakai affiliate_id lo.

    Ini yang lo jalankan SEKALI setelah daftar Shopee Affiliate.
    Setelah itu, semua produk otomatis punya link affiliate.
    """
    conn = sqlite3.connect(DB_PATH, timeout=30)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, product_name, origin_url, affiliate_link
        FROM affiliate_catalog
        WHERE origin_url IS NOT NULL AND origin_url != ''
    """)
    rows = cur.fetchall()

    if not rows:
        print("[!] Gak ada produk dengan origin_url di katalog")
        conn.close()
        return 0

    print(f"\n=== UPDATE LINK AFFILIATE ===")
    print(f"Affiliate ID: {affiliate_id}")
    print(f"Total produk: {len(rows)}\n")

    updated = 0
    for pid, name, origin, old_link in rows:
        try:
            clean_origin = normalize_url(origin)
            sub = f"{sub_id_prefix}-{pid:02d}"
            new_link = build_link(clean_origin, affiliate_id, sub)

            if new_link == old_link:
                print(f"  ⏭  [{pid}] {name[:35]} — sudah sama, skip")
                continue

            if dry_run:
                print(f"  [DRY] [{pid}] {name[:35]}")
                print(f"        LAMA: {old_link}")
                print(f"        BARU: {new_link[:100]}...")
            else:
                cur.execute("""
                    UPDATE affiliate_catalog SET affiliate_link = ? WHERE id = ?
                """, (new_link, pid))
                print(f"  ✓ [{pid}] {name[:35]} — link diupdate")
            updated += 1
        except Exception as e:
            print(f"  ✗ [{pid}] {name[:35]} — ERROR: {e}")

    if not dry_run:
        conn.commit()
    conn.close()

    print(f"\n{'[DRY-RUN] ' if dry_run else ''}Total diupdate: {updated}")
    return updated


def validate_links():
    """
    Cek semua link di katalog formatnya bener.

    PENTING: link shortlink Shopee (s.shopee.co.id/xxx) TIDAK punya
    affiliate_id yang kelihatan di string. Tracking-nya baru muncul
    setelah redirect. Jadi validasi harus ikuti redirect.
    """
    conn = sqlite3.connect(DB_PATH, timeout=30)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, product_name, affiliate_link, origin_url
        FROM affiliate_catalog
    """)
    rows = cur.fetchall()
    conn.close()

    print(f"\n=== VALIDASI LINK ({len(rows)} produk) ===")
    print("(mengikuti redirect untuk deteksi tracking affiliate)\n")

    ok = bad = 0
    for pid, name, link, origin in rows:
        if not link:
            print(f"  ⚠️  [{pid}] {name[:35]} — link KOSONG")
            bad += 1
            continue

        # link dengan an_redir eksplisit
        if 'an_redir' in link and 'affiliate_id=' in link:
            aid = re.search(r'affiliate_id=(\d+)', link)
            print(f"  ✅ [{pid}] {name[:32]} (an_redir)")
            print(f"      affiliate_id={aid.group(1) if aid else '?'}")
            ok += 1
            continue

        # link shortlink — ikuti redirect
        if 's.shopee.co.id' in link or 'shope.ee' in link:
            try:
                import urllib.request
                req = urllib.request.Request(link, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                                  "Chrome/131.0.0.0 Safari/537.36"
                })
                resp = urllib.request.urlopen(req, timeout=25)
                final = resp.geturl()

                m_aff = re.search(r'utm_source=an_(\d+)', final)
                has_track = ('uls_trackid' in final or 'utm_source=an_' in final
                             or 'affiliate' in final.lower())

                if has_track:
                    print(f"  ✅ [{pid}] {name[:32]} (shortlink + tracking)")
                    if m_aff:
                        print(f"      affiliate_id={m_aff.group(1)}")
                    ok += 1
                else:
                    print(f"  ❌ [{pid}] {name[:35]} — shortlink TANPA tracking")
                    print(f"      redirect: {final[:100]}")
                    bad += 1
            except Exception as e:
                print(f"  ⚠️  [{pid}] {name[:35]} — gak bisa cek ({type(e).__name__})")
                bad += 1
            continue

        # link langsung ke shopee.co.id tanpa tracking
        print(f"  ❌ [{pid}] {name[:35]} — link langsung, kemungkinan tanpa tracking")
        print(f"      {link[:90]}")
        bad += 1

    print(f"\nValid: {ok} | Bermasalah: {bad}")
    return ok, bad


def test_link(url, affiliate_id):
    """Tes apakah link affiliate redirect dengan benar (tanpa buka browser)."""
    import urllib.request
    link = build_link(url, affiliate_id)
    print(f"\nLink: {link}")
    print(f"Panjang: {len(link)} char")

    try:
        req = urllib.request.Request(link, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/131.0.0.0 Safari/537.36"
        })
        resp = urllib.request.urlopen(req, timeout=30)
        final = resp.geturl()
        print(f"\nRedirect ke: {final[:150]}")

        # cek apakah affiliate tracking masuk
        if 'utm_source=an_' in final or 'affiliate' in final.lower():
            print("✅ TRACKING AFFILIATE MASUK")
        else:
            print("⚠️  Tracking gak kelihatan di URL akhir (mungkin tetap jalan)")
        return True
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return False


if __name__ == "__main__":
    import sys
    import argparse

    ap = argparse.ArgumentParser(description="Shopee affiliate link generator (no API)")
    ap.add_argument("--affiliate-id", help="ID affiliate Shopee lo")
    ap.add_argument("--update", action="store_true", help="Update semua link di katalog")
    ap.add_argument("--validate", action="store_true", help="Cek link yang ada")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--test", help="Tes satu URL produk")
    ap.add_argument("--demo", action="store_true", help="Contoh cara pakai")
    args = ap.parse_args()

    if args.demo:
        print("=" * 65)
        print("  CARA PAKAI — TANPA API SHOPEE")
        print("=" * 65)
        print("""
1. Daftar Shopee Affiliate (gratis):
   https://affiliate.shopee.co.id

2. Ambil Affiliate ID lo:
   Login -> menu Profil/Akun -> cari "Affiliate ID"
   Bentuknya angka, contoh: 12345678

3. Update semua link di katalog:
   python affiliate_link.py --update --affiliate-id 12345678

4. Cek hasilnya:
   python affiliate_link.py --validate

5. Tes satu link:
   python affiliate_link.py --test "https://shopee.co.id/Produk-i.123.456" --affiliate-id 12345678

RUMUS (dari Shopee Help Center resmi):
  https://s.shopee.co.id/an_redir
    ?origin_link={URL_PRODUK_ENCODED}
    &affiliate_id={ID_LO}
    &sub_id={TRACKING}

Contoh produk lo sekarang (link lama tanpa affiliate_id):
  https://s.shopee.co.id/5fpkj5RGXk
  ^ link ini TIDAK ada affiliate_id = TIDAK DAPAT KOMISI
""")
        print("=" * 65)
        sys.exit(0)

    if args.validate:
        validate_links()
        sys.exit(0)

    if args.update:
        if not args.affiliate_id:
            print("[!] Butuh --affiliate-id")
            sys.exit(1)
        update_catalog_links(args.affiliate_id, dry_run=args.dry_run)
        sys.exit(0)

    if args.test:
        if not args.affiliate_id:
            print("[!] Butuh --affiliate-id")
            sys.exit(1)
        test_link(args.test, args.affiliate_id)
        sys.exit(0)

    ap.print_help()
