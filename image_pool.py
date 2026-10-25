"""
image_pool.py — Manajemen pool gambar dengan rotasi adil.

Menjawab pertanyaan: "affiliate dan random, folder-nya dipisah atau digabung?"

JAWABAN: DIPISAH. Alasannya beda fungsi total:
  - random  -> gambar persona (orangnya), caption nyesuain visual
  - affiliate -> gambar produk (barangnya), caption nyesuain produk

Struktur:
  media/
    inbox/                  <- lo drop gambar baru (belum diproses)
    pool/
      random/
        siang/  m_001.jpg + m_001.json
        malam/  s_001.jpg + s_001.json
      affiliate/
        01_kulot_linen/
          a_001.jpg + a_001.json

Setiap gambar punya sidecar .json berisi caption + metadata.
"""

import json
import hashlib
import shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta

BASE_DIR = Path(__file__).resolve().parent
MEDIA_DIR = BASE_DIR / "media"
INBOX_DIR = MEDIA_DIR / "inbox"
POOL_DIR = MEDIA_DIR / "pool"
RANDOM_DIR = POOL_DIR / "random"
AFFILIATE_DIR = POOL_DIR / "affiliate"

WIB = timezone(timedelta(hours=7))
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp"}


def ensure_dirs():
    for d in [INBOX_DIR, POOL_DIR, RANDOM_DIR / "siang", RANDOM_DIR / "malam", AFFILIATE_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def file_hash(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sidecar_path(img_path):
    return Path(str(img_path).rsplit(".", 1)[0] + ".json")


def read_sidecar(img_path):
    sp = sidecar_path(img_path)
    if sp.exists():
        try:
            return json.loads(sp.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def write_sidecar(img_path, data):
    sp = sidecar_path(img_path)
    sp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return sp


# ─────────────────────────────────────────────────────────────
# DEDUPLIKASI
# ─────────────────────────────────────────────────────────────

def build_hash_index():
    """Index semua hash gambar di pool. Deteksi duplikat."""
    idx = {}
    for img in POOL_DIR.rglob("*"):
        if img.suffix.lower() in IMG_EXT and img.is_file():
            idx.setdefault(file_hash(img), []).append(str(img.relative_to(MEDIA_DIR)))
    return idx


def find_duplicates():
    """Return dict hash -> list file yang isinya sama."""
    return {h: files for h, files in build_hash_index().items() if len(files) > 1}


# ─────────────────────────────────────────────────────────────
# ROTASI POOL
# ─────────────────────────────────────────────────────────────

def list_pool(slot=None, kind="random"):
    """
    List gambar siap pakai.

    Args:
        slot: "siang" | "malam" | None (semua)
        kind: "random" | "affiliate"
    """
    ensure_dirs()
    base = RANDOM_DIR / slot if (kind == "random" and slot) else (
        RANDOM_DIR if kind == "random" else AFFILIATE_DIR)

    out = []
    for img in sorted(base.rglob("*")):
        if img.suffix.lower() not in IMG_EXT:
            continue
        meta = read_sidecar(img) or {}
        out.append({
            "path": str(img),
            "rel": str(img.relative_to(MEDIA_DIR)),
            "caption": meta.get("caption", ""),
            "used": meta.get("used", 0),
            "last_used": meta.get("last_used") or "",
            "slot": meta.get("slot", slot or ""),
            "tema": meta.get("tema", ""),
            "visual": meta.get("visual", ""),
            "product_id": meta.get("product_id"),
        })
    return out


def pick_next(slot=None, kind="random"):
    """
    Pilih gambar berikutnya: yang paling jarang dipakai, dan paling lama gak dipakai.

    Logika sama dengan get_next_product_to_post() di db.py:
      ORDER BY used ASC, last_used ASC

    Return: dict gambar atau None kalau pool kosong.
    """
    items = list_pool(slot=slot, kind=kind)
    # hanya yang punya caption (siap pakai)
    ready = [i for i in items if i["caption"].strip()]
    if not ready:
        return None

    ready.sort(key=lambda x: (x["used"], x["last_used"] or "0000"))
    return ready[0]


def mark_used(img_path, threads_url=None):
    """Tandai gambar udah dipakai -> naikin counter."""
    meta = read_sidecar(img_path) or {}
    meta["used"] = meta.get("used", 0) + 1
    meta["last_used"] = datetime.now(WIB).isoformat()
    if threads_url:
        meta.setdefault("posted_urls", []).append(threads_url)
    write_sidecar(img_path, meta)
    return meta


# ─────────────────────────────────────────────────────────────
# LIFECYCLE: DIPAKAI -> ARSIP -> HAPUS
# ─────────────────────────────────────────────────────────────

# Gambar random: habis dipakai 1x, langsung pindah arsip.
# Alasannya: gambar random = foto orang/gaya. Kalau dipost 2x, follower notice.
# Gambar affiliate: boleh dipakai ulang (produk sama, angle beda), tapi
#   maksimal MAX_AFFILIATE_USE kali, lalu arsip.

MAX_RANDOM_USE = 1        # random cuma boleh 1x
MAX_AFFILIATE_USE = 3     # affiliate boleh 3x (beda caption/angle)
ARSIP_DIR = MEDIA_DIR / "arsip"


def _arsip_path(img_path):
    """Tentukan path arsip, pertahankan struktur (random/siang, affiliate/01_produk)."""
    p = Path(img_path)
    try:
        rel = p.relative_to(MEDIA_DIR)
    except ValueError:
        rel = Path(p.name)
    dest = ARSIP_DIR / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    return dest


def retire_if_exhausted(img_path, kind="random"):
    """
    Setelah dipost, cek apakah gambar udah habis masa pakai.
    Kalau iya -> pindah ke media/arsip/ (bukan langsung hapus).

    Return: (retired: bool, reason: str)
    """
    meta = read_sidecar(img_path) or {}
    used = meta.get("used", 0)
    limit = MAX_RANDOM_USE if kind == "random" else MAX_AFFILIATE_USE

    if used < limit:
        return False, f"masih boleh dipakai ({used}/{limit})"

    src = Path(img_path)
    if not src.exists():
        return False, "file gak ada"

    dest = _arsip_path(src)
    # hindari nimpa
    n = 1
    base_dest = dest
    while dest.exists():
        dest = base_dest.with_name(f"{base_dest.stem}_{n}{base_dest.suffix}")
        n += 1

    shutil.move(str(src), str(dest))

    # pindahin sidecar juga
    side_src = sidecar_path(src)
    if side_src.exists():
        meta["retired_at"] = datetime.now(WIB).isoformat()
        meta["retired_reason"] = f"habis masa pakai ({used}/{limit})"
        write_sidecar(dest, meta)
        try:
            side_src.unlink()
        except OSError:
            pass

    return True, f"dipindah ke arsip ({used}/{limit})"


def purge_arsip(days=30, dry_run=False):
    """
    Hapus gambar di arsip yang udah lewat N hari.
    Default 30 hari — cukup buat audit kalau ada masalah.

    Return: jumlah file dihapus.
    """
    ensure_dirs()
    if not ARSIP_DIR.exists():
        return 0

    cutoff = datetime.now(WIB) - timedelta(days=days)
    n = 0
    for f in list(ARSIP_DIR.rglob("*")):
        if not f.is_file():
            continue
        if f.suffix.lower() not in IMG_EXT and f.suffix.lower() != ".json":
            continue
        mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=WIB)
        if mtime < cutoff:
            if dry_run:
                print(f"  [DRY] hapus {f.relative_to(MEDIA_DIR)}")
            else:
                try:
                    f.unlink()
                except OSError:
                    continue
            n += 1
    return n


def arsip_stats():
    """Ringkasan isi arsip."""
    ensure_dirs()
    if not ARSIP_DIR.exists():
        return {"files": 0, "mb": 0, "oldest": None}
    files = [f for f in ARSIP_DIR.rglob("*")
             if f.is_file() and f.suffix.lower() in IMG_EXT]
    total = sum(f.stat().st_size for f in files)
    oldest = None
    if files:
        oldest = min(datetime.fromtimestamp(f.stat().st_mtime, tz=WIB) for f in files)
    return {"files": len(files), "mb": round(total / 1024 / 1024, 2), "oldest": oldest}


# ─────────────────────────────────────────────────────────────
# INBOX -> POOL
# ─────────────────────────────────────────────────────────────

def list_inbox():
    """Gambar baru yang belum diproses."""
    ensure_dirs()
    out = []
    for img in sorted(INBOX_DIR.rglob("*")):
        if img.suffix.lower() in IMG_EXT and img.is_file():
            out.append({"path": str(img), "rel": str(img.relative_to(MEDIA_DIR))})
    return out


def move_to_pool(img_path, slot, caption, tema="", visual="", kind="random", subdir=None):
    """
    Pindahkan gambar dari inbox ke pool, sekalian tulis sidecar.

    Args:
        img_path: path gambar di inbox
        slot: "siang" | "malam" (buat random) atau nama produk (buat affiliate)
        caption: caption yang udah disetujui
        tema: fashion/kos/kuliner/kerja/sosial/selfcare/random
        visual: deskripsi visual dari vision
        kind: "random" | "affiliate"
    """
    ensure_dirs()
    src = Path(img_path)
    if not src.exists():
        raise FileNotFoundError(src)

    # cegah duplikat masuk pool
    h = file_hash(src)
    for existing, files in build_hash_index().items():
        if existing == h:
            return {"skipped": True, "reason": "duplikat", "existing": files}

    if kind == "affiliate":
        target_dir = AFFILIATE_DIR / (subdir or slot)
    else:
        target_dir = RANDOM_DIR / slot
    target_dir.mkdir(parents=True, exist_ok=True)

    # nama unik
    prefix = "m" if slot == "malam" else "s"
    if kind == "affiliate":
        prefix = "a"
    n = 1
    while (target_dir / f"{prefix}_{n:03d}{src.suffix.lower()}").exists():
        n += 1
    dest = target_dir / f"{prefix}_{n:03d}{src.suffix.lower()}"

    shutil.move(str(src), str(dest))

    meta = {
        "file": dest.name,
        "kind": kind,
        "slot": slot,
        "tema": tema,
        "visual": visual,
        "caption": caption,
        "used": 0,
        "last_used": None,
        "created": datetime.now(WIB).isoformat(),
        "hash": h,
    }
    write_sidecar(dest, meta)
    return {"skipped": False, "path": str(dest), "meta": meta}


# ─────────────────────────────────────────────────────────────
# STATISTIK
# ─────────────────────────────────────────────────────────────

def stats():
    ensure_dirs()
    s = {
        "inbox": len(list_inbox()),
        "random_siang": len([i for i in list_pool("siang") if i["caption"]]),
        "random_malam": len([i for i in list_pool("malam") if i["caption"]]),
        "affiliate": len([i for i in list_pool(kind="affiliate") if i["caption"]]),
        "duplikat": len(find_duplicates()),
        "tanpa_caption": len([i for i in list_pool(kind="random") if not i["caption"]])
                        + len([i for i in list_pool(kind="affiliate") if not i["caption"]]),
    }
    return s


# ─────────────────────────────────────────────────────────────
# TEST
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ensure_dirs()
    print("=== STRUKTUR FOLDER ===")
    print(f"  inbox     : {INBOX_DIR}")
    print(f"  random    : {RANDOM_DIR}")
    print(f"  affiliate : {AFFILIATE_DIR}")

    print("\n=== STATISTIK ===")
    for k, v in stats().items():
        print(f"  {k:16}: {v}")

    print("\n=== TEST DEDUP (dari gambar lama) ===")
    old = BASE_DIR / "indo_real_1.jpg"
    old2 = BASE_DIR / "dress_kosan_1.jpg"
    if old.exists() and old2.exists():
        h1, h2 = file_hash(old), file_hash(old2)
        print(f"  indo_real_1.jpg   hash: {h1[:12]}")
        print(f"  dress_kosan_1.jpg hash: {h2[:12]}")
        print(f"  SAMA? {h1 == h2}  <- ini kenapa dedup penting")

    print("\n=== TEST PICK NEXT (pool kosong = None) ===")
    print(f"  pick_next('malam'): {pick_next('malam')}")
