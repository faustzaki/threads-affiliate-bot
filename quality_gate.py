"""
quality_gate.py — Gate kualitas konten sebelum dipost.

Diadaptasi dari pola lib/quality-gate.ts (yanstd888/threads-auto-poster),
disesuaikan untuk persona fashion/kos + konteks affiliate.

Prinsip:
- Tolak engagement bait (minta like/tag/follow)
- Tolak klaim tanpa bukti (pengalaman pakai padahal belum beli)
- Tolak link shortener berbahaya
- Tolak hook terlalu pendek
- Skor 0-100, minimal 70 buat lolos
"""

import re

# ─────────────────────────────────────────────────────────────
# POLA PENOLAKAN
# ─────────────────────────────────────────────────────────────

# Engagement bait — dilarang Meta/Threads, nurunin reach
ENGAGEMENT_BAIT = [
    r'\b(?:like|suka)\s+(?:postingan|post|ini)\b',
    r'\b(?:share|bagikan|repost)\s+(?:postingan|post|ini|ke\s+\d+)\b',
    r'\b(?:tag|tandai)\s+(?:\d+\s*)?(?:teman|orang)\b',
    r'\b(?:follow|ikuti)\b.{0,48}\b(?:untuk|agar|biar|supaya)\b',
    r'\b(?:tulis|komen|komentar|balas)\b.{0,64}\b(?:done|hadir|amin|setuju|angka)\b',
    r'\b(?:simpan|save)\s+(?:postingan|post|panduan|catatan)\s+ini\b',
    r'\bkomen\s+["\']?[a-z]{2,}["\']?\s+(?:biar|untuk|nanti)\b',
]

# Klaim tanpa bukti — KHUSUS affiliate fashion.
# Ini yang bikin lo aman: gak boleh ngaku pengalaman yang belum terjadi.
UNVERIFIED_CLAIM = [
    # Klaim durasi pemakaian
    (r'\budah\s+(?:gue\s+|aku\s+)?(?:pake|pakai|pake)\s+\d+\s*(?:hari|minggu|bulan|tahun)\b',
     'Klaim durasi pemakaian — hanya boleh kalau sudah beli sendiri'),
    # Klaim kualitas subjektif absolut
    (r'\bbeneran\s+(?:adem|dingin|tahan|awet|kuat|gak\s+melar|anti\s+kusut)\b',
     'Klaim kualitas absolut — ubah jadi deskripsi bahan/fakta produk'),
    # Klaim hasil pada tubuh
    (r'\b(?:kulit|muka|badan)\s+(?:jadi|makin|langsung)\s+(?:glowing|cerah|halus|putih)\b',
     'Klaim hasil pada tubuh — dilarang tanpa bukti'),
    # Klaim durasi ketahanan
    (r'\b(?:tahan|awet|kuat)\s+(?:sampai\s+)?\d+\s*(?:jam|hari|minggu)\b',
     'Klaim durasi ketahanan — dilarang tanpa uji nyata'),
    # Klaim testimoni/klien
    (r'\b(?:sudah\s+)?(?:\d+\s+)?(?:orang|pembeli|customer)\s+(?:udah|sudah|pada)\s+(?:beli|order|coba)\b',
     'Klaim jumlah pembeli — dilarang tanpa data terverifikasi'),
    # Klaim perbandingan absolut
    (r'\b(?:paling|terbaik|nomor\s+1|no\.?\s*1)\s+(?:bagus|murah|awet|nyaman)\b',
     'Klaim superlatif — dilarang, subjektif dan gak terverifikasi'),
]

# Link shortener yang sering dipakai buat spam/scam
BAD_SHORTENERS = [
    'bit.ly', 'tinyurl.com', 't.co', 'goo.gl', 'rebrand.ly',
    'cutt.ly', 'shorturl.at', 'buff.ly', 's.id', 'linktr.ee',
    'bit.do', 'is.gd', 'v.gd', 'clck.ru', 'ow.ly',
]

# Link affiliate yang DIIZINKAN (whitelist)
ALLOWED_AFFILIATE_DOMAINS = [
    's.shopee.co.id', 'shopee.co.id', 'shope.ee',
    'tokopedia.link', 'tk.tokopedia.com',
    's.lazada.co.id', 'lazada.co.id',
]

# Kata bot/AI yang bikin caption keliatan template
BOT_WORDS = [
    'racun shopee', 'wajib checkout', 'spill racun', 'link di bio',
    'murce bgt say', 'auto checkout', 'mumpung murah',
]

# Tracking param yang gak perlu
TRACKING_PARAMS = re.compile(r'[?&](?:utm_[a-z_]+|fbclid|gclid|mc_[a-z_]+)=')


# ─────────────────────────────────────────────────────────────
# HASIL
# ─────────────────────────────────────────────────────────────

class QualityResult:
    def __init__(self):
        self.passed = False
        self.score = 100
        self.reasons = []
        self.warnings = []

    def fail(self, reason, penalty=100):
        self.reasons.append(reason)
        self.score -= penalty

    def warn(self, msg):
        self.warnings.append(msg)

    def to_dict(self):
        return {
            "passed": self.passed,
            "score": max(0, self.score),
            "reasons": self.reasons,
            "warnings": self.warnings,
        }

    def __repr__(self):
        status = "✅ LOLOS" if self.passed else "❌ DITOLAK"
        out = [f"{status} (skor {max(0,self.score)}/100)"]
        for r in self.reasons:
            out.append(f"  ❌ {r}")
        for w in self.warnings:
            out.append(f"  ⚠️  {w}")
        return "\n".join(out)


# ─────────────────────────────────────────────────────────────
# HELPER
# ─────────────────────────────────────────────────────────────

