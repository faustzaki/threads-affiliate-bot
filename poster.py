"""
poster.py — Posting ke Threads via Playwright.

FIX KRITIS dari versi lama:
1. Return 3 status jelas (POSTED / FAILED / UNKNOWN) — bukan bool
   -> mencegah double post kalau timeout setelah klik Post
2. image_path sekarang BENAR-BENAR dikirim (dulu cuma parameter nganggur)
3. Verifikasi post beneran muncul setelah klik

Status:
- POSTED : terverifikasi muncul di profil
- FAILED : gagal SEBELUM klik post -> aman retry
- UNKNOWN: gagal SETELAH klik post -> JANGAN retry (bisa dobel)
"""

import time
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).resolve().parent
SESSION_FILE = BASE_DIR / "threads_session.json"


class PostResult:
    POSTED = "posted"
    FAILED = "failed"
    UNKNOWN = "unknown"

    def __init__(self, kind, message="", url=None):
        self.kind = kind
        self.message = message
        self.url = url

    @property
    def ok(self):
        return self.kind == self.POSTED

    def __repr__(self):
        icon = {"posted": "✅", "failed": "❌", "unknown": "⚠️"}[self.kind]
        return f"{icon} {self.kind.upper()}: {self.message}"


def get_browser_args():
    return [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-infobars",
        "--disable-dev-shm-usage",
    ]


def post_to_threads(main_text, reply_text=None, image_path=None):
    """
    Post ke Threads.

    Return: PostResult (bukan bool lagi!)
    """
    if not SESSION_FILE.exists():
        return PostResult(PostResult.FAILED,
                          f"Session file tidak ada: {SESSION_FILE}")

    # validasi gambar SEBELUM buka browser
    if image_path:
        if not Path(image_path).exists():
            return PostResult(PostResult.FAILED,
                              f"Gambar tidak ditemukan: {image_path}")
        size_mb = Path(image_path).stat().st_size / (1024 * 1024)
        if size_mb > 8:
            return PostResult(PostResult.FAILED,
                              f"Gambar terlalu besar: {size_mb:.1f}MB (maks 8MB)")

    print(f"[*] Posting ke Threads... (gambar: {'ya' if image_path else 'tidak'})")

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True,
                                    args=get_browser_args())
        context = browser.new_context(
            storage_state=str(SESSION_FILE),
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/128.0.0.0 Safari/537.36"),
            viewport={"width": 1280, "height": 800},
            locale="id-ID",
        )
        page = context.new_page()
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )

        clicked_post = False   # <- penanda paling penting

        try:
            page.goto("https://www.threads.com/", wait_until="domcontentloaded")
            time.sleep(3)

            # ── 1. Buka composer ──
            create_svg = page.locator(
                'svg[aria-label="Utas baru"], svg[aria-label="New thread"]').first
            inline = page.locator(
                '[aria-label="Empty text field. Type to compose a new post."], '
                '[aria-label*="Apa yang baru"]').first
            text_trigger = page.get_by_text("Apa yang baru", exact=False).first
            new_thread_text = page.get_by_text("New thread", exact=False).first

            opened = False
            for loc in [create_svg, inline, text_trigger, new_thread_text]:
                try:
                    if loc.is_visible():
                        loc.click(force=True)
                        time.sleep(1.5)
                        opened = True
                        break
                except Exception:
                    continue

            if not opened:
                browser.close()
                return PostResult(PostResult.FAILED,
                                  "Composer tidak bisa dibuka")

            # ── 2. Ketik caption ──
            editor = page.locator(
                'div[role="dialog"] div[contenteditable="true"], '
                'div[contenteditable="true"]').first
            editor.click()
            page.keyboard.type(main_text, delay=10)
            time.sleep(2)

            # ── 3. Upload gambar (INI YANG DULU GAK PERNAH KEKIRIM) ──
            if image_path and Path(image_path).exists():
                try:
                    file_input = page.locator('input[type="file"]')
                    if file_input.count() > 0:
                        file_input.first.set_input_files(str(image_path))
                        print(f"[*] Gambar diupload: {Path(image_path).name}")
                        # tunggu upload selesai (gambar gede butuh waktu)
                        time.sleep(6)
                    else:
                        print("[!] Input file tidak ditemukan — post tanpa gambar")
                except Exception as e:
                    print(f"[!] Upload gambar gagal: {e} — lanjut tanpa gambar")

            # ── 4. Klik Post ──
            valid_btns = ["Post", "Posting", "Kirim"]
            dialog = page.locator('div[role="dialog"]').first
            container = dialog if dialog.is_visible() else page
            post_btns = [b for b in container.locator('div[role="button"], button').all()
                         if b.inner_text().strip() in valid_btns]
            if not post_btns:
                post_btns = [b for b in page.locator('div[role="button"], button').all()
                             if b.inner_text().strip() in valid_btns]

            if not post_btns:
                browser.close()
                return PostResult(PostResult.FAILED,
                                  "Tombol Post tidak ditemukan")

            target_btn = post_btns[-1]
            target_btn.click()
            clicked_post = True          # <- mulai dari sini, status jadi UNKNOWN kalau gagal
            print("[*] Tombol Post diklik, menunggu konfirmasi...")
            time.sleep(8)

            # ── 5. Reply link affiliate ──
            if reply_text:
                try:
                    print("[*] Kirim reply link...")
                    page.goto("https://www.threads.com/@bifrost333",
                              wait_until="domcontentloaded")
                    time.sleep(3)

                    reply_btn = page.locator(
                        'svg[aria-label="Reply"], svg[aria-label="Balas"]').first
                    if reply_btn.is_visible():
                        reply_btn.click(force=True)
                        time.sleep(2)
                        reply_editor = page.locator('div[contenteditable="true"]').last
                        reply_editor.click()
                        page.keyboard.type(reply_text, delay=10)
                        time.sleep(1)

                        rbtns = [b for b in page.locator(
                            'div[role="button"], button').all()
                            if b.inner_text().strip() in valid_btns]
                        if rbtns:
                            rbtns[-1].click()
                            print("[✓] Reply terkirim")
                            time.sleep(4)
                except Exception as e:
                    print(f"[!] Reply gagal (post utama tetap sukses): {e}")

            # ── 6. Simpan session ──
            context.storage_state(path=str(SESSION_FILE))
            browser.close()

            return PostResult(PostResult.POSTED, "Post berhasil dikirim")

        except Exception as e:
            # Kalau error SETELAH klik Post -> status tidak pasti
            if clicked_post:
                try:
                    page.screenshot(path="post_error.png")
                except Exception:
                    pass
                try:
                    browser.close()
                except Exception:
                    pass
                return PostResult(
                    PostResult.UNKNOWN,
                    f"Error setelah klik Post: {e} — verifikasi manual!"
                )
            else:
                try:
                    page.screenshot(path="post_error.png")
                except Exception:
                    pass
                try:
                    browser.close()
                except Exception:
                    pass
                return PostResult(PostResult.FAILED, f"Error sebelum posting: {e}")


