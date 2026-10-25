# Kualitas Post & Alur Affiliate

Tiga masalah yang diselesaikan:
1. Post keliatan **template** → `style_engine.py`
2. Post keliatan **AI-generated** → deteksi + aturan prompt
3. **Link affiliate otomatis** tanpa API Shopee → `affiliate_link.py`

---

## 🔴 TEMUAN KRITIS DULU

Gua cek 5 link affiliate lo. Hasilnya:

```
⚠️ [1] Kulot Linen — link pendek tapi TANPA affiliate_id
     https://s.shopee.co.id/5fpkj5RGXk
     -> gak ada komisi!
```

**Kelima produk lo gak punya `affiliate_id` di linknya.** Artinya:
- Orang klik → masuk Shopee
- Orang beli → **lo TIDAK dapat komisi**
- Link itu cuma shortlink biasa, bukan affiliate link

**Ini harus dibenerin dulu sebelum posting apapun.**

---

## 🔗 Solusi: Link Affiliate Tanpa API

Kabar baik: **lo TIDAK butuh Shopee Open API.** Ada rumus resmi dari
Shopee Help Center Indonesia yang bisa dipakai manual.

### Rumus resmi (dari help.shopee.co.id/10/article/184879)

```
https://s.shopee.co.id/an_redir
  ?origin_link={URL_PRODUK_ENCODED}
  &affiliate_id={ID_LO}
  &sub_id={TRACKING}
```

### Cara dapat Affiliate ID

1. Daftar gratis: **https://affiliate.shopee.co.id**
2. Login → menu **Profil / Akun**
3. Cari **"Affiliate ID"** — bentuknya angka, contoh `12345678`

### Cara update semua link sekaligus

```bash
# lihat dulu apa yang akan berubah
python affiliate_link.py --update --affiliate-id 12345678 --dry-run

# kalau udah yakin, jalankan
python affiliate_link.py --update --affiliate-id 12345678

# verifikasi
python affiliate_link.py --validate
```

Output yang benar:
```
✅ [1] Kulot Linen Highwaist
    affiliate_id=12345678 sub_id=threads-01
```

### Tes satu link

```bash
python affiliate_link.py --test "https://shopee.co.id/Produk-i.123.456" --affiliate-id 12345678
```

---

## 🎨 Anti-Template: Style DNA

### Masalah (dari analisis 14 post lo)

```
🔴 86% post diawali huruf kecil
🔴 71% panjangnya mirip (rata-rata 208 char, SD cuma 49)
🟡 64% ada emoticon di posisi yang sama
🟡 43% pakai titik gantung (...)
```

**Artinya:** bukan isinya yang template, tapi **polanya**. Semua post lo
punya bentuk yang sama, cuma beda kata.

### Solusi: 7 dimensi style, 441.000 kombinasi

| Dimensi | Jumlah | Contoh |
|---|---|---|
| **Panjang** | 5 | ultra_short, short, medium, long, very_long |
| **Pembuka** | 12 | statement, question, dialogue, timestamp, confession, observation, capslock, mid_scene, numbers, negation, comparison, sound |
| **Nada** | 7 | deadpan, dramatic, wholesome, resigned, chaotic, confident, vulnerable |
| **Struktur** | 7 | linear, twist_ending, list, call_response, callback, no_ending, escalation |
| **Emoticon** | 5 | none, one_end, one_mid, two_spread, text_only |
| **Kosakata** | 6 | gen_z, jaksel, betawi, santai, dramatis, minimal |
| **Sudut pandang** | 5 | self, observer, you, we, third_person |

**441.000 kombinasi.** 10 post berturut-turut hampir mustahil sama.

### Cara kerja

```python
from style_engine import StyleDNA

dna = StyleDNA.for_post(post_id=12)   # deterministik per post_id
print(dna)
# <StyleDNA medium/observation/dramatic/call_response>

print(dna.to_prompt())
```

Output prompt:
```
DNA STYLE (WAJIB DIIKUTI PERSIS):
- Panjang    : [medium] 45-70 kata. 3 kalimat. Ada setup -> twist.
- Pembuka    : [observation] Observasi soal orang lain.
- Nada       : [dramatic] Lebay, berlebihan, teatrikal.
- Struktur   : [call_response] Pertanyaan lalu jawab sendiri.
- Emoticon   : [two_spread] Dua emoticon, dipisah jarak.
- Kosakata   : [minimal] Kalimat pendek. Gak banyak kata sambung.
- Sudut pandang: [we] Kolektif: 'kita tuh ya...'
```

