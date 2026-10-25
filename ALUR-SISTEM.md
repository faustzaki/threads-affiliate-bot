# ALUR SISTEM — Hulu ke Hilir

Update: 25 Okt 2026, 05:20 WIB
Status: **cron sudah pakai `scheduler_v2.py`** (bukan yang lama lagi)

---

## 🗺️ Peta Besar

```
┌──────────────────────────────────────────────────────────────────┐
│  HULU (manual, lo yang kerja)                                    │
│                                                                  │
│  1. Riset topik      → threads_scraper.py                       │
│  2. Pilih produk     → app Shopee                               │
│  3. Generate gambar  → Nano Banana                              │
│  4. Sortir gambar    → buang yang jelek                         │
└──────────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────────┐
│  TENGAH (semi-auto, lo jalanin script)                           │
│                                                                  │
│  5. Drop gambar      → media/inbox/                             │
│  6. Proses inbox     → process_inbox.py --describe --commit     │
│  7. Isi caption      → agent vision baca gambar                 │
│  8. Setup produk     → affiliate_flow.py add                    │
└──────────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────────┐
│  HILIR (auto, cron yang jalan)                                   │
│                                                                  │
│  9.  Cron 12:58      → scheduler_v2.py Siang                    │
│  10. Cron 20:45      → scheduler_v2.py Malam                    │
│      ↓                                                           │
│      generate 2 opsi caption                                     │
│      → quality gate (tolak kalau jelek)                          │
│      → kirim ke Telegram                                         │
│      ↓                                                           │
│  11. Lo approve      → balas "post 1" / "post 2"                │
│      ↓                                                           │
│      → posting ke Threads (dengan gambar kalau ada)             │
│      → link affiliate di reply                                   │
│      → notif hasil ke Telegram                                   │
└──────────────────────────────────────────────────────────────────┘
```

---

## ✅ YANG AUTO (jalan sendiri tanpa lo)

| # | Proses | Trigger | Script |
|---|---|---|---|
| 1 | Generate draft siang | Cron **12:58 WIB** | `scheduler_v2.py Siang` |
| 2 | Generate draft malam | Cron **20:45 WIB** | `scheduler_v2.py Malam` |
| 3 | **Quality gate** | Otomatis tiap generate | `quality_gate.py` |
| 4 | **Anti-duplikat angle** | Otomatis tiap generate | `angle_picker.py` |
| 5 | **DNA style unik** | Otomatis tiap generate | `style_engine.py` |
| 6 | **Rotasi gambar** | Otomatis (mode random_image) | `image_pool.py` |
| 7 | **Kirim draft ke Telegram** | Otomatis setelah generate | `notifier.py` |
| 8 | **Anti double-post** | Otomatis saat posting | `publish_guard.py` |
| 9 | **Publish_unknown detection** | Otomatis saat startup | `publish_guard.py` |
| 10 | **Notif hasil posting** | Otomatis setelah post | `notifier.py` |
| 11 | **Rotasi katalog produk** | Otomatis setelah affiliate post | `db.py` |
| 12 | **Update counter gambar** | Otomatis setelah post | `image_pool.py` |

---

## ❌ YANG MANUAL (lo harus kerjain)

| # | Proses | Kenapa manual | Frekuensi |
|---|---|---|---|
| 1 | **Riset topik** | Butuh keputusan lo | 2 minggu sekali |
| 2 | **Pilih produk Shopee** | Shopee blokir scraping | Per produk baru |
| 3 | **Generate gambar** | Gak ada API gratis reliable | Batch bulanan |
| 4 | **Sortir gambar** | Butuh selera lo | Batch bulanan |
| 5 | **Drop ke inbox** | Manual taruh file | Batch bulanan |
| 6 | **Jalanin process_inbox** | Lo trigger sendiri | Batch bulanan |
| 7 | **Isi caption gambar** | Butuh vision + selera | Batch bulanan |
| 8 | **Approve draft** | Lo baca di Telegram | 2× sehari |
| 9 | **Cek performa** | Insight Threads + Shopee | Mingguan |

---

## 🔄 Detail Alur Harian

