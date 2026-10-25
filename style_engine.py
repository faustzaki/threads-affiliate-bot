"""
style_engine.py — Anti-template & anti-AI-detection.

MASALAH YANG DISELESAIKAN (dari analisis data lo):
  86% post diawali huruf kecil          -> monoton
  71% panjang mirip (SD cuma 49)        -> semua post berasa sama
  64% ada emoticon di posisi sama       -> pola berulang

SOLUSI: "DNA style" — tiap post punya kombinasi unik dari 7 dimensi.
Bukan random murni, tapi random terstruktur: yang dijamin beda.

Cara pakai:
    from style_engine import StyleDNA
    dna = StyleDNA.for_post(post_id=12)
    print(dna.to_prompt())
"""

import random
import re
import hashlib
from datetime import datetime, timezone, timedelta

WIB = timezone(timedelta(hours=7))


# ─────────────────────────────────────────────────────────────
# DIMENSI STYLE
# ─────────────────────────────────────────────────────────────

# 1. PANJANG — variasinya harus lebar, bukan cuma 3 pilihan
LENGTHS = [
    ("ultra_short", "10-25 kata. Satu kalimat doang. Punchy. Kayak orang lagi kesel."),
    ("short", "25-45 kata. 2 kalimat pendek. Langsung ke inti."),
    ("medium", "45-70 kata. 3 kalimat. Ada setup -> twist."),
    ("long", "70-100 kata. 4-5 kalimat. Storytelling mini, ada detail."),
    ("very_long", "100-140 kata. Cerita lengkap, ada dialog atau detail berlebih yang lucu."),
]

# 2. PEMBUKA — 12 cara, bukan 5
HOOKS = [
    ("statement", "Kalimat pernyataan datar. Tanpa basa-basi. Contoh: 'kursi kamar itu bukan buat duduk.'"),
    ("question", "Pertanyaan langsung ke pembaca. Contoh: 'kursi kamar kalian masih buat duduk?'"),
    ("dialogue", "Mulai dari dialog. Contoh: 'gue: mau nyetrika\\notak gue: besok aja'"),
    ("timestamp", "Mulai dari jam/waktu. Contoh: 'jam 11 malem, mata udah sepet.'"),
    ("confession", "Ngaku sesuatu yang memalukan. Contoh: 'gue udah 3 hari gak nyetrika.'"),
    ("observation", "Observasi soal orang lain. Contoh: 'ada orang yang kamarnya selalu rapi. gimana caranya.'"),
    ("capslock", "Mulai dengan capslock dramatis. Contoh: 'ANJIRRR gue baru sadar...'"),
    ("mid_scene", "Mulai di tengah kejadian, tanpa konteks. Contoh: 'dan akhirnya tumpukan itu menang lagi.'"),
    ("numbers", "Mulai dari angka. Contoh: '3 hari. 3 hari gue ngeliatin tumpukan itu.'"),
    ("negation", "Mulai dari penyangkalan. Contoh: 'bukan males. cuma... ya udah males.'"),
    ("comparison", "Bandingin dua hal. Contoh: 'orang rapi vs gue: sebuah perbandingan.'"),
    ("sound", "Mulai dari suara. Contoh: 'kriuk kriuk. itu suara tumpukan baju jatuh.'"),
]

# 3. NADA — beda emosi, beda rasa
TONES = [
    ("deadpan", "Datar, sarkas, tanpa emosi. Kayak lagi cerita biasa padahal isinya absurd."),
    ("dramatic", "Lebay, berlebihan, teatrikal. Semua dibilang 'parah' atau 'gila'."),
    ("wholesome", "Hangat, cute, positif. Nada lagi seneng."),
    ("resigned", "Pasrah, capek, 'yaudah lah'. Nada orang yang udah nyerah."),
    ("chaotic", "Random, lompat-lompat, gak fokus. Kayak isi kepala jam 2 pagi."),
    ("confident", "Pede, nge-claim hal dengan yakin. Bisa jadi lucu karena overconfident."),
    ("vulnerable", "Jujur, agak sedih, reflektif. Nada lagi curhat serius."),
]