def _first_sentence(text):
    m = re.search(r'[.!?\n]', text)
    return text[:m.start()].strip() if m else text.strip()


def _find_urls(text):
    return re.findall(r'https?://[^\s<>()"\']+', text)


def _extract_domain(url):
    m = re.match(r'https?://([^/?#]+)', url)
    return m.group(1).lower().replace('www.', '') if m else ''


# ─────────────────────────────────────────────────────────────
# GATE UTAMA
# ─────────────────────────────────────────────────────────────

def run_quality_gate(text, reply_text=None, post_type="random", is_affiliate=False):
    """
    Jalankan semua pemeriksaan.

    Args:
        text: caption utama
        reply_text: isi reply (kalau affiliate, isinya link)
        post_type: "random" | "affiliate"
        is_affiliate: True kalau ini post affiliate

    Returns:
        QualityResult
    """
    res = QualityResult()
    main = (text or "").strip()
    reply = (reply_text or "").strip()
    full = f"{main} {reply}".strip()

    if not main:
        res.fail("Caption kosong")
        return res

    # ── 1. Panjang ──
    if len(main) > 500:
        res.fail(f"Caption kepanjangan ({len(main)}/500 char)")
    elif len(main) < 40:
        res.fail(f"Caption terlalu pendek ({len(main)} char, min 40)", penalty=30)

    # ── 2. Hook ──
    hook = _first_sentence(main)
    if len(hook) < 20:
        res.warn(f"Hook pendek ({len(hook)} char) — kurang nendang")

    # ── 3. Engagement bait ──
    for pattern in ENGAGEMENT_BAIT:
        m = re.search(pattern, full, re.IGNORECASE)
        if m:
            res.fail(f"Engagement bait terdeteksi: '{m.group(0)[:40]}'")
            break

    # ── 4. Klaim tanpa bukti (HANYA untuk affiliate) ──
    if is_affiliate:
        for pattern, reason in UNVERIFIED_CLAIM:
            m = re.search(pattern, full, re.IGNORECASE)
            if m:
                res.fail(f"{reason} → '{m.group(0)[:50]}'")
                break

    # ── 5. Link ──
    urls = _find_urls(full)
    for u in urls:
        dom = _extract_domain(u)

        # shortener berbahaya
        if any(s in dom for s in BAD_SHORTENERS):
            res.fail(f"Link shortener dilarang: {dom}")

        # link di caption utama (harusnya di reply)
        if u in main:
            res.warn("Link ada di caption utama — sebaiknya pindah ke reply")

        # domain affiliate harus whitelist
        if is_affiliate:
            if not any(a in dom for a in ALLOWED_AFFILIATE_DOMAINS):
                res.fail(f"Domain affiliate gak dikenal: {dom}")

        # tracking param
        if TRACKING_PARAMS.search(u):
            res.warn(f"Ada tracking param di link: {dom}")

    # ── 6. Affiliate wajib ada link ──
    if is_affiliate and not urls:
        res.fail("Post affiliate tapi gak ada link sama sekali")

    # ── 7. Kata bot ──
    for w in BOT_WORDS:
        if w in full.lower():
            res.fail(f"Kata template/bot terdeteksi: '{w}'")

    # ── 8. Spam simbol berlebih ──
    if main.count('!') > 3:
        res.warn("Terlalu banyak tanda seru — keliatan spam")
    if len(re.findall(r'[A-Z]{5,}', main)) > 2:
        res.warn("Terlalu banyak CAPSLOCK — bisa keliatan spam")

    # ── 9. Hashtag berlebihan ──
    hashtags = re.findall(r'#[\w]+', main)
    if len(hashtags) > 3:
        res.warn(f"Hashtag kebanyakan ({len(hashtags)}) — maksimal 2-3")

    # ── 10. Caption harus ada huruf kecil (gaya Gen Z) ──
    if main.isupper():
        res.warn("Caption semua kapital — kurang natural buat Threads")

    # ── Final ──
    res.passed = res.score >= 70 and not any(
        # kalau ada fail dengan penalti 100, langsung gugur
        True for _ in res.reasons
    ) or (res.score >= 70 and len([r for r in res.reasons if 'pendek' not in r]) == 0)

    # aturan tegas: kalau ada reason yang bukan warning ringan, gugur
    hard_fails = [r for r in res.reasons if 'terlalu pendek' not in r]
    res.passed = (res.score >= 70) and (len(hard_fails) == 0)

    return res


# ─────────────────────────────────────────────────────────────
# TEST
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    samples = [
        ("random", False, 
         "kursi kamar kalian fungsinya emang buat numpuk baju kering juga ga sih?\n"
         "tadi niat mau nyetrika, pas liat tumpukannya kok kayak ngajak ribut. yauda tarik selimut pura-pura buta aja.", None),
        
        ("affiliate", True,
         "udah gue pake 2 minggu, kulot linen ini beneran adem dan gak melar. wajib checkout!",
         "https://s.shopee.co.id/5fpkj5RGXk"),
        
        ("affiliate", True,
         "kulot linen beige ini paling aman dipair sama atasan putih boxy + loafers cream.\n"
         "bahannya jatuh jadi gak keliatan kaku, cocok buat kerja maupun kuliah.",
         "https://s.shopee.co.id/5fpkj5RGXk"),
        
        ("random", False,
         "like postingan ini biar dapet diskon!!",
         None),
    ]

    for ptype, aff, txt, rep in samples:
        print("=" * 65)
        print(f"TIPE: {ptype} | affiliate={aff}")
        print(f"TEKS: {txt[:70]}...")
        print("-" * 65)
        print(run_quality_gate(txt, rep, ptype, aff))
        print()