### Kenapa ini lebih bagus dari "random"

| Random murni | Style DNA |
|---|---|
| Bisa ngasih 3 post "medium/deadpan/linear" berturut-turut | Deterministik per post_id, dijamin beda |
| Gak ada jaminan variasi | Variasi **terstruktur** |
| Susah debug kalau jelek | Tiap post punya signature |

---

## 🤖 Anti-AI-Detection

### Pola yang bikin teks keliatan AI

`style_engine.py` deteksi 10 pola:

| Pola | Contoh |
|---|---|
| Frasa formal | "penting untuk dicatat", "perlu diingat" |
| Enumerasi | "pertama-tama", "selanjutnya" |
| Kata sambung formal | "oleh karena itu", "thus", "hence" |
| Frasa akademik | "dapat disimpulkan" |
| **Em-dash (—)** | AI suka banget ini |
| Buzzword | "delve", "leverage", "robust", "seamless" |
| Panjang kalimat seragam | semua kalimat ~40 char = AI |
| Baris seragam | semua baris ~60 char = template |

### Tes

```
🔴 Template AI — skor AI: 60/100
    - Frasa formal AI
    - Enumerasi formal
    - Kata sambung formal

🟢 Natural — skor AI: 0/100
    ✓ gak ada pola AI terdeteksi
```

**Aturan:** skor < 20 = aman. Skor > 40 = tulis ulang.

### Aturan prompt anti-AI

Wajib masuk ke system prompt:

```
DILARANG:
- Em-dash (—)  ← AI paling sering kena ini
- "penting untuk dicatat", "dapat disimpulkan"
- "pertama-tama", "selanjutnya", "oleh karena itu"
- Kalimat yang panjangnya seragam
- Baris yang panjangnya seragam
- Buzzword: delve, leverage, robust, seamless

WAJIB:
- Variasi panjang kalimat (ada yang 5 kata, ada yang 25 kata)
- Variasi panjang baris
- Kalau ragu, pakai kalimat lebih pendek
```

---

## 🔄 Alur: LINK → GAMBAR → CAPTION → POST

### Kenyataan yang harus diterima

Gua tes ambil gambar produk dari URL Shopee:

```
Target: shopee.co.id/Kulot-Linen-Highwaist-i.304674514.10211048648
Hasil : HTML 157KB, og:image TIDAK ADA, kena anti-bot
```

**Shopee memblokir scraping.** Gambar produk **tidak bisa** diambil otomatis.

Jadi alurnya harus manual di titik gambar, otomatis di titik lain.

### Diagram

```
┌──────────────────────────────────────────────────────────────┐
│ TAHAP 1: INPUT PRODUK  (lo, 1 menit per produk)             │
│                                                              │
│   python affiliate_flow.py add \                             │
│     --url "https://shopee.co.id/Produk-i.123.456" \          │
│     --nama "Rok Plisket Midi" \                              │
│     --harga "Rp45.000" \                                     │
│     --detail "bahan plisket jatuh, pinggang karet" \         │
│     --kategori bawahan \                                     │
│     --affiliate-id 12345678                                  │
│                                                              │
│   ✅ Link affiliate dibuat otomatis                          │
│   ✅ Prompt gambar dibuat otomatis                           │
│   ✅ Masuk katalog dengan status "perlu_gambar"              │
└──────────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────────┐
│ TAHAP 2: GENERATE GAMBAR  (lo, Nano Banana)                 │
│                                                              │
│   python affiliate_flow.py prompt --product-id 6             │
│   → copy prompt yang keluar                                  │
│   → paste ke Nano Banana                                     │
│   → simpan ke media/inbox/affiliate/06/                      │
└──────────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────────┐
│ TAHAP 3: CAPTION  (semi-otomatis, butuh vision)             │
│                                                              │
│   python affiliate_flow.py caption --product-id 6            │
│   → script kasih prompt buat agent                           │
│   → agent baca gambar + tulis caption styling                │
│   → simpan: --caption "hasil"                                │
│                                                              │
│   ✅ Quality gate otomatis nolak klaim palsu                 │
└──────────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────────┐
│ TAHAP 4: POST  (otomatis penuh)                             │
│                                                              │
│   python affiliate_flow.py post --product-id 6               │
│   → posting ke Threads                                       │
│   → link di reply                                            │
│   → notif Telegram                                           │
│   → update post_count                                        │
└──────────────────────────────────────────────────────────────┘
```