# 4. STRUKTUR — cara nyusun kalimat
STRUCTURES = [
    ("linear", "Setup -> masalah -> reaksi. Alur normal."),
    ("twist_ending", "Setup panjang, twist di kalimat terakhir."),
    ("list", "Daftar 2-3 hal. 'yang bikin beda: 1)... 2)...'"),
    ("call_response", "Pertanyaan lalu jawab sendiri. 'kenapa? karena...'"),
    ("callback", "Buka dengan satu hal, tutup dengan balik ke hal itu."),
    ("no_ending", "Gantung. Gak ada kesimpulan. Biarin pembaca mikir."),
    ("escalation", "Makin lama makin parah. Tiap kalimat naikin level."),
]

# 5. EMOTICON — bukan cuma 'ada/tidak', tapi posisi & jumlah
EMOJI_POLICY = [
    ("none", "TANPA emoticon sama sekali. Titik. Ini yang bikin keliatan paling natural."),
    ("one_end", "Satu emoticon di akhir aja."),
    ("one_mid", "Satu emoticon di tengah, bukan akhir."),
    ("two_spread", "Dua emoticon, dipisah jarak."),
    ("text_only", "Gak pakai emoji, tapi pakai 'wkwk' atau 'kwkwk' sebagai gantinya."),
]

# 6. KATA KHAS — variasi kosakata, jangan selalu 'padahal'
SIGNATURE_WORDS = [
    ("gen_z", "Pakai: jir, anjir, bgt, beneran, parah, gila, co"),
    ("jaksel", "Pakai: jujurly, literally, which is, honestly, kinda"),
    ("betawi", "Pakai: dong, deh, nih, tuh, gitu, kagak"),
    ("santai", "Pakai: yaudah, gitu deh, hehe, hmm, ya gitu"),
    ("dramatis", "Pakai: parah sih, gak kuat, ampun, tolong"),
    ("minimal", "Kosakata minim. Kalimat pendek. Gak banyak kata sambung."),
]

# 7. ANGLE NARATIF — siapa yang cerita
PERSPECTIVES = [
    ("self", "Gue cerita soal diri sendiri."),
    ("observer", "Gue ngamatin orang lain, bukan diri sendiri."),
    ("you", "Ngajak pembaca: 'kalian pasti pernah...'"),
    ("we", "Kolektif: 'kita tuh ya...'"),
    ("third_person", "Cerita soal 'dia' atau 'temen gue'."),
]


# ─────────────────────────────────────────────────────────────
# STYLE DNA
# ─────────────────────────────────────────────────────────────

class StyleDNA:
    """
    Kombinasi unik 7 dimensi style.
    Dijamin beda tiap post karena pakai hash dari post_id + tanggal.
    """

    def __init__(self, length, hook, tone, structure, emoji, vocab, perspective):
        self.length = length
        self.hook = hook
        self.tone = tone
        self.structure = structure
        self.emoji = emoji
        self.vocab = vocab
        self.perspective = perspective

    @classmethod
    def for_post(cls, post_id, seed_date=None):
        """
        Generate DNA deterministik dari post_id.
        Post #12 selalu dapet DNA yang sama, tapi beda dari post #13.
        """
        d = seed_date or datetime.now(WIB).date()
        seed_str = f"{post_id}-{d.isoformat()}"
        seed = int(hashlib.md5(seed_str.encode()).hexdigest()[:8], 16)

        rng = random.Random(seed)
        return cls(
            length=rng.choice(LENGTHS),
            hook=rng.choice(HOOKS),
            tone=rng.choice(TONES),
            structure=rng.choice(STRUCTURES),
            emoji=rng.choice(EMOJI_POLICY),
            vocab=rng.choice(SIGNATURE_WORDS),
            perspective=rng.choice(PERSPECTIVES),
        )

    @classmethod
    def random(cls):
        """DNA acak — buat testing."""
        return cls(
            length=random.choice(LENGTHS), hook=random.choice(HOOKS),
            tone=random.choice(TONES), structure=random.choice(STRUCTURES),
            emoji=random.choice(EMOJI_POLICY), vocab=random.choice(SIGNATURE_WORDS),
            perspective=random.choice(PERSPECTIVES),
        )

    def to_prompt(self):
        """Format buat dimasukin ke prompt LLM."""
        return f"""DNA STYLE (WAJIB DIIKUTI PERSIS):
- Panjang    : [{self.length[0]}] {self.length[1]}
- Pembuka    : [{self.hook[0]}] {self.hook[1]}
- Nada       : [{self.tone[0]}] {self.tone[1]}
- Struktur   : [{self.structure[0]}] {self.structure[1]}
- Emoticon   : [{self.emoji[0]}] {self.emoji[1]}
- Kosakata   : [{self.vocab[0]}] {self.vocab[1]}
- Sudut pandang: [{self.perspective[0]}] {self.perspective[1]}"""

    def signature(self):
        """Signature pendek buat logging."""
        return f"{self.length[0]}/{self.hook[0]}/{self.tone[0]}/{self.structure[0]}"

    def __repr__(self):
        return f"<StyleDNA {self.signature()}>"


