"""
publish_guard.py — Anti double-post & publish_unknown handling.

Diadaptasi dari pola lib/publish-claim.ts + lib/publish.ts
(yanstd888/threads-auto-poster).

Masalah yang diselesaikan:
1. Cron jalan 2x (restart) -> post dobel  => atomic claim
2. Timeout setelah klik Post -> gak tau udah kepost atau belum
   => status publish_unknown, JANGAN retry buta
"""

import sqlite3
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "affiliate_content.db"
WIB = timezone(timedelta(hours=7))

# Status yang mungkin
STATUS_PENDING = "pending"
STATUS_PUBLISHING = "publishing"
STATUS_POSTED = "posted"
STATUS_FAILED = "failed"
STATUS_UNKNOWN = "publish_unknown"   # <- paling penting
STATUS_SUPERSEDED = "superseded"


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS publish_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proposal_id INTEGER,
            post_type TEXT,
            attempt INTEGER DEFAULT 1,
            status TEXT,
            error TEXT,
            image_path TEXT,
            threads_url TEXT,
            started_at TIMESTAMP,
            finished_at TIMESTAMP
        )
    """)
    conn.commit()
    return conn


def claim_post(proposal_id):
    """
    Klaim atomik. Return True kalau berhasil diklaim (aman lanjut posting).
    Return False kalau proses lain udah klaim (SKIP, jangan posting).

    Ini mencegah: cron jalan 2x -> 2 post dobel.
    """
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        UPDATE cron_proposals
        SET status = ?
        WHERE id = ? AND status = ?
    """, (STATUS_PUBLISHING, proposal_id, STATUS_PENDING))
    claimed = cur.rowcount == 1
    conn.commit()

    if claimed:
        cur.execute("""
            INSERT INTO publish_log (proposal_id, status, started_at)
            VALUES (?, ?, ?)
        """, (proposal_id, STATUS_PUBLISHING, datetime.now(WIB).isoformat()))
        conn.commit()

    conn.close()
    return claimed


def release_claim(proposal_id, final_status, error=None, image_path=None, threads_url=None):
    """Lepas klaim dengan status akhir."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        UPDATE cron_proposals SET status = ? WHERE id = ?
    """, (final_status, proposal_id))
    cur.execute("""
        UPDATE publish_log
        SET status = ?, error = ?, image_path = ?, finished_at = ?
        WHERE proposal_id = ? AND status = ?
    """, (final_status, error, image_path,
          datetime.now(WIB).isoformat(), proposal_id, STATUS_PUBLISHING))
    conn.commit()
    conn.close()


def get_stale_publishing(minutes=10):
    """
    Cari post yang nyangkut di status 'publishing' lebih dari N menit.
    Ini tanda proses mati di tengah jalan (crash / restart).

    PENTING: post seperti ini TIDAK boleh auto-retry, karena mungkin
    udah kepost ke Threads. Harus ditandai publish_unknown.
    """
    conn = get_db()
    cur = conn.cursor()
    cutoff = (datetime.now(WIB) - timedelta(minutes=minutes)).isoformat()
    cur.execute("""
        SELECT id, proposal_id, started_at
        FROM publish_log
        WHERE status = ? AND started_at < ?
    """, (STATUS_PUBLISHING, cutoff))
    rows = cur.fetchall()
    conn.close()
    return rows


def recover_stale():
    """
    Jalankan saat startup. Tandai post yang nyangkut jadi publish_unknown.

    Return: jumlah post yang ditandai.
    """
    stale = get_stale_publishing()
    if not stale:
        return 0

    conn = get_db()
    cur = conn.cursor()
    for log_id, proposal_id, started in stale:
        cur.execute("""
            UPDATE cron_proposals SET status = ? WHERE id = ?
        """, (STATUS_UNKNOWN, proposal_id))
        cur.execute("""
            UPDATE publish_log
            SET status = ?, error = ?, finished_at = ?
            WHERE id = ?
        """, (STATUS_UNKNOWN,
              "App restart/proses mati saat publishing; verifikasi manual",
              datetime.now(WIB).isoformat(), log_id))
    conn.commit()
    conn.close()
    return len(stale)


