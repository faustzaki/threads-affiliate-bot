# 🧵 Threads Affiliate Bot

> Bot auto-posting Threads untuk affiliate Shopee. Bikin caption yang **gak keliatan AI**, rotasi jadwal **acak kayak manusia**, dan gate stok biar gak pernah posting asal-asalan.

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Playwright-45ba4b?style=for-the-badge&logo=playwright&logoColor=white" alt="Playwright">
  <img src="https://img.shields.io/badge/SQLite-003B57?style=for-the-badge&logo=sqlite&logoColor=white" alt="SQLite">
  <img src="https://img.shields.io/badge/Notion-000000?style=for-the-badge&logo=notion&logoColor=white" alt="Notion">
  <img src="https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge" alt="MIT">
</p>

---

## 🤔 Masalah yang dipecahin

Bikin konten affiliate konsisten itu nyiksa:

- **Caption keliatan AI** → orang skip, algoritma turunin reach
- **Posting jam sama tiap hari** → keliatan bot, akun di-flag
- **Topik ngulang** → follower notice, engagement mati
- **Posting tanpa gambar siap** → post jelek, malu sendiri
- **Lupa mana yang udah dipost** → gambar sama kepost 2x

Bot ini ngurus semua itu. Lo tinggal **generate gambar** dan **taruh di folder**. Sisanya jalan sendiri.

---

## ✨ Fitur

### 🎲 Randomization engine

Bukan cron `0 12 * * *`. Jadwal **dibangkitkan ulang tiap hari**:

```
Hari  1: 1 post  11:29
Hari  2: 2 post  10:19, 13:22
Hari  3: 1 post  10:14
Hari  4: 0 post  (libur)
Hari  5: 2 post  12:37, 20:45
```

| Yang diacak | Detail |
|---|---|
| **Jumlah post** | 12% libur · 38% 1 post · 50% 2 post (maks 2) |
| **Jam posting** | Titik acak dalam window 09:00–22:30 |
| **Jeda antar post** | Minimal 3 jam |
| **Mode konten** | Probabilistik 40% text / 30% gambar / 30% affiliate |
| **Skip** | 10% peluang gak posting sama sekali |

Plus **guard anti-pola**: gak mungkin 3x mode sama berturut-turut.

### ✍️ Anti-AI caption engine

```
style_engine.py  →  441.000 kombinasi DNA
                    (panjang × pembuka × nada × struktur × emoticon × kosakata × perspektif)
```

Tiap post dapet DNA unik dari `hashlib` — deterministik per post_id, jadi gak pernah sama tapi juga reproducible.

**Detektor AI** nangkep 10 pola:
- Frasa formal ("perlu diketahui bahwa", "dalam hal ini")
- Enumerasi kaku ("pertama-tama", "selanjutnya")
- Konjungsi formal ("oleh karena itu", "dengan demikian")
- **Em-dash (—)** ← tell paling kuat
- Dan 6 lainnya

Skor 0–100. Aturan: **<20 aman, >40 wajib rewrite.**

### 🚦 Quality gate

Nolak caption yang:
- Engagement bait ("like kalau setuju", "comment YES")
- Link shortener (bit.ly, tinyurl, t.co, s.id)
- Tracking param (utm_*, fbclid)
- Hook <20 karakter
- Klaim tanpa dasar ("udah gue pake 2 minggu")

### 📸 Image lifecycle

```
STOK/  ──sync──>  media/pool/  ──dipost──>  media/arsip/  ──30 hari──>  🗑️
```

| Jenis | Batas pakai | Alasan |
|---|---|---|
| **Random** | 1× | Foto orang. Dipost 2× = follower notice |
| **Affiliate** | 3× | Produk sama boleh, caption beda |

**Gak ada gambar lama kepost ulang.** Pool cuma isi yang `used < batas`.

### 🛡️ Publish safety

- **Atomic claim** — gak mungkin double-post walau proses restart
- **`publish_unknown` state** — kalau timeout, **jangan** blind-retry. Cek manual dulu
- **Stale recovery** — post nyangkut >10 menit otomatis ditandai

### 📊 Notion sebagai dashboard

Lo edit dari HP, bot baca dari SQLite. **Auto-sync dua arah.**

```
Notion (lo edit)  ⇄  SQLite (bot baca)
```

**Cuma isi 1 kolom** (URL Shopee), sisanya auto-fill:

| Kolom | Sumber |
|---|---|
| Nama Produk | Dari slug URL |
| Kategori | Deteksi dari nama (kulot→bawahan, pashmina→hijab) |
| Link Affiliate | Generate `an_redir` otomatis |
| Detail | Template per kategori |
| Caption | Generate + quality gate |
| Prompt Gambar | Template per kategori |
| Folder Gambar | Path otomatis |

### 📱 Telegram notifikasi

```
🧵 DRAFT MALAM — TEXT-ONLY
ID 19 · short/mid_scene/confident/callback

1️⃣ Opsi 1 ✅ (100/100 · AI 0)
spill kulot linen yang beneran gak nerawang dong...

2️⃣ Opsi 2 ✅ (100/100 · AI 0)
kalian beli kemeja linen di toko mana sih?

👉 Balas post 1 atau post 2
```

**Auto-post** kalau skor ≥90 dan AI 0. Selain itu minta approval.

---

## 🚀 Mulai

### Prasyarat

```bash
Python 3.10+
Node.js 18+ (buat Playwright)
```

### Install

```bash
git clone https://github.com/faustzaki/threads-affiliate-bot.git
cd threads-affiliate-bot

pip install -r requirements.txt
playwright install chromium
```