### Pagi/siang (lo, 10 menit)

```
09:00  Cek Telegram — ada draft dari cron malam?
       ↓
       Baca 2 opsi, cek quality gate score
       ↓
       Balas "post 1" atau "post 2" atau "skip"
       ↓
       Sistem posting otomatis
       ↓
       Dapat notif "✅ POST #X TERKIRIM"
```

### Siang (otomatis, 12:58)

```
12:58  Cron jalan: scheduler_v2.py Siang
       ↓
       1. Cek udah jalan hari ini? (skip kalau udah)
       2. Recovery post nyangkut
       3. Tentukan mode (rotasi 7 hari)
       4. Generate DNA style
       5. Pilih gambar (kalau mode random_image)
       6. Generate 2 caption via LLM
       7. Quality gate kedua opsi
       8. Simpan ke DB
       9. Kirim ke Telegram
```

### Malam (otomatis, 20:45)

Sama seperti siang, slot malam.

---

## 🎲 Rotasi Mode Konten

`scheduler_v2.py` pakai rotasi 7 hari:

```
Hari 1: text_only      (40%)
Hari 2: text_only      (40%)
Hari 3: random_image   (30%)
Hari 4: affiliate      (30%)
Hari 5: text_only      (40%)
Hari 6: random_image   (30%)
Hari 7: affiliate      (30%)
```

**Hasil:**
- Text-only: 3/7 = **43%** (target 40%) ✅
- Random+gambar: 2/7 = **29%** (target 30%) ✅
- Affiliate: 2/7 = **29%** (target 30%) ✅

**Total: 2 post/hari × 7 hari = 14 post/minggu**
→ 6 text-only, 4 random+gambar, 4 affiliate

---

## 🛡️ Proteksi yang Jalan Otomatis

### 1. Quality Gate

Setiap caption dicek sebelum dikirim:

```
✅ Lolos: skor ≥ 70, gak ada pelanggaran keras
❌ Ditolak: engagement bait, klaim palsu, link shortener, dll
```

Kalau **kedua opsi ditolak** → gak dikirim ke Telegram, lo dapat notif.

### 2. Anti-Duplikat Angle

```
Pool: 40 angle malam, 29 angle siang
Filter: skip angle yang kata kuncinya muncul 14 hari terakhir
Tema: rotasi 7 hari (fashion/kos/kuliner/kerja/sosial/selfcare/random)
```

Cek kesehatan kapan aja:
```bash
python angle_picker.py
```

### 3. Anti Double-Post

```
Klaim atomik: cuma 1 proses bisa posting 1 post
Kalau cron jalan 2× → yang kedua otomatis skip
```

### 4. Publish Unknown

```
Kalau timeout SETELAH klik "Post":
  → status = publish_unknown
  → JANGAN retry (bisa dobel)
  → notif: "⚠️ CEK MANUAL"
  → coba verifikasi otomatis ke profil
```

### 5. Fallback LLM

```
Kalau 9router mati:
  → pakai caption manual dari data/fallback_captions.json
  → 6 pasang caption cadangan (3 siang + 3 malam)
  → tetap lolos quality gate
```

Cek stok fallback:
```bash
python scheduler_v2.py --fallback
```

---

## 📊 Status Sekarang

```
CRON
  threads_draft_siang_v2   12:58  ✅ AKTIF → scheduler_v2.py
  threads_draft_malam_v2   20:45  ✅ AKTIF → scheduler_v2.py

KATALOG AFFILIATE
  1 Kulot Linen      Cap✅  Link✅  Post:0   ← SIAP
  2 Kemeja Linen     Cap❌  Link✅  Post:0
  3 Set Crinkle      Cap❌  Link✅  Post:0
  4 Cardigan Rajut   Cap❌  Link✅  Post:0
  5 Pashmina         Cap❌  Link✅  Post:0

POOL GAMBAR
  Random siang : 1  (cukup 1 hari)
  Random malam : 1  (cukup 1 hari)
  Affiliate    : 0

ANGLE POOL
  Siang : 18/29 fresh — cukup 9 hari  ✅
  Malam : 22/40 fresh — cukup 11 hari ✅

CAPTION FALLBACK
  Siang : 2/3 tersedia
  Malam : 3/3 tersedia
```

