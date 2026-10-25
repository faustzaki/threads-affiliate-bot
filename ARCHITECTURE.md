# Threads Auto Poster — Arsitektur Baru

Sistem posting Threads otomatis dengan quality gate, anti double-post,
dan pool gambar terpisah untuk random & affiliate.

---

## 🎯 Jawaban: 2 folder terpisah

**PERTANYAAN LO:** "gambar affiliate dan random, dipisah atau digabung?"

**JAWABAN: DIPISAH.** Alasannya beda fungsi total:

| | **Random** | **Affiliate** |
|---|---|---|
| Objek gambar | **Persona** (orangnya) | **Produk** (barangnya) |
| Caption nyesuain | Visual gambar | Data produk |
| Sumber | AI persona, konsisten | Foto produk asli |
| Rotasi | Per slot (siang/malam) | Per product_id |

Kalau digabung, lo bakal bingung: gambar cewek di kamar mau dipair sama
caption jualan kulot? **Gak nyambung.**

---

## 📁 Struktur folder

```
threads-affiliate-bot/
│
├── media/
│   ├── inbox/                 ← LO DROP GAMBAR BARU DI SINI
│   │   ├── siang/             (opsional, auto-detect slot)
│   │   ├── malam/
│   │   └── affiliate/         (auto-detect kind)
│   │
│   └── pool/                  ← SIAP PAKAI (ada caption)
│       ├── random/
│       │   ├── siang/
│       │   │   ├── s_001.jpg
│       │   │   └── s_001.json   ← caption nempel di sini
│       │   └── malam/
│       │       ├── m_001.jpg
│       │       └── m_001.json
│       └── affiliate/
│           └── 01_produk/
│               ├── a_001.jpg
│               └── a_001.json
│
├── quality_gate.py       ← tolak konten jelek
├── publish_guard.py      ← anti double-post
├── image_pool.py         ← rotasi gambar
├── angle_picker.py       ← anti duplikat teks
├── notifier.py           ← notif Telegram
├── poster.py             ← Playwright posting (FIXED)
├── process_inbox.py      ← inbox → pool
├── run_post.py           ← ORCHESTRATOR (entry point)
└── inbox_manifest.json   ← manifest sementara
```

---

## 🔄 Alur lengkap

### FASE 1 — Stok gambar (lo, batch bulanan)

1. Generate gambar pakai Nano Banana / tool lo
2. Taruh di `media/inbox/` (subfolder `siang/`, `malam/`, atau `affiliate/`)
3. Jalankan:
   ```bash
   python process_inbox.py --describe
   ```
4. Minta agent Hermes isi caption:
   > *"baca inbox_manifest.json, deskripsikan tiap gambar pakai vision,
   > tulis caption Threads yang nyambung sama visual, simpan balik"*
5. Review hasilnya
6. Commit:
   ```bash
   python process_inbox.py --commit
   ```

**Hasil:** gambar pindah ke `media/pool/`, siap dipost otomatis.

### FASE 2 — Posting (otomatis)

```bash
# Random dengan gambar
python run_post.py random --slot malam

# Random text-only
python run_post.py random --text "caption lo di sini"

# Affiliate (besok: text-only dulu)
python run_post.py affiliate --product-id 1 --text-only --caption "..."
```

### FASE 3 — Notif (otomatis)

Setelah tiap post, notif masuk Telegram dengan format jelas.

---

## 🛡️ Tiga ide dari repo yanstd888 yang diadopsi

### 1. Quality Gate (`quality_gate.py`)

Menolak sebelum dipost:

| Yang ditolak | Contoh |
|---|---|
| **Engagement bait** | "like postingan ini biar dapet diskon" |
| **Klaim durasi** | "udah gue pake 2 minggu" (padahal belum beli) |
| **Klaim kualitas absolut** | "beneran adem dan gak melar" |
| **Klaim hasil tubuh** | "kulit jadi glowing" |
| **Klaim jumlah pembeli** | "100 orang udah beli" |
| **Superlatif** | "paling bagus", "nomor 1" |
| **Link shortener** | bit.ly, tinyurl, s.id |
| **Kata template bot** | "wajib checkout", "racun shopee" |
| **Caption < 40 char** | terlalu pendek |
| **Caption > 500 char** | melebihi limit Threads |

