"""
cek_stok.py — Cek stok sebelum posting. GATE: jangan posting kalau belum siap.

ATURAN BARU (sesuai permintaan lo):
  - Kalau BELUM ada gambar + link  -> JANGAN posting apa-apa
  - Kalau BELUM ada gambar         -> posting text-only aja
  - Kalau ada gambar               -> boleh post dengan gambar
  - Kalau ada link affiliate       -> boleh post affiliate

Cara pakai:
  python cek_stok.py              # cek + tampilkan status
  python cek_stok.py --json       # output JSON (buat mesin)
  python cek_stok.py --sync       # pindahkan dari STOK/ ke pool
"""

import argparse
import json
import shutil
import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "affiliate_content.db"
STOK = BASE_DIR / "STOK"
POOL = BASE_DIR / "media" / "pool"

IMG_EXT = {".jpg", ".jpeg", ".png", ".webp"}
WIB = timezone(timedelta(hours=7))


# ─────────────────────────────────────────────────────────────
# HITUNG STOK
# ─────────────────────────────────────────────────────────────

def count_images(folder):
    if not folder.exists():
        return 0
    return len([f for f in folder.rglob("*") if f.suffix.lower() in IMG_EXT])


def get_stock():
    """Return dict berisi semua info stok."""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    cur = conn.cursor()

    # produk affiliate
    cur.execute("""
        SELECT id, product_name, price, category, affiliate_link,
               CASE WHEN caption IS NOT NULL AND caption != '' THEN 1 ELSE 0 END,
               image_status
        FROM affiliate_catalog ORDER BY id
    """)
    products = []
    for r in cur.fetchall():
        pid, name, price, cat, link, has_cap, img_status = r
        # hitung gambar di folder STOK
        slug_dirs = list((STOK / "02-GAMBAR-AFFILIATE").glob(f"{pid}-*"))
        n_img = sum(count_images(d) for d in slug_dirs)

        products.append({
            "id": pid,
            "nama": name,
            "harga": price,
            "kategori": cat,
            "has_link": bool(link and "shopee" in link),
            "has_caption": bool(has_cap),
            "n_images": n_img,
            "ready_image": n_img > 0,
            "ready_affiliate": bool(link and "shopee" in link and has_cap and n_img > 0),
        })

    conn.close()

    # gambar random
    siang = count_images(STOK / "01-GAMBAR-RANDOM" / "SIANG")
    malam = count_images(STOK / "01-GAMBAR-RANDOM" / "MALAM")

    # pool yang udah siap
    pool_siang = count_images(POOL / "random" / "siang")
    pool_malam = count_images(POOL / "random" / "malam")
    pool_aff = count_images(POOL / "affiliate")

    return {
        "checked_at": datetime.now(WIB).isoformat(),
        "random": {
            "stok_siang": siang,
            "stok_malam": malam,
            "pool_siang": pool_siang,
            "pool_malam": pool_malam,
            "ready": (siang + malam + pool_siang + pool_malam) > 0,
        },
        "affiliate": {
            "total_produk": len(products),
            "siap_post": sum(1 for p in products if p["ready_affiliate"]),
            "ada_link": sum(1 for p in products if p["has_link"]),
            "ada_gambar": sum(1 for p in products if p["ready_image"]),
            "ada_caption": sum(1 for p in products if p["has_caption"]),
            "pool_gambar": pool_aff,
            "ready": any(p["ready_affiliate"] for p in products),
            "produk": products,
        },
    }


# ─────────────────────────────────────────────────────────────
# GATE — boleh posting apa?
# ─────────────────────────────────────────────────────────────

def allowed_modes(stock=None):
    """
    Tentukan mode apa yang BOLEH dijalankan sekarang.

    Aturan:
      - Belum ada gambar random + belum ada affiliate siap
        -> cuma text_only
      - Ada gambar random
        -> text_only + random_image
      - Ada affiliate siap (link + caption + gambar)
        -> + affiliate
    """
    if stock is None:
        stock = get_stock()

    modes = ["text_only"]   # selalu boleh

    if stock["random"]["ready"]:
        modes.append("random_image")

    if stock["affiliate"]["ready"]:
        modes.append("affiliate")

    return modes


def can_post_image(slot=None):
    """Apakah ada gambar random siap pakai?"""
    stock = get_stock()
    if slot == "siang":
        return stock["random"]["pool_siang"] > 0 or stock["random"]["stok_siang"] > 0
    if slot == "malam":
        return stock["random"]["pool_malam"] > 0 or stock["random"]["stok_malam"] > 0
    return stock["random"]["ready"]


