import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "affiliate_content.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS drafts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_name TEXT,
        price TEXT,
        highlights TEXT,
        affiliate_link TEXT,
        main_post TEXT,
        reply_post TEXT,
        status TEXT DEFAULT 'draft',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS affiliate_catalog (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_name TEXT,
        price TEXT,
        commission_rate TEXT,
        highlights TEXT,
        origin_url TEXT,
        affiliate_link TEXT,
        category TEXT,
        post_count INTEGER DEFAULT 0,
        last_posted_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    conn.close()

def add_catalog_item(product_name: str, price: str, highlights: str, affiliate_link: str, origin_url: str = "", commission_rate: str = "", category: str = "daily_wear") -> int:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO affiliate_catalog (product_name, price, commission_rate, highlights, origin_url, affiliate_link, category)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (product_name, price, commission_rate, highlights, origin_url, affiliate_link, category))
    cid = cur.lastrowid
    conn.commit()
    conn.close()
    return cid

def get_next_product_to_post() -> dict:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    SELECT id, product_name, price, highlights, affiliate_link, commission_rate, category
    FROM affiliate_catalog
    WHERE affiliate_link IS NOT NULL AND affiliate_link != ''
    ORDER BY post_count ASC, last_posted_at ASC
    LIMIT 1
    """)
    row = cur.fetchone()
    conn.close()
    if row:
        return {
            "id": row[0],
            "name": row[1],
            "price": row[2],
            "highlights": row[3],
            "link": row[4],
            "commission_rate": row[5],
            "category": row[6]
        }
    return None

def mark_product_posted(product_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    UPDATE affiliate_catalog
    SET post_count = post_count + 1, last_posted_at = CURRENT_TIMESTAMP
    WHERE id = ?
    """, (product_id,))
    conn.commit()
    conn.close()


def save_draft(product_name: str, price: str, highlights: str, affiliate_link: str, main_post: str, reply_post: str) -> int:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO drafts (product_name, price, highlights, affiliate_link, main_post, reply_post, status)
    VALUES (?, ?, ?, ?, ?, ?, 'draft')
    """, (product_name, price, highlights, affiliate_link, main_post, reply_post))
    draft_id = cur.lastrowid
    conn.commit()
    conn.close()
    return draft_id

if __name__ == "__main__":
    init_db()
    print("Database initialized at:", DB_PATH)