**Skor 0-100, minimal 70 buat lolos.**

Contoh nyata:

```
❌ DITOLAK (skor 0/100)
  ❌ Klaim durasi pemakaian → 'udah gue pake 2 minggu'
  ❌ Kata template/bot terdeteksi: 'wajib checkout'

✅ LOLOS (skor 100/100)
  "kulot linen beige ini paling aman dipair sama atasan putih boxy
   + loafers cream. bahannya jatuh jadi gak keliatan kaku."
```

### 2. Anti double-post (`publish_guard.py`)

**Masalah:** cron jalan 2× (restart) → post dobel.

**Solusi:** atomic claim.

```
Claim #1: True   ← proses ini lanjut
Claim #2: False  ← proses lain skip
Claim #3: False
```

### 3. `publish_unknown` — JANGAN retry buta

**Masalah:** timeout setelah klik "Post" → gak tau udah kepost atau belum.

**Solusi:** 3 status jelas.

| Status | Arti | Aksi |
|---|---|---|
| `POSTED` | Sukses terverifikasi | Lanjut |
| `FAILED` | Gagal **sebelum** klik Post | ✅ Aman retry |
| `UNKNOWN` | Gagal **setelah** klik Post | 🚨 **JANGAN retry** |

Kalau `UNKNOWN`, sistem otomatis coba verifikasi ke profil. Kalau gak bisa
verifikasi, kirim notif "JANGAN AUTO-RETRY" + link profil.

---

## 🖼️ Soal gambar — keputusan final

### Random (persona)

**Manual, batch bulanan.** Alasan:
- Pollinations free cuma ~1 gambar lalu 402 (udah gua tes)
- HF Inference 410 Gone (deprecated)
- Semua hasil gratis ada **watermark** = bunuh kredibilitas
- Manual Nano Banana: gratis, kualitas terbaik, no watermark

**Pool + rotasi otomatis** yang bikin tetap "otomatis" dari sisi posting.

### Affiliate (produk)

**Cara lo (bagus, gua setuju):**

```
foto produk asli → AI ubah jadi kontekstual → TANPA MUKA → gak ketara AI
```

Contoh prompt:
```
tangan narik bahan kulot beige, tekstur linen keliatan jelas,
gak melar walau ditarik, close-up, natural window light,
flat lay di kasur putih, no face, no person, --ar 3:4
```

**Kenapa aman:**
- Objek asli (bukan halusinasi AI)
- Gak ada wajah → gak ada uncanny valley
- Konteks jujur (lo emang promosi produk itu)

**Caption wajib gaya "styling/pamer", BUKAN "review":**

```
✅ "kulot linen beige ini paling aman dipair sama atasan putih boxy
   + loafers cream. bahannya jatuh jadi gak keliatan kaku."

❌ "udah 2 minggu gue pake, beneran adem dan gak melar"
   (klaim pengalaman — akan DITOLAK quality gate)
```

---

## 📱 Format notif Telegram

### Sukses (affiliate)
```
✅ POST #12 TERKIRIM

📝 Tipe     : Affiliate
🛍️ Produk   : Kulot Linen Highwaist
💰 Harga    : Rp59.000
🖼️ Gambar   : Ya
🔗 Link     : Di reply
⏰ Waktu    : 20:45 WIB
```

### Sukses (random text-only)
```
✅ POST #13 TERKIRIM

📝 Tipe     : Random
📊 Panjang  : 180 karakter
🖼️ Gambar   : Tidak
⏰ Waktu    : 12:58 WIB
```

### Gagal (aman retry)
```
❌ POST #14 GAGAL

📝 Tipe     : Affiliate
🛍️ Produk   : Kemeja Linen Oversize
⚠️ Error    : Tombol Post tidak ditemukan
⏰ Waktu    : 20:45 WIB

👉 Aman di-retry, gagal sebelum posting
```

