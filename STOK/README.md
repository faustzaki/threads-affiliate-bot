# 📁 STOK — Tempat Lo Nyimpen Bahan

Semua bahan posting ada di sini. **Cuma drop gambar, sisanya otomatis.**

---

## Struktur

```
STOK/
├── 01-GAMBAR-RANDOM/
│   ├── SIANG/          ← drop gambar post siang
│   └── MALAM/          ← drop gambar post malam
│
├── 02-GAMBAR-AFFILIATE/
│   ├── 1-Kulot-Linen/          ← 1 folder per produk
│   ├── 2-Kemeja-Linen/
│   └── ...
│
├── 03-LINK-AFFILIATE/
│   ├── link-produk.md    ← semua link, tinggal copy
│   └── link-produk.json
│
└── 99-SUDAH-DIPAKAI/     ← (lama, gak dipakai lagi)
```

---

## Aturan simpel

### 1. Gambar random
Drop ke `01-GAMBAR-RANDOM/SIANG/` atau `MALAM/`. Nama file bebas.

```bash
python cek_stok.py --sync
```
→ otomatis pindah ke pool + bikin sidecar.

### 2. Gambar affiliate
Drop ke `02-GAMBAR-AFFILIATE/{ID}-{Nama}/`. 2-3 gambar per produk.

```bash
python cek_stok.py --sync
```
→ otomatis pindah ke pool affiliate.

### 3. Link affiliate
**Otomatis** di `03-LINK-AFFILIATE/link-produk.md`. Gak perlu ngapa-ngapain.

Kalau mau nambah produk baru, pakai **Notion** (lebih enak).

---

## 🔄 Siklus hidup gambar (otomatis)

```
STOK/          media/pool/         media/arsip/        (hilang)
   │               │                    │
   │  --sync       │                    │
   └──────────────>│                    │
                   │                    │
                   │  dipost            │
                   ├───────────────────>│
                   │                    │
                   │                    │  --purge (30 hari)
                   │                    └───────────────> ✗
```

### Berapa kali boleh dipakai?

| Jenis | Batas | Kenapa |
|---|---|---|
| **Random** | **1x** | Foto orang/gaya. Dipost 2x = follower notice |
| **Affiliate** | **3x** | Produk sama boleh, caption/angle beda |

### Setelah dipost, otomatis:
1. `used` naik +1
2. Kalau udah mentok batas → **pindah ke `media/arsip/`**
3. Di arsip **nunggu 30 hari** (buat audit kalau ada masalah)
4. Lewat 30 hari → **dihapus permanen** (`--purge`)

**Gak ada gambar lama kepost ulang.** Pool cuma isi yang `used < batas`.

### Link affiliate beda

Link **gak dihapus**, cuma rotasi. Produk yang udah 3x dipost tetap ada di katalog
tapi jarang kepilih (`ORDER BY post_count ASC`). Alasannya: link itu aset, bukan
konsumsi. Yang perlu diganti gambar + caption-nya, bukan link-nya.

---

## Cek stok kapan aja

```bash
python cek_stok.py
```

Kalau kosong, sistem **gak akan posting** yang butuh gambar/link.
Dia cuma posting text-only.

---

## Perintah lengkap

| Perintah | Fungsi |
|---|---|
| `python cek_stok.py` | Lihat stok + arsip |
| `python cek_stok.py --sync` | Pindah STOK → pool |
| `python cek_stok.py --purge` | Hapus arsip > 30 hari |
| `python cek_stok.py --purge --dry-run` | Lihat apa yang akan dihapus |
| `python notion_sync.py --pull` | Notion → SQLite |
| `python notion_sync.py --push` | SQLite → Notion |

**Notion auto-sync:** tiap cron jalan, `cron_wrapper.py` otomatis pull sebelum
posting dan push setelah posting. Lo gak perlu manual.

---

## Notion

Database: **Katalog Produk Affiliate**
https://app.notion.com/p/404112a407a68139a3d8c9dbf91c0e45

Di sana lo bisa:
- Tambah produk baru (auto masuk SQLite)
- Edit caption
- Lihat prompt gambar
- Pantau status (Perlu Gambar / Siap Post / Sudah Dipost)
- Lihat jumlah gambar (auto update)

**Gambar tetap di folder ini** — Notion gak bisa simpen path lokal.
