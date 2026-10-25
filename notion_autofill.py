"""
notion_autofill.py — Isi otomatis semua kolom Notion dari 1 URL Shopee.

LO CUMA PERLU ISI:
  - Link Produk (URL Shopee apapun bentuknya)

BOT OTOMATIS ISI:
  - Nama Produk     (dari slug URL)
  - Product ID      (dari item_id Shopee)
  - Harga           (dari URL kalau ada, atau "-")
  - Kategori        (deteksi dari nama: kulot->bawahan, kemeja->atasan, dst)
  - Link Affiliate  (generate an_redir)
  - Detail          (template per kategori)
  - Caption         (generate + quality gate)
  - Prompt Gambar   (template per kategori)
  - Folder Gambar   (path otomatis)
  - Status          (Perlu Gambar)

Cara pakai:
  python notion_autofill.py                    # isi semua baris yang cuma ada link
  python notion_autofill.py --dry-run          # lihat dulu, gak nulis
  python notion_autofill.py --page-id XXX      # isi 1 baris tertentu
"""

import argparse
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

import affiliate_link
from affiliate_flow import build_image_prompt
from quality_gate import run_quality_gate
from style_engine import check_ai_tells

NOTION_DB_ID = "404112a4-07a6-8139-a3d8-c9dbf91c0e45"
AFFILIATE_ID = "11342632100"


# ─────────────────────────────────────────────────────────────
# TOKEN
# ─────────────────────────────────────────────────────────────

def _load_token():
    import json as _j
    import yaml
    for p in [Path.home() / ".hermes" / "config.yaml",
              Path.home() / "AppData" / "Local" / "hermes" / "config.yaml"]:
        if p.exists():
            try:
                cfg = yaml.safe_load(p.read_text(encoding="utf-8"))
                raw = cfg["mcp_servers"]["notion"]["env"]["OPENAPI_MCP_HEADERS"]
                return _j.loads(raw)["Authorization"].replace("Bearer ", "").strip()
            except Exception:
                continue
    return None


TOKEN = _load_token()


def notion(method, path, body=None):
    import json as _j
    if not TOKEN:
        return {"_error": "no_token"}
    req = urllib.request.Request(
        "https://api.notion.com/v1" + path,
        data=_j.dumps(body).encode() if body else None,
        method=method)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Notion-Version", "2022-06-28")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return _j.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"_error": e.code, "_body": e.read().decode()[:400]}
    except Exception as e:
        return {"_error": str(e)}


def p_text(prop):
    if not prop:
        return ""
    t = prop.get("type")
    if t == "title":
        return "".join(x.get("plain_text", "") for x in prop.get("title", []))
    if t == "rich_text":
        return "".join(x.get("plain_text", "") for x in prop.get("rich_text", []))
    if t == "url":
        return prop.get("url") or ""
    if t == "select":
        return (prop.get("select") or {}).get("name", "")
    if t == "number":
        return prop.get("number")
    return ""


def rt(s):
    import json as _j
    return [{"type": "text", "text": {"content": (s or "")[:1900]}}] if s else []


# ─────────────────────────────────────────────────────────────
# EKSTRAK DATA DARI URL
# ─────────────────────────────────────────────────────────────

def parse_shopee_url(url):
    """
    Ambil info dari URL Shopee. Support:
      - https://shopee.co.id/Nama-Produk-i.123456.789012
      - https://shopee.co.id/Nama-Produk-i.123456.789012?xxx
      - https://s.shopee.co.id/xxxxx  (shortlink, gak ada nama)
    Return: dict(nama, item_id, shop_id, valid)
    """
    out = {"nama": "", "item_id": None, "shop_id": None, "valid": False}

    # shortlink -> gak bisa parse nama
    if "s.shopee" in url or re.search(r"shopee\.co\.id/[A-Za-z0-9]{8,}$", url):
        out["valid"] = False
        return out

    # pola -i.{shop}.{item}
    m = re.search(r"-i\.(\d+)\.(\d+)", url)
    if m:
        out["shop_id"] = int(m.group(1))
        out["item_id"] = int(m.group(2))
        out["valid"] = True

    # ambil nama dari path
    path = urllib.parse.urlparse(url).path
    slug = path.strip("/").split("/")[-1]
    slug = re.sub(r"-i\.\d+\.\d+.*$", "", slug)
    # Shopee pakai dash sebagai spasi
    nama = urllib.parse.unquote(slug).replace("-", " ").strip()
    nama = re.sub(r"\s+", " ", nama)
    out["nama"] = nama

    return out