### Status tidak pasti (JANGAN retry)
```
⚠️ POST #15 STATUS TIDAK PASTI

📝 Tipe     : Random
🔍 Masalah  : Timeout setelah klik Post
⏰ Waktu    : 20:45 WIB

🚨 JANGAN AUTO-RETRY
Post mungkin sudah terkirim. Cek dulu di Threads:
https://www.threads.com/@bifrost333
```

---

## 🎲 Anti-duplikat teks (3 lapis)

### Masalah lama

```
13 angle, butuh 14 draw/minggu
→ pool HABIS
→ P(duplikat dalam 6 malam) = 87,7%
```

Bukan kebetulan. **Kepastian statistik.**

### Solusi baru

**Lapis 1 — History filter**
Skip angle yang kata kuncinya muncul 14 hari terakhir.

**Lapis 2 — Pool diperluas**
- Malam: 13 → **40 angle**
- Siang: 15 → **29 angle**

**Lapis 3 — Tema harian (bukan mingguan)**

```python
THEMES = ["fashion", "kos", "kuliner", "kerja", "sosial", "selfcare", "random"]
theme = THEMES[day.toordinal() % 7]
```

**Kenapa tema harian > tema mingguan:**

| Tema mingguan | Tema harian |
|---|---|
| Tiap minggu harus ngarang 13 angle baru | Nambah angle kapan aja |
| Capek, berhenti di minggu 3 | Sustainable |
| Lompatan terlalu jauh buat akun baru | Rotasi halus |

### Cek kesehatan pool

```bash
python angle_picker.py
```

Output:
```
Pool health: ✅ OK
  Total angle    : 40
  Masih fresh    : 22
  Dipakai 14 hari: 18
  Estimasi cukup : 11 hari (@2 angle/hari)
```

---

## 📊 Porsi konten

| Tipe | Porsi | Gambar | Otomatis |
|---|---|---|---|
| **A** Text-only random | 40% | ❌ | ✅ Full |
| **B** Random + gambar | 30% | ✅ Pool | ✅ Full |
| **C** Affiliate | 30% | ⚠️ Nanti | ✅ Full |

**Besok:** affiliate text-only dulu (pilihan lo — paling aman, gak butuh stok gambar).

---

## 🚀 Quick start

```bash
# 1. Cek status
python run_post.py status

# 2. Lihat inbox
python process_inbox.py --list

# 3. Proses inbox (3 langkah)
python process_inbox.py --describe
#    -> minta agent isi caption di inbox_manifest.json
python process_inbox.py --commit

# 4. Cek statistik pool
python process_inbox.py --stats

# 5. Dry-run sebelum posting
python run_post.py random --slot malam --dry-run

# 6. Posting beneran
python run_post.py random --slot malam

# 7. Cek post yang perlu verifikasi manual
python run_post.py status
```

---

## ⚠️ Troubleshooting

### `Session file tidak ada`
Session Threads expired. Perlu login ulang:
```bash
python poster.py "test"
```

### `Pool kosong`
Belum ada gambar siap pakai. Cek:
```bash
python process_inbox.py --stats
```

### `Quality gate nolak terus`
Caption terlalu mirip template. Cek alasan di output, revisi caption.

### `publish_unknown` muncul
**JANGAN retry.** Cek manual di Threads dulu:
https://www.threads.com/@bifrost333

Kalau ternyata gak kepost, baru retry:
```bash
python run_post.py status
```

---

## 📝 Catatan penting

1. **Gambar manual, posting otomatis.** Ini trade-off yang lo pilih — kualitas
   lebih penting dari kecepatan.

2. **Caption dari gambar, bukan sebaliknya.** Jadi gak akan "miss" —
   caption selalu nyambung sama visual.

3. **Affiliate: styling, bukan review.** Kalau belum beli, jangan klaim
   pengalaman. Quality gate akan nolak.

4. **`publish_unknown` bukan bug, itu fitur.** Mencegah double post.

5. **Pool health dicek berkala.** Kalau `days_left < 3`, waktunya batch
   gambar baru.
