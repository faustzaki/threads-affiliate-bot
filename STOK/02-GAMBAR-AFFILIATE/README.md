# Gambar Affiliate

Satu folder per produk. Nama folder: `{ID}-{NamaProduk}`

Contoh:
```
02-GAMBAR-AFFILIATE/
├── 1-Kulot-Linen/
│   ├── 1.jpg
│   ├── 2.jpg
│   └── 3.jpg
├── 2-Kemeja-Linen/
│   └── 1.jpg
```

**Prompt gambar** bisa lo dapet dari:
```bash
python affiliate_flow.py prompt --product-id 1
```

**Prinsip prompt:** NO FACE, cuma tangan + produk.