def detect_kategori(nama):
    """Deteksi kategori dari nama produk. Urutan penting: yang spesifik dulu."""
    n = (nama or "").lower()

    # urutan cek: spesifik -> umum
    # hijab harus dicek sebelum atasan (pashmina kaos = hijab, bukan kaos)
    rules = [
        ("hijab", ["pashmina", "hijab", "kerudung", "scarf", "voal", "bergo", "khimar"]),
        ("outer", ["cardigan", "jaket", "blazer", "outer", "vest", "bolero", "kimono"]),
        ("bawahan", ["kulot", "celana", "rok", "skirt", "pants", "palazzo", "jeans", "short"]),
        ("rumahan", ["one set", "set crinkle", "set ", "dress", "gamis", "jumpsuit",
                     "terusan", "piyama", "daster"]),
        ("aksesoris", ["tas", "sepatu", "sandal", "belt", "topi", "gelang", "kalung"]),
        ("atasan", ["kemeja", "blouse", "kaos", "shirt", "top", "tunik", "kaus", "t-shirt"]),
    ]
    for kat, keys in rules:
        for k in keys:
            if k in n:
                return kat
    return "bawahan"   # default


def build_detail(nama, kategori):
    """Bikin deskripsi produk dari nama + kategori."""
    templates = {
        "bawahan": "bahan adem, cuttingan longgar, pinggang karet, gak nerawang",
        "atasan": "bahan jatuh, gak kaku, lengan longgar, cocok daily",
        "hijab": "bahan flowy, gak licin, jatuh di bahu, mudah dibentuk",
        "outer": "rajut lembut, gak gerah, potongan crop, mudah dipadupadan",
        "rumahan": "bahan crinkle airflow, adem, gak perlu disetrika",
        "aksesoris": "bahan awet, warna netral, mudah dipadupadan",
    }
    return templates.get(kategori, "bahan nyaman, cocok buat daily")


def build_caption(nama, kategori, detail):
    """
    Generate caption UNIK per produk, pakai masalah spesifik per kategori.
    Validasi quality gate + AI detection.
    Return: (caption, score, ai_score) atau (None, 0, 0) kalau gagal.
    """
    n = nama.lower()

    # tentuin kata produk yang natural
    produk = None
    for k in ["kulot", "kemeja", "pashmina", "cardigan", "set", "dress", "celana", "rok", "blouse"]:
        if k in n:
            produk = k
            break
    if not produk:
        produk = "ini"

    # masalah khas per kategori (biar caption gak seragam)
    masalah = {
        "bawahan": [
            ("nerawang", "udah 3x beli yang murah malah keliatan dalemnya"),
            ("melar", "baru dipake 2x udah melar di lutut, kesel"),
            ("panjang", "tinggi gue 155 jadi semua keliatan kebesaran"),
        ],
        "atasan": [
            ("lecek", "punya gue selalu lecek abis 1x pake, nyerah"),
            ("kaku", "bahannya kaku banget, gak jatuh di badan"),
            ("gerah", "adem di awal tapi lama-lama panas sendiri"),
        ],
        "hijab": [
            ("licin", "selalu melorot tiap gerak, harus dipegangin terus"),
            ("kaku", "gak mau jatuh di bahu, kaku banget"),
            ("nerawang", "yang tipis malah keliatan rambutnya, gimana dong"),
        ],
        "outer": [
            ("gerah", "rajut tebel, dipake 10 menit udah keringetan"),
            ("melar", "bagian siku langsung melar, gak balik lagi"),
            ("bulu", "baru 2x cuci udah berbulu semua, sedih"),
        ],
        "rumahan": [
            ("luntur", "adem tapi warnanya luntur abis dicuci"),
            ("kusut", "katanya anti kusut, nyatanya tetep kusut"),
            ("panas", "bahannya gak napas, gerah seharian"),
        ],
        "aksesoris": [
            ("cepat rusak", "baru seminggu udah lepas jahitannya"),
            ("warna", "warnanya beda jauh sama foto"),
            ("kecil", "ukuran ternyata lebih kecil dari yang gue kira"),
        ],
    }

    pool = masalah.get(kategori, masalah["bawahan"])

    # template caption, variasikan struktur
    templates = [
        lambda p, m, d: f"spill {p} yang beneran gak {m} dong, budget 70rb.\n{d}",
        lambda p, m, d: f"kalian beli {p} di toko mana sih?\n{d}",
        lambda p, m, d: f"ada yang tau {p} yang gak {m}?\nkayaknya semua yang murah pasti gitu deh",
        lambda p, m, d: f"baru sadar semua {p} gue masalahnya sama.\n{d}",
        lambda p, m, d: f"spill {p} yang gak {m} dong.\n{d}",
    ]

    for i, (masalah_kata, detail_kata) in enumerate(pool):
        tmpl = templates[i % len(templates)]
        cap = tmpl(produk, masalah_kata, detail_kata)
        q = run_quality_gate(cap)
        ai_score, _ = check_ai_tells(cap)
        if q.passed and ai_score == 0:
            return cap, q.score, ai_score

    return None, 0, 0


# ─────────────────────────────────────────────────────────────
# AUTOFILL
# ─────────────────────────────────────────────────────────────

