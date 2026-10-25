"""
run_post.py — Orchestrator: satu entry point buat semua jenis post.

Menggabungkan:
  - quality_gate  -> tolak konten jelek sebelum dipost
  - image_pool    -> rotasi gambar adil (random & affiliate dipisah)
  - publish_guard -> anti double-post + publish_unknown handling
  - notifier      -> notif Telegram jelas
  - poster        -> Playwright posting

Cara pakai:
  python run_post.py random --slot malam
  python run_post.py random --slot siang --text-only
  python run_post.py affiliate --product-id 1
  python run_post.py affiliate --product-id 1 --text-only
  python run_post.py --dry-run random --slot malam
"""

import argparse
import sqlite3
import sys
from pathlib import Path

import image_pool
import notifier
import publish_guard as pg
from db import get_next_product_to_post, mark_product_posted
from poster import post_to_threads, PostResult, verify_latest_post
from quality_gate import run_quality_gate

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "affiliate_content.db"


# ─────────────────────────────────────────────────────────────
# DB HELPERS
# ─────────────────────────────────────────────────────────────

def save_proposal(post_type, text, reply=None, image=None, product=None):
    """Simpan post ke cron_proposals dengan status pending."""
    conn = pg.get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO cron_proposals (day_number, slot, opt1_text, opt1_reply, status)
        VALUES (?, ?, ?, ?, ?)
    """, (0, post_type, text, reply, pg.STATUS_PENDING))
    pid = cur.lastrowid
    conn.commit()
    conn.close()

    if image:
        conn = pg.get_db()
        conn.execute("""
            INSERT INTO publish_log (proposal_id, post_type, image_path, status)
            VALUES (?, ?, ?, 'queued')
        """, (pid, post_type, image))
        conn.commit()
        conn.close()

    return pid


def count_posts_today():
    conn = pg.get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM cron_proposals
        WHERE date(created_at, '+7 hours') = date('now', '+7 hours')
          AND status IN (?, ?)
    """, (pg.STATUS_POSTED, pg.STATUS_PUBLISHING))
    n = cur.fetchone()[0]
    conn.close()
    return n


# ─────────────────────────────────────────────────────────────
# ALUR RANDOM
# ─────────────────────────────────────────────────────────────

