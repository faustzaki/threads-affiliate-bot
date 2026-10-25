"""
notion_sync.py — Jembatan Notion <-> SQLite.

PERAN:
  Notion = tempat LO edit (enak dari HP, tabel visual, filter, warna)
  SQLite = tempat BOT baca (cepat, offline, gak butuh internet)

Cara pakai:
  python notion_sync.py --pull     # Notion -> SQLite (lo edit di Notion)
  python notion_sync.py --push     # SQLite -> Notion (bot update status)
  python notion_sync.py --status   # bandingkan dua sisi
  python notion_sync.py --watch    # pull tiap 5 menit (buat cron)

ATURAN:
  - Lo TAMBAH produk baru di Notion -> --pull masukin ke SQLite
  - Bot UPDATE status post -> --push ke Notion
  - GAMBAR tetap di folder STOK/ (Notion gak bisa simpen path lokal)
"""

import argparse
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "affiliate_content.db"
CONFIG = BASE_DIR / "data" / "notion_config.json"

NOTION_DB_ID = "404112a4-07a6-8139-a3d8-c9dbf91c0e45"
NOTION_PAGE = "https://app.notion.com/p/404112a407a68139a3d8c9dbf91c0e45"


# ─────────────────────────────────────────────────────────────
# TOKEN (dibaca dari config Hermes, gak pernah di-print)
# ─────────────────────────────────────────────────────────────

def _load_token():
    import yaml
    for p in [Path.home() / ".hermes" / "config.yaml",
              Path.home() / "AppData" / "Local" / "hermes" / "config.yaml"]:
        if p.exists():
            try:
                cfg = yaml.safe_load(p.read_text(encoding="utf-8"))
                raw = cfg["mcp_servers"]["notion"]["env"]["OPENAPI_MCP_HEADERS"]
                return json.loads(raw)["Authorization"].replace("Bearer ", "").strip()
            except Exception:
                continue
    return None


TOKEN = _load_token()


def notion(method, path, body=None):
    if not TOKEN:
        return {"_error": "no_token"}
    req = urllib.request.Request(
        "https://api.notion.com/v1" + path,
        data=json.dumps(body).encode() if body else None,
        method=method)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Notion-Version", "2022-06-28")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"_error": e.code, "_body": e.read().decode()[:300]}
    except Exception as e:
        return {"_error": str(e)}


# ─────────────────────────────────────────────────────────────
# HELPER BACA PROPERTI NOTION
# ─────────────────────────────────────────────────────────────

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
    return [{"type": "text", "text": {"content": (s or "")[:1900]}}] if s else []


# ─────────────────────────────────────────────────────────────
# PULL: Notion -> SQLite
# ─────────────────────────────────────────────────────────────

def pull():
    """Ambil semua produk dari Notion, masukin ke SQLite."""
    print(f"\n{'='*64}")
    print("  PULL: Notion -> SQLite")
    print(f"{'='*64}")

    res = notion("POST", f"/databases/{NOTION_DB_ID}/query", {"page_size": 100})
    if res.get("_error"):
        print(f"[!] Gagal query Notion: {res}")
        return 1

    pages = res.get("results", [])
    print(f"\n  {len(pages)} produk di Notion\n")

    conn = sqlite3.connect(DB_PATH, timeout=30)
    cur = conn.cursor()

    added = updated = 0
    for pg in pages:
        pr = pg["properties"]
        name = p_text(pr.get("Nama Produk")).strip()
        pid = p_text(pr.get("Product ID"))
        price = p_text(pr.get("Harga")).strip()
        cat = p_text(pr.get("Kategori")).strip()
        link = p_text(pr.get("Link Affiliate")).strip()
        detail = p_text(pr.get("Detail")).strip()
        caption = p_text(pr.get("Caption")).strip()
        status = p_text(pr.get("Status")).strip()

        if not name:
            continue

        # cari by notion page id dulu, lalu by nama
        cur.execute("SELECT id FROM affiliate_catalog WHERE product_name = ?", (name,))
        row = cur.fetchone()

        if row:
            # update
            cur.execute("""
                UPDATE affiliate_catalog
                SET price=?, category=?, affiliate_link=?, highlights=?, caption=?
                WHERE id=?
            """, (price, cat, link, detail, caption, row[0]))
            updated += 1
            print(f"  ~ [{row[0]}] {name[:40]} (update)")
        else:
            # insert baru
            cur.execute("""
                INSERT INTO affiliate_catalog
                (product_name, price, highlights, affiliate_link, category,
                 caption, image_status)
                VALUES (?, ?, ?, ?, ?, ?, 'perlu_gambar')
            """, (name, price, detail, link, cat, caption))
            new_id = cur.lastrowid
            added += 1
            print(f"  + [{new_id}] {name[:40]} (baru)")
            # tulis balik ID ke Notion biar sinkron
            notion("PATCH", f"/pages/{pg['id']}", {
                "properties": {"Product ID": {"number": new_id}}
            })

    conn.commit()
    conn.close()

    print(f"\n  Hasil: {added} baru, {updated} update")
    return 0