# ─────────────────────────────────────────────────────────────
# ANTI-AI DETECTION
# ─────────────────────────────────────────────────────────────

# Pola yang bikin teks keliatan AI-generated
AI_TELLS = [
    (r'\b(?:sebagai|as an?)\s+(?:AI|model bahasa|asisten)\b', 'Menyebut diri AI'),
    (r'\b(?:penting untuk dicatat|it\'?s important to note|perlu diingat)\b', 'Frasa formal AI'),
    (r'\b(?:dalam kesimpulan|sebagai kesimpulan|in conclusion)\b', 'Kesimpulan formal'),
    (r'\b(?:pertama-tama|secondly|selanjutnya|lebih lanjut)\b', 'Enumerasi formal'),
    (r'\b(?:oleh karena itu|thus|hence|therefore)\b', 'Kata sambung formal'),
    (r'\b(?:dapat disimpulkan|dapat dikatakan)\b', 'Frasa akademik'),
    (r'\b(?:sangat penting|sangat dianjurkan|sangat direkomendasikan)\b', 'Superlatif formal'),
    (r'\b(?:mari kita|let us|let\'s dive)\b', 'Ajakan formal'),
    (r'—', 'Em-dash (AI suka banget)'),
    (r'\b(?:delve|leverage|robust|seamless|holistic)\b', 'Kata buzzword Inggris'),
]

# Kata yang bikin caption keliatan "jualan banget"
SALESY_WORDS = [
    'wajib punya', 'must have', 'wajib beli', 'jangan sampai kehabisan',
    'stok terbatas', 'promo terbatas', 'harga spesial', 'diskon gede',
    'buruan', 'grab fast', 'jangan nyesel', 'auto checkout',
]


def check_ai_tells(text):
    """
    Cek apakah teks keliatan AI-generated.
    Return: (skor_ai 0-100, list masalah)
    """
    issues = []
    score = 0

    for pattern, reason in AI_TELLS:
        if re.search(pattern, text, re.IGNORECASE):
            issues.append(reason)
            score += 12

    for w in SALESY_WORDS:
        if w in text.lower():
            issues.append(f"Kata jualan: '{w}'")
            score += 10

    # cek struktur terlalu rapi
    sentences = [s.strip() for s in re.split(r'[.!?]', text) if s.strip()]
    if len(sentences) >= 3:
        lengths = [len(s) for s in sentences]
        avg = sum(lengths) / len(lengths)
        # kalau semua kalimat panjangnya mirip = terlalu rapi
        if all(abs(l - avg) < avg * 0.25 for l in lengths):
            issues.append("Panjang kalimat terlalu seragam (AI suka begini)")
            score += 15

    # cek paragraf terlalu rapi
    lines = [l for l in text.split("\n") if l.strip()]
    if len(lines) >= 3:
        line_lens = [len(l) for l in lines]
        if max(line_lens) - min(line_lens) < 20:
            issues.append("Semua baris panjangnya mirip (keliatan template)")
            score += 15

    return min(100, score), issues