class PublishResult:
    """Hasil publishing dengan 3 kemungkinan yang jelas."""
    POSTED = "posted"       # sukses, terverifikasi
    FAILED = "failed"       # gagal SEBELUM klik post -> aman retry
    UNKNOWN = "unknown"     # gagal SETELAH klik post -> JANGAN retry

    def __init__(self, kind, message="", url=None):
        self.kind = kind
        self.message = message
        self.url = url

    def __repr__(self):
        icon = {"posted": "✅", "failed": "❌", "unknown": "⚠️"}[self.kind]
        return f"{icon} {self.kind.upper()}: {self.message}"


def safe_publish(proposal_id, publish_fn, post_type="random", image_path=None):
    """
    Wrapper aman buat publishing.

    Args:
        proposal_id: id di cron_proposals
        publish_fn: callable() -> PublishResult
        post_type: "random" | "affiliate"
        image_path: path gambar (buat log)

    Return: PublishResult
    """
    # 1. Klaim atomik
    if not claim_post(proposal_id):
        return PublishResult(PublishResult.FAILED,
                             f"Post {proposal_id} sudah diklaim proses lain — skip")

    # 2. Eksekusi
    try:
        result = publish_fn()
    except Exception as e:
        # Exception = gak tau udah kepost atau belum
        release_claim(proposal_id, STATUS_UNKNOWN,
                      error=f"Exception: {e}", image_path=image_path)
        return PublishResult(PublishResult.UNKNOWN,
                             f"Exception saat publish: {e}")

    # 3. Catat hasil
    if result.kind == PublishResult.POSTED:
        release_claim(proposal_id, STATUS_POSTED,
                      image_path=image_path, threads_url=result.url)
    elif result.kind == PublishResult.FAILED:
        release_claim(proposal_id, STATUS_FAILED,
                      error=result.message, image_path=image_path)
    else:  # UNKNOWN
        release_claim(proposal_id, STATUS_UNKNOWN,
                      error=result.message, image_path=image_path)

    return result


def get_unverified_posts():
    """Ambil semua post dengan status publish_unknown — perlu cek manual."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, day_number, slot, opt1_text, created_at
        FROM cron_proposals
        WHERE status = ?
        ORDER BY created_at DESC
    """, (STATUS_UNKNOWN,))
    rows = cur.fetchall()
    conn.close()
    return rows


# ─────────────────────────────────────────────────────────────
# TEST
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== TEST ATOMIC CLAIM ===")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""INSERT INTO cron_proposals (day_number, slot, opt1_text, status)
                   VALUES (99, 'Test', 'test claim', 'pending')""")
    test_id = cur.lastrowid
    conn.commit()
    conn.close()

    print(f"Test post ID: {test_id}")
    print(f"Claim #1: {claim_post(test_id)}  (harus True)")
    print(f"Claim #2: {claim_post(test_id)}  (harus False — udah diklaim)")
    print(f"Claim #3: {claim_post(test_id)}  (harus False)")

    print("\n=== TEST RECOVERY ===")
    print(f"Stale publishing (>0 menit): {len(get_stale_publishing(minutes=0))}")
    n = recover_stale()
    print(f"Recovered: {n} post ditandai publish_unknown")

    print("\n=== TEST SAFE PUBLISH ===")
    def mock_ok():
        return PublishResult(PublishResult.POSTED, "sukses", "https://threads.com/p/123")

    def mock_fail():
        return PublishResult(PublishResult.FAILED, "tombol post gak ketemu")

    def mock_unknown():
        return PublishResult(PublishResult.UNKNOWN, "timeout setelah klik post")

    for name, fn in [("ok", mock_ok), ("fail", mock_fail), ("unknown", mock_unknown)]:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""INSERT INTO cron_proposals (day_number, slot, opt1_text, status)
                       VALUES (99, 'Test', ?, 'pending')""", (f"test {name}",))
        tid = cur.lastrowid
        conn.commit()
        conn.close()
        r = safe_publish(tid, fn, "random")
        print(f"  [{name:8}] -> {r}")

    print("\n=== UNVERIFIED POSTS ===")
    for row in get_unverified_posts():
        print(f"  ID {row[0]}: {row[3][:40]}...")

    # cleanup
    conn = get_db()
    conn.execute("DELETE FROM cron_proposals WHERE day_number = 99")
    conn.execute("DELETE FROM publish_log WHERE proposal_id NOT IN (SELECT id FROM cron_proposals)")
    conn.commit()
    conn.close()
    print("\n[cleanup] test data dihapus")
