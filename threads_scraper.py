"""
threads_scraper.py — Scraping post Threads untuk riset niche & engagement.

Yang diambil:
  - Topik/kategori trending
  - Post terpopuler per topik
  - Angka engagement (likes, replies, reposts)
  - Jam posting
  - Niche akun

Cara pakai:
  python threads_scraper.py --topics "ootd,fashion,kuliner" --limit 20
  python threads_scraper.py --trending          # topik trending hari ini
  python threads_scraper.py --analyze           # analisis hasil terakhir
  python threads_scraper.py --report            # laporan lengkap

Output: data/threads_research.json
"""

import asyncio
import json
import re
import sys
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta

from playwright.async_api import async_playwright

BASE_DIR = Path(__file__).resolve().parent
SESSION_FILE = BASE_DIR / "threads_session.json"
OUT_DIR = BASE_DIR / "data"
OUT_FILE = OUT_DIR / "threads_research.json"

WIB = timezone(timedelta(hours=7))

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")


# ─────────────────────────────────────────────────────────────
# SCRAPE TOPIK
# ─────────────────────────────────────────────────────────────

async def scrape_topic(pg, topic, limit=20):
    """
    Scrape post terpopuler untuk satu topik.

    Return list dict: author, text, likes, replies, reposts, age
    """
    url = f"https://www.threads.com/search?q={topic}&serp_type=default"
    await pg.goto(url, wait_until="domcontentloaded", timeout=60000)
    await pg.wait_for_timeout(5000)

    # klik tab "Terpopuler" kalau ada
    try:
        pop = pg.get_by_text("Terpopuler", exact=True).first
        if await pop.count():
            await pop.click()
            await pg.wait_for_timeout(3500)
    except Exception:
        pass

    # scroll buat load lebih banyak
    for _ in range(4):
        await pg.mouse.wheel(0, 1400)
        await pg.wait_for_timeout(1400)

    # ekstrak data post via JS
    raw = await pg.evaluate("""() => {
        const out = [];
        // post container: cari elemen yang punya link ke /post/
        const links = Array.from(document.querySelectorAll('a[href*="/post/"]'));
        const seen = new Set();

        for (const a of links) {
            const href = a.getAttribute('href');
            if (!href || seen.has(href)) continue;

            // naik cari container post
            let el = a;
            for (let i=0;i<14;i++){
                if(!el.parentElement) break;
                el = el.parentElement;
                if ((el.innerText||'').length > 80) break;
            }
            const txt = (el.innerText||'').trim();
            if (txt.length < 40) continue;
            seen.add(href);

            out.push({
                href: href,
                raw: txt.slice(0, 900)
            });
        }
        return out;
    }""")

    posts = []
    seen_texts = set()
    for item in raw[:limit * 3]:   # ambil lebih banyak, nanti di-dedup
        parsed = parse_post(item["raw"])
        if not parsed:
            continue
        # dedup berdasarkan teks (bukan URL, karena URL bisa beda)
        key = parsed["text"][:80].lower()
        if key in seen_texts:
            continue
        seen_texts.add(key)
        parsed["topic"] = topic
        parsed["url"] = ("https://www.threads.com" + item["href"]
                         if item["href"].startswith("/") else item["href"])
        posts.append(parsed)
        if len(posts) >= limit:
            break

    return posts


def parse_post(raw):
    """
    Parse teks mentah jadi struktur.

    Format Threads feed biasanya:
        username
        [badge]
        [waktu]
        teks post...
        [angka likes]
        [angka replies]
        [angka reposts]
    """
    lines = [l.strip() for l in raw.split("\n") if l.strip()]
    if len(lines) < 3:
        return None

    # cari pola waktu
    age_pat = re.compile(r'^(\d+)\s*(menit|jam|hari|mgg|minggu|dtk|detik)$', re.I)
    age_idx = None
    age_val = ""

    for i, l in enumerate(lines[:8]):
        if age_pat.match(l):
            age_idx = i
            age_val = l
            break

    if age_idx is None:
        return None

    author = lines[0] if age_idx > 0 else "?"

    # teks post = setelah waktu, sebelum angka-angka
    text_lines = []
    for l in lines[age_idx+1:]:
        if re.fullmatch(r'\d+[\.,]?\d*[rbk]?', l, re.I):
            break
        text_lines.append(l)

    text = " ".join(text_lines).strip()
    if len(text) < 15:
        return None

    # angka engagement = sisa setelah teks
    numbers = [l for l in lines[age_idx+1:] if re.fullmatch(r'\d+[\.,]?\d*[rbk]?', l, re.I)]

    def to_int(s):
        s = s.lower().replace(",", ".")
        if s.endswith("rb"):
            return int(float(s[:-2]) * 1000)
        if s.endswith("k"):
            return int(float(s[:-1]) * 1000)
        if s.endswith("b"):
            return int(float(s[:-1]) * 1000000)
        try:
            return int(float(s))
        except Exception:
            return 0

    vals = [to_int(n) for n in numbers[:3]]
    while len(vals) < 3:
        vals.append(0)

    likes, replies, reposts = vals[0], vals[1], vals[2]

    return {
        "author": author,
        "text": text[:400],
        "likes": likes,
        "replies": replies,
        "reposts": reposts,
        "engagement": likes + replies * 2 + reposts * 3,
        "age": age_val,
        "n_lines": len(text_lines),
        "has_emoji": bool(re.search(r'[\U0001F300-\U0001FAFF]', text)),
        "has_question": '?' in text,
        "length": len(text),
    }