def check_variation(recent_texts, new_text):
    """
    Cek apakah post baru terlalu mirip dengan yang lama.
    Return: (skor_mirip 0-100, list masalah)
    """
    issues = []
    score = 0

    new_lines = len([l for l in new_text.split("\n") if l.strip()])
    new_len = len(new_text)
    new_emoji = len(re.findall(r'[🫠😭🥹💀😅🥲✨🤍]', new_text))
    new_start_lower = new_text[:1].islower()

    for old in recent_texts[-10:]:
        old_lines = len([l for l in old.split("\n") if l.strip()])
        old_len = len(old)
        old_emoji = len(re.findall(r'[🫠😭🥹💀😅🥲✨🤍]', old))
        old_start_lower = old[:1].islower()

        # jumlah baris sama
        if new_lines == old_lines:
            score += 8
        # panjang mirip (dalam 20%)
        if abs(new_len - old_len) < max(new_len, old_len) * 0.2:
            score += 10
        # emoji count sama
        if new_emoji == old_emoji:
            score += 6
        # sama-sama mulai huruf kecil
        if new_start_lower and old_start_lower:
            score += 4

    score = min(100, score)

    if score > 50:
        issues.append(f"Terlalu mirip post sebelumnya (skor kemiripan {score})")
    if new_lines == 3:
        issues.append("3 baris — post lo sering 3 baris, coba variasikan")

    return score, issues


# ─────────────────────────────────────────────────────────────
# TEST
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 70)
    print("  STYLE DNA — 7 DIMENSI")
    print("=" * 70)

    total_combo = (len(LENGTHS) * len(HOOKS) * len(TONES) * len(STRUCTURES)
                   * len(EMOJI_POLICY) * len(SIGNATURE_WORDS) * len(PERSPECTIVES))
    print(f"\nTotal kombinasi: {total_combo:,}")
    print(f"  Panjang     : {len(LENGTHS)}")
    print(f"  Pembuka     : {len(HOOKS)}")
    print(f"  Nada        : {len(TONES)}")
    print(f"  Struktur    : {len(STRUCTURES)}")
    print(f"  Emoticon    : {len(EMOJI_POLICY)}")
    print(f"  Kosakata    : {len(SIGNATURE_WORDS)}")
    print(f"  Perspektif  : {len(PERSPECTIVES)}")
    print(f"\n  -> 10 post berturut-turut hampir MUSTAHIL sama")

    print("\n" + "=" * 70)
    print("  CONTOH DNA 5 POST BERURUTAN")
    print("=" * 70)
    for i in range(1, 6):
        dna = StyleDNA.for_post(i)
        print(f"\nPost #{i}: {dna}")
        print(f"  {dna.length[0]:12} | {dna.hook[0]:12} | {dna.tone[0]:11}")
        print(f"  {dna.structure[0]:14} | {dna.emoji[0]:10} | {dna.vocab[0]}")

    print("\n" + "=" * 70)
    print("  CONTOH PROMPT LENGKAP (post #3)")
    print("=" * 70)
    print(StyleDNA.for_post(3).to_prompt())

    print("\n" + "=" * 70)
    print("  TEST AI DETECTION")
    print("=" * 70)

    samples = [
        ("Template AI", 
         "Penting untuk dicatat bahwa memilih pakaian yang tepat sangat penting. "
         "Pertama-tama, pertimbangkan bahan. Selanjutnya, perhatikan ukuran. "
         "Oleh karena itu, dapat disimpulkan bahwa riset diperlukan."),
        ("Natural",
         "nyetrika tuh kayak... niat jam 8, mulai jam 10, selesai jam 11, "
         "tapi yang disetrika cuma 3 lembar. sisanya masuk lemari lagi."),
        ("Jualan banget",
         "Wajib punya! Stok terbatas, buruan checkout sebelum kehabisan. "
         "Harga spesial hari ini aja!"),
    ]

    for name, txt in samples:
        score, issues = check_ai_tells(txt)
        status = "🔴" if score > 40 else ("🟡" if score > 15 else "🟢")
        print(f"\n{status} {name} — skor AI: {score}/100")
        if issues:
            for i in issues[:4]:
                print(f"    - {i}")
        else:
            print(f"    ✓ gak ada pola AI terdeteksi")
