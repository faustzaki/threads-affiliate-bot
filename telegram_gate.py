import urllib.request
import urllib.parse
import json
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

def send_draft_to_telegram(product_name: str, price: str, main_post: str, reply_post: str, image_url: str = None) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[!] TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing in config.")
        return False

    caption = (
        f"🧵 <b>DRAFT KONTEN THREADS (AFFILIATE)</b>\n\n"
        f"📦 <b>Produk:</b> {product_name} (~{price})\n\n"
        f"📝 <b>POST UTAMA (Copy):</b>\n"
        f"<code>{main_post}</code>\n\n"
        f"💬 <b>REPLY PERTAMA (Copy):</b>\n"
        f"<code>{reply_post}</code>\n\n"
        f"<i>Status: Siap dipost saat akun sudah selesai warm-up.</i>"
    )

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": caption,
        "parse_mode": "HTML"
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            return res.get("ok", False)
    except Exception as e:
        print(f"[!] Gagal kirim Telegram: {e}")
        return False

if __name__ == "__main__":
    ok = send_draft_to_telegram(
        product_name="Loose Pants Celana Kulot Highwaist Linen",
        price="Rp55.000",
        main_post="awalnya skeptis celana linen 55 ribuan biasanya zonk tipis nerawang. ternyata cuttingannya rapi, paha tebel aman ga nyeplak. link tokonya di reply ya.",
        reply_post="beli di official store ini: https://s.shopee.co.id/9zycTvmkpq"
    )
    print("Telegram send result:", ok)