def run_random(slot, text_only=False, dry_run=False):
    """
    Post random: pakai gambar dari pool, caption dari sidecar.
    Kalau text_only=True: pakai teks manual (tanpa gambar).
    """
    print(f"\n{'='*60}")
    print(f"  POST RANDOM — slot: {slot} | text_only={text_only}")
    print(f"{'='*60}")

    image_path = None
    caption = None
    tema = ""

    if not text_only:
        picked = image_pool.pick_next(slot=slot, kind="random")
        if not picked:
            print(f"[!] Pool random/{slot} kosong atau belum ada caption.")
            print(f"    Taruh gambar di: media/inbox/ lalu jalankan process_inbox.py")
            return 1
        image_path = picked["path"]
        caption = picked["caption"]
        tema = picked.get("tema", "")
        print(f"[*] Gambar dipilih: {picked['rel']} (used={picked['used']}x)")
        print(f"[*] Tema: {tema or '-'}")
    else:
        # text-only: ambil dari generator (nanti diisi generator.py)
        print("[!] Mode text-only butuh teks manual.")
        print("    Pakai: python run_post.py random --text 'isi caption'")
        return 1

    # ── Quality gate ──
    qr = run_quality_gate(caption, None, post_type="random", is_affiliate=False)
    print(f"\n[*] Quality Gate:\n{qr}")
    if not qr.passed:
        notifier.notify_quality_rejected(0, "random", qr.reasons)
        return 2

    if dry_run:
        print(f"\n[DRY-RUN] Akan post:\n{caption}")
        print(f"[DRY-RUN] Gambar: {image_path}")
        return 0

    # ── Simpan & posting ──
    pid = save_proposal("random", caption, None, image_path)

    def do_post():
        return post_to_threads(main_text=caption, image_path=image_path)

    result = pg.safe_publish(pid, do_post, post_type="random", image_path=image_path)
    print(f"\n[*] Hasil: {result}")

    # ── Notif ──
    if result.kind == PostResult.POSTED:
        image_pool.mark_used(image_path, result.url)
        notifier.notify_posted(
            post_no=pid, post_type="random",
            caption_preview=caption,
            has_image=bool(image_path),
            threads_url=result.url,
        )
        print("[✓] Sukses + notif terkirim")
        return 0

    elif result.kind == PostResult.FAILED:
        notifier.notify_failed(pid, "random", result.message, image_path=image_path)
        print("[✗] Gagal — aman retry")
        return 1

    else:  # UNKNOWN
        # coba verifikasi otomatis
        print("[?] Status tidak pasti, verifikasi ke profil...")
        found = verify_latest_post(caption)
        if found is True:
            print("[✓] Terverifikasi ADA di profil — anggap sukses")
            image_pool.mark_used(image_path)
            pg.release_claim(pid, pg.STATUS_POSTED, image_path=image_path)
            notifier.notify_posted(pid, "random", caption, has_image=True)
            return 0
        elif found is False:
            print("[✗] Terverifikasi TIDAK ADA — aman retry")
            pg.release_claim(pid, pg.STATUS_FAILED, error="verified not found")
            notifier.notify_failed(pid, "random", "Terverifikasi gagal")
            return 1
        else:
            print("[!] Gak bisa verifikasi — tandai publish_unknown")
            notifier.notify_unknown(pid, "random", result.message)
            return 3


# ─────────────────────────────────────────────────────────────
# ALUR AFFILIATE
# ─────────────────────────────────────────────────────────────