# ─────────────────────────────────────────────────────────────
# SCRAPE TRENDING TOPICS
# ─────────────────────────────────────────────────────────────

async def scrape_trending(pg):
    """Ambil topik trending dari halaman search."""
    await pg.goto("https://www.threads.com/search", wait_until="domcontentloaded", timeout=60000)
    await pg.wait_for_timeout(5000)

    topics = await pg.evaluate("""() => {
        const out = [];
        const els = Array.from(document.querySelectorAll('a[href*="q="]'));
        for (const a of els) {
            const t = (a.innerText||'').trim();
            if (t && t.length < 40) out.push(t);
        }
        return [...new Set(out)].slice(0, 40);
    }""")
    return topics


# ─────────────────────────────────────────────────────────────
# ANALISIS
# ─────────────────────────────────────────────────────────────

def analyze(posts):
    """Analisis pola dari hasil scraping."""
    if not posts:
        return {}

    # group per topik
    by_topic = {}
    for p in posts:
        by_topic.setdefault(p["topic"], []).append(p)

    topic_stats = []
    for topic, ps in by_topic.items():
        engs = [p["engagement"] for p in ps]
        topic_stats.append({
            "topic": topic,
            "n_posts": len(ps),
            "total_engagement": sum(engs),
            "avg_engagement": sum(engs) // len(engs),
            "max_engagement": max(engs),
            "median_likes": sorted(p["likes"] for p in ps)[len(ps)//2],
        })
    topic_stats.sort(key=lambda x: -x["avg_engagement"])

    # pola konten
    top = sorted(posts, key=lambda x: -x["engagement"])[:30]

    def pct(ps, cond):
        return round(sum(1 for p in ps if cond(p)) / len(ps) * 100) if ps else 0

    patterns = {
        "ada_emoji": pct(top, lambda p: p["has_emoji"]),
        "ada_pertanyaan": pct(top, lambda p: p["has_question"]),
        "panjang_rata2": sum(p["length"] for p in top) // len(top) if top else 0,
        "baris_rata2": sum(p["n_lines"] for p in top) // len(top) if top else 0,
    }

    # distribusi panjang
    lengths = [p["length"] for p in top]
    buckets = {"<100": 0, "100-200": 0, "200-350": 0, "350-500": 0, ">500": 0}
    for l in lengths:
        if l < 100: buckets["<100"] += 1
        elif l < 200: buckets["100-200"] += 1
        elif l < 350: buckets["200-350"] += 1
        elif l < 500: buckets["350-500"] += 1
        else: buckets[">500"] += 1

    return {
        "total_posts": len(posts),
        "topics": topic_stats,
        "patterns": patterns,
        "length_dist": buckets,
        "top_posts": top[:10],
    }


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

async def run_scrape(topics, limit):
    OUT_DIR.mkdir(exist_ok=True)

    if not SESSION_FILE.exists():
        print(f"[!] Session gak ada: {SESSION_FILE}")
        return 1

    all_posts = []
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="chrome", headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"])
        ctx = await b.new_context(storage_state=SESSION_FILE,
            user_agent=UA, viewport={"width": 1280, "height": 1600}, locale="id-ID")
        pg = await ctx.new_page()

        for i, topic in enumerate(topics, 1):
            print(f"\n[{i}/{len(topics)}] Scraping: {topic}")
            try:
                posts = await scrape_topic(pg, topic, limit)
                print(f"    -> {len(posts)} post")
                all_posts.extend(posts)
            except Exception as e:
                print(f"    [!] Error: {type(e).__name__}: {e}")

        await b.close()

    data = {
        "scraped_at": datetime.now(WIB).isoformat(),
        "topics": topics,
        "posts": all_posts,
        "analysis": analyze(all_posts),
    }

    # MERGE dengan data lama (jangan overwrite) — biar scrape bertahap gak hilang
    if OUT_FILE.exists():
        try:
            old = json.loads(OUT_FILE.read_text(encoding="utf-8"))
            old_posts = old.get("posts", [])
            # dedup by text
            seen = {p["text"][:80].lower() for p in all_posts}
            merged = list(all_posts)
            for op in old_posts:
                if op["text"][:80].lower() not in seen:
                    merged.append(op)
            all_topics = list(dict.fromkeys(old.get("topics", []) + topics))
            data = {
                "scraped_at": datetime.now(WIB).isoformat(),
                "topics": all_topics,
                "posts": merged,
                "analysis": analyze(merged),
            }
            print(f"[merge] +{len(old_posts)} post lama = {len(merged)} total")
        except Exception as e:
            print(f"[merge] gagal merge, pakai data baru: {e}")

    OUT_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n✅ Tersimpan: {OUT_FILE}")
    print(f"   Post baru     : {len(all_posts)}")
    print(f"   Total di file : {data['analysis']['total_posts']}")

    print_analysis(data["analysis"])
    return 0


def print_analysis(a):
    if not a:
        print("[!] Gak ada data buat dianalisis")
        return

    print(f"\n{'='*70}")
    print(f"  ANALISIS ({a['total_posts']} post)")
    print(f"{'='*70}")

    print(f"\n📊 PERINGKAT TOPIK (by avg engagement):")
    for i, t in enumerate(a["topics"], 1):
        print(f"  {i:2}. {t['topic']:20} avg={t['avg_engagement']:6} "
              f"max={t['max_engagement']:6} median_like={t['median_likes']:5}")

    print(f"\n🎯 POLA KONTEN (top 30 post):")
    p = a["patterns"]
    print(f"  Pakai emoji      : {p['ada_emoji']}%")
    print(f"  Ada pertanyaan   : {p['ada_pertanyaan']}%")
    print(f"  Panjang rata-rata: {p['panjang_rata2']} char")
    print(f"  Baris rata-rata  : {p['baris_rata2']}")

    print(f"\n📏 DISTRIBUSI PANJANG:")
    for k, v in a["length_dist"].items():
        bar = "█" * v
        print(f"  {k:10} {v:3} {bar}")

    print(f"\n🔥 TOP 10 POST:")
    for i, p in enumerate(a["top_posts"], 1):
        print(f"\n  {i}. @{p['author']} | {p['age']} | "
              f"❤️{p['likes']} 💬{p['replies']} 🔁{p['reposts']}")
        print(f"     {p['text'][:130]}")


def load_and_report():
    if not OUT_FILE.exists():
        print(f"[!] Belum ada data. Jalankan: python threads_scraper.py --topics \"ootd\"")
        return 1
    data = json.loads(OUT_FILE.read_text(encoding="utf-8"))
    print(f"Data dari: {data['scraped_at']}")
    print(f"Topik: {', '.join(data['topics'])}")
    print_analysis(data["analysis"])
    return 0


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Threads scraper untuk riset niche")
    ap.add_argument("--topics", help="Topik dipisah koma: ootd,fashion,kuliner")
    ap.add_argument("--limit", type=int, default=20, help="Post per topik")
    ap.add_argument("--trending", action="store_true", help="Lihat topik trending")
    ap.add_argument("--analyze", action="store_true", help="Analisis data terakhir")
    ap.add_argument("--report", action="store_true", help="Laporan lengkap")
    args = ap.parse_args()

    if args.report or args.analyze:
        return load_and_report()

    if args.trending:
        async def go():
            async with async_playwright() as p:
                b = await p.chromium.launch(channel="chrome", headless=True,
                    args=["--no-sandbox"])
                ctx = await b.new_context(storage_state=SESSION_FILE,
                    user_agent=UA, viewport={"width":1280,"height":1600}, locale="id-ID")
                pg = await ctx.new_page()
                topics = await scrape_trending(pg)
                print("=== TOPIK TRENDING ===")
                for t in topics:
                    print(f"  - {t}")
                await b.close()
        asyncio.run(go())
        return 0

    if not args.topics:
        ap.print_help()
        return 0

    topics = [t.strip() for t in args.topics.split(",") if t.strip()]
    return asyncio.run(run_scrape(topics, args.limit))


if __name__ == "__main__":
    sys.exit(main())
