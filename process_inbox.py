"""
process_inbox.py — Proses gambar dari inbox jadi pool siap pakai.

ALUR:
  1. Lo generate gambar (Nano Banana / manual) -> taruh di media/inbox/
  2. Jalankan script ini -> dia baca gambar, tulis caption, pindah ke pool
  3. Siap dipost otomatis

Mode:
  python process_inbox.py --list           # lihat isi inbox
  python process_inbox.py --describe       # cuma deskripsi visual (buat lo review)
  python process_inbox.py --commit         # pindahkan ke pool (butuh caption)
  python process_inbox.py --stats          # statistik pool

CATATAN PENTING:
Script ini TIDAK generate caption sendiri (butuh vision model).
Alurnya: script kasih deskripsi visual -> agent Hermes tulis caption ->
lo approve -> baru commit.

Jadi ada 2 langkah:
  LANGKAH 1: python process_inbox.py --describe
             -> hasilkan inbox_manifest.json berisi deskripsi visual
  LANGKAH 2: agent tulis caption ke manifest
  LANGKAH 3: python process_inbox.py --commit
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

import image_pool

BASE_DIR = Path(__file__).resolve().parent
MANIFEST = BASE_DIR / "inbox_manifest.json"
WIB = timezone(timedelta(hours=7))


def cmd_list():
    items = image_pool.list_inbox()
    print(f"\n=== INBOX: {len(items)} gambar ===\n")
    for i, it in enumerate(items, 1):
        p = Path(it["path"])
        size_kb = p.stat().st_size / 1024
        print(f"  [{i:2}] {it['rel']:45} {size_kb:7.0f} KB")
    if not items:
        print("  (kosong)")
        print(f"\n  Taruh gambar di: {image_pool.INBOX_DIR}")
        print("  Subfolder juga bisa: media/inbox/siang/, media/inbox/malam/")
    return 0


def cmd_describe():
    """
    Buat manifest berisi daftar gambar yang perlu dideskripsikan.
    Agent Hermes yang akan isi field 'visual' dan 'caption'.
    """
    items = image_pool.list_inbox()
    if not items:
        print("[!] Inbox kosong")
        return 1

    # deteksi duplikat dulu
    hashes = {}
    for it in items:
        h = image_pool.file_hash(it["path"])
        hashes.setdefault(h, []).append(it["rel"])

    dupes = {h: f for h, f in hashes.items() if len(f) > 1}

    manifest = {
        "created": datetime.now(WIB).isoformat(),
        "total": len(items),
        "duplikat": dupes,
        "items": [],
    }

    for i, it in enumerate(items, 1):
        h = image_pool.file_hash(it["path"])
        # deteksi slot dari nama folder
        rel = it["rel"].lower()
        slot_guess = "malam" if "malam" in rel else ("siang" if "siang" in rel else "")
        is_affiliate = "affiliate" in rel or "produk" in rel or "product" in rel

        manifest["items"].append({
            "no": i,
            "file": it["path"],
            "rel": it["rel"],
            "hash": h,
            "kind_guess": "affiliate" if is_affiliate else "random",
            "slot_guess": slot_guess,
            "visual": "",      # <- agent isi
            "caption": "",     # <- agent isi
            "tema": "",        # <- agent isi
            "product_id": None,
            "status": "pending",
        })

    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                        encoding="utf-8")

    print(f"\n=== MANIFEST DIBUAT: {MANIFEST} ===")
    print(f"Total gambar: {len(items)}")
    if dupes:
        print(f"\n⚠️ DUPLIKAT TERDETEKSI ({len(dupes)} grup):")
        for h, files in dupes.items():
            print(f"  {h[:8]}: {', '.join(files)}")
        print("  -> Yang duplikat akan di-skip saat commit")

    print(f"\nLANGKAH BERIKUTNYA:")
    print(f"  1. Minta agent Hermes isi caption:")
    print(f"     'baca inbox_manifest.json, deskripsikan tiap gambar,")
    print(f"      tulis caption Threads yang nyambung, simpan balik'")
    print(f"  2. Review hasilnya di file itu")
    print(f"  3. python process_inbox.py --commit")
    return 0


def cmd_commit():
    """Pindahkan gambar yang caption-nya udah diisi ke pool."""
    if not MANIFEST.exists():
        print(f"[!] Manifest belum ada. Jalankan: python process_inbox.py --describe")
        return 1

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    items = manifest.get("items", [])

    moved = skipped_no_caption = skipped_dupe = 0
    errors = []

    for it in items:
        if it.get("status") == "done":
            continue

        caption = (it.get("caption") or "").strip()
        if not caption:
            skipped_no_caption += 1
            continue

        # cek duplikat
        if it["hash"] in manifest.get("duplikat", {}):
            files = manifest["duplikat"][it["hash"]]
            if it["rel"] != files[0]:
                skipped_dupe += 1
                continue

        # tentukan slot & kind
        kind = it.get("kind_guess", "random")
        slot = it.get("slot_guess") or ("malam" if kind == "random" else "")

        if kind == "random" and not slot:
            errors.append(f"{it['rel']}: slot belum ditentukan")
            continue

        try:
            if kind == "affiliate":
                pid = it.get("product_id")
                if not pid:
                    errors.append(f"{it['rel']}: product_id belum diisi")
                    continue
                subdir = f"{pid:02d}_produk"
                result = image_pool.move_to_pool(
                    it["file"], slot=subdir, caption=caption,
                    tema=it.get("tema", ""), visual=it.get("visual", ""),
                    kind="affiliate", subdir=subdir,
                )
            else:
                result = image_pool.move_to_pool(
                    it["file"], slot=slot, caption=caption,
                    tema=it.get("tema", ""), visual=it.get("visual", ""),
                    kind="random",
                )

            if result.get("skipped"):
                skipped_dupe += 1
            else:
                it["status"] = "done"
                moved += 1
                print(f"  ✓ {it['rel']} -> {Path(result['path']).name}")

        except Exception as e:
            errors.append(f"{it['rel']}: {e}")

    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                        encoding="utf-8")

    print(f"\n=== HASIL COMMIT ===")
    print(f"  Dipindah ke pool : {moved}")
    print(f"  Skip (no caption): {skipped_no_caption}")
    print(f"  Skip (duplikat)  : {skipped_dupe}")
    if errors:
        print(f"\n  ⚠️ Error ({len(errors)}):")
        for e in errors[:10]:
            print(f"    - {e}")

    print(f"\n=== POOL SEKARANG ===")
    for k, v in image_pool.stats().items():
        print(f"  {k:16}: {v}")
    return 0


def cmd_stats():
    s = image_pool.stats()
    print("\n=== STATISTIK POOL ===\n")
    labels = {
        "inbox": "📥 Inbox (belum diproses)",
        "random_siang": "☀️ Random siang (siap)",
        "random_malam": "🌙 Random malam (siap)",
        "affiliate": "🛍️ Affiliate (siap)",
        "duplikat": "⚠️ Duplikat",
        "tanpa_caption": "📝 Tanpa caption",
    }
    for k, v in s.items():
        print(f"  {labels.get(k, k):32}: {v}")

    # estimasi umur pool
    siang, malam = s["random_siang"], s["random_malam"]
    if siang or malam:
        print(f"\n  Estimasi umur pool:")
        if siang:
            print(f"    Siang : {siang} post (~{siang//7} minggu @ 1/hari)")
        if malam:
            print(f"    Malam : {malam} post (~{malam//7} minggu @ 1/hari)")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Proses inbox gambar jadi pool")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--describe", action="store_true")
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()

    image_pool.ensure_dirs()

    if args.list:
        return cmd_list()
    if args.describe:
        return cmd_describe()
    if args.commit:
        return cmd_commit()
    if args.stats:
        return cmd_stats()

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
