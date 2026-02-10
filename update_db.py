import sqlite3

conn = sqlite3.connect("warranty.db")
cur = conn.cursor()

cur.executescript("""
CREATE TABLE IF NOT EXISTS category (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_code TEXT UNIQUE NOT NULL,
    product_name TEXT NOT NULL,
    category TEXT
);

""")

conn.commit()
conn.close()
print("✅ DB READY")