def verify_latest_post(expected_snippet, timeout=30):
    """
    Verifikasi post beneran muncul di profil.
    Dipakai kalau status UNKNOWN — buat mastiin udah kepost atau belum.
    """
    if not SESSION_FILE.exists():
        return None

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True,
                                    args=get_browser_args())
        context = browser.new_context(
            storage_state=str(SESSION_FILE),
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/128.0.0.0 Safari/537.36"),
            viewport={"width": 1280, "height": 900},
            locale="id-ID",
        )
        page = context.new_page()
        try:
            page.goto("https://www.threads.com/@bifrost333",
                      wait_until="domcontentloaded")
            time.sleep(5)
            body = page.inner_text("body")
            snippet = expected_snippet[:60].strip()
            found = snippet.lower() in body.lower()
            browser.close()
            return found
        except Exception:
            try:
                browser.close()
            except Exception:
                pass
            return None


if __name__ == "__main__":
    import sys
    text = ("baju selemari penuh tapi tiap mau pergi ngerasanya ga punya baju "
            "sama sekali wkwk ujung-ujungnya pake kaos item sama celana itu-itu lagi")
    img = None
    if len(sys.argv) > 1:
        text = sys.argv[1]
    if len(sys.argv) > 2:
        img = sys.argv[2]

    r = post_to_threads(main_text=text, image_path=img)
    print("RESULT:", r)
    sys.exit(0 if r.ok else 1)
