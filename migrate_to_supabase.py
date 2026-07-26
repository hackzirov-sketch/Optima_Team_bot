"""Copy the existing SQLite data into the configured Supabase Postgres database."""
import os
import sqlite3

import psycopg
from dotenv import load_dotenv

load_dotenv()
sqlite_path = os.getenv("DATABASE_PATH", "bot.db")
database_url = os.getenv("DATABASE_URL", "").strip()

if not database_url:
    raise SystemExit("DATABASE_URL .env faylida ko‘rsatilmagan.")
if not os.path.exists(sqlite_path):
    raise SystemExit(f"SQLite fayli topilmadi: {sqlite_path}")

source = sqlite3.connect(sqlite_path)
source.row_factory = sqlite3.Row

with psycopg.connect(database_url, options="-c search_path=bot_app") as target:
    with target.cursor() as cur:
        for row in source.execute("SELECT * FROM users"):
            data = dict(row)
            cur.execute("""INSERT INTO users(tg_id,username,full_name,phone,portfolio,about,role,status,created_at,specialty)
              VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
              ON CONFLICT(tg_id) DO UPDATE SET username=excluded.username,full_name=excluded.full_name,
              phone=excluded.phone,portfolio=excluded.portfolio,about=excluded.about,
              role=excluded.role,status=excluded.status,specialty=excluded.specialty""",
              (data["tg_id"],data["username"],data["full_name"],data["phone"],data["portfolio"],data["about"],
               data["role"],data["status"],data["created_at"],data.get("specialty")))
        for row in source.execute("SELECT * FROM groups"):
            cur.execute("""INSERT INTO groups(chat_id,title,added_by,created_at) VALUES(%s,%s,%s,%s)
              ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title,added_by=excluded.added_by""", tuple(row))
        for row in source.execute("SELECT * FROM tasks"):
            cur.execute("""INSERT INTO tasks(id,name,description,deadline,group_id,created_by,created_at)
              OVERRIDING SYSTEM VALUE VALUES(%s,%s,%s,%s,%s,%s,%s)
              ON CONFLICT(id) DO UPDATE SET name=excluded.name,description=excluded.description,
              deadline=excluded.deadline,group_id=excluded.group_id,created_by=excluded.created_by""", tuple(row))
        task_columns = {r[1] for r in source.execute("PRAGMA table_info(task_users)")}
        for row in source.execute("SELECT * FROM task_users"):
            data = dict(row)
            cur.execute("""INSERT INTO task_users(task_id,user_id,status,completed_at) VALUES(%s,%s,%s,%s)
              ON CONFLICT(task_id,user_id) DO UPDATE SET status=excluded.status,completed_at=excluded.completed_at""",
              (data["task_id"], data["user_id"], data.get("status", "assigned") if "status" in task_columns else "assigned",
               data.get("completed_at") if "completed_at" in task_columns else None))
        if "settings" in {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
            for row in source.execute("SELECT key,value FROM settings"):
                cur.execute("""INSERT INTO settings(key,value) VALUES(%s,%s)
                  ON CONFLICT(key) DO UPDATE SET value=excluded.value""", tuple(row))
        cur.execute("""SELECT setval(pg_get_serial_sequence('tasks','id'),
          greatest(coalesce((select max(id) from tasks), 1), 1), true)""")

source.close()
print("SQLite ma’lumotlari Supabase’ga muvaffaqiyatli ko‘chirildi.")