def run_affiliate(product_id=None, text_only=True, dry_run=False, caption=None):
    """
    Post affiliate: rotasi produk dari catalog + link di reply.

    text_only=True  -> tanpa gambar (pilihan lo buat besok)
    text_only=False -> pakai gambar dari media/pool/affiliate/{product_id}/
    """
    print(f"\n{'='*60}")
    print(f"  POST AFFILIATE — text_only={text_only}")
    print(f"{'='*60}")

    # ── Pilih produk ──
    if product_id:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("""SELECT id, product_name, price, highlights, affiliate_link, category
                       FROM affiliate_catalog WHERE id = ?""", (product_id,))
        row = cur.fetchone()
        conn.close()
        if not row:
            print(f"[!] Produk ID {product_id} tidak ada di katalog")
            return 1
        product = {
            "id": row[0], "name": row[1], "price": row[2],
            "highlights": row[3], "link": row[4], "category": row[5],
        }
    else:
        product = get_next_product_to_post()
        if not product:
            print("[!] Katalog kosong atau semua produk udah dipost")
            return 1

    print(f"[*] Produk: {product['name']} ({product['price']})")
    print(f"[*] Kategori: {product.get('category', '-')}")

    # ── Gambar ──
    image_path = None
    if not text_only:
        picked = image_pool.pick_next(slot=str(product["id"]), kind="affiliate")
        if picked:
            image_path = picked["path"]
            print(f"[*] Gambar: {picked['rel']} (used={picked['used']}x)")
        else:
            print(f"[!] Gambar affiliate untuk produk {product['id']} belum ada")
            print(f"    Taruh di: media/pool/affiliate/{product['id']:02d}_*/")
            print(f"    Fallback ke text-only")

    # ── Caption ──
    if not caption:
        print("[!] Caption belum ada.")
        print(f"    Pakai: python run_post.py affiliate --product-id {product['id']} --caption 'isi caption'")
        print(f"\n    Info produk buat caption styling:")
        print(f"      Nama  : {product['name']}")
        print(f"      Harga : {product['price']}")
        print(f"      Detail: {product['highlights']}")
        return 1

    # ── Quality gate (mode affiliate = lebih ketat) ──
    qr = run_quality_gate(caption, product["link"],
                          post_type="affiliate", is_affiliate=True)
    print(f"\n[*] Quality Gate:\n{qr}")
    if not qr.passed:
        notifier.notify_quality_rejected(0, "affiliate", qr.reasons)
        return 2

    if dry_run:
        print(f"\n[DRY-RUN] Caption:\n{caption}")
        print(f"[DRY-RUN] Reply: {product['link']}")
        print(f"[DRY-RUN] Gambar: {image_path or 'tidak ada'}")
        return 0

    # ── Posting ──
    pid = save_proposal("affiliate", caption, product["link"], image_path, product)

    def do_post():
        return post_to_threads(main_text=caption, reply_text=product["link"],
                               image_path=image_path)

    result = pg.safe_publish(pid, do_post, post_type="affiliate", image_path=image_path)
    print(f"\n[*] Hasil: {result}")

    if result.kind == PostResult.POSTED:
        if image_path:
            image_pool.mark_used(image_path, result.url)
        mark_product_posted(product["id"])
        notifier.notify_posted(
            post_no=pid, post_type="affiliate",
            product=product["name"], price=product["price"],
            has_image=bool(image_path), link_in_reply=True,
            threads_url=result.url,
        )
        print("[✓] Sukses + katalog diupdate")
        return 0

    elif result.kind == PostResult.FAILED:
        notifier.notify_failed(pid, "affiliate", result.message,
                               product=product["name"], image_path=image_path)
        return 1

    else:
        print("[?] Status tidak pasti, verifikasi...")
        found = verify_latest_post(caption)
        if found is True:
            mark_product_posted(product["id"])
            pg.release_claim(pid, pg.STATUS_POSTED, image_path=image_path)
            notifier.notify_posted(pid, "affiliate", product=product["name"],
                                   price=product["price"], has_image=bool(image_path),
                                   link_in_reply=True)
            return 0
        notifier.notify_unknown(pid, "affiliate", result.message, product=product["name"])
        return 3


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Threads auto poster")
    ap.add_argument("mode", choices=["random", "affiliate", "status"])
    ap.add_argument("--slot", default="malam", choices=["siang", "malam"])
    ap.add_argument("--product-id", type=int)
    ap.add_argument("--caption")
    ap.add_argument("--text", help="teks manual buat random text-only")
    ap.add_argument("--text-only", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    # recovery dulu — tandai post nyangkut
    n = pg.recover_stale()
    if n:
        print(f"[recovery] {n} post nyangkut ditandai publish_unknown")

    if args.mode == "status":
        print(f"Post hari ini: {count_posts_today()}")
        print(f"\nPool stats: {image_pool.stats()}")
        unver = pg.get_unverified_posts()
        if unver:
            print(f"\n⚠️ {len(unver)} post perlu cek manual:")
            for r in unver:
                print(f"  ID {r[0]}: {(r[3] or '')[:50]}...")
        return 0

    if args.mode == "random":
        if args.text:
            # text-only manual
            caption = args.text
            qr = run_quality_gate(caption, None, "random", False)
            print(qr)
            if not qr.passed:
                return 2
            if args.dry_run:
                print(f"[DRY-RUN] {caption}")
                return 0
            pid = save_proposal("random", caption)
            r = pg.safe_publish(pid, lambda: post_to_threads(caption),
                                "random")
            print(r)
            if r.kind == PostResult.POSTED:
                notifier.notify_posted(pid, "random", caption, has_image=False)
                return 0
            return 1
        return run_random(args.slot, args.text_only, args.dry_run)

    if args.mode == "affiliate":
        return run_affiliate(args.product_id, args.text_only,
                             args.dry_run, args.caption)


if __name__ == "__main__":
    sys.exit(main())