# ─────────────────────────────────────────────────────────────
# PUSH: SQLite -> Notion
# ─────────────────────────────────────────────────────────────

def push():
    """Kirim status dari SQLite ke Notion (post_count, status, jumlah gambar)."""
    print(f"\n{'='*64}")
    print("  PUSH: SQLite -> Notion")
    print(f"{'='*64}")

    res = notion("POST", f"/databases/{NOTION_DB_ID}/query", {"page_size": 100})
    if res.get("_error"):
        print(f"[!] Gagal query Notion: {res}")
        return 1

    # peta nama -> page id
    by_name = {}
    for pg in res.get("results", []):
        nm = p_text(pg["properties"].get("Nama Produk")).strip()
        if nm:
            by_name[nm] = pg["id"]

    conn = sqlite3.connect(DB_PATH, timeout=30)
    cur = conn.cursor()
    cur.execute("""SELECT product_name, post_count, caption, image_status, id
                   FROM affiliate_catalog""")
    rows = cur.fetchall()
    conn.close()

    # hitung gambar dari folder STOK
    IMG_EXT = {".jpg", ".jpeg", ".png", ".webp"}
    def count_img(pid):
        dirs = list((BASE_DIR / "STOK" / "02-GAMBAR-AFFILIATE").glob(f"{pid}-*"))
        n = 0
        for d in dirs:
            n += len([f for f in d.rglob("*") if f.suffix.lower() in IMG_EXT])
        return n

    updated = 0
    for name, pc, caption, img_status, pid in rows:
        page_id = by_name.get(name)
        if not page_id:
            continue

        n_img = count_img(pid)
        has_cap = bool(caption)
        if pc and pc > 0:
            status = "Sudah Dipost"
        elif has_cap and n_img > 0:
            status = "Siap Post"
        elif has_cap:
            status = "Perlu Gambar"
        else:
            status = "Perlu Caption"

        slug = name.replace("/", "-").replace(" ", "-")[:30]
        r = notion("PATCH", f"/pages/{page_id}", {
            "properties": {
                "Post Count": {"number": pc or 0},
                "Status": {"select": {"name": status}},
                "Jumlah Gambar": {"number": n_img},
                "Folder Gambar": {"rich_text": rt(f"STOK/02-GAMBAR-AFFILIATE/{pid}-{slug}/")},
            }
        })
        if not r.get("_error"):
            updated += 1
            print(f"  → {name[:38]:38} gbr={n_img} post={pc or 0} {status}")

    print(f"\n  {updated} produk diupdate di Notion")
    return 0


# ─────────────────────────────────────────────────────────────
# STATUS
# ─────────────────────────────────────────────────────────────

def status():
    res = notion("POST", f"/databases/{NOTION_DB_ID}/query", {"page_size": 100})
    n_notion = len(res.get("results", [])) if not res.get("_error") else "ERR"

    conn = sqlite3.connect(DB_PATH, timeout=30)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM affiliate_catalog")
    n_sqlite = cur.fetchone()[0]
    conn.close()

    print(f"\n{'='*52}")
    print(f"  STATUS SYNC")
    print(f"{'='*52}")
    print(f"  Notion  : {n_notion} produk")
    print(f"  SQLite  : {n_sqlite} produk")
    print(f"\n  Notion  : {NOTION_PAGE}")
    print(f"  Token   : {'✅ ada' if TOKEN else '❌ gak ada'}")
    print(f"{'='*52}\n")
    return 0


def watch(interval=300):
    print(f"[watch] pull tiap {interval}s. Ctrl+C buat stop.")
    while True:
        try:
            pull()
        except Exception as e:
            print(f"[watch] error: {e}")
        time.sleep(interval)


def main():
    ap = argparse.ArgumentParser(description="Sync Notion <-> SQLite")
    ap.add_argument("--pull", action="store_true")
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--watch", action="store_true")
    args = ap.parse_args()

    if args.pull:
        return pull()
    if args.push:
        return push()
    if args.status:
        return status()
    if args.watch:
        return watch()

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