### Setup

**1. Buat `.env`:**

```env
# LLM (OpenAI-compatible endpoint)
NINEROUTER_URL=http://127.0.0.1:20128/v1
HERMES_CUSTOM_LOCALHOST_20128_API_KEY=sk-xxx
AFFILIATE_MODEL=ag/gemini-3.8-flash-high

# Telegram
TELEGRAM_BOT_TOKEN=123456:ABC-xxx
TELEGRAM_ALLOWED_USERS=987654321

# Shopee
SHOPEE_AFFILIATE_ID=11342632100
```

**2. Login Threads (sekali aja):**

```bash
python poster.py --login
```

Bakal buka browser. Login manual, session kesimpen.

**3. Init database:**

```bash
python db.py --init
```

**4. Cek semua siap:**

```bash
python cek_stok.py
```

### Jalanin

```bash
# Manual
python scheduler_v2.py Siang
python scheduler_v2.py Malam

# Lihat rencana hari ini
python cron_wrapper.py --plan

# Simulasi 100 hari (tes randomness)
python scheduler_v2.py --simulate

# Cek stok
python cek_stok.py
```

**Cron (tiap 30 menit, jitter otomatis):**

```cron
*/30 9-23 * * * cd /path/to/bot && python cron_wrapper.py
```

---

## 📁 Struktur

```
threads-affiliate-bot/
├── cron_wrapper.py       ← penentu jadwal acak
├── scheduler_v2.py       ← generate + gate + post
├── generator.py          ← LLM caption generation
├── style_engine.py       ← DNA 441rb kombinasi + detektor AI
├── quality_gate.py       ← filter caption jelek
├── angle_picker.py       ← anti-duplikat topik (history 14 hari)
├── image_pool.py         ← lifecycle gambar
├── poster.py             ← Playwright → Threads
├── publish_guard.py      ← anti double-post
├── notifier.py           ← Telegram
├── cek_stok.py           ← gate stok
├── notion_sync.py        ← Notion ⇄ SQLite
├── notion_autofill.py    ← isi otomatis dari 1 URL
├── affiliate_link.py     ← generate link affiliate
├── affiliate_flow.py     ← pipeline produk
├── product_intake.py     ← terima produk baru
├── threads_scraper.py    ← riset topik
│
├── STOK/                 ← lo taruh gambar di sini
│   ├── 01-GAMBAR-RANDOM/
│   ├── 02-GAMBAR-AFFILIATE/
│   └── 03-LINK-AFFILIATE/
│
├── media/
│   ├── pool/             ← gambar siap pakai
│   └── arsip/            ← gambar udah dipost
│
└── data/
    └── threads_research.json
```

---

## 🔬 Hasil riset

Scrape **95 post Threads** (12 topik) buat cari pola:

| Topik | Median likes | Sample |
|---|---|---|
| **ootd** | **18** | n=6 |
| memes | 25 | n=18 |
| curhat | 21 | n=3 |
| skincare | 10 | n=10 |
| kuliner | 6 | n=7 |
| travel | 6 | n=16 |
| **fashion** | **1** | n=9 |
| **outfit** | **1** | n=9 |

**Temuan kunci:** `ootd` **18× lebih tinggi** dari `fashion`/`outfit`. Jadi pakai keyword `ootd`, bukan `fashion`.

**Format "spill" menang telak** — reply:like ratio 3:1 sampai 5:1:

> "Spill basic skincare kalian dong guys, in this economy :("
> → 17 likes, **50 replies**

**Panjang optimal:** 80–130 karakter, 2 baris. (Awalnya gua kira 120–190, ternyata kepanjangan.)

Detail lengkap: [`RISET-THREADS.md`](RISET-THREADS.md)

---

## ⚠️ Yang gak bot ini lakuin

Jujur ya:

| ❌ Gak bisa | Kenapa |
|---|---|
| **Scrape produk Shopee** | Anti-bot berlapis. Semua jalur diblokir (403, login wall, signature) |
| **Auto-generate gambar** | Pollinations watermark + 402 setelah 1 gambar. Gak reliable |
| **Auto-komen di post orang** | Risiko shadowban tinggi buat akun baru |
| **Cari produk komisi gede** | Info komisi cuma ada di dashboard affiliate (login) |

**Yang lo harus manual:** generate gambar, isi URL produk.

---

## 🎯 Roadmap

- [x] Randomization engine
- [x] Anti-AI caption
- [x] Quality gate
- [x] Image lifecycle
- [x] Notion sync + autofill
- [x] Publish safety
- [ ] Auto-balas komen di post sendiri
- [ ] A/B testing caption
- [ ] Analytics dashboard
- [ ] Multi-akun support

---

## ⚖️ Disclaimer

Bot ini buat **otomasi konten milik sendiri**. Bukan buat spam.

Yang **harus** lo perhatiin:

- Ikutin [Threads Terms of Service](https://help.instagram.com/769983657850450)
- Ikutin [Shopee Affiliate Program terms](https://affiliate.shopee.co.id)
- **Jangan** fabricate review ("udah gue pake 2 minggu" padahal belum)
- **Jangan** auto-komen spam di akun orang
- Kalau akun kena limit, itu risiko lo

Gua gak bertanggung jawab kalau akun lo di-ban karena pakai bot ini di luar batas wajar.

---

## 📄 Lisensi

MIT — pakai, modif, jual, terserah lo.

---

<p align="center">
  <sub>Dibikin karena males posting manual tapi pengen tetap keliatan manusia</sub>
</p>
