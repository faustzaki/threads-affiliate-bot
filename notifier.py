"""
notifier.py — Notif Telegram dengan format jelas.

Format dirancang biar lo bisa baca cepat di HP tanpa buka laptop:
- Sukses: tau produk apa, tipe apa, jam berapa
- Gagal: tau error apa, harus ngapain
- Unknown: tau harus cek manual (JANGAN retry)
"""

import json
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

WIB = timezone(timedelta(hours=7))


def _send(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[notifier] Telegram belum dikonfigurasi")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = json.dumps({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }).encode()

    try:
        req = urllib.request.Request(url, data=payload,
                                     headers={"Content-Type": "application/json"})
        r = urllib.request.urlopen(req, timeout=20)
        return json.loads(r.read().decode()).get("ok", False)
    except Exception as e:
        print(f"[notifier] gagal kirim: {e}")
        return False


def _now():
    return datetime.now(WIB).strftime("%H:%M WIB")


def notify_posted(post_no, post_type, caption_preview="", product=None,
                  price=None, has_image=False, link_in_reply=False, threads_url=None):
    """
    Notif sukses.

    post_type: "random" | "affiliate"
    """
    lines = [f"✅ <b>POST #{post_no} TERKIRIM</b>", ""]

    if post_type == "affiliate":
        lines.append(f"📝 Tipe     : <b>Affiliate</b>")
        if product:
            lines.append(f"🛍️ Produk   : {product}")
        if price:
            lines.append(f"💰 Harga    : {price}")
    else:
        lines.append(f"📝 Tipe     : <b>Random</b>")
        if caption_preview:
            lines.append(f"📊 Panjang  : {len(caption_preview)} karakter")

    lines.append(f"🖼️ Gambar   : {'Ya' if has_image else 'Tidak'}")
    if link_in_reply:
        lines.append(f"🔗 Link     : Di reply")
    lines.append(f"⏰ Waktu    : {_now()}")

    if threads_url:
        lines.append(f"\n🔗 <a href='{threads_url}'>Lihat post</a>")

    return _send("\n".join(lines))


def notify_failed(post_no, post_type, error, product=None, image_path=None):
    """Notif gagal — aman retry."""
    lines = [f"❌ <b>POST #{post_no} GAGAL</b>", ""]
    lines.append(f"📝 Tipe     : {'Affiliate' if post_type=='affiliate' else 'Random'}")
    if product:
        lines.append(f"🛍️ Produk   : {product}")
    lines.append(f"⚠️ Error    : {error}")
    if image_path:
        lines.append(f"🖼️ Gambar   : {image_path.split('/')[-1] if '/' in image_path else image_path}")
    lines.append(f"⏰ Waktu    : {_now()}")
    lines.append("")
    lines.append("👉 <i>Aman di-retry, gagal sebelum posting</i>")
    return _send("\n".join(lines))


def notify_unknown(post_no, post_type, error, product=None):
    """
    Notif publish_unknown — JANGAN retry.
    Ini yang paling penting: mencegah double post.
    """
    lines = [f"⚠️ <b>POST #{post_no} STATUS TIDAK PASTI</b>", ""]
    lines.append(f"📝 Tipe     : {'Affiliate' if post_type=='affiliate' else 'Random'}")
    if product:
        lines.append(f"🛍️ Produk   : {product}")
    lines.append(f"🔍 Masalah  : {error}")
    lines.append(f"⏰ Waktu    : {_now()}")
    lines.append("")
    lines.append("🚨 <b>JANGAN AUTO-RETRY</b>")
    lines.append("Post mungkin sudah terkirim. Cek dulu di Threads:")
    lines.append("https://www.threads.com/@bifrost333")
    return _send("\n".join(lines))


def notify_quality_rejected(post_no, post_type, reasons):
    """Notif kalau quality gate nolak caption."""
    lines = [f"🚫 <b>POST #{post_no} DITOLAK QUALITY GATE</b>", ""]
    lines.append(f"📝 Tipe     : {'Affiliate' if post_type=='affiliate' else 'Random'}")
    lines.append("")
    for r in reasons[:5]:
        lines.append(f"❌ {r}")
    lines.append(f"\n⏰ {_now()}")
    lines.append("\n👉 <i>Caption perlu direvisi dulu</i>")
    return _send("\n".join(lines))


def notify_daily_summary(stats):
    """Ringkasan harian — opsional."""
    lines = ["📊 <b>RINGKASAN POOL</b>", ""]
    lines.append(f"📥 Inbox        : {stats.get('inbox', 0)}")
    lines.append(f"☀️ Random siang : {stats.get('random_siang', 0)}")
    lines.append(f"🌙 Random malam : {stats.get('random_malam', 0)}")
    lines.append(f"🛍️ Affiliate    : {stats.get('affiliate', 0)}")
    if stats.get('duplikat'):
        lines.append(f"⚠️ Duplikat     : {stats['duplikat']}")
    if stats.get('tanpa_caption'):
        lines.append(f"📝 Tanpa caption: {stats['tanpa_caption']}")
    lines.append(f"\n⏰ {_now()}")
    return _send("\n".join(lines))


def test_connection():
    """Tes koneksi Telegram."""
    return _send(
        "🤖 <b>Tes Notifier</b>\n\n"
        "Kalau lo lihat pesan ini, Telegram udah nyambung.\n"
        f"⏰ {_now()}"
    )


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        ok = test_connection()
        print("Telegram:", "✅ OK" if ok else "❌ GAGAL — cek token & chat_id di .env")
    else:
        print("=== CONTOH FORMAT NOTIF ===\n")

        print("[1] SUKSES — AFFILIATE")
        print("-" * 55)
        print(f"""✅ POST #12 TERKIRIM

📝 Tipe     : Affiliate
🛍️ Produk   : Kulot Linen Highwaist
💰 Harga    : Rp59.000
🖼️ Gambar   : Ya
🔗 Link     : Di reply
⏰ Waktu    : 20:45 WIB""")

        print("\n[2] SUKSES — RANDOM TEXT-ONLY")
        print("-" * 55)
        print(f"""✅ POST #13 TERKIRIM

📝 Tipe     : Random
📊 Panjang  : 180 karakter
🖼️ Gambar   : Tidak
⏰ Waktu    : 12:58 WIB""")

        print("\n[3] GAGAL (aman retry)")
        print("-" * 55)
        print(f"""❌ POST #14 GAGAL

📝 Tipe     : Affiliate
🛍️ Produk   : Kemeja Linen Oversize
⚠️ Error    : Tombol Post tidak ditemukan
⏰ Waktu    : 20:45 WIB

👉 Aman di-retry, gagal sebelum posting""")

        print("\n[4] STATUS TIDAK PASTI (JANGAN retry)")
        print("-" * 55)
        print(f"""⚠️ POST #15 STATUS TIDAK PASTI

📝 Tipe     : Random
🔍 Masalah  : Timeout setelah klik Post
⏰ Waktu    : 20:45 WIB

🚨 JANGAN AUTO-RETRY
Post mungkin sudah terkirim. Cek dulu di Threads:
https://www.threads.com/@bifrost333""")

        print("\n" + "=" * 55)
        print("Tes kirim beneran: python notifier.py --test")
