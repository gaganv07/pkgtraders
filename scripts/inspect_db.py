import sqlite3

def main():
    conn = sqlite3.connect("database/trading.db")
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in c.fetchall()]
    print("Tables:", tables)
    for table in tables:
        c.execute(f"PRAGMA table_info({table})")
        columns = [r[1] for r in c.fetchall()]
        print(f"Table {table} columns:", columns)
        c.execute(f"SELECT COUNT(*) FROM {table}")
        count = c.fetchone()[0]
        print(f"Table {table} rows:", count)
        if count > 0:
            c.execute(f"SELECT * FROM {table} LIMIT 1")
            print(f"Sample row from {table}:", c.fetchone())
    conn.close()

if __name__ == "__main__":
    main()
