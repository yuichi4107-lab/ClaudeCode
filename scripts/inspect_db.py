import sqlite3

DB_PATH = r'D:\data\nankan.db'

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

tables = ['races', 'horses', 'race_entries', 'horse_history_cache', 'race_payouts', 'scrape_log']
for t in tables:
    try:
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        print(f"{t}: {cur.fetchone()[0]}")
    except Exception as e:
        print(f"{t}: ERROR {e}")

print('\nSample races:')
try:
    cur.execute("SELECT race_id, race_date, race_name FROM races ORDER BY race_date LIMIT 5")
    for row in cur.fetchall():
        print(row)
except Exception as e:
    print('races sample ERROR', e)

conn.close()