def autofill(dry_run=False, page_id=None):
    print(f"\n{'='*68}")
    print(f"  AUTOFILL NOTION {'(DRY RUN)' if dry_run else ''}")
    print(f"{'='*68}\n")

    if page_id:
        res = notion("GET", f"/pages/{page_id}")
        pages = [res] if not res.get("_error") else []
    else:
        res = notion("POST", f"/databases/{NOTION_DB_ID}/query", {"page_size": 100})
        if res.get("_error"):
            print(f"[!] Gagal query: {res}")
            return 1
        pages = res.get("results", [])

    print(f"  {len(pages)} baris diperiksa\n")

    done = skip = fail = 0

    for pg in pages:
        pr = pg["properties"]
        pid_val = p_text(pr.get("Product ID"))
        nama_now = p_text(pr.get("Nama Produk")).strip()
        link_now = p_text(pr.get("Link Affiliate")).strip()

        # cari URL sumber: cek Link Affiliate dulu, kalau kosong cek Nama Produk
        src_url = ""
        if "shopee" in link_now:
            src_url = link_now
        elif "shopee" in nama_now:
            src_url = nama_now

        if not src_url:
            print(f"  ⊘ [{pid_val or '?'}] gak ada URL Shopee -> skip")
            skip += 1
            continue

        # kalau udah lengkap, skip
        if nama_now and "http" not in nama_now and link_now and "shopee" in link_now \
                and p_text(pr.get("Prompt Gambar")) and p_text(pr.get("Caption")):
            print(f"  ✓ [{pid_val}] {nama_now[:34]} udah lengkap -> skip")
            skip += 1
            continue

        # parse URL
        info = parse_shopee_url(src_url)

        # kalau shortlink, gak bisa dapet nama -> pakai nama yang udah ada
        if not info["valid"] and nama_now and "http" not in nama_now:
            nama = nama_now
        elif info["nama"]:
            nama = info["nama"]
        else:
            print(f"  ✗ [{pid_val or '?'}] URL shortlink & gak ada nama -> skip")
            print(f"      kirim URL lengkap (shopee.co.id/Nama-i.123.456)")
            fail += 1
            continue

        # bangun semua field
        kategori = detect_kategori(nama)
        detail = build_detail(nama, kategori)
        caption, qscore, aiscore = build_caption(nama, kategori, detail)
        prompt = build_image_prompt(nama, detail, kategori)

        # link affiliate
        aff_link = ""
        if info["valid"]:
            try:
                clean = affiliate_link.normalize_url(src_url)
                aff_link = affiliate_link.build_link(clean, AFFILIATE_ID, "threads")
            except Exception as e:
                print(f"      [warn] gagal bikin link: {e}")

        slug = nama.replace("/", "-").replace(" ", "-")[:30]
        folder = f"STOK/02-GAMBAR-AFFILIATE/{pid_val or '?'}-{slug}/"

        print(f"  → [{pid_val or '?'}] {nama[:40]}")
        print(f"      kategori : {kategori}")
        print(f"      detail   : {detail[:50]}")
        print(f"      caption  : {(caption or 'GAGAL')[:50]}... ({qscore}/100, AI {aiscore})")
        print(f"      prompt   : {prompt[:50]}...")

        if dry_run:
            done += 1
            continue

        # tulis ke Notion
        props = {
            "Nama Produk": {"title": rt(nama)},
            "Kategori": {"select": {"name": kategori}},
            "Detail": {"rich_text": rt(detail)},
            "Prompt Gambar": {"rich_text": rt(prompt)},
            "Folder Gambar": {"rich_text": rt(folder)},
            "Status": {"select": {"name": "Perlu Gambar"}},
        }
        if caption:
            props["Caption"] = {"rich_text": rt(caption)}
        if aff_link:
            props["Link Affiliate"] = {"url": aff_link}
        if info["item_id"]:
            props["Product ID"] = {"number": info["item_id"]}

        r = notion("PATCH", f"/pages/{pg['id']}", {"properties": props})
        if r.get("_error"):
            print(f"      [X] gagal tulis: {r}")
            fail += 1
        else:
            print(f"      ✅ tersimpan")
            done += 1
        print()

    print(f"{'='*68}")
    print(f"  HASIL: {done} diisi, {skip} skip, {fail} gagal")
    print(f"{'='*68}\n")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Auto-isi kolom Notion dari URL Shopee")
    ap.add_argument("--dry-run", action="store_true", help="Lihat dulu tanpa nulis")
    ap.add_argument("--page-id", help="Isi 1 baris tertentu")
    args = ap.parse_args()

    if not TOKEN:
        print("[!] Token Notion gak ketemu di config Hermes")
        return 1

    return autofill(dry_run=args.dry_run, page_id=args.page_id)


if __name__ == "__main__":
    sys.exit(main())