---

## 🚨 Yang Masih Jadi PR

| # | Masalah | Dampak | Prioritas |
|---|---|---|---|
| 1 | **LLM (9router) mati** | Cuma pakai caption fallback (terbatas) | 🔴 Tinggi |
| 2 | **Pool gambar hampir habis** | Mode random_image bakal fallback text-only | 🟡 Sedang |
| 3 | **4 produk belum ada caption** | Affiliate cuma bisa post produk #1 | 🟡 Sedang |
| 4 | **Belum ada auto-post** | Masih butuh approval manual | 🟢 Rendah (by design) |

### Soal #1 — LLM mati

Cek:
```bash
curl http://127.0.0.1:20128/v1/models
```

Kalau mati, nyalain 9router. Kalau gak bisa, sistem tetap jalan pakai fallback
(6 pasang caption = cukup 3 hari).

### Soal #2 — Pool gambar

Butuh **14 gambar** (7 siang + 7 malam) buat seminggu.

### Soal #3 — Caption produk

Bikin caption buat produk #2-5:
```bash
python affiliate_flow.py caption --product-id 2
```

---

## 🎮 Cara Kontrol Manual

```bash
# Cek status semua
python scheduler_v2.py --status

# Cek stok caption fallback
python scheduler_v2.py --fallback

# Generate manual (paksa, walau udah jalan hari ini)
python scheduler_v2.py Malam --force

# Posting setelah approval
python scheduler_v2.py --post 1

# Cek kesehatan angle pool
python angle_picker.py

# Cek status katalog affiliate
python affiliate_flow.py status

# Cek statistik gambar
python process_inbox.py --stats
```

---

## 📱 Yang Lo Terima di Telegram

### Draft (2× sehari)
```
🧵 DRAFT MALAM — TEXT-ONLY
ID 19 · short/mid_scene/confident/callback

1️⃣ Opsi 1 ✅ (100/100 · AI 0)
spill set crinkle yang gak bikin gerah dong.
yang gue punya adem tapi warnanya luntur abis dicuci

2️⃣ Opsi 2 ✅ (100/100 · AI 0)
lemari penuh tapi tiap malem tetep bengong mikirin outfit besok.
gimana cara berhenti begini?

👉 Balas post 1 atau post 2
👉 Atau skip buat buang draft ini
```

### Notif sukses
```
✅ POST #19 TERKIRIM

📝 Tipe     : Random
📊 Panjang  : 97 karakter
🖼️ Gambar   : Tidak
⏰ Waktu    : 20:45 WIB
```

### Notif gagal
```
❌ POST #19 GAGAL

📝 Tipe     : Affiliate
🛍️ Produk   : Kulot Linen
⚠️ Error    : Tombol Post tidak ditemukan

👉 Aman di-retry, gagal sebelum posting
```

### Notif status tidak pasti
```
⚠️ POST #19 STATUS TIDAK PASTI

🔍 Masalah  : Timeout setelah klik Post

🚨 JANGAN AUTO-RETRY
Post mungkin sudah terkirim. Cek dulu:
https://www.threads.com/@bifrost333
```

---

## 📌 Ringkasan 1 Paragraf

Sistem sekarang: **cron 2× sehari** (12:58 & 20:45) generate 2 opsi caption
pakai **DNA style unik**, lewatin **quality gate** yang nolak klaim palsu dan
engagement bait, lalu kirim ke **Telegram buat lo approve**. Setelah lo balas
"post 1", sistem posting ke Threads pakai **anti double-post guard**, kirim
**gambar** kalau mode-nya random_image, taruh **link affiliate di reply**, dan
kasih **notif hasil**. Yang masih manual: **riset topik, generate gambar,
sortir gambar, isi caption gambar, dan approve draft**. PR terbesar sekarang:
**LLM 9router mati** (cuma bisa pakai 6 caption fallback) dan **pool gambar
hampir habis** (1 siang + 1 malam).