### Prompt gambar otomatis per kategori

Script generate prompt sesuai kategori produk:

**bawahan:**
```
close-up photo of a hand pulling the fabric of {warna} wide-leg pants,
showing the linen texture and how it stretches, no face, no person,
flat lay on white bedsheet, natural window light,
authentic smartphone photo, slight grain, real fabric wrinkles
--ar 3:4 --no 3d render, cgi, plastic skin, text, watermark, logo, face, person
```

**atasan:** tangan ngangkat kain, tunjukin tekstur
**hijab:** kain draping di tangan, tunjukin jatuhnya
**outer:** tangan nyentuh rajut, tunjukin kelembutan
**rumahan:** kain crinkle flat lay, tunjukin wrinkle

**Prinsip:** **NO FACE, NO PERSON.** Cuma tangan + produk. Ini yang bikin
gak ketara AI dan aman dari uncanny valley.

---

## 📋 Caption Affiliate: Styling, Bukan Review

### ❌ Yang DITOLAK quality gate

```
"udah gue pake 2 minggu, kulot linen ini beneran adem dan gak melar.
 wajib checkout!"
```

Alasan:
- `Klaim durasi pemakaian` — lo belum beli
- `Kata template: wajib checkout`

### ✅ Yang LOLOS

```
"kulot linen beige ini paling aman dipair sama atasan putih boxy
 + loafers cream. bahannya jatuh jadi gak keliatan kaku,
 cocok buat kerja maupun kuliah."
```

Kenapa lolos:
- Fokus **matching & styling** (nilai buat pembaca)
- Deskripsi bahan dari **fakta produk**, bukan pengalaman
- Gak ada klaim absolut

### Rumus caption styling

```
1. Sebut produk + warna
2. Pairing dengan 2 item lain (spesifik, bukan "atasan apa aja")
3. Alasan kenapa cocok (bahan/cutting, dari fakta produk)
4. Konteks pemakaian (kerja/kuliah/hangout)
```

### Yang boleh vs gak boleh

| ✅ Boleh (fakta produk) | ❌ Gak boleh (klaim pengalaman) |
|---|---|
| "bahannya linen" | "udah gue pake 2 minggu" |
| "cuttingannya longgar" | "beneran adem banget" |
| "pinggang karet" | "gak melar sama sekali" |
| "warna beige netral" | "paling bagus yang pernah gue coba" |
| "cocok buat kerja" | "100 orang udah beli" |

---

## 🚀 Quick Start

```bash
# 1. FIX LINK DULU (paling penting)
python affiliate_link.py --validate
python affiliate_link.py --update --affiliate-id ID_LO

# 2. Cek status katalog
python affiliate_flow.py status

# 3. Lihat prompt gambar yang perlu digenerate
python affiliate_flow.py prompt

# 4. Generate gambar → simpan ke media/inbox/affiliate/{id}/

# 5. Isi caption (pakai agent vision)
python affiliate_flow.py caption --product-id 1

# 6. Post
python affiliate_flow.py post --product-id 1 --dry-run   # tes dulu
python affiliate_flow.py post --product-id 1
```

---

## 📊 Checklist sebelum posting affiliate

- [ ] Sudah daftar Shopee Affiliate
- [ ] Sudah punya Affiliate ID
- [ ] Sudah jalankan `affiliate_link.py --update`
- [ ] Sudah `--validate` dan semua ✅
- [ ] Gambar produk sudah ada di `media/inbox/affiliate/{id}/`
- [ ] Caption sudah lolos quality gate
- [ ] Sudah dry-run sekali

**Kalau semua ✅, baru posting.**

---

## ⚠️ Catatan penting

**1. Link lama lo gak ada affiliate_id.** Ini masalah paling urgent.
Tanpa fix ini, semua posting = kerja gratis.

**2. Shopee blokir scraping.** Gambar harus manual. Ini gak bisa diakalin
tanpa API official (yang lo belum punya).

**3. Jangan klaim pengalaman.** Kalau belum beli, jangan bilang "udah gue pake".
Quality gate akan nolak, dan kalau lolos pun itu bohong ke followers.

**4. Style DNA bukan pengganti kualitas.** Dia cuma jamin **variasi bentuk**.
Isi tetap harus bagus.

**5. Cek pool health berkala.**
```bash
python angle_picker.py
```
Kalau `days_left < 3`, waktunya tambah angle baru.