def can_post_affiliate():
    """Apakah ada produk affiliate yang siap (link + caption + gambar)?"""
    stock = get_stock()
    return stock["affiliate"]["ready"]


# ─────────────────────────────────────────────────────────────
# SYNC: STOK -> POOL
# ─────────────────────────────────────────────────────────────

def sync_to_pool(dry_run=False):
    """
    Pindahkan gambar dari STOK/ ke media/pool/ biar siap dipakai.

    - 01-GAMBAR-RANDOM/SIANG/*  -> media/pool/random/siang/
    - 01-GAMBAR-RANDOM/MALAM/*  -> media/pool/random/malam/
    - 02-GAMBAR-AFFILIATE/{id}-*/ -> media/pool/affiliate/{id}_produk/
    """
    moved = 0

    # random siang
    for src_dir, dst_dir, prefix in [
        (STOK / "01-GAMBAR-RANDOM" / "SIANG", POOL / "random" / "siang", "s"),
        (STOK / "01-GAMBAR-RANDOM" / "MALAM", POOL / "random" / "malam", "m"),
    ]:
        if not src_dir.exists():
            continue
        dst_dir.mkdir(parents=True, exist_ok=True)

        for img in list(src_dir.glob("*")):
            if img.suffix.lower() not in IMG_EXT:
                continue
            # nama unik
            n = 1
            while (dst_dir / f"{prefix}_{n:03d}{img.suffix.lower()}").exists():
                n += 1
            dest = dst_dir / f"{prefix}_{n:03d}{img.suffix.lower()}"

            if dry_run:
                print(f"  [DRY] {img.name} -> {dest.name}")
            else:
                shutil.move(str(img), str(dest))
                # bikin sidecar kosong (caption diisi nanti)
                sidecar = dest.with_suffix(".json")
                if not sidecar.exists():
                    sidecar.write_text(json.dumps({
                        "file": dest.name,
                        "kind": "random",
                        "slot": "siang" if prefix == "s" else "malam",
                        "tema": "",
                        "visual": "",
                        "caption": "",
                        "used": 0,
                        "last_used": None,
                        "created": datetime.now(WIB).isoformat(),
                    }, indent=2, ensure_ascii=False), encoding="utf-8")
                print(f"  ✓ {img.name} -> {dest.name}")
            moved += 1

    # affiliate
    aff_root = STOK / "02-GAMBAR-AFFILIATE"
    if aff_root.exists():
        for prod_dir in aff_root.iterdir():
            if not prod_dir.is_dir():
                continue
            # ambil ID dari nama folder "1-Nama-Produk"
            try:
                pid = int(prod_dir.name.split("-")[0])
            except (ValueError, IndexError):
                continue

            dst_dir = POOL / "affiliate" / f"{pid:02d}_produk"
            dst_dir.mkdir(parents=True, exist_ok=True)

            for img in list(prod_dir.glob("*")):
                if img.suffix.lower() not in IMG_EXT:
                    continue
                n = 1
                while (dst_dir / f"a_{n:03d}{img.suffix.lower()}").exists():
                    n += 1
                dest = dst_dir / f"a_{n:03d}{img.suffix.lower()}"

                if dry_run:
                    print(f"  [DRY] {prod_dir.name}/{img.name} -> {dest.name}")
                else:
                    shutil.move(str(img), str(dest))
                    sidecar = dest.with_suffix(".json")
                    if not sidecar.exists():
                        sidecar.write_text(json.dumps({
                            "file": dest.name,
                            "kind": "affiliate",
                            "product_id": pid,
                            "visual": "",
                            "caption": "",
                            "used": 0,
                            "last_used": None,
                            "created": datetime.now(WIB).isoformat(),
                        }, indent=2, ensure_ascii=False), encoding="utf-8")
                    print(f"  ✓ {prod_dir.name}/{img.name} -> {dest.name}")
                moved += 1

    return moved


# ─────────────────────────────────────────────────────────────
# TAMPILAN
# ─────────────────────────────────────────────────────────────

def print_status(stock):
    r = stock["random"]
    a = stock["affiliate"]

    print(f"\n{'='*66}")
    print(f"  CEK STOK — {datetime.now(WIB).strftime('%d %b %Y %H:%M')}")
    print(f"{'='*66}")

    print(f"\n📸 GAMBAR RANDOM")
    print(f"   STOK siang   : {r['stok_siang']}")
    print(f"   STOK malam   : {r['stok_malam']}")
    print(f"   POOL siang   : {r['pool_siang']}")
    print(f"   POOL malam   : {r['pool_malam']}")
    print(f"   Status       : {'✅ siap' if r['ready'] else '❌ KOSONG — cuma text-only'}")

    # arsip
    try:
        import image_pool as _ip
        a_stats = _ip.arsip_stats()
        if a_stats["files"]:
            print(f"\n🗄️  ARSIP (udah dipost, nunggu dihapus)")
            print(f"   File   : {a_stats['files']}")
            print(f"   Ukuran : {a_stats['mb']} MB")
            if a_stats["oldest"]:
                print(f"   Tertua : {a_stats['oldest'].strftime('%d %b %Y')}")
            print(f"   Hapus  : python cek_stok.py --purge")
    except Exception:
        pass

    print(f"\n🛍️  AFFILIATE")
    print(f"   Total produk : {a['total_produk']}")
    print(f"   Ada link     : {a['ada_link']}")
    print(f"   Ada gambar   : {a['ada_gambar']}")
    print(f"   Ada caption  : {a['ada_caption']}")
    print(f"   SIAP POST    : {a['siap_post']}")
    print(f"   Status       : {'✅ siap' if a['ready'] else '❌ belum ada yang siap'}")

    if a["produk"]:
        print(f"\n   {'ID':>3} {'Produk':32} {'Link':5} {'Cap':5} {'Gbr':5} {'Siap':5}")
        print(f"   {'-'*60}")
        for p in a["produk"]:
            print(f"   {p['id']:>3} {p['nama'][:32]:32} "
                  f"{'✅' if p['has_link'] else '❌':5} "
                  f"{'✅' if p['has_caption'] else '❌':5} "
                  f"{p['n_images'] or '❌':>5} "
                  f"{'✅' if p['ready_affiliate'] else '—':5}")

    modes = allowed_modes(stock)
    print(f"\n{'='*66}")
    print(f"  MODE YANG BOLEH JALAN SEKARANG")
    print(f"{'='*66}")
    for m in ["text_only", "random_image", "affiliate"]:
        ok = m in modes
        print(f"  {'✅' if ok else '❌'} {m}")
        if not ok:
            if m == "random_image":
                print(f"      -> butuh gambar di STOK/01-GAMBAR-RANDOM/")
            elif m == "affiliate":
                print(f"      -> butuh produk dengan link + caption + gambar")

    print(f"\n{'='*66}")
    if len(modes) == 1:
        print(f"  ⚠️  Hanya TEXT-ONLY yang bisa jalan.")
        print(f"      Stok gambar & affiliate masih kosong.")
    else:
        print(f"  ✅ {len(modes)} mode aktif: {', '.join(modes)}")
    print(f"{'='*66}\n")


def main():
    ap = argparse.ArgumentParser(description="Cek stok sebelum posting")
    ap.add_argument("--json", action="store_true", help="Output JSON")
    ap.add_argument("--sync", action="store_true", help="Pindah STOK -> pool")
    ap.add_argument("--dry-run", action="store_true", help="Simulasi sync")
    ap.add_argument("--modes", action="store_true", help="Cuma tampilkan mode yang boleh")
    ap.add_argument("--purge", action="store_true", help="Hapus arsip > 30 hari")
    ap.add_argument("--purge-days", type=int, default=30, help="Umur arsip (hari)")
    args = ap.parse_args()

    if args.purge:
        import image_pool as _ip
        print(f"\n=== HAPUS ARSIP > {args.purge_days} HARI ===")
        n = _ip.purge_arsip(days=args.purge_days, dry_run=args.dry_run)
        print(f"\n{'[DRY] ' if args.dry_run else ''}{n} file {'akan ' if args.dry_run else ''}dihapus")
        return 0

    if args.modes:
        print(json.dumps(allowed_modes()))
        return 0

    if args.sync:
        print(f"\n=== SYNC STOK -> POOL {'(DRY RUN)' if args.dry_run else ''} ===")
        n = sync_to_pool(dry_run=args.dry_run)
        print(f"\n{'[DRY] ' if args.dry_run else ''}{n} file dipindah")
        if not args.dry_run:
            print("\nCatatan: gambar udah di pool tapi BELUM ada caption.")
            print("Isi caption dengan: python process_inbox.py --describe")
        return 0

    stock = get_stock()

    if args.json:
        print(json.dumps(stock, indent=2, ensure_ascii=False))
        return 0

    print_status(stock)
    return 0


if __name__ == "__main__":
    sys.exit(main())
