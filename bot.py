import asyncio
import html
import json
import logging
import os
import re
from contextlib import suppress
from datetime import datetime, timedelta, timezone

import aiosqlite
from aiohttp import web
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ChatType, MessageEntityType, ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand, CallbackQuery, InlineKeyboardButton as AiogramInlineKeyboardButton, InlineKeyboardMarkup,
    ErrorEvent, KeyboardButton as AiogramKeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder as AiogramInlineKeyboardBuilder
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN", "")
DB_PATH = os.getenv("DATABASE_PATH", "bot.db")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
SUPERADMINS = {int(x) for x in os.getenv("SUPERADMIN_IDS", "").split(",") if x.strip().isdigit()}
BOOTSTRAP_ADMINS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
DEFAULT_GROUP_ID = int(os.getenv("DEFAULT_GROUP_ID", "0"))
pg_pool = AsyncConnectionPool(
    conninfo=DATABASE_URL,
    kwargs={"row_factory": dict_row, "options": "-c search_path=bot_app"},
    min_size=1,
    max_size=5,
    open=False,
) if DATABASE_URL else None
APP_READY = False
STARTED_AT = datetime.now(timezone.utc)
TASHKENT_TZ = timezone(timedelta(hours=5))


def create_health_app():
    async def health(_request):
        return web.json_response({"status": "ok" if APP_READY else "starting"}, status=200 if APP_READY else 503)

    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    return app

router = Router()


class Application(StatesGroup):
    full_name = State()
    age = State()
    specialty = State()
    phone = State()
    portfolio = State()
    about = State()
    confirm = State()


class TaskForm(StatesGroup):
    name = State()
    description = State()
    deadline = State()
    selection_mode = State()
    users = State()
    group = State()
    confirm = State()


class AdminManage(StatesGroup):
    add_id = State()
    remove_id = State()


class DesignForm(StatesGroup):
    emoji_id = State()
    preview = State()


class MessageEmojiForm(StatesGroup):
    value = State()
    preview = State()


class TaskResult(StatesGroup):
    content = State()


class TaskReviewForm(StatesGroup):
    note = State()


class ProfileEdit(StatesGroup):
    value = State()


class UserSearch(StatesGroup):
    query = State()


class ApplicationReviewForm(StatesGroup):
    note = State()


class TaskQuestionForm(StatesGroup):
    question = State()
    answer = State()


class MessageTemplateForm(StatesGroup):
    value = State()


class TemplateForm(StatesGroup):
    name = State()
    description = State()


PAGE_SIZE = 8
STATUS_LABELS = {"draft": "To‘ldirilmagan", "pending": "Kutilmoqda", "accepted": "Qabul qilingan", "rejected": "Rad etilgan", "blocked": "Bloklangan"}
TASK_STATUS_LABELS = {"assigned": "⏳ Boshlanmagan", "in_progress": "🔄 Bajarilmoqda", "submitted": "👀 Tekshiruvda", "rework": "🔁 Qayta ishlash", "approved": "✅ Tasdiqlangan", "completed": "✅ Tugallangan"}
ROLE_LABELS = {"user": "User", "manager": "Manager", "admin": "Admin", "superadmin": "Superadmin"}
SPECIALTIES = {"backend": "Backend", "frontend": "Frontend", "fullstack": "Full stack", "vibecoder": "Vibecoder"}
DESIGN = {"button_style": "primary", "premium_emoji_id": "", "button_designs": {}, "message_emojis": {}, "message_templates": {}}

MESSAGE_TEMPLATE_CATALOG = {
    "application_accepted": ("Ariza qabul qilindi", "{full_name}, arizangiz qabul qilindi. Endi vazifalaringizni menyudan kuzatishingiz mumkin."),
    "application_rejected": ("Ariza rad etildi", "{full_name}, arizangiz rad etildi. Sabab: {note}. Qayta arizani 24 soatdan keyin topshirishingiz mumkin."),
    "task_assigned": ("Yangi topshiriq", "Yangi topshiriq: {task_name}. Muddat: {deadline}."),
    "task_reminder": ("Vazifa eslatmasi", "Eslatma: {task_name}. Muddat: {deadline}. Qolgan vaqt: {remaining}."),
}

MESSAGE_EMOJI_CATALOG = [
    ("application", "Ariza", "📝"), ("user", "Foydalanuvchi", "👤"),
    ("age", "Yosh", "🎂"), ("specialty", "Yo‘nalish", "💼"),
    ("username", "Username", "🔗"), ("phone", "Telefon", "☎️"),
    ("portfolio", "Portfolio", "📎"), ("about", "O‘zi haqida", "🗒"),
    ("accepted", "Qabul qilindi", "✅"), ("rejected", "Rad etildi", "❌"),
    ("task", "Topshiriq", "📌"), ("reminder", "Eslatma", "🔔"),
    ("deadline", "Muddat", "⏰"), ("warning", "Ogohlantirish", "⚠️"),
    ("group", "Guruh", "👥"), ("completed", "Tugallandi", "☑️"),
]
MESSAGE_EMOJI_DEFAULTS = {key: fallback for key, _label, fallback in MESSAGE_EMOJI_CATALOG}

BUTTON_CATALOG = [
    ("application", "📝 Ariza to‘ldirish"), ("admin_panel", "📊 Admin panel"),
    ("users", "👥 Userlar"), ("team", "👥 Jamoa"), ("team_admins", "🛡 Adminlar"),
    ("team_managers", "🧑‍💼 Managerlar"), ("team_developers", "💻 Dasturchilar"), ("new_task", "➕ Topshiriq"),
    ("tasks", "📋 Topshiriqlar"), ("groups", "📂 Guruhlar"),
    ("admins", "🛡 Adminlar"), ("button_design", "🎨 Tugma dizayni"),
    ("message_emoji_design", "✨ Xabar emojilari"), ("message_templates", "📝 Xabar matnlari"),
    ("home", "🏠 Bosh sahifa"), ("design_list", "🎨 Tugmalar ro‘yxati"),
    ("save", "💾 Saqlash"), ("reset_default", "♻️ Standartga qaytarish"),
    ("switch_role", "🔄 Rolni almashtirish"), ("superadmin", "👑 Superadmin"),
    ("admin", "🛡 Admin"), ("user", "👤 User"),
    ("backend", "⚙️ Backend"), ("frontend", "🎨 Frontend"),
    ("fullstack", "🧩 Full stack"), ("vibecoder", "✨ Vibecoder"),
    ("send_phone", "📱 Telefon raqamni yuborish"),
    ("appoint_admin", "➕ Admin tayinlash"), ("remove_admin", "➖ Adminni olib tashlash"),
    ("edit", "✏️ Tahrirlash"), ("send_application", "📨 Arizani jo‘natish"),
    ("reject", "❌ Rad etish"), ("accept", "✅ Qabul qilish"),
    ("activate", "✅ Faollashtirish"), ("block", "⛔ Bloklash"),
    ("refresh", "🔄 Yangilash"), ("continue", "Davom etish ➡️"),
    ("cancel", "❌ Bekor qilish"), ("send_task", "🚀 Yuborish"),
    ("done", "☑️ Bajardim"), ("remind", "🔔 Eslatma yuborish"),
    ("my_tasks", "📥 Vazifalar"), ("my_completed_tasks", "✅ Tugallangan vazifalarim"),
    ("profile", "👤 Profilim"), ("search", "🔎 Qidiruv"), ("templates", "🧾 Shablonlar"),
    ("audit", "🕘 Audit"), ("submissions", "👀 Natijalar"), ("begin_task", "▶️ Boshladim"),
    ("open_applications", "📂 Arizalar bo‘limini ochish"), ("view_application", "📝 Arizani ko‘rish"),
    ("submit_result", "📤 Natija topshirish"), ("approve_result", "✅ Tasdiqlash"),
    ("rework", "🔁 Qayta ishlash"), ("save_template", "🧾 Shablon sifatida saqlash"),
    ("pending_applications", "⏳ Arizalar"), ("pending_status", "⏳ Kutilmoqda"),
    ("accepted_status", "✅ Qabul qilingan"), ("blocked_status", "⛔ Bloklangan"),
    ("confirm_yes", "✅ Ha, tasdiqlayman"), ("confirm_remove", "✅ Ha, olib tashlash"),
    ("confirm_no", "❌ Yo‘q"), ("single_user", "👤 Bitta user"),
    ("multiple_users", "👥 Bir nechta user"), ("ask_question", "💬 Savol berish"),
    ("answer_question", "💬 Javob berish"), ("portfolio_file", "📄 Portfolio faylini ko‘rish"),
    ("open_portfolio", "📎 Portfolio faylini ochish"), ("edit_phone", "☎️ Telefon"),
    ("edit_portfolio", "💼 Portfolio"), ("edit_about", "🗒 O‘zim haqimda"),
    ("edit_specialty", "💼 Yo‘nalishni o‘zgartirish"), ("deadline_1h", "⏰ 1 soat"),
    ("deadline_today", "Bugun 18:00"), ("deadline_tomorrow", "Ertaga 18:00"),
    ("deadline_week", "7 kun"), ("premium_emoji", "✨ Premium emojini yuborish"),
    ("unicode_fallback", "🙂 Unicode fallback"),
    ("back", "⬅️ Orqaga"), ("previous", "⬅️"), ("next", "➡️"),
]
BUTTON_LABELS = dict(BUTTON_CATALOG)


def infer_button_key(text: str):
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    _clean_icon, clean_sep, clean_without_icon = clean.partition(" ")
    clean_plain = clean_without_icon if clean_sep and _clean_icon and not _clean_icon[0].isalnum() else clean
    for key, label in BUTTON_CATALOG:
        _label_icon, label_sep, label_without_icon = label.partition(" ")
        label_plain = label_without_icon if label_sep and _label_icon and not _label_icon[0].isalnum() else label
        if clean == label or clean.startswith(label + " ") or clean_plain == label_plain:
            return key
    if "Bosh menyu" in clean or "Bosh sahifa" in clean: return "home"
    if "Ro‘yxat" in clean or "Qayta tanlash" in clean: return "design_list"
    if clean.startswith("⬅️"): return "back"
    if clean.startswith("✅ Faollashtirish"): return "activate"
    if clean.startswith("⛔ Bloklash"): return "block"
    return None


def button_appearance(text: str, design_key=None):
    key = design_key or infer_button_key(text)
    custom = DESIGN["button_designs"].get(key, {}) if key else {}
    style = custom["style"] if "style" in custom else DESIGN["button_style"]
    emoji = custom["emoji_id"] if "emoji_id" in custom else DESIGN["premium_emoji_id"]
    return (None if style == "default" else style or None), emoji or None


def button_label(text: str, emoji_id):
    if not emoji_id:
        return text
    _icon, separator, label = str(text).partition(" ")
    return label if separator and label else text


def InlineKeyboardButton(**kwargs):
    design_key = kwargs.pop("design_key", None)
    style, emoji = button_appearance(kwargs.get("text", ""), design_key)
    kwargs["text"] = button_label(kwargs.get("text", ""), emoji)
    kwargs["style"] = style
    kwargs["icon_custom_emoji_id"] = emoji
    return AiogramInlineKeyboardButton(**kwargs)


def KeyboardButton(**kwargs):
    design_key = kwargs.pop("design_key", None)
    style, emoji = button_appearance(kwargs.get("text", ""), design_key)
    kwargs["text"] = button_label(kwargs.get("text", ""), emoji)
    kwargs["style"] = style
    kwargs["icon_custom_emoji_id"] = emoji
    return AiogramKeyboardButton(**kwargs)


class InlineKeyboardBuilder(AiogramInlineKeyboardBuilder):
    def button(self, **kwargs):
        design_key = kwargs.pop("design_key", None)
        style, emoji = button_appearance(kwargs.get("text", ""), design_key)
        kwargs["text"] = button_label(kwargs.get("text", ""), emoji)
        kwargs["style"] = style
        kwargs["icon_custom_emoji_id"] = emoji
        return super().button(**kwargs)


def h(value, limit=1000):
    """Escape user text and keep the encoded result inside Telegram limits."""
    raw = str(value or "")
    escaped = html.escape(raw)
    if len(escaped) <= limit:
        return escaped
    low, high = 0, len(raw)
    while low < high:
        mid = (low + high + 1) // 2
        if len(html.escape(raw[:mid])) <= max(0, limit - 1): low = mid
        else: high = mid - 1
    return html.escape(raw[:low]) + "…"


def user_mention(user, limit=60):
    data = dict(user)
    label = data.get("full_name") or (f"@{data['username']}" if data.get("username") else str(data["tg_id"]))
    return f"<a href='tg://user?id={int(data['tg_id'])}'>{h(label, limit)}</a>"


def utc_datetime(value):
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


async def db_execute(sql: str, params=()):
    if pg_pool:
        async with pg_pool.connection() as conn:
            await conn.execute(sql.replace("?", "%s"), params)
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(sql, params)
        await db.commit()


async def db_one(sql: str, params=()):
    if pg_pool:
        async with pg_pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql.replace("?", "%s"), params)
                return await cur.fetchone()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(sql, params) as cur:
            return await cur.fetchone()


async def db_all(sql: str, params=()):
    if pg_pool:
        async with pg_pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql.replace("?", "%s"), params)
                return await cur.fetchall()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(sql, params) as cur:
            return await cur.fetchall()


async def init_db():
    if pg_pool:
        await pg_pool.open()
        await pg_pool.wait()
        await db_one("SELECT 1 AS ok")
        for admin_id in SUPERADMINS:
            await db_execute("""INSERT INTO users(tg_id,full_name,role,status)
              VALUES(?,?,'superadmin','accepted') ON CONFLICT(tg_id) DO UPDATE SET role='superadmin'""",
              (admin_id, "Superadmin"))
        for admin_id in BOOTSTRAP_ADMINS - SUPERADMINS:
            await db_execute("""INSERT INTO users(tg_id,full_name,role,status)
              VALUES(?,?,'admin','accepted') ON CONFLICT(tg_id) DO UPDATE SET role='admin'""",
              (admin_id, f"Admin {admin_id}"))
        if DEFAULT_GROUP_ID:
            await db_execute("""INSERT INTO groups(chat_id,title,added_by) VALUES(?,? ,NULL)
              ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title""", (DEFAULT_GROUP_ID, "Optima Team"))
        await load_design()
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS users(
          tg_id INTEGER PRIMARY KEY, username TEXT, full_name TEXT NOT NULL, age INTEGER,
          phone TEXT, portfolio TEXT, portfolio_file_id TEXT,
          portfolio_file_name TEXT, portfolio_file_mime TEXT, about TEXT,
          role TEXT NOT NULL DEFAULT 'user', status TEXT NOT NULL DEFAULT 'draft',
          active_mode TEXT NOT NULL DEFAULT 'user',
          specialty TEXT,
          rejected_at TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS groups(
          chat_id INTEGER PRIMARY KEY, title TEXT NOT NULL, added_by INTEGER,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS tasks(
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
          description TEXT NOT NULL, deadline TEXT NOT NULL, group_id INTEGER,
          created_by INTEGER NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS task_users(
          task_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
          status TEXT NOT NULL DEFAULT 'assigned', completed_at TEXT,
          PRIMARY KEY(task_id,user_id)
        );
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS task_templates(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,description TEXT NOT NULL,created_by INTEGER,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS audit_logs(id INTEGER PRIMARY KEY AUTOINCREMENT,actor_id INTEGER,action TEXT NOT NULL,target_type TEXT,target_id TEXT,details TEXT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS application_review_messages(
          application_user_id INTEGER NOT NULL, staff_id INTEGER NOT NULL, message_id INTEGER NOT NULL,
          sent_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(application_user_id,staff_id)
        );
        CREATE TABLE IF NOT EXISTS task_questions(id INTEGER PRIMARY KEY AUTOINCREMENT,task_id INTEGER NOT NULL,user_id INTEGER NOT NULL,question TEXT NOT NULL,answer TEXT,answered_by INTEGER,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,answered_at TEXT);
        """)
        user_columns = {row[1] for row in await (await db.execute("PRAGMA table_info(users)")).fetchall()}
        if "active_mode" not in user_columns:
            await db.execute("ALTER TABLE users ADD COLUMN active_mode TEXT NOT NULL DEFAULT 'user'")
        if "specialty" not in user_columns:
            await db.execute("ALTER TABLE users ADD COLUMN specialty TEXT")
        if "portfolio_file_id" not in user_columns:
            await db.execute("ALTER TABLE users ADD COLUMN portfolio_file_id TEXT")
        if "portfolio_file_name" not in user_columns:
            await db.execute("ALTER TABLE users ADD COLUMN portfolio_file_name TEXT")
        if "portfolio_file_mime" not in user_columns:
            await db.execute("ALTER TABLE users ADD COLUMN portfolio_file_mime TEXT")
        if "age" not in user_columns:
            await db.execute("ALTER TABLE users ADD COLUMN age INTEGER")
        if "rejected_at" not in user_columns:
            await db.execute("ALTER TABLE users ADD COLUMN rejected_at TEXT")
        if "application_review_note" not in user_columns:
            await db.execute("ALTER TABLE users ADD COLUMN application_review_note TEXT")
        if "application_reviewed_by" not in user_columns:
            await db.execute("ALTER TABLE users ADD COLUMN application_reviewed_by INTEGER")
        if "application_reviewed_at" not in user_columns:
            await db.execute("ALTER TABLE users ADD COLUMN application_reviewed_at TEXT")
        if "last_seen_at" not in user_columns:
            await db.execute("ALTER TABLE users ADD COLUMN last_seen_at TEXT")
        group_columns = {row[1] for row in await (await db.execute("PRAGMA table_info(groups)")).fetchall()}
        if "is_active" not in group_columns:
            await db.execute("ALTER TABLE groups ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
        task_columns = {row[1] for row in await (await db.execute("PRAGMA table_info(tasks)")).fetchall()}
        for name, definition in {"deadline_at":"TEXT", "group_message_id":"INTEGER", "is_pinned":"INTEGER NOT NULL DEFAULT 0"}.items():
            if name not in task_columns: await db.execute(f"ALTER TABLE tasks ADD COLUMN {name} {definition}")
        columns = {row[1] for row in await (await db.execute("PRAGMA table_info(task_users)")).fetchall()}
        if "status" not in columns:
            await db.execute("ALTER TABLE task_users ADD COLUMN status TEXT NOT NULL DEFAULT 'assigned'")
        if "completed_at" not in columns:
            await db.execute("ALTER TABLE task_users ADD COLUMN completed_at TEXT")
        for name, definition in {"result_text":"TEXT", "result_file_id":"TEXT", "result_file_name":"TEXT", "submitted_at":"TEXT", "review_note":"TEXT", "opened_at":"TEXT", "reminded_24":"INTEGER NOT NULL DEFAULT 0", "reminded_3":"INTEGER NOT NULL DEFAULT 0", "reminded_1":"INTEGER NOT NULL DEFAULT 0"}.items():
            if name not in columns: await db.execute(f"ALTER TABLE task_users ADD COLUMN {name} {definition}")
        if "rating" not in columns: await db.execute("ALTER TABLE task_users ADD COLUMN rating INTEGER")
        for admin_id in SUPERADMINS:
            await db.execute("""INSERT INTO users(tg_id,full_name,role,status)
              VALUES(?,?,'superadmin','accepted') ON CONFLICT(tg_id) DO UPDATE SET role='superadmin'""",
              (admin_id, "Superadmin"))
        for admin_id in BOOTSTRAP_ADMINS - SUPERADMINS:
            await db.execute("""INSERT INTO users(tg_id,full_name,role,status)
              VALUES(?,?,'admin','accepted') ON CONFLICT(tg_id) DO UPDATE SET role='admin'""",
              (admin_id, f"Admin {admin_id}"))
        if DEFAULT_GROUP_ID:
            await db.execute("""INSERT INTO groups(chat_id,title,added_by) VALUES(?,? ,NULL)
              ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title""", (DEFAULT_GROUP_ID, "Optima Team"))
        await db.commit()
    await load_design()


async def ensure_user(tg_user):
    await db_execute("""INSERT INTO users(tg_id,username,full_name,last_seen_at) VALUES(?,?,?,?)
      ON CONFLICT(tg_id) DO UPDATE SET username=excluded.username,
      full_name=CASE WHEN users.status='draft' THEN excluded.full_name ELSE users.full_name END,last_seen_at=excluded.last_seen_at""",
      (tg_user.id, tg_user.username, tg_user.full_name, datetime.now(timezone.utc).isoformat(timespec="seconds")))


async def audit(actor_id, action, target_type=None, target_id=None, details=None):
    await db_execute("INSERT INTO audit_logs(actor_id,action,target_type,target_id,details) VALUES(?,?,?,?,?)",
                     (actor_id, action, target_type, str(target_id) if target_id is not None else None, details))


async def create_task(data, created_by):
    if pg_pool:
        async with pg_pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""INSERT INTO tasks(name,description,deadline,deadline_at,group_id,created_by)
                  VALUES(%s,%s,%s,%s,%s,%s) RETURNING id""",
                  (data["name"], data["description"], data["deadline"], data.get("deadline_at"), data["group_id"], created_by))
                task_id = (await cur.fetchone())["id"]
                await cur.executemany("INSERT INTO task_users(task_id,user_id) VALUES(%s,%s)", [(task_id, u) for u in data["selected"]])
                return task_id
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("INSERT INTO tasks(name,description,deadline,deadline_at,group_id,created_by) VALUES(?,?,?,?,?,?)",
                               (data["name"], data["description"], data["deadline"], data.get("deadline_at"), data["group_id"], created_by))
        task_id = cur.lastrowid
        await db.executemany("INSERT INTO task_users(task_id,user_id) VALUES(?,?)", [(task_id, u) for u in data["selected"]])
        await db.commit()
        return task_id


async def role_of(user_id: int) -> str:
    row = await db_one("SELECT role FROM users WHERE tg_id=?", (user_id,))
    return row["role"] if row else "user"


async def effective_role(user_id: int) -> str:
    row = await db_one("SELECT role,active_mode FROM users WHERE tg_id=?", (user_id,))
    if not row: return "user"
    return row["active_mode"] if row["role"] == "superadmin" else row["role"]


async def is_staff(user_id: int) -> bool:
    return await effective_role(user_id) in {"superadmin", "admin", "manager"}


async def is_actual_staff(user_id: int) -> bool:
    """Direct moderation buttons must respect the permanent role, not the selected UI mode."""
    return await role_of(user_id) in {"superadmin", "admin", "manager"}


async def load_design():
    with suppress(Exception):
        for row in await db_all("SELECT key,value FROM settings"):
            if row["key"] == "button_designs":
                DESIGN["button_designs"] = json.loads(row["value"] or "{}")
            elif row["key"] == "message_emojis":
                DESIGN["message_emojis"] = json.loads(row["value"] or "{}")
            elif row["key"] == "message_templates":
                DESIGN["message_templates"] = json.loads(row["value"] or "{}")
            elif row["key"] in DESIGN:
                DESIGN[row["key"]] = row["value"]


async def save_setting(key, value):
    stored_value = json.dumps(value, ensure_ascii=False) if key in {"button_designs", "message_emojis", "message_templates"} else value
    await db_execute("""INSERT INTO settings(key,value) VALUES(?,?)
      ON CONFLICT(key) DO UPDATE SET value=excluded.value""", (key, stored_value))
    DESIGN[key] = value


def message_emoji(key: str) -> str:
    fallback = MESSAGE_EMOJI_DEFAULTS.get(key, "✨")
    config = DESIGN["message_emojis"].get(key, {})
    text = h(config.get("text") or fallback, 20)
    custom_id = config.get("custom_id")
    return f'<tg-emoji emoji-id="{h(custom_id, 40)}">{text}</tg-emoji>' if custom_id else text


def render_template(key: str, **values) -> str:
    template = DESIGN["message_templates"].get(key) or MESSAGE_TEMPLATE_CATALOG[key][1]
    safe = {name: h(value if value not in (None, "") else "—", 1000) for name, value in values.items()}
    with suppress(KeyError, ValueError, IndexError): return template.format(**safe)
    return MESSAGE_TEMPLATE_CATALOG[key][1].format(**safe)


async def save_button_design(key, style, emoji_id):
    designs = dict(DESIGN["button_designs"])
    designs[key] = {"style": style, "emoji_id": emoji_id}
    await save_setting("button_designs", designs)


def kb_button(text, **kwargs):
    return KeyboardButton(text=text, **kwargs)


def main_kb(staff=False, superadmin=False, show_application=True, accepted_user=False):
    rows = [[kb_button("🔄 Yangilash", design_key="refresh")]]
    if superadmin:
        rows = [[kb_button("🔄 Rolni almashtirish", design_key="switch_role"),
                 kb_button("🔄 Yangilash", design_key="refresh")]]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def main_inline_kb(staff=False, superadmin=False, show_application=True, accepted_user=False):
    rows = []
    if not staff and show_application:
        rows.append([InlineKeyboardButton(text="📝 Ariza to‘ldirish", callback_data="menu:application")])
    if not staff and accepted_user:
        rows += [[InlineKeyboardButton(text="📥 Vazifalar", callback_data="menu:my_tasks"),
                  InlineKeyboardButton(text="✅ Tugallangan vazifalarim", callback_data="menu:my_completed")],
                 [InlineKeyboardButton(text="👤 Profilim", callback_data="menu:profile")]]
    if staff:
        rows += [[InlineKeyboardButton(text="📊 Admin panel", callback_data="menu:panel")],
                 [InlineKeyboardButton(text="➕ Topshiriq", callback_data="menu:new_task"),
                  InlineKeyboardButton(text="📋 Topshiriqlar", callback_data="menu:tasks")],
                 [InlineKeyboardButton(text="📂 Guruhlar", callback_data="menu:groups")]]
    if superadmin:
        rows += [[InlineKeyboardButton(text="🛡 Adminlar", callback_data="menu:admins"),
                  InlineKeyboardButton(text="🎨 Tugma dizayni", callback_data="menu:design")],
                 [InlineKeyboardButton(text="✨ Xabar emojilari", callback_data="menu:message_emojis")],
                 [InlineKeyboardButton(text="📝 Xabar matnlari", callback_data="menu:message_templates")],
                 [InlineKeyboardButton(text="🔄 Rolni almashtirish", callback_data="menu:switch_role")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def send_main_menu(message, staff=False, superadmin=False):
    profile = await db_one("SELECT status,rejected_at FROM users WHERE tg_id=?", (message.from_user.id,))
    status = profile["status"] if profile else "draft"
    show_application = status == "draft"
    if status == "rejected" and profile["rejected_at"]:
        rejected_at = utc_datetime(profile["rejected_at"])
        show_application = datetime.now(timezone.utc) >= rejected_at + timedelta(hours=24)
    accepted_user = not staff and status == "accepted"
    private = message.chat.type == ChatType.PRIVATE
    if private:
        actual_superadmin = await role_of(message.from_user.id) == "superadmin"
        await message.answer("🔄 Pastdagi Yangilash tugmasi menyuni qayta ochadi.", reply_markup=main_kb(staff, actual_superadmin, show_application, accepted_user))
    await message.answer("Kerakli bo‘limni tanlang:", reply_markup=main_inline_kb(staff, superadmin, show_application, accepted_user))


def menu_texts(label):
    _icon, separator, plain = label.partition(" ")
    return {label, plain if separator else label}


@router.message(F.text.in_(menu_texts("🔄 Yangilash")))
async def refresh_main_menu(message:Message,state:FSMContext):
    await state.clear();await load_design()
    role=await effective_role(message.from_user.id)
    await send_main_menu(message,role in {"superadmin","admin","manager"},role=="superadmin")


def app_text(data, user=None):
    username = (user.username if user else None) or data.get("username") or "yo‘q"
    full_name = data.get("full_name") or (user.full_name if user else None) or ""
    specialty = SPECIALTIES.get(data.get("specialty"), "Tanlanmagan")
    suffix = "\n\n<i>Uzun matn admin paneldagi user kartasida saqlandi.</i>" if len(str(data.get("portfolio", ""))) > 1200 or len(str(data.get("about", ""))) > 2100 else ""
    portfolio = data.get("portfolio") or "—"
    if data.get("portfolio_file_id"):
        portfolio = f"{data.get('portfolio_file_name') or 'Portfolio fayli'} (PDF/DOCX)"
    return (f"<b>{message_emoji('application')} Ariza</b>\n\n{message_emoji('user')} {h(full_name, 200)}\n"
            f"{message_emoji('age')} {h(data.get('age') or '—', 20)} yosh\n{message_emoji('specialty')} {h(specialty, 100)}\n"
            f"{message_emoji('username')} @{h(username, 100)}\n{message_emoji('phone')} {h(data.get('phone'), 100)}\n"
            f"{message_emoji('portfolio')} <b>Portfolio:</b>\n{h(portfolio, 1200)}\n\n"
            f"{message_emoji('about')} <b>O‘zi haqida:</b>\n{h(data.get('about'), 2100)}{suffix}")


def portfolio_display(user):
    data=dict(user)
    if data.get("portfolio_file_id"):
        name=data.get("portfolio_file_name") or "Portfolio fayli"
        kind="PDF" if str(name).lower().endswith(".pdf") else "DOCX"
        return f"📎 <b>{h(name,300)}</b> ({kind} fayl)"
    return h(data.get("portfolio") or "—",1200)


@router.message(CommandStart())
async def start(message: Message):
    await ensure_user(message.from_user)
    if await role_of(message.from_user.id) == "superadmin":
        return await show_role_picker(message)
    staff = await is_staff(message.from_user.id)
    await send_main_menu(message, staff)


async def show_role_picker(message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👑 Superadmin", callback_data="mode:superadmin", style="primary")],
        [InlineKeyboardButton(text="🛡 Admin", callback_data="mode:admin", style="success")],
        [InlineKeyboardButton(text="👤 User", callback_data="mode:user")],
    ])
    await message.answer("<b>Qaysi rol bilan kirmoqchisiz?</b>", reply_markup=kb)


async def send_specialty_picker(message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚙️ Backend", callback_data="specialty:backend", style="primary"),
         InlineKeyboardButton(text="🎨 Frontend", callback_data="specialty:frontend", style="primary")],
        [InlineKeyboardButton(text="🧩 Full stack", callback_data="specialty:fullstack", style="success"),
         InlineKeyboardButton(text="✨ Vibecoder", callback_data="specialty:vibecoder", style="success")],
        [InlineKeyboardButton(text="⬅️ Ortga", callback_data="formback:age")],
    ])
    await message.answer("<b>💼 Kasbiy yo‘nalishingizni tanlang:</b>", reply_markup=kb)


@router.callback_query(Application.specialty, F.data.startswith("specialty:"))
async def select_specialty(call: CallbackQuery, state: FSMContext):
    specialty = call.data.split(":")[1]
    if specialty not in SPECIALTIES: return await call.answer("Noto‘g‘ri yo‘nalish", show_alert=True)
    await db_execute("UPDATE users SET specialty=? WHERE tg_id=?", (specialty, call.from_user.id))
    await state.update_data(specialty=specialty)
    await call.message.edit_text(f"✅ Yo‘nalishingiz: <b>{SPECIALTIES[specialty]}</b>")
    await ask_phone(call.message, state)
    await call.answer("Saqlandi")


async def ask_phone(message, state):
    await state.set_state(Application.phone)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Telefon raqamni yuborish", request_contact=True)],
                                       [KeyboardButton(text="⬅️ Ortga")]],
                             resize_keyboard=True, one_time_keyboard=True)
    await message.answer("Telefon raqamingizni yuboring yoki matn ko‘rinishida yozing:", reply_markup=kb)


@router.message(F.text.in_(menu_texts("🔄 Rolni almashtirish")))
async def change_mode(message: Message):
    if await role_of(message.from_user.id) != "superadmin": return
    await show_role_picker(message)


@router.callback_query(F.data.startswith("mode:"))
async def select_mode(call: CallbackQuery):
    if await role_of(call.from_user.id) != "superadmin": return await call.answer("Ruxsat yo‘q", show_alert=True)
    mode = call.data.split(":")[1]
    if mode not in {"superadmin", "admin", "user"}: return await call.answer("Noto‘g‘ri rol", show_alert=True)
    await db_execute("UPDATE users SET active_mode=? WHERE tg_id=?", (mode, call.from_user.id))
    await call.message.edit_text(f"✅ <b>{ROLE_LABELS[mode]}</b> rejimi tanlandi.")
    await send_main_menu(call.message, mode in {"superadmin","admin"}, mode == "superadmin")
    await call.answer()


async def require_superadmin(user_id):
    return await role_of(user_id) == "superadmin" and await effective_role(user_id) == "superadmin"


async def admins_markup():
    admins = await db_all("SELECT tg_id,full_name,username FROM users WHERE role='admin' ORDER BY full_name")
    lines = ["<b>🛡 Adminlar ro‘yxati</b>"]
    lines += [f"• {h(x['full_name'],100)} · <code>{x['tg_id']}</code> · " +
              (f"@{h(x['username'],50)}" if x["username"] else "username yo‘q") for x in admins]
    if not admins: lines.append("Hozircha adminlar yo‘q.")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Admin tayinlash", callback_data="admin:add", style="success")],
        [InlineKeyboardButton(text="➖ Adminni olib tashlash", callback_data="admin:remove", style="danger")],
        [InlineKeyboardButton(text="🏠 Bosh sahifa", callback_data="nav:home", design_key="home")],
    ])
    return "\n".join(lines), kb


@router.message(F.text.in_(menu_texts("🛡 Adminlar")))
async def admins_list(message: Message):
    if not await require_superadmin(message.from_user.id): return await message.answer("Superadmin rejimini tanlang.")
    text, kb = await admins_markup(); await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.in_({"admin:add", "admin:remove"}))
async def admin_action(call: CallbackQuery, state: FSMContext):
    if not await require_superadmin(call.from_user.id): return await call.answer("Faqat Superadmin rejimida", show_alert=True)
    adding = call.data == "admin:add"
    await state.set_state(AdminManage.add_id if adding else AdminManage.remove_id)
    await call.message.answer("Admin qilinadigan Telegram ID’ni yuboring:" if adding else "Adminlikdan olinadigan Telegram ID’ni yuboring:")
    await call.answer()


async def set_admin_role(message: Message, state: FSMContext, adding: bool, raw_id=None, bot: Bot = None, confirmed=False):
    if not await require_superadmin(message.from_user.id): await state.clear(); return
    value = str(raw_id if raw_id is not None else (message.text or "")).strip()
    if not value.isdigit(): return await message.answer("Faqat raqamlardan iborat Telegram ID yuboring.")
    uid = int(value)
    if uid in SUPERADMINS: return await message.answer("Superadmin rolini o‘zgartirib bo‘lmaydi.")
    if not adding and not confirmed:
        target=await db_one("SELECT full_name FROM users WHERE tg_id=? AND role='admin'",(uid,))
        if not target:return await message.answer("Bu ID adminlar ro‘yxatida yo‘q.")
        await state.clear()
        kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Ha, olib tashlash",callback_data=f"adminremoveconfirm:{uid}",style="danger")],[InlineKeyboardButton(text="❌ Bekor qilish",callback_data="menu:admins")]])
        return await message.answer(f"⚠️ <b>{h(target['full_name'],150)}</b> adminligini olib tashlashni tasdiqlaysizmi?",reply_markup=kb)
    if adding:
        full_name, username = f"Admin {uid}", None
        if bot:
            with suppress(TelegramBadRequest, TelegramForbiddenError):
                chat = await bot.get_chat(uid)
                full_name = chat.full_name or full_name
                username = chat.username
        await db_execute("""INSERT INTO users(tg_id,full_name,username,role,status) VALUES(?,?,?,'admin','accepted')
          ON CONFLICT(tg_id) DO UPDATE SET full_name=excluded.full_name,
          username=COALESCE(excluded.username,users.username),role='admin',status='accepted'""", (uid, full_name, username))
        username_text = f"@{h(username, 50)}" if username else "username topilmadi — /start bosganda yangilanadi"
        result = f"✅ {h(full_name, 100)} · <code>{uid}</code> · {username_text}\nAdmin etib tayinlandi."
    else:
        user = await db_one("SELECT role FROM users WHERE tg_id=?", (uid,))
        if not user or user["role"] != "admin": return await message.answer("Bu ID adminlar ro‘yxatida yo‘q.")
        await db_execute("UPDATE users SET role='user',active_mode='user' WHERE tg_id=?", (uid,))
        result = f"✅ <code>{uid}</code> adminlikdan olib tashlandi."
    await audit(message.from_user.id,"admin_added" if adding else "admin_removed","user",uid)
    await state.clear(); text, kb = await admins_markup(); await message.answer(result); await message.answer(text, reply_markup=kb)


@router.message(AdminManage.add_id)
async def add_admin_id(message: Message, state: FSMContext, bot: Bot): await set_admin_role(message, state, True, bot=bot)


@router.message(AdminManage.remove_id)
async def remove_admin_id(message: Message, state: FSMContext, bot: Bot): await set_admin_role(message, state, False, bot=bot)


@router.message(Command("add_admin"))
async def add_admin_command(message: Message, state: FSMContext, bot: Bot):
    parts = message.text.split(maxsplit=1)
    if len(parts) != 2: return await message.answer("Format: /add_admin TELEGRAM_ID")
    await set_admin_role(message, state, True, parts[1], bot)


@router.message(Command("remove_admin"))
async def remove_admin_command(message: Message, state: FSMContext, bot: Bot):
    parts = message.text.split(maxsplit=1)
    if len(parts) != 2: return await message.answer("Format: /remove_admin TELEGRAM_ID")
    await set_admin_role(message, state, False, parts[1], bot)


def design_catalog_keyboard(page=0):
    page_size = 7
    pages = max(1, (len(BUTTON_CATALOG) + page_size - 1) // page_size)
    page = max(0, min(page, pages - 1))
    rows = []
    page_buttons = []
    for key, label in BUTTON_CATALOG[page * page_size:(page + 1) * page_size]:
        style, emoji = button_appearance(label, key)
        page_buttons.append(AiogramInlineKeyboardButton(text=button_label(label, emoji), callback_data=f"design:button:{key}",
                                                        style=style, icon_custom_emoji_id=emoji))
    rows.extend(page_buttons[index:index + 2] for index in range(0, len(page_buttons), 2))
    nav = []
    if page: nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"design:list:{page-1}", design_key="previous"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{pages}", callback_data="noop", design_key="design_list"))
    if page + 1 < pages: nav.append(InlineKeyboardButton(text="➡️", callback_data=f"design:list:{page+1}", design_key="next"))
    rows.append(nav)
    rows.append([InlineKeyboardButton(text="🏠 Bosh sahifa", callback_data="nav:home", design_key="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows), page


async def show_design_catalog(target, page=0, edit=False):
    kb, page = design_catalog_keyboard(page)
    text = ("<b>🎨 Barcha tugmalar dizayni</b>\n\n"
            "Har bir tugma quyida hozir saqlangan real rang va Premium emoji bilan ko‘rsatiladi. Sozlash uchun ustiga bosing.")
    if edit:
        await target.edit_text(text, reply_markup=kb)
    else:
        await target.answer(text, reply_markup=kb)


@router.message(F.text.in_(menu_texts("🎨 Tugma dizayni")))
async def design_panel(message: Message):
    if not await require_superadmin(message.from_user.id): return await message.answer("Superadmin rejimini tanlang.")
    await show_design_catalog(message)


@router.callback_query(F.data.startswith("design:list:"))
async def design_list_page(call: CallbackQuery):
    if not await require_superadmin(call.from_user.id): return await call.answer("Ruxsat yo‘q", show_alert=True)
    await show_design_catalog(call.message, int(call.data.rsplit(":", 1)[1]), edit=True)
    await call.answer()


@router.callback_query(F.data.startswith("design:button:"))
async def design_choose_button(call: CallbackQuery, state: FSMContext):
    if not await require_superadmin(call.from_user.id): return await call.answer("Ruxsat yo‘q", show_alert=True)
    key = call.data.rsplit(":", 1)[1]
    if key not in BUTTON_LABELS: return await call.answer("Tugma topilmadi", show_alert=True)
    catalog_page = next(i for i, item in enumerate(BUTTON_CATALOG) if item[0] == key) // 7
    current = DESIGN["button_designs"].get(key, {})
    await state.update_data(design_key=key, design_style=current.get("style", DESIGN["button_style"]),
                            design_emoji=current.get("emoji_id", DESIGN["premium_emoji_id"]), design_page=catalog_page)
    rows = [[
        AiogramInlineKeyboardButton(text="⚪ Standart", callback_data="design:pickstyle:default"),
        AiogramInlineKeyboardButton(text="🔵 Ko‘k", callback_data="design:pickstyle:primary", style="primary"),
    ], [
        AiogramInlineKeyboardButton(text="🟢 Yashil", callback_data="design:pickstyle:success", style="success"),
        AiogramInlineKeyboardButton(text="🔴 Qizil", callback_data="design:pickstyle:danger", style="danger"),
    ], [InlineKeyboardButton(text="♻️ Standartga qaytarish", callback_data=f"design:reset:{key}", design_key="reset_default")],
       [InlineKeyboardButton(text="🎨 Tugmalar ro‘yxati", callback_data=f"design:list:{catalog_page}", design_key="design_list")]]
    await call.message.edit_text(f"<b>{h(BUTTON_LABELS[key])}</b>\n\n1/3 — Tugma rangini tanlang:",
                                 reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await call.answer()


@router.callback_query(F.data.startswith("design:pickstyle:"))
async def design_choose_style(call: CallbackQuery, state: FSMContext):
    if not await require_superadmin(call.from_user.id): return await call.answer("Ruxsat yo‘q", show_alert=True)
    choice = call.data.rsplit(":", 1)[1]
    style = choice
    if style not in {"default", "primary", "success", "danger"}: return await call.answer("Noto‘g‘ri rang", show_alert=True)
    await state.update_data(design_style=style)
    rows = [[AiogramInlineKeyboardButton(text="✨ Premium emojini yuborish", callback_data="design:pickemoji:custom")],
            [AiogramInlineKeyboardButton(text="🙂 Unicode fallback", callback_data="design:pickemoji:none")]]
    await call.message.edit_text("2/3 — Tugma uchun emoji variantini tanlang:",
                                 reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await call.answer()


@router.callback_query(F.data.startswith("design:pickemoji:"))
async def design_choose_emoji(call: CallbackQuery, state: FSMContext):
    if not await require_superadmin(call.from_user.id): return await call.answer("Ruxsat yo‘q", show_alert=True)
    choice = call.data.rsplit(":", 1)[1]
    if choice == "custom":
        await state.set_state(DesignForm.emoji_id)
        await call.message.edit_text("Bitta animatsion Telegram Premium emojini yuboring. ID avtomatik aniqlanadi. /cancel bilan bekor qilishingiz mumkin.")
        return await call.answer()
    emoji = None
    await state.update_data(design_emoji=emoji)
    await show_design_preview(call.message, state)
    await call.answer()


async def show_design_preview(message, state):
    data = await state.get_data()
    key, style, emoji = data.get("design_key"), data.get("design_style"), data.get("design_emoji", "")
    if key not in BUTTON_LABELS: return await message.answer("Dizayn sessiyasi tugagan. Qaytadan tanlang.")
    await state.set_state(DesignForm.preview)
    preview = AiogramInlineKeyboardButton(text=button_label(BUTTON_LABELS[key], emoji), callback_data="noop",
                                          style=None if style == "default" else style,
                                          icon_custom_emoji_id=emoji or None)
    save = InlineKeyboardButton(text="💾 Saqlash", callback_data="design:save", design_key="save")
    back = InlineKeyboardButton(text="🎨 Tugmalar ro‘yxati", callback_data=f"design:button:{key}", design_key="design_list")
    await message.edit_text(f"<b>3/3 — Preview</b>\n\nRang: <code>{style}</code>\nEmoji: <code>{emoji or 'yo‘q'}</code>",
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[preview], [save, back]]))


@router.message(DesignForm.emoji_id)
async def set_emoji(message: Message, state: FSMContext):
    if not await require_superadmin(message.from_user.id): await state.clear(); return
    entities = tuple(message.entities or ()) + tuple(message.caption_entities or ())
    emoji_ids = [entity.custom_emoji_id for entity in entities
                 if entity.type == MessageEntityType.CUSTOM_EMOJI and entity.custom_emoji_id]
    emoji_id = emoji_ids[0] if len(emoji_ids) == 1 else None
    if not emoji_id:
        return await message.answer("Custom animatsion emoji aniqlanmadi. Faqat bitta Telegram Premium emojini yuboring.")
    await state.update_data(design_emoji=emoji_id)
    await state.set_state(DesignForm.preview)
    data = await state.get_data()
    key, style = data.get("design_key"), data.get("design_style")
    try:
        preview = AiogramInlineKeyboardButton(text=button_label(BUTTON_LABELS[key], emoji_id), callback_data="noop",
                                              style=None if style == "default" else style,
                                              icon_custom_emoji_id=emoji_id)
        save = InlineKeyboardButton(text="💾 Saqlash", callback_data="design:save", design_key="save")
        back = InlineKeyboardButton(text="🎨 Tugmalar ro‘yxati", callback_data=f"design:button:{key}", design_key="design_list")
        await message.answer(f"<b>3/3 — Preview</b>\n\nRang: <code>{style}</code>\nEmoji: <code>{emoji_id}</code>",
                             reply_markup=InlineKeyboardMarkup(inline_keyboard=[[preview], [save, back]]))
    except TelegramBadRequest:
        await state.set_state(DesignForm.emoji_id)
        return await message.answer("Telegram emoji ID’ni qabul qilmadi. Boshqa ID yuboring.")


@router.callback_query(DesignForm.preview, F.data == "design:save")
async def save_selected_design(call: CallbackQuery, state: FSMContext):
    if not await require_superadmin(call.from_user.id): return await call.answer("Ruxsat yo‘q", show_alert=True)
    data = await state.get_data()
    key = data.get("design_key")
    if key not in BUTTON_LABELS: return await call.answer("Dizayn sessiyasi tugagan", show_alert=True)
    await save_button_design(key, data.get("design_style", "default"), data.get("design_emoji"))
    page = int(data.get("design_page", 0))
    await state.clear()
    await call.answer("Dizayn saqlandi ✅", show_alert=True)
    await show_design_catalog(call.message, page=page, edit=True)


@router.callback_query(F.data.startswith("design:reset:"))
async def reset_selected_design(call: CallbackQuery, state: FSMContext):
    if not await require_superadmin(call.from_user.id): return await call.answer("Ruxsat yo‘q", show_alert=True)
    key = call.data.rsplit(":", 1)[1]
    if key not in BUTTON_LABELS: return await call.answer("Tugma topilmadi", show_alert=True)
    designs = dict(DESIGN["button_designs"])
    designs.pop(key, None)
    await save_setting("button_designs", designs)
    page = next(i for i, item in enumerate(BUTTON_CATALOG) if item[0] == key) // 7
    await state.clear()
    await call.answer("Default holat qaytarildi ✅", show_alert=True)
    await show_design_catalog(call.message, page=page, edit=True)


def message_emoji_catalog_keyboard():
    buttons = []
    for key, label, fallback in MESSAGE_EMOJI_CATALOG:
        configured = DESIGN["message_emojis"].get(key, {})
        marker = "✨" if configured.get("custom_id") else (configured.get("text") or fallback)
        buttons.append(AiogramInlineKeyboardButton(text=f"{marker} {label}", callback_data=f"msgemoji:choose:{key}"))
    rows = [buttons[index:index + 2] for index in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton(text="🏠 Bosh sahifa", callback_data="nav:home", design_key="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def show_message_emoji_catalog(target, edit=False):
    text = ("<b>✨ Xabarlardagi emojilar</b>\n\n"
            "O‘zgartirmoqchi bo‘lgan xabar qismini tanlang. Oddiy emoji yoki bitta Telegram Premium emoji yuborish mumkin.")
    kb = message_emoji_catalog_keyboard()
    if edit: await target.edit_text(text, reply_markup=kb)
    else: await target.answer(text, reply_markup=kb)


@router.message(F.text.in_(menu_texts("✨ Xabar emojilari")))
async def message_emoji_panel(message: Message):
    if not await require_superadmin(message.from_user.id): return await message.answer("Superadmin rejimini tanlang.")
    await show_message_emoji_catalog(message)


@router.callback_query(F.data == "msgemoji:list")
async def message_emoji_list(call: CallbackQuery, state: FSMContext):
    if not await require_superadmin(call.from_user.id): return await call.answer("Ruxsat yo‘q", show_alert=True)
    await state.clear(); await show_message_emoji_catalog(call.message, edit=True); await call.answer()


@router.callback_query(F.data.startswith("msgemoji:choose:"))
async def message_emoji_choose(call: CallbackQuery, state: FSMContext):
    if not await require_superadmin(call.from_user.id): return await call.answer("Ruxsat yo‘q", show_alert=True)
    key = call.data.rsplit(":", 1)[1]
    item = next((item for item in MESSAGE_EMOJI_CATALOG if item[0] == key), None)
    if not item: return await call.answer("Emoji turi topilmadi", show_alert=True)
    await state.set_state(MessageEmojiForm.value)
    await state.update_data(message_emoji_key=key)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [AiogramInlineKeyboardButton(text="♻️ Standartga qaytarish", callback_data=f"msgemoji:reset:{key}", style="danger")],
        [AiogramInlineKeyboardButton(text="⬅️ Ro‘yxat", callback_data="msgemoji:list")],
    ])
    await call.message.edit_text(f"<b>{h(item[1])}</b> uchun yangi oddiy emoji yoki bitta Premium emoji yuboring:", reply_markup=kb)
    await call.answer()


@router.message(MessageEmojiForm.value)
async def message_emoji_receive(message: Message, state: FSMContext):
    if not await require_superadmin(message.from_user.id): await state.clear(); return
    data = await state.get_data(); key = data.get("message_emoji_key")
    if key not in MESSAGE_EMOJI_DEFAULTS: await state.clear(); return await message.answer("Sozlash sessiyasi tugagan.")
    entities = tuple(message.entities or ()) + tuple(message.caption_entities or ())
    custom_ids = [entity.custom_emoji_id for entity in entities
                  if entity.type == MessageEntityType.CUSTOM_EMOJI and entity.custom_emoji_id]
    raw_text = (message.text or message.caption or "").strip()
    if custom_ids:
        config = {"text": raw_text or MESSAGE_EMOJI_DEFAULTS[key], "custom_id": custom_ids[0]}
    else:
        if not raw_text or len(raw_text) > 16:
            return await message.answer("Faqat bitta emoji yuboring (16 belgidan oshmasin).")
        config = {"text": raw_text, "custom_id": None}
    await state.update_data(message_emoji_config=config)
    await state.set_state(MessageEmojiForm.preview)
    preview = (f'<tg-emoji emoji-id="{h(config["custom_id"],40)}">{h(config["text"],20)}</tg-emoji>'
               if config.get("custom_id") else h(config["text"], 20))
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [AiogramInlineKeyboardButton(text="💾 Saqlash", callback_data="msgemoji:save", style="success")],
        [AiogramInlineKeyboardButton(text="⬅️ Qayta tanlash", callback_data=f"msgemoji:choose:{key}")],
    ])
    try: await message.answer(f"<b>Preview:</b>\n\n{preview} Namuna xabar", reply_markup=kb)
    except TelegramBadRequest:
        await state.set_state(MessageEmojiForm.value)
        await message.answer("Telegram bu emojini qabul qilmadi. Boshqasini yuboring.")


@router.callback_query(MessageEmojiForm.preview, F.data == "msgemoji:save")
async def message_emoji_save(call: CallbackQuery, state: FSMContext):
    if not await require_superadmin(call.from_user.id): return await call.answer("Ruxsat yo‘q", show_alert=True)
    data = await state.get_data(); key = data.get("message_emoji_key"); config = data.get("message_emoji_config")
    if key not in MESSAGE_EMOJI_DEFAULTS or not config: return await call.answer("Sozlash sessiyasi tugagan", show_alert=True)
    settings = dict(DESIGN["message_emojis"]); settings[key] = config
    await save_setting("message_emojis", settings); await state.clear()
    await call.answer("Emoji saqlandi ✅", show_alert=True); await show_message_emoji_catalog(call.message, edit=True)


@router.callback_query(F.data.startswith("msgemoji:reset:"))
async def message_emoji_reset(call: CallbackQuery, state: FSMContext):
    if not await require_superadmin(call.from_user.id): return await call.answer("Ruxsat yo‘q", show_alert=True)
    key = call.data.rsplit(":", 1)[1]
    settings = dict(DESIGN["message_emojis"]); settings.pop(key, None)
    await save_setting("message_emojis", settings); await state.clear()
    await call.answer("Standart emoji qaytarildi ✅", show_alert=True); await show_message_emoji_catalog(call.message, edit=True)


async def show_message_templates(target, edit=False):
    rows = [[InlineKeyboardButton(text=label, callback_data=f"msgtpl:choose:{key}")]
            for key, (label, _default) in MESSAGE_TEMPLATE_CATALOG.items()]
    rows.append([InlineKeyboardButton(text="🏠 Bosh sahifa", callback_data="nav:home", design_key="home")])
    text = ("<b>📝 Xabar matnlari</b>\n\nShablonni tanlang. Mavjud o‘zgaruvchilar: "
            "<code>{full_name}</code>, <code>{note}</code>, <code>{task_name}</code>, "
            "<code>{deadline}</code>, <code>{remaining}</code>.")
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    if edit: await target.edit_text(text, reply_markup=kb)
    else: await target.answer(text, reply_markup=kb)


@router.message(F.text.in_(menu_texts("📝 Xabar matnlari")))
async def message_templates_panel(message: Message):
    if not await require_superadmin(message.from_user.id): return await message.answer("Superadmin rejimini tanlang.")
    await show_message_templates(message)


@router.callback_query(F.data == "msgtpl:list")
async def message_templates_list(call: CallbackQuery, state: FSMContext):
    if not await require_superadmin(call.from_user.id): return await call.answer("Ruxsat yo‘q", show_alert=True)
    await state.clear(); await show_message_templates(call.message, True); await call.answer()


@router.callback_query(F.data.startswith("msgtpl:choose:"))
async def message_template_choose(call: CallbackQuery, state: FSMContext):
    if not await require_superadmin(call.from_user.id): return await call.answer("Ruxsat yo‘q", show_alert=True)
    key = call.data.rsplit(":", 1)[1]
    if key not in MESSAGE_TEMPLATE_CATALOG: return await call.answer("Shablon topilmadi", show_alert=True)
    label, default = MESSAGE_TEMPLATE_CATALOG[key]; current = DESIGN["message_templates"].get(key, default)
    await state.set_state(MessageTemplateForm.value); await state.update_data(message_template_key=key)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="♻️ Standartga qaytarish", callback_data=f"msgtpl:reset:{key}")], [InlineKeyboardButton(text="⬅️ Ro‘yxat", callback_data="msgtpl:list")]])
    await call.message.edit_text(f"<b>{h(label)}</b>\n\nHozirgi matn:\n<code>{h(current,2000)}</code>\n\nYangi matnni yuboring:", reply_markup=kb); await call.answer()


@router.message(MessageTemplateForm.value, F.text)
async def message_template_save(message: Message, state: FSMContext):
    if not await require_superadmin(message.from_user.id): await state.clear(); return
    data = await state.get_data(); key = data.get("message_template_key")
    if key not in MESSAGE_TEMPLATE_CATALOG: await state.clear(); return await message.answer("Sessiya tugagan.")
    if len(message.text) > 3000: return await message.answer("Xabar 3000 belgidan oshmasin.")
    templates = dict(DESIGN["message_templates"]); templates[key] = message.text
    await save_setting("message_templates", templates); await state.clear()
    await message.answer("✅ Xabar matni saqlandi."); await show_message_templates(message)


@router.callback_query(F.data.startswith("msgtpl:reset:"))
async def message_template_reset(call: CallbackQuery, state: FSMContext):
    if not await require_superadmin(call.from_user.id): return await call.answer("Ruxsat yo‘q", show_alert=True)
    key = call.data.rsplit(":", 1)[1]; templates = dict(DESIGN["message_templates"]); templates.pop(key, None)
    await save_setting("message_templates", templates); await state.clear(); await call.answer("Standart matn qaytarildi", show_alert=True)
    await show_message_templates(call.message, True)


@router.message(Command("cancel"))
@router.message(F.text.in_(menu_texts("❌ Bekor qilish")))
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Amal bekor qilindi.", reply_markup=ReplyKeyboardRemove() if message.chat.type != ChatType.PRIVATE else None)
    role = await effective_role(message.from_user.id)
    await send_main_menu(message, role in {"superadmin", "admin", "manager"}, role == "superadmin")


@router.message(F.text.in_(menu_texts("📝 Ariza to‘ldirish")))
async def application_start(message: Message, state: FSMContext):
    if message.chat.type != ChatType.PRIVATE:
        return await message.answer("Ariza shaxsiy ma’lumotlarni saqlaydi. Uni botning shaxsiy chatida to‘ldiring.")
    current = await db_one("SELECT status,rejected_at FROM users WHERE tg_id=?", (message.from_user.id,))
    if current and current["status"] == "blocked":
        return await message.answer("⛔ Profilingiz admin tomonidan vaqtincha bloklangan.")
    if current and current["status"] == "pending":
        return await message.answer("⏳ Arizangiz ko‘rib chiqilmoqda. Natija chiqquncha qayta ariza yuborib bo‘lmaydi.")
    if current and current["status"] == "accepted":
        return await message.answer("✅ Arizangiz qabul qilingan. Sizga qayta ariza topshirish kerak emas.",
                                    reply_markup=main_inline_kb(accepted_user=True, show_application=False))
    if current and current["status"] == "rejected" and current["rejected_at"]:
        rejected_at = utc_datetime(current["rejected_at"])
        available_at = rejected_at + timedelta(hours=24)
        now = datetime.now(timezone.utc)
        if now < available_at:
            remaining = available_at - now
            hours, remainder = divmod(max(1, int(remaining.total_seconds())), 3600)
            minutes = remainder // 60
            return await message.answer(f"❌ Arizangiz rad etilgan. Qayta topshirish uchun yana {hours} soat {minutes} daqiqa kuting.")
    await state.clear()
    await state.update_data(username=message.from_user.username)
    await state.set_state(Application.full_name)
    await message.answer("Ism va familiyangizni kiriting:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🏠 Bosh sahifa", callback_data="nav:home", design_key="home")
    ]]))


@router.message(Application.full_name, F.text)
async def app_full_name(message: Message, state: FSMContext):
    full_name = " ".join(message.text.split())
    if len(full_name.split()) < 2:
        return await message.answer("Ism va familiyani to‘liq kiriting. Masalan: Ali Valiyev")
    await state.update_data(full_name=full_name)
    await db_execute("UPDATE users SET full_name=? WHERE tg_id=?", (full_name, message.from_user.id))
    await state.set_state(Application.age)
    await message.answer("Yoshingizni raqam bilan kiriting (14–100):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⬅️ Ortga", callback_data="formback:full_name")
    ]]))


@router.message(Application.age, F.text)
async def app_age(message: Message, state: FSMContext):
    if not message.text.isdigit() or not 14 <= int(message.text) <= 100:
        return await message.answer("Yosh 14 dan 100 gacha bo‘lgan raqam bo‘lishi kerak.")
    age = int(message.text)
    await state.update_data(age=age)
    await db_execute("UPDATE users SET age=? WHERE tg_id=?", (age, message.from_user.id))
    await state.set_state(Application.specialty)
    await send_specialty_picker(message)


@router.callback_query(F.data.startswith("formback:"))
async def application_back(call: CallbackQuery, state: FSMContext):
    target = call.data.split(":", 1)[1]
    if target == "full_name":
        await state.set_state(Application.full_name)
        await call.message.edit_text("Ism va familiyangizni qayta kiriting:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🏠 Bosh sahifa", callback_data="nav:home", design_key="home")
        ]]))
    elif target == "age":
        await state.set_state(Application.age)
        await call.message.edit_text("Yoshingizni raqam bilan kiriting (14–100):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="⬅️ Ortga", callback_data="formback:full_name")
        ]]))
    elif target == "phone":
        await state.set_state(Application.phone)
        await ask_phone(call.message, state)
    elif target == "portfolio":
        await state.set_state(Application.portfolio)
        await call.message.edit_text("Portfolio havolasi/matnini yozing yoki PDF/DOCX fayl yuboring:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="⬅️ Ortga", callback_data="formback:phone")
        ]]))
    await call.answer()


@router.message(Application.phone, F.contact)
async def app_phone_contact(message: Message, state: FSMContext):
    if message.contact.user_id and message.contact.user_id != message.from_user.id:
        return await message.answer("Iltimos, aynan o‘zingizning kontaktingizni yuboring.")
    await state.update_data(phone=message.contact.phone_number)
    await db_execute("UPDATE users SET phone=? WHERE tg_id=?", (message.contact.phone_number, message.from_user.id))
    await state.set_state(Application.portfolio)
    await message.answer("Portfolio havolasi/matnini yozing yoki PDF/DOCX fayl yuboring:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⬅️ Ortga", callback_data="formback:phone")
    ]]))


@router.message(Application.phone, F.text.in_(menu_texts("⬅️ Ortga")))
async def app_phone_back(message: Message, state: FSMContext):
    await state.set_state(Application.specialty)
    await send_specialty_picker(message)


@router.message(Application.phone, F.text)
async def app_phone_text(message: Message, state: FSMContext):
    await state.update_data(phone=message.text)
    await db_execute("UPDATE users SET phone=? WHERE tg_id=?", (message.text, message.from_user.id))
    await state.set_state(Application.portfolio)
    await message.answer("Portfolio havolasi/matnini yozing yoki PDF/DOCX fayl yuboring:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⬅️ Ortga", callback_data="formback:phone")
    ]]))


@router.message(Application.portfolio, F.text)
async def app_portfolio(message: Message, state: FSMContext):
    await state.update_data(portfolio=message.text, portfolio_file_id=None,
                            portfolio_file_name=None, portfolio_file_mime=None)
    await db_execute("""UPDATE users SET portfolio=?,portfolio_file_id=NULL,
      portfolio_file_name=NULL,portfolio_file_mime=NULL WHERE tg_id=?""",
      (message.text, message.from_user.id))
    await state.set_state(Application.about)
    await message.answer("O‘zingiz haqingizda yozing (hajm cheklanmagan):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⬅️ Ortga", callback_data="formback:portfolio")
    ]]))


@router.message(Application.portfolio, F.document)
async def app_portfolio_document(message: Message, state: FSMContext):
    document = message.document
    filename = document.file_name or "portfolio"
    extension = os.path.splitext(filename)[1].lower()
    allowed_mimes = {"application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
    if extension not in {".pdf", ".docx"} or (document.mime_type and document.mime_type not in allowed_mimes):
        return await message.answer("Faqat PDF yoki DOCX formatidagi portfolio faylini yuboring.")
    await state.update_data(portfolio=None, portfolio_file_id=document.file_id,
                            portfolio_file_name=filename, portfolio_file_mime=document.mime_type)
    await db_execute("""UPDATE users SET portfolio=NULL,portfolio_file_id=?,
      portfolio_file_name=?,portfolio_file_mime=? WHERE tg_id=?""",
      (document.file_id, filename, document.mime_type, message.from_user.id))
    await state.set_state(Application.about)
    await message.answer(f"✅ <b>{h(filename, 200)}</b> qabul qilindi.\n\nO‘zingiz haqingizda yozing (hajm cheklanmagan):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⬅️ Ortga", callback_data="formback:portfolio")
    ]]))


@router.message(Application.about, F.text)
async def app_about(message: Message, state: FSMContext):
    await state.update_data(about=message.text)
    await db_execute("UPDATE users SET about=? WHERE tg_id=?", (message.text, message.from_user.id))
    await state.set_state(Application.confirm)
    data = await state.get_data()
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✏️ Tahrirlash", callback_data="app:edit"),
                                                InlineKeyboardButton(text="📨 Arizani jo‘natish", callback_data="app:send")]])
    await message.answer(app_text(data, message.from_user), reply_markup=kb)


@router.callback_query(Application.confirm, F.data == "app:edit")
async def app_edit(call: CallbackQuery, state: FSMContext):
    await state.set_state(Application.phone)
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer("Telefon raqamingizni qayta kiriting:")
    await call.answer()


@router.callback_query(F.data == "app:send")
async def app_send(call: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    current = await db_one("SELECT * FROM users WHERE tg_id=?", (call.from_user.id,))
    if current and current["status"] in {"pending", "accepted"}:
        await state.clear()
        return await call.answer("Ariza qayta yuborilishi mumkin emas", show_alert=True)
    if current:
        for field in ("full_name", "age", "specialty", "phone", "portfolio", "portfolio_file_id",
                      "portfolio_file_name", "portfolio_file_mime", "about"):
            if data.get(field) is None and current[field] is not None:
                data[field] = current[field]
    required = ("full_name", "age", "specialty", "phone", "about")
    if any(data.get(field) in (None, "") for field in required):
        await state.clear()
        await call.message.edit_reply_markup(reply_markup=None)
        await call.answer("Forma ma’lumotlari yetarli emas", show_alert=True)
        return await call.message.answer("Forma sessiyasi yangilangan. Iltimos, arizani boshidan qayta to‘ldiring.",
                                         reply_markup=main_kb(False, show_application=True))
    await call.answer("Ariza yuborilmoqda…")
    await db_execute("""UPDATE users SET username=?,full_name=?,age=?,phone=?,portfolio=?,portfolio_file_id=?,
      portfolio_file_name=?,portfolio_file_mime=?,about=?,status='pending',rejected_at=NULL WHERE tg_id=?""",
      (call.from_user.username, data["full_name"], data["age"], data["phone"], data.get("portfolio"),
       data.get("portfolio_file_id"), data.get("portfolio_file_name"), data.get("portfolio_file_mime"),
       data["about"], call.from_user.id))
    await audit(call.from_user.id,"application_submitted","user",call.from_user.id)
    staff = await db_all("SELECT tg_id FROM users WHERE role IN ('superadmin','admin','manager')")
    direct_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Rad etish", callback_data=f"review:reject:{call.from_user.id}"),
                                                       InlineKeyboardButton(text="✅ Qabul qilish", callback_data=f"review:accept:{call.from_user.id}")]])
    delivered = 0
    for member in staff:
        with suppress(TelegramForbiddenError, TelegramBadRequest):
            sent = await bot.send_message(member["tg_id"], app_text(data, call.from_user), reply_markup=direct_kb)
            await db_execute("""INSERT INTO application_review_messages(application_user_id,staff_id,message_id)
              VALUES(?,?,?) ON CONFLICT(application_user_id,staff_id) DO UPDATE SET
              message_id=excluded.message_id,sent_at=CURRENT_TIMESTAMP""",
              (call.from_user.id, member["tg_id"], sent.message_id))
            if data.get("portfolio_file_id"):
                await bot.send_document(member["tg_id"], data["portfolio_file_id"],
                                        caption=f"📎 {h(data.get('portfolio_file_name'), 200)}")
            delivered += 1
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer("✅ Arizangiz yuborildi." if delivered else "⚠️ Ariza saqlandi, ammo mas’ullarga xabar yetkazilmadi.",
                              reply_markup=main_kb(False, show_application=False))
    await state.clear()


@router.callback_query(F.data.startswith("review:"))
async def review(call: CallbackQuery, bot: Bot, state: FSMContext):
    if not await is_actual_staff(call.from_user.id): return await call.answer("Ruxsat yo‘q", show_alert=True)
    _, action, raw_id = call.data.split(":"); uid = int(raw_id)
    current = await db_one("SELECT * FROM users WHERE tg_id=?", (uid,))
    if not current: return await call.answer("User topilmadi", show_alert=True)
    if current["status"] != "pending":
        with suppress(TelegramBadRequest): await call.message.edit_reply_markup(reply_markup=None)
        return await call.answer(f"Bu ariza allaqachon: {STATUS_LABELS.get(current['status'], current['status'])}", show_alert=True)
    status = "accepted" if action == "accept" else "rejected"
    rejected_at = datetime.now(timezone.utc).isoformat(timespec="seconds") if status == "rejected" else None
    reviewed_at_db = datetime.now(timezone.utc).isoformat(timespec="seconds")
    await db_execute("""UPDATE users SET status=?,rejected_at=?,application_review_note=NULL,
      application_reviewed_by=?,application_reviewed_at=? WHERE tg_id=?""",
      (status, rejected_at, call.from_user.id, reviewed_at_db, uid));await audit(call.from_user.id,f"application_{status}","user",uid)
    plain_label = "✅ Qabul qilindi" if status == "accepted" else "❌ Rad etildi"
    label = f"{message_emoji('accepted')} Qabul qilindi" if status == "accepted" else f"{message_emoji('rejected')} Rad etildi"
    reviewer = call.from_user.full_name or (f"@{call.from_user.username}" if call.from_user.username else str(call.from_user.id))
    reviewed_at = datetime.now(timezone(timedelta(hours=5))).strftime("%d.%m.%Y %H:%M")
    review_status = (f"\n\n────────────\n<b>{label}</b>\n"
                     f"👤 Qaror qildi: {h(reviewer, 150)}\n🕒 {reviewed_at}")
    notification_rows = await db_all("SELECT staff_id,message_id FROM application_review_messages WHERE application_user_id=?", (uid,))
    reviewed_text = app_text(dict(current)) + review_status
    updated_messages = 0
    for notification in notification_rows:
        with suppress(TelegramForbiddenError, TelegramBadRequest):
            await bot.edit_message_text(reviewed_text, chat_id=notification["staff_id"],
                                        message_id=notification["message_id"], reply_markup=None)
            updated_messages += 1
    if not updated_messages:
        with suppress(TelegramBadRequest):
            await call.message.edit_text(reviewed_text, reply_markup=None)
    with suppress(TelegramForbiddenError):
        template_key = "application_accepted" if status == "accepted" else "application_rejected"
        user_notice = render_template(template_key, full_name=current["full_name"], note="Ko‘rsatilmagan")
        await bot.send_message(uid, f"Arizangiz holati: {label}\n\n{user_notice}",
                               reply_markup=main_kb(show_application=False, accepted_user=status == "accepted"))
        if status == "accepted":
            await bot.send_message(uid, "Kerakli bo‘limni tanlang:",
                                   reply_markup=main_inline_kb(show_application=False, accepted_user=True))
    await state.set_state(ApplicationReviewForm.note)
    await state.update_data(review_user_id=uid, review_status=status)
    await call.message.answer("Qaror saqlandi. Endi user uchun qisqa izoh yozing yoki /skip yuboring.")
    await call.answer(plain_label, show_alert=True)


@router.message(ApplicationReviewForm.note, F.text)
async def save_application_review_note(message: Message, state: FSMContext, bot: Bot):
    if not await is_actual_staff(message.from_user.id): await state.clear(); return
    data = await state.get_data(); uid = data.get("review_user_id")
    if not uid: await state.clear(); return await message.answer("Ko‘rib chiqish sessiyasi tugagan.")
    if message.text == "/skip": note = "Izoh qoldirilmadi"
    else: note = message.text.strip()
    await db_execute("UPDATE users SET application_review_note=? WHERE tg_id=?", (note, uid))
    await audit(message.from_user.id, "application_review_note", "user", uid, note[:500])
    with suppress(TelegramForbiddenError, TelegramBadRequest): await bot.send_message(uid, f"💬 Admin izohi:\n{h(note,2000)}")
    await state.clear(); await message.answer("✅ Izoh saqlandi va userga yuborildi.")


async def users_keyboard(page=0, viewer_id=None):
    can_see_superadmins = viewer_id is not None and await effective_role(viewer_id) == "superadmin"
    where = "" if can_see_superadmins else " WHERE role!='superadmin'"
    total = (await db_one(f"SELECT COUNT(*) AS c FROM users{where}"))["c"]
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE); page = max(0, min(page, pages - 1))
    rows = await db_all(f"SELECT tg_id,full_name,status,role,specialty FROM users{where} ORDER BY created_at DESC LIMIT ? OFFSET ?", (PAGE_SIZE, page * PAGE_SIZE))
    b = InlineKeyboardBuilder()
    for u in rows:
        title = f"{u['full_name']} · {SPECIALTIES.get(u['specialty'], '—')} · {STATUS_LABELS[u['status']]}"
        b.button(text=title[:60], callback_data=f"usr:{u['tg_id']}:{page}")
    b.button(text="⬅️ Admin panel", callback_data="menu:panel")
    if page: b.button(text="⬅️", callback_data=f"users:{page-1}")
    b.button(text=f"{page+1}/{pages}", callback_data="noop")
    if page + 1 < pages: b.button(text="➡️", callback_data=f"users:{page+1}")
    b.adjust(*([1] * len(rows)), 1, 3)
    return b.as_markup(), total


@router.message(Command("panel"))
@router.message(F.text.in_(menu_texts("📊 Admin panel")))
async def panel(message: Message):
    if not await is_staff(message.from_user.id): return await message.answer("Bu bo‘lim uchun ruxsat yo‘q.")
    stats = await db_one("""SELECT COUNT(*) total,
      COUNT(*) FILTER (WHERE status='pending') pending,
      COUNT(*) FILTER (WHERE status='accepted') accepted,
      COUNT(*) FILTER (WHERE role='manager') managers FROM users""")
    tasks = (await db_one("SELECT COUNT(*) c FROM tasks"))["c"]
    groups = (await db_one("SELECT COUNT(*) c FROM groups"))["c"]
    completion = await db_one("SELECT COUNT(*) total, COUNT(*) FILTER (WHERE status IN ('approved','completed')) done FROM task_users")
    inactive_since=(datetime.now(timezone.utc)-timedelta(days=7)).isoformat(timespec='seconds')
    inactive=(await db_one("SELECT COUNT(*) c FROM users WHERE status='accepted' AND (last_seen_at IS NULL OR last_seen_at<?)",(inactive_since,)))["c"]
    leaders=await db_all("""SELECT u.full_name,COUNT(*) done FROM task_users tu JOIN users u ON u.tg_id=tu.user_id WHERE tu.status IN ('approved','completed') GROUP BY u.tg_id,u.full_name ORDER BY done DESC LIMIT 5""")
    leaderboard="\n".join(f"{i+1}. {h(x['full_name'],60)} — {x['done']}" for i,x in enumerate(leaders)) or "Hozircha yo‘q"
    b = InlineKeyboardBuilder()
    b.button(text=f"⏳ Arizalar ({stats['pending'] or 0})", callback_data="pending:0")
    b.button(text="👥 Jamoa", callback_data="team:categories")
    b.button(text="📋 Topshiriqlar", callback_data="tasks:0")
    b.button(text="📂 Guruhlar", callback_data="groups:show")
    b.button(text="🔎 Qidiruv", callback_data="menu:search")
    b.button(text="🧾 Shablonlar", callback_data="menu:templates")
    b.button(text="🕘 Audit", callback_data="menu:audit")
    b.button(text="👀 Natijalar",callback_data="submissions:show")
    b.button(text="📈 Kengaytirilgan statistika",callback_data="stats:v1")
    b.button(text="🏠 Bosh sahifa", callback_data="nav:home", design_key="home")
    b.adjust(2, 2, 2, 2, 1)
    await message.answer(f"<b>📊 Admin panel</b>\n\n👥 Jami: {stats['total']}\n⏳ Kutilmoqda: {stats['pending'] or 0}\n✅ Qabul qilingan: {stats['accepted'] or 0}\n🧑‍💼 Managerlar: {stats['managers'] or 0}\n😴 7 kundan beri faol emas: {inactive}\n📂 Guruhlar: {groups}\n📌 Topshiriqlar: {tasks}\n☑️ Bajarilish: {completion['done'] or 0}/{completion['total'] or 0}\n\n<b>🏆 Eng faol userlar</b>\n{leaderboard}", reply_markup=b.as_markup())


@router.callback_query(F.data == "stats:v1")
async def v1_statistics(call: CallbackQuery):
    if not await is_staff(call.from_user.id): return await call.answer("Ruxsat yo‘q", show_alert=True)
    summary = await db_one("""SELECT COUNT(*) assignments,
      COUNT(*) FILTER (WHERE status IN ('approved','completed')) completed,
      COUNT(*) FILTER (WHERE deadline_at IS NOT NULL AND completed_at > deadline_at) late,
      ROUND(AVG(EXTRACT(EPOCH FROM (completed_at-opened_at))/3600)::numeric,1) avg_hours,
      ROUND(AVG(rating)::numeric,2) avg_rating FROM task_users tu JOIN tasks t ON t.id=tu.task_id""") if pg_pool else await db_one("SELECT COUNT(*) assignments,SUM(CASE WHEN status IN ('approved','completed') THEN 1 ELSE 0 END) completed,0 late,NULL avg_hours,AVG(rating) avg_rating FROM task_users")
    specialties = await db_all("""SELECT COALESCE(u.specialty,'tanlanmagan') specialty,
      COUNT(*) FILTER (WHERE tu.status IN ('approved','completed')) done,ROUND(AVG(tu.rating)::numeric,2) rating
      FROM users u LEFT JOIN task_users tu ON tu.user_id=u.tg_id WHERE u.status='accepted'
      GROUP BY u.specialty ORDER BY done DESC""") if pg_pool else []
    leaders = await db_all("""SELECT u.full_name,COUNT(*) FILTER (WHERE tu.status IN ('approved','completed')) done,
      COUNT(*) FILTER (WHERE t.deadline_at IS NOT NULL AND tu.completed_at>t.deadline_at) late,
      ROUND(AVG(tu.rating)::numeric,2) rating FROM task_users tu JOIN users u ON u.tg_id=tu.user_id
      JOIN tasks t ON t.id=tu.task_id GROUP BY u.tg_id,u.full_name ORDER BY done DESC LIMIT 10""") if pg_pool else []
    spec_text = "\n".join(f"• {h(SPECIALTIES.get(x['specialty'],x['specialty']),50)}: {x['done']} ta · ⭐ {x['rating'] or '—'}" for x in specialties) or "Hozircha ma’lumot yo‘q"
    leader_text = "\n".join(f"{i+1}. {h(x['full_name'],60)} — ✅ {x['done']} · ⏱ {x['late']} · ⭐ {x['rating'] or '—'}" for i,x in enumerate(leaders)) or "Hozircha ma’lumot yo‘q"
    text=(f"<b>📈 V1 statistika</b>\n\n📋 Biriktirishlar: {summary['assignments'] or 0}\n✅ Bajarilgan: {summary['completed'] or 0}\n"
          f"⏱ Kechikkan: {summary['late'] or 0}\n🕒 O‘rtacha vaqt: {summary['avg_hours'] or '—'} soat\n⭐ O‘rtacha baho: {summary['avg_rating'] or '—'}\n\n"
          f"<b>Yo‘nalishlar</b>\n{spec_text}\n\n<b>Userlar</b>\n{leader_text}")
    await call.message.edit_text(text,reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Panel",callback_data="menu:panel")]]));await call.answer()


async def pending_keyboard(page=0):
    total = (await db_one("SELECT COUNT(*) c FROM users WHERE status='pending'"))["c"]
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE); page = max(0, min(page, pages - 1))
    rows = await db_all("SELECT tg_id,full_name,username FROM users WHERE status='pending' ORDER BY created_at LIMIT ? OFFSET ?", (PAGE_SIZE, page * PAGE_SIZE))
    b = InlineKeyboardBuilder()
    for u in rows:
        b.button(text=f"📝 {u['full_name'][:48]}", callback_data=f"pendingview:{u['tg_id']}:{page}")
    b.button(text="⬅️ Admin panel", callback_data="menu:panel")
    if page: b.button(text="⬅️", callback_data=f"pending:{page-1}")
    b.button(text=f"{page+1}/{pages}", callback_data="noop")
    if page + 1 < pages: b.button(text="➡️", callback_data=f"pending:{page+1}")
    b.adjust(*([1] * len(rows)), 1, 3)
    return b.as_markup(), total


@router.callback_query(F.data.startswith("pending:"))
async def pending_list(call: CallbackQuery):
    if not await is_actual_staff(call.from_user.id): return await call.answer("Ruxsat yo‘q", show_alert=True)
    page = int(call.data.split(":")[1]); kb, total = await pending_keyboard(page)
    text = f"<b>⏳ Kutilayotgan arizalar</b> — {total} ta"
    if not total: text += "\n\nHozircha yangi ariza yo‘q."
    await call.message.edit_text(text, reply_markup=kb); await call.answer()


@router.callback_query(F.data.startswith("pendingview:"))
async def pending_detail(call: CallbackQuery):
    if not await is_actual_staff(call.from_user.id): return await call.answer("Ruxsat yo‘q", show_alert=True)
    _, raw_uid, page = call.data.split(":"); uid = int(raw_uid)
    u = await db_one("SELECT * FROM users WHERE tg_id=? AND status='pending'", (uid,))
    if not u: return await call.answer("Ariza allaqachon ko‘rib chiqilgan", show_alert=True)
    data = dict(u)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Rad etish", callback_data=f"review:reject:{uid}"),
         InlineKeyboardButton(text="✅ Qabul qilish", callback_data=f"review:accept:{uid}")],
        *([[InlineKeyboardButton(text="📎 Portfolio faylini ochish", callback_data=f"portfolio:{uid}")]] if u["portfolio_file_id"] else []),
        [InlineKeyboardButton(text="⬅️ Arizalar", callback_data=f"pending:{page}")],
    ])
    await call.message.edit_text(app_text(data), reply_markup=kb); await call.answer()


@router.message(F.text.in_(menu_texts("👥 Userlar")))
async def users_list(message: Message):
    if not await is_staff(message.from_user.id): return
    await show_team_categories(message)


async def team_counts(viewer_id: int):
    can_see_superadmins = await role_of(viewer_id) == "superadmin"
    developer_where = "status='accepted' AND role IN ('user','superadmin')" if can_see_superadmins else "role='user' AND status='accepted'"
    return await db_one("""SELECT
      COUNT(*) FILTER (WHERE role='admin') admins,
      COUNT(*) FILTER (WHERE role='manager') managers,
      COUNT(*) FILTER (WHERE """ + developer_where + """) developers
      FROM users""")


async def show_team_categories(message, edit=False):
    counts=await team_counts(message.chat.id)
    kb=InlineKeyboardMarkup(inline_keyboard=[
      [InlineKeyboardButton(text=f"🛡 Adminlar ({counts['admins'] or 0})",callback_data="teamlist:admin")],
      [InlineKeyboardButton(text=f"🧑‍💼 Managerlar ({counts['managers'] or 0})",callback_data="teamlist:manager")],
      [InlineKeyboardButton(text=f"💻 Dasturchilar ({counts['developers'] or 0})",callback_data="teamlist:developer")],
      [InlineKeyboardButton(text="⬅️ Admin panel",callback_data="menu:panel")],
    ])
    text="<b>👥 Jamoa</b>\n\nKo‘rmoqchi bo‘lgan bo‘limni tanlang:"
    if edit:await message.edit_text(text,reply_markup=kb)
    else:await message.answer(text,reply_markup=kb)


@router.callback_query(F.data=="team:categories")
async def team_categories_callback(call:CallbackQuery):
    if not await is_staff(call.from_user.id):return await call.answer("Ruxsat yo‘q",show_alert=True)
    await show_team_categories(call.message,True);await call.answer()


@router.callback_query(F.data.startswith("teamlist:"))
async def team_list_callback(call:CallbackQuery):
    if not await is_staff(call.from_user.id):return await call.answer("Ruxsat yo‘q",show_alert=True)
    category=call.data.split(':',1)[1]
    if category=='admin':where="role='admin'";title="🛡 Adminlar"
    elif category=='manager':where="role='manager'";title="🧑‍💼 Managerlar"
    elif category=='developer':
        where="status='accepted' AND role IN ('user','superadmin')" if await role_of(call.from_user.id)=='superadmin' else "role='user' AND status='accepted'"
        title="💻 Dasturchilar"
    else:return await call.answer("Bo‘lim topilmadi",show_alert=True)
    rows=await db_all(f"SELECT tg_id,full_name,specialty,status FROM users WHERE {where} ORDER BY full_name LIMIT 100")
    b=InlineKeyboardBuilder()
    for u in rows:b.button(text=u['full_name'][:55],callback_data=f"teamusr:{u['tg_id']}:{category}")
    b.button(text="⬅️ Jamoa",callback_data="team:categories");b.adjust(1)
    await call.message.edit_text(f"<b>{title}</b> — {len(rows)} ta\n\nMa’lumotni ko‘rish uchun ism-familiyani tanlang:",reply_markup=b.as_markup());await call.answer()


@router.callback_query(F.data.startswith("teamusr:"))
async def team_user_detail(call:CallbackQuery):
    if not await is_staff(call.from_user.id):return await call.answer("Ruxsat yo‘q",show_alert=True)
    _,raw_uid,category=call.data.split(':');u=await db_one("SELECT * FROM users WHERE tg_id=?",(int(raw_uid),))
    if not u or (u['role']=='superadmin' and await role_of(call.from_user.id)!='superadmin'):return await call.answer("User topilmadi",show_alert=True)
    text=(f"<b>👤 {h(u['full_name'],200)}</b>\n\n🎂 Yosh: {h(u['age'] or '—',20)}\n🆔 ID: <code>{u['tg_id']}</code>\n"
          f"🔗 Username: @{h(u['username'] or '—',80)}\n☎️ Telefon: {h(u['phone'] or '—',100)}\n"
          f"🛡 Vakolat: {ROLE_LABELS[u['role']]}\n💼 Yo‘nalish: {SPECIALTIES.get(u['specialty'],'Tanlanmagan')}\n"
          f"📊 Holat: {STATUS_LABELS[u['status']]}\n\n<b>Portfolio:</b>\n{portfolio_display(u)}\n\n<b>O‘zi haqida:</b>\n{h(u['about'] or '—',1800)}")
    buttons=[]
    if u['portfolio_file_id']:buttons.append([InlineKeyboardButton(text="📄 Portfolio faylini ko‘rish",callback_data=f"portfolio:{u['tg_id']}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Ro‘yxat",callback_data=f"teamlist:{category}")])
    await call.message.answer(text,reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons));await call.answer()


@router.callback_query(F.data.startswith("users:"))
async def users_page(call: CallbackQuery):
    if not await is_staff(call.from_user.id): return await call.answer("Ruxsat yo‘q", show_alert=True)
    page = int(call.data.split(":")[1]); kb, total = await users_keyboard(page, call.from_user.id)
    await call.message.edit_text(f"<b>👥 Userlar</b> — jami {total}\nBatafsil ko‘rish uchun userni tanlang:", reply_markup=kb); await call.answer()


@router.callback_query(F.data.startswith("usr:"))
async def user_detail(call: CallbackQuery):
    if not await is_staff(call.from_user.id): return await call.answer("Ruxsat yo‘q", show_alert=True)
    _, raw_uid, raw_page = call.data.split(":"); u = await db_one("SELECT * FROM users WHERE tg_id=?", (int(raw_uid),))
    if not u: return await call.answer("User topilmadi", show_alert=True)
    if u["role"] == "superadmin" and await effective_role(call.from_user.id) != "superadmin":
        return await call.answer("Bu profil ko‘rinmaydi", show_alert=True)
    b = InlineKeyboardBuilder()
    if await effective_role(call.from_user.id) in {"admin","superadmin"} and u["role"] not in {"admin","superadmin"}:
        b.button(text="User qilish" if u["role"] == "manager" else "Manager qilish", callback_data=f"role:{u['tg_id']}:{raw_page}")
        b.button(text="✅ Faollashtirish" if u["status"] == "blocked" else "⛔ Bloklash", callback_data=f"block:{u['tg_id']}:{raw_page}")
    if u["portfolio_file_id"]:
        file_kind="PDF" if str(u["portfolio_file_name"] or "").lower().endswith(".pdf") else "DOCX"
        b.button(text=f"📄 {file_kind} portfolioni ko‘rish", callback_data=f"portfolio:{u['tg_id']}")
    b.button(text="📋 Vazifalar tarixi",callback_data=f"userhistory:{u['tg_id']}:{raw_page}")
    b.button(text="⬅️ Ro‘yxat", callback_data=f"users:{raw_page}"); b.adjust(1)
    text = (f"<b>{h(u['full_name'], 200)}</b>\n🎂 Yosh: {h(u['age'] or '—', 20)}\nID: <code>{u['tg_id']}</code>\nUsername: @{h(u['username'] or '-', 100)}\n"
            f"Telefon: {h(u['phone'] or '-', 100)}\nVakolat: {ROLE_LABELS[u['role']]}\nYo‘nalish: {SPECIALTIES.get(u['specialty'], 'Tanlanmagan')}\nHolat: {STATUS_LABELS[u['status']]}\n\n"
            f"<b>Portfolio:</b>\n{portfolio_display(u)}\n\n<b>O‘zi haqida:</b>\n{h(u['about'] or '-', 2100)}")
    await call.message.edit_text(text, reply_markup=b.as_markup()); await call.answer()


@router.callback_query(F.data.startswith("userhistory:"))
async def user_task_history(call:CallbackQuery):
    if not await is_staff(call.from_user.id):return await call.answer("Ruxsat yo‘q",show_alert=True)
    _,raw_uid,page=call.data.split(':');uid=int(raw_uid);u=await db_one("SELECT full_name,role FROM users WHERE tg_id=?",(uid,))
    if not u or (u['role']=='superadmin' and await effective_role(call.from_user.id)!='superadmin'):return await call.answer("User topilmadi",show_alert=True)
    rows=await db_all("SELECT t.id,t.name,tu.status,tu.completed_at FROM task_users tu JOIN tasks t ON t.id=tu.task_id WHERE tu.user_id=? ORDER BY t.id DESC LIMIT 25",(uid,))
    lines=[f"• #{x['id']} · {h(x['name'],70)} · {TASK_STATUS_LABELS.get(x['status'],x['status'])}" for x in rows]
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ User",callback_data=f"usr:{uid}:{page}")]])
    await call.message.edit_text(f"<b>📋 {h(u['full_name'],100)} — vazifalar tarixi</b>\n\n"+("\n".join(lines) or "Vazifa yo‘q."),reply_markup=kb);await call.answer()


@router.callback_query(F.data.startswith("portfolio:"))
async def send_portfolio_file(call: CallbackQuery, bot: Bot):
    if not await is_actual_staff(call.from_user.id): return await call.answer("Ruxsat yo‘q", show_alert=True)
    uid = int(call.data.split(":", 1)[1])
    user = await db_one("SELECT * FROM users WHERE tg_id=?", (uid,))
    if not user or not user["portfolio_file_id"]: return await call.answer("Portfolio fayli topilmadi", show_alert=True)
    caption=(f"<b>👤 USER MA’LUMOTNOMASI</b>\n\n<b>{h(user['full_name'],150)}</b>\n"
             f"🎂 Yosh: {h(user['age'] or '—',20)}\n💼 Yo‘nalish: {SPECIALTIES.get(user['specialty'],'Tanlanmagan')}\n"
             f"☎️ Telefon: {h(user['phone'] or '—',80)}\n📎 Portfolio: {h(user['portfolio_file_name'] or 'Portfolio fayli',180)}\n\n"
             f"🗒 <b>O‘zi haqida:</b>\n{h(user['about'] or '—',300)}")
    await bot.send_document(call.message.chat.id, user["portfolio_file_id"],
                            caption=caption)
    await call.answer("Portfolio ma’lumotnoma bilan yuborildi")


@router.callback_query(F.data.startswith("role:"))
async def toggle_role(call: CallbackQuery):
    if await effective_role(call.from_user.id) not in {"admin","superadmin"}: return await call.answer("Faqat admin uchun", show_alert=True)
    _, raw_uid, page = call.data.split(":"); uid = int(raw_uid); u = await db_one("SELECT role FROM users WHERE tg_id=?", (uid,))
    if not u or u["role"] in {"admin","superadmin"}: return await call.answer("Rolni o‘zgartirib bo‘lmaydi", show_alert=True)
    new_role = "user" if u["role"] == "manager" else "manager"
    await db_execute("UPDATE users SET role=?,status='accepted' WHERE tg_id=?", (new_role, uid));await audit(call.from_user.id,"role_changed","user",uid,new_role)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Ro‘yxatga qaytish", callback_data=f"users:{page}")]])
    await call.message.edit_text(f"✅ Rol o‘zgartirildi: <b>{ROLE_LABELS[new_role]}</b>", reply_markup=kb)
    await call.answer()


@router.callback_query(F.data.startswith("block:"))
async def toggle_block(call: CallbackQuery, bot: Bot):
    if await effective_role(call.from_user.id) not in {"admin","superadmin"}: return await call.answer("Faqat admin uchun", show_alert=True)
    _, raw_uid, page = call.data.split(":"); uid = int(raw_uid)
    u = await db_one("SELECT role,status,full_name FROM users WHERE tg_id=?", (uid,))
    if not u or u["role"] in {"admin","superadmin"}: return await call.answer("Bu profilni bloklab bo‘lmaydi", show_alert=True)
    action_text = "bloklash" if u["status"] != "blocked" else "qayta faollashtirish"
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Ha, tasdiqlayman",callback_data=f"confirmblock:{uid}:{page}",style="danger")],[InlineKeyboardButton(text="❌ Yo‘q",callback_data=f"usr:{uid}:{page}")]])
    await call.message.edit_text(f"<b>⚠️ Tasdiqlash</b>\n\n{h(u['full_name'],150)} profilini {action_text}ni tasdiqlaysizmi?",reply_markup=kb);await call.answer()


@router.callback_query(F.data.startswith("confirmblock:"))
async def confirm_toggle_block(call:CallbackQuery,bot:Bot):
    if await effective_role(call.from_user.id) not in {"admin","superadmin"}:return await call.answer("Faqat admin uchun",show_alert=True)
    _,raw_uid,page=call.data.split(':');uid=int(raw_uid);u=await db_one("SELECT role,status,full_name FROM users WHERE tg_id=?",(uid,))
    if not u or u['role'] in {'admin','superadmin'}:return await call.answer("Bu profilni o‘zgartirib bo‘lmaydi",show_alert=True)
    new_status = "accepted" if u["status"] == "blocked" else "blocked"
    await db_execute("UPDATE users SET status=? WHERE tg_id=?", (new_status, uid));await audit(call.from_user.id,"user_status_changed","user",uid,new_status)
    notice = "✅ Profilingiz qayta faollashtirildi." if new_status == "accepted" else "⛔ Profilingiz admin tomonidan vaqtincha bloklandi."
    with suppress(TelegramForbiddenError, TelegramBadRequest): await bot.send_message(uid, notice)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Ro‘yxatga qaytish", callback_data=f"users:{page}")]])
    await call.message.edit_text(f"{notice}\n👤 {h(u['full_name'],200)}", reply_markup=kb); await call.answer()


@router.callback_query(F.data == "noop")
async def noop(call: CallbackQuery): await call.answer()


@router.callback_query(F.data.startswith("menu:"))
async def inline_main_menu(call: CallbackQuery, state: FSMContext):
    await ensure_user(call.from_user)
    action = call.data.split(":", 1)[1]
    actor_message = call.message.model_copy(update={"from_user": call.from_user})
    await call.answer()
    if action == "application": return await application_start(actor_message, state)
    if action == "panel": return await panel(actor_message)
    if action == "users": return await users_list(actor_message)
    if action == "groups": return await groups_list(actor_message)
    if action == "new_task": return await task_start(actor_message, state)
    if action == "tasks": return await tasks_list(actor_message)
    if action == "my_tasks": return await my_tasks_list(actor_message, False)
    if action == "my_completed": return await my_tasks_list(actor_message, True)
    if action == "profile": return await show_profile(actor_message)
    if action == "templates": return await templates_list(actor_message)
    if action == "audit": return await audit_list(actor_message)
    if action == "search": return await start_user_search(actor_message, state)
    if action == "admins": return await admins_list(actor_message)
    if action == "design": return await design_panel(actor_message)
    if action == "message_emojis": return await message_emoji_panel(actor_message)
    if action == "message_templates": return await message_templates_panel(actor_message)
    if action == "switch_role": return await change_mode(actor_message)


@router.callback_query(F.data == "nav:home")
async def navigate_home(call: CallbackQuery, state: FSMContext):
    await state.clear()
    role = await effective_role(call.from_user.id)
    actor_message = call.message.model_copy(update={"from_user": call.from_user})
    with suppress(TelegramBadRequest): await call.message.edit_reply_markup(reply_markup=None)
    await send_main_menu(actor_message, role in {"superadmin", "admin", "manager"}, role == "superadmin")
    await call.answer()


@router.message(Command("register_group"))
async def register_group(message: Message):
    if message.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}: return await message.answer("Bu buyruqni guruhda yuboring.")
    if not await is_staff(message.from_user.id): return await message.answer("Faqat admin yoki manager uchun.")
    await db_execute("""INSERT INTO groups(chat_id,title,added_by) VALUES(?,?,?)
      ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title,added_by=excluded.added_by""",
                     (message.chat.id, message.chat.title, message.from_user.id))
    await audit(message.from_user.id,"group_registered","group",message.chat.id,message.chat.title)
    await message.answer(f"✅ Guruh ro‘yxatdan o‘tdi. ID: <code>{message.chat.id}</code>")


@router.message(Command("add_group"))
async def add_group_by_id(message: Message, bot: Bot):
    if not await is_staff(message.from_user.id): return await message.answer("Bu bo‘lim uchun ruxsat yo‘q.")
    parts = message.text.split(maxsplit=2)
    if len(parts) < 2 or not parts[1].lstrip("-").isdigit():
        return await message.answer("Format: <code>/add_group -1001234567890</code> yoki <code>/add_group -1001234567890 Guruh nomi</code>")
    chat_id = int(parts[1])
    try:
        chat = await bot.get_chat(chat_id)
    except (TelegramBadRequest, TelegramForbiddenError):
        return await message.answer("Guruh topilmadi. Bot avval guruhga qo‘shilganini va ID to‘g‘riligini tekshiring.")
    title = parts[2] if len(parts) == 3 else (chat.title or str(chat_id))
    await db_execute("""INSERT INTO groups(chat_id,title,added_by) VALUES(?,?,?)
      ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title,added_by=excluded.added_by""", (chat_id, title, message.from_user.id))
    await audit(message.from_user.id,"group_added","group",chat_id,title)
    await message.answer(f"✅ {html.escape(title)} ro‘yxatga qo‘shildi.")


@router.message(F.text.in_(menu_texts("📂 Guruhlar")))
async def groups_list(message: Message):
    if not await is_staff(message.from_user.id): return
    text, kb = await groups_view(await effective_role(message.from_user.id) in {"admin","superadmin"})
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("adminremoveconfirm:"))
async def confirm_admin_removal(call:CallbackQuery,state:FSMContext,bot:Bot):
    if not await require_superadmin(call.from_user.id):return await call.answer("Faqat Superadmin rejimida",show_alert=True)
    uid=int(call.data.split(':')[1]);actor=call.message.model_copy(update={"from_user":call.from_user})
    await set_admin_role(actor,state,False,uid,bot,confirmed=True);await call.answer("Adminlik olib tashlandi",show_alert=True)


async def groups_view(admin=False):
    groups = await db_all("SELECT * FROM groups ORDER BY created_at DESC")
    text = "<b>📂 Guruhlar</b>\n\n" + ("\n".join(f"{'🟢' if g['is_active'] else '⚪️'} {h(g['title'],100)} — <code>{g['chat_id']}</code>" for g in groups) or "Hozircha yo‘q. Botni guruhga qo‘shib /register_group yuboring.")
    b = InlineKeyboardBuilder()
    if admin:
        for g in groups:
            b.button(text=f"{'⏸ O‘chirish' if g['is_active'] else '▶️ Faollashtirish'} · {g['title'][:32]}", callback_data=f"grouptoggle:{g['chat_id']}")
            b.button(text=f"🗑 {g['title'][:45]}", callback_data=f"groupdel:{g['chat_id']}")
    b.button(text="🔄 Yangilash", callback_data="groups:show")
    b.button(text="⬅️ Admin panel", callback_data="menu:panel"); b.adjust(1)
    return text, b.as_markup()


@router.callback_query(F.data == "groups:show")
async def groups_callback(call: CallbackQuery):
    if not await is_staff(call.from_user.id): return await call.answer("Ruxsat yo‘q", show_alert=True)
    text, kb = await groups_view(await effective_role(call.from_user.id) in {"admin","superadmin"})
    await call.message.edit_text(text, reply_markup=kb); await call.answer()


@router.callback_query(F.data.startswith("groupdel:"))
async def delete_group(call: CallbackQuery):
    if await effective_role(call.from_user.id) not in {"admin","superadmin"}: return await call.answer("Faqat admin o‘chira oladi", show_alert=True)
    chat_id = int(call.data.split(":")[1])
    group = await db_one("SELECT title FROM groups WHERE chat_id=?", (chat_id,))
    if not group: return await call.answer("Guruh topilmadi", show_alert=True)
    await db_execute("DELETE FROM groups WHERE chat_id=?", (chat_id,));await audit(call.from_user.id,"group_deleted","group",chat_id)
    text, kb = await groups_view(True)
    await call.message.edit_text(text, reply_markup=kb)
    await call.answer(f"{group['title']} ro‘yxatdan olib tashlandi", show_alert=True)


@router.callback_query(F.data.startswith("grouptoggle:"))
async def toggle_group(call:CallbackQuery):
    if await effective_role(call.from_user.id) not in {"admin","superadmin"}:return await call.answer("Faqat admin uchun",show_alert=True)
    gid=int(call.data.split(':')[1]);await db_execute("UPDATE groups SET is_active=NOT is_active WHERE chat_id=?",(gid,));await audit(call.from_user.id,"group_toggled","group",gid)
    text,kb=await groups_view(True);await call.message.edit_text(text,reply_markup=kb);await call.answer("Guruh holati yangilandi")


async def show_profile(message: Message):
    u = await db_one("SELECT * FROM users WHERE tg_id=?", (message.from_user.id,))
    if not u or u["status"] != "accepted": return await message.answer("Profil faqat qabul qilingan user uchun.")
    done = (await db_one("SELECT COUNT(*) c FROM task_users WHERE user_id=? AND status IN ('approved','completed')", (message.from_user.id,)))["c"]
    text = (f"<b>👤 Profilim</b>\n\n<b>{h(u['full_name'],200)}</b>\n🎂 {h(u['age'] or '—',20)} yosh\n💼 {SPECIALTIES.get(u['specialty'],'Tanlanmagan')}\n"
            f"☎️ {h(u['phone'] or '—',100)}\n✅ Tugallangan vazifalar: {done}\n\n<b>Portfolio:</b> {h(u['portfolio'] or u['portfolio_file_name'] or '—',800)}\n\n<b>O‘zi haqida:</b> {h(u['about'] or '—',1400)}")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="☎️ Telefon",callback_data="profileedit:phone"),InlineKeyboardButton(text="💼 Portfolio",callback_data="profileedit:portfolio")],[InlineKeyboardButton(text="🗒 O‘zim haqimda",callback_data="profileedit:about")],[InlineKeyboardButton(text="💼 Yo‘nalishni o‘zgartirish",callback_data="profile:specialty")],[InlineKeyboardButton(text="🏠 Bosh sahifa",callback_data="nav:home",design_key="home")]])
    await message.answer(text,reply_markup=kb)


@router.message(F.text.in_(menu_texts("👤 Profilim")))
async def profile_menu(message: Message): await show_profile(message)


@router.callback_query(F.data.startswith("profileedit:"))
async def profile_edit_start(call: CallbackQuery,state:FSMContext):
    field=call.data.split(":",1)[1]
    if field not in {"phone","portfolio","about"}: return await call.answer("Noto‘g‘ri maydon",show_alert=True)
    await state.update_data(profile_field=field); await state.set_state(ProfileEdit.value)
    await call.message.answer({"phone":"Yangi telefon raqamingizni yozing:","portfolio":"Yangi portfolio matni yoki havolasini yozing:","about":"O‘zingiz haqingizdagi yangi matnni yozing:"}[field]); await call.answer()


@router.callback_query(F.data=="profile:specialty")
async def request_specialty_menu(call:CallbackQuery):
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=label,callback_data=f"specialtyreq:{key}") for key,label in list(SPECIALTIES.items())[:2]],[InlineKeyboardButton(text=label,callback_data=f"specialtyreq:{key}") for key,label in list(SPECIALTIES.items())[2:]],[InlineKeyboardButton(text="⬅️ Profil",callback_data="menu:profile")]])
    await call.message.edit_text("Yangi yo‘nalishni tanlang. Admin tasdiqlagach o‘zgaradi:",reply_markup=kb);await call.answer()


@router.callback_query(F.data.startswith("specialtyreq:"))
async def request_specialty(call:CallbackQuery,bot:Bot):
    specialty=call.data.split(':')[1]
    if specialty not in SPECIALTIES:return await call.answer("Noto‘g‘ri yo‘nalish",show_alert=True)
    u=await db_one("SELECT full_name FROM users WHERE tg_id=?",(call.from_user.id,));kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Tasdiqlash",callback_data=f"specialtyapprove:{call.from_user.id}:{specialty}"),InlineKeyboardButton(text="❌ Rad etish",callback_data=f"specialtyreject:{call.from_user.id}")]])
    for staff in await db_all("SELECT tg_id FROM users WHERE role IN ('admin','superadmin')"):
        with suppress(TelegramBadRequest,TelegramForbiddenError):await bot.send_message(staff['tg_id'],f"💼 <b>Yo‘nalish o‘zgartirish so‘rovi</b>\n👤 {h(u['full_name'],100)}\n➡️ {SPECIALTIES[specialty]}",reply_markup=kb)
    await audit(call.from_user.id,"specialty_requested","user",call.from_user.id,specialty);await call.answer("So‘rov adminlarga yuborildi",show_alert=True)


@router.callback_query(F.data.startswith("specialtyapprove:"))
async def approve_specialty(call:CallbackQuery,bot:Bot):
    if await effective_role(call.from_user.id) not in {'admin','superadmin'}:return await call.answer("Ruxsat yo‘q",show_alert=True)
    _,raw_uid,specialty=call.data.split(':');uid=int(raw_uid);await db_execute("UPDATE users SET specialty=? WHERE tg_id=?",(specialty,uid));await audit(call.from_user.id,"specialty_approved","user",uid,specialty)
    await call.message.edit_reply_markup(reply_markup=None);await call.answer("Tasdiqlandi",show_alert=True)
    with suppress(TelegramBadRequest,TelegramForbiddenError):await bot.send_message(uid,f"✅ Yo‘nalishingiz {SPECIALTIES[specialty]} ga o‘zgartirildi.")


@router.callback_query(F.data.startswith("specialtyreject:"))
async def reject_specialty(call:CallbackQuery,bot:Bot):
    if await effective_role(call.from_user.id) not in {'admin','superadmin'}:return await call.answer("Ruxsat yo‘q",show_alert=True)
    uid=int(call.data.split(':')[1]);await call.message.edit_reply_markup(reply_markup=None);await audit(call.from_user.id,"specialty_rejected","user",uid);await call.answer("Rad etildi",show_alert=True)
    with suppress(TelegramBadRequest,TelegramForbiddenError):await bot.send_message(uid,"❌ Yo‘nalishni o‘zgartirish so‘rovingiz rad etildi.")


@router.message(ProfileEdit.value,F.text)
async def profile_edit_save(message:Message,state:FSMContext):
    field=(await state.get_data())["profile_field"]
    await db_execute(f"UPDATE users SET {field}=? WHERE tg_id=?",(message.text,message.from_user.id)); await audit(message.from_user.id,"profile_updated","user",message.from_user.id,field)
    await state.clear(); await message.answer("✅ Profil yangilandi."); await show_profile(message)


@router.message(ProfileEdit.value,F.document)
async def profile_portfolio_file(message:Message,state:FSMContext):
    field=(await state.get_data()).get('profile_field');doc=message.document;name=doc.file_name or 'portfolio';ext=os.path.splitext(name)[1].lower()
    if field!='portfolio' or ext not in {'.pdf','.docx'}:return await message.answer("Bu yerda faqat portfolio uchun PDF yoki DOCX yuborish mumkin.")
    await db_execute("UPDATE users SET portfolio=NULL,portfolio_file_id=?,portfolio_file_name=?,portfolio_file_mime=? WHERE tg_id=?",(doc.file_id,name,doc.mime_type,message.from_user.id));await audit(message.from_user.id,"portfolio_file_updated","user",message.from_user.id,name)
    await state.clear();await message.answer("✅ Portfolio fayli yangilandi.");await show_profile(message)


async def start_user_search(message:Message,state:FSMContext):
    if not await is_staff(message.from_user.id): return
    await state.set_state(UserSearch.query)
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Backend",callback_data="filter:backend"),InlineKeyboardButton(text="Frontend",callback_data="filter:frontend")],[InlineKeyboardButton(text="Full stack",callback_data="filter:fullstack"),InlineKeyboardButton(text="Vibecoder",callback_data="filter:vibecoder")],[InlineKeyboardButton(text="✅ Qabul qilingan",callback_data="filterstatus:accepted"),InlineKeyboardButton(text="⛔ Bloklangan",callback_data="filterstatus:blocked")],[InlineKeyboardButton(text="⏳ Kutilmoqda",callback_data="filterstatus:pending")],[InlineKeyboardButton(text="⬅️ Panel",callback_data="menu:panel")]])
    await message.answer("Ism, username yoki Telegram ID yozing; yoki yo‘nalishni tanlang:",reply_markup=kb)


async def send_search_results(message,rows):
    b=InlineKeyboardBuilder()
    for u in rows:b.button(text=f"{u['full_name']} · {SPECIALTIES.get(u['specialty'],'—')}",callback_data=f"usr:{u['tg_id']}:0")
    b.button(text="⬅️ Panel",callback_data="menu:panel");b.adjust(1)
    await message.answer(f"🔎 Natijalar: {len(rows)} ta",reply_markup=b.as_markup())


@router.message(UserSearch.query,F.text)
async def user_search_query(message:Message,state:FSMContext):
    q=message.text.strip();username_q=q.lstrip('@');pattern=f"%{username_q}%"
    rows=await db_all("SELECT tg_id,full_name,specialty,status FROM users WHERE role!='superadmin' AND (full_name LIKE ? OR username LIKE ? OR CAST(tg_id AS TEXT)=?) ORDER BY full_name LIMIT 20",(pattern,pattern,q))
    await state.clear();await send_search_results(message,rows)


@router.callback_query(F.data.startswith("filter:"))
async def filter_users(call:CallbackQuery):
    if not await is_staff(call.from_user.id):return await call.answer("Ruxsat yo‘q",show_alert=True)
    rows=await db_all("SELECT tg_id,full_name,specialty,status FROM users WHERE role!='superadmin' AND specialty=? ORDER BY full_name LIMIT 50",(call.data.split(':',1)[1],))
    actor=call.message.model_copy(update={"from_user":call.from_user});await send_search_results(actor,rows);await call.answer()


@router.callback_query(F.data.startswith("filterstatus:"))
async def filter_users_status(call:CallbackQuery):
    if not await is_staff(call.from_user.id):return await call.answer("Ruxsat yo‘q",show_alert=True)
    rows=await db_all("SELECT tg_id,full_name,specialty,status FROM users WHERE role!='superadmin' AND status=? ORDER BY full_name LIMIT 50",(call.data.split(':',1)[1],))
    actor=call.message.model_copy(update={"from_user":call.from_user});await send_search_results(actor,rows);await call.answer()


async def templates_list(message:Message):
    if not await is_staff(message.from_user.id):return
    rows=await db_all("SELECT id,name FROM task_templates ORDER BY id DESC LIMIT 30");b=InlineKeyboardBuilder()
    for x in rows:b.button(text=f"🧾 {x['name'][:45]}",callback_data=f"template:use:{x['id']}")
    b.button(text="➕ Yangi shablon",callback_data="template:new");b.button(text="⬅️ Panel",callback_data="menu:panel");b.adjust(1)
    await message.answer(f"<b>🧾 Vazifa shablonlari</b> — {len(rows)} ta",reply_markup=b.as_markup())


@router.callback_query(F.data=="template:new")
async def template_new(call:CallbackQuery,state:FSMContext):
    if not await is_staff(call.from_user.id):return await call.answer("Ruxsat yo‘q",show_alert=True)
    await state.set_state(TemplateForm.name);await call.message.answer("Shablon nomini yozing:");await call.answer()


@router.message(TemplateForm.name,F.text)
async def template_name(message:Message,state:FSMContext):await state.update_data(template_name=message.text);await state.set_state(TemplateForm.description);await message.answer("Shablon tavsifini yozing:")


@router.message(TemplateForm.description,F.text)
async def template_description(message:Message,state:FSMContext):
    data=await state.get_data();await db_execute("INSERT INTO task_templates(name,description,created_by) VALUES(?,?,?)",(data['template_name'],message.text,message.from_user.id));await audit(message.from_user.id,"template_created","template",None,data['template_name']);await state.clear();await message.answer("✅ Shablon saqlandi.");await templates_list(message)


@router.callback_query(F.data.startswith("template:use:"))
async def template_use(call:CallbackQuery,state:FSMContext):
    row=await db_one("SELECT name,description FROM task_templates WHERE id=?",(int(call.data.split(':')[2]),))
    if not row:return await call.answer("Shablon topilmadi",show_alert=True)
    await state.update_data(name=row['name'],description=row['description']);await state.set_state(TaskForm.deadline);await ask_task_deadline(call.message);await call.answer("Shablon tanlandi")


async def audit_list(message:Message):
    if not await is_staff(message.from_user.id):return
    rows=await db_all("SELECT a.*,u.full_name actor FROM audit_logs a LEFT JOIN users u ON u.tg_id=a.actor_id ORDER BY a.id DESC LIMIT 30")
    lines=[f"• {h(x['actor'] or x['actor_id'] or 'Tizim',60)} — {h(x['action'],80)} — {h(x['target_id'] or '',40)}" for x in rows]
    await message.answer("<b>🕘 So‘nggi audit amallari</b>\n\n"+("\n".join(lines) or "Hozircha yozuv yo‘q."),reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Panel",callback_data="menu:panel")]]))


@router.message(F.text.in_(menu_texts("➕ Topshiriq")))
async def task_start(message: Message, state: FSMContext):
    if not await is_staff(message.from_user.id): return
    await state.clear(); await state.set_state(TaskForm.name)
    await message.answer("Topshiriq nomini kiriting:")


@router.message(TaskForm.name, F.text)
async def task_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text); await state.set_state(TaskForm.description)
    await message.answer("Vazifa tavsifini kiriting:")


@router.message(TaskForm.description, F.text)
async def task_desc(message: Message, state: FSMContext):
    await state.update_data(description=message.text); await state.set_state(TaskForm.deadline)
    await ask_task_deadline(message)


async def ask_task_deadline(message):
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⏰ 1 soat",callback_data="deadline:1h"),InlineKeyboardButton(text="Bugun 18:00",callback_data="deadline:today18")],[InlineKeyboardButton(text="Ertaga 18:00",callback_data="deadline:tomorrow18"),InlineKeyboardButton(text="7 kun",callback_data="deadline:7d")],[InlineKeyboardButton(text="🏠 Bosh sahifa",callback_data="nav:home",design_key="home")]])
    await message.answer("Muddatni tanlang yoki <code>30.07.2026 18:00</code> formatida yozing:",reply_markup=kb)


def parse_deadline(value):
    try:
        local=datetime.strptime(value.strip(),"%d.%m.%Y %H:%M").replace(tzinfo=TASHKENT_TZ)
        return local.astimezone(timezone.utc)
    except ValueError:return None


async def finish_deadline(message,state,display,deadline_at):
    users_count=(await db_one("SELECT COUNT(*) c FROM users WHERE status='accepted' AND (role='user' OR (role='superadmin' AND active_mode='user'))"))["c"]
    if not users_count:await state.clear();return await message.answer("Qabul qilingan userlar yo‘q.")
    await state.update_data(deadline=display,deadline_at=deadline_at.isoformat(timespec="seconds"),selected=[]);await state.set_state(TaskForm.selection_mode)
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="👤 Bitta user",callback_data="selectmode:single")],[InlineKeyboardButton(text="👥 Bir nechta user",callback_data="selectmode:multiple")],[InlineKeyboardButton(text="🏠 Bosh sahifa",callback_data="nav:home",design_key="home")]])
    await message.answer("Ijrochilarni tanlash turini belgilang:",reply_markup=kb)


@router.callback_query(TaskForm.deadline,F.data.startswith("deadline:"))
async def deadline_shortcut(call:CallbackQuery,state:FSMContext):
    now=datetime.now(TASHKENT_TZ);key=call.data.split(':')[1]
    if key=='1h':target=now+timedelta(hours=1)
    elif key=='7d':target=now+timedelta(days=7)
    elif key=='today18':target=now.replace(hour=18,minute=0,second=0,microsecond=0);target=target if target>now else target+timedelta(days=1)
    else:target=(now+timedelta(days=1)).replace(hour=18,minute=0,second=0,microsecond=0)
    await call.message.edit_reply_markup(reply_markup=None);await finish_deadline(call.message,state,target.strftime('%d.%m.%Y %H:%M'),target.astimezone(timezone.utc));await call.answer()


async def user_picker(selected: set[int], selection_mode="multiple"):
    users = await db_all("""SELECT tg_id,full_name,username,specialty FROM users WHERE status='accepted'
      AND (role='user' OR (role='superadmin' AND active_mode='user')) ORDER BY full_name""")
    b = InlineKeyboardBuilder()
    for u in users:
        mark = "🔘" if selection_mode == "single" and u["tg_id"] in selected else ("✅" if u["tg_id"] in selected else "▫️")
        b.button(text=f"{mark} {u['full_name']} · {SPECIALTIES.get(u['specialty'], '—')}", callback_data=f"pick:{u['tg_id']}")
    b.button(text="Davom etish ➡️", callback_data="pick:done")
    b.button(text="⬅️ Tanlash turiga qaytish", callback_data="pick:mode"); b.adjust(1)
    return b.as_markup()


@router.message(TaskForm.deadline, F.text)
async def task_deadline(message: Message, state: FSMContext):
    parsed=parse_deadline(message.text)
    if not parsed or parsed<=datetime.now(timezone.utc):return await message.answer("Kelajakdagi vaqtni <code>30.07.2026 18:00</code> formatida yozing.")
    await finish_deadline(message,state,message.text,parsed)


@router.callback_query(TaskForm.selection_mode, F.data.startswith("selectmode:"))
async def choose_selection_mode(call: CallbackQuery, state: FSMContext):
    mode = call.data.split(":", 1)[1]
    if mode not in {"single", "multiple"}: return await call.answer("Noto‘g‘ri tanlov", show_alert=True)
    await state.update_data(selection_mode=mode, selected=[])
    await state.set_state(TaskForm.users)
    title = "Bitta userni tanlang:" if mode == "single" else "Bir yoki bir nechta userni tanlang:"
    await call.message.edit_text(title, reply_markup=await user_picker(set(), mode)); await call.answer()


@router.callback_query(TaskForm.users, F.data.startswith("pick:"))
async def pick_user(call: CallbackQuery, state: FSMContext):
    value = call.data.split(":",1)[1]; data = await state.get_data(); selected = set(data.get("selected", [])); mode = data.get("selection_mode", "multiple")
    if value == "mode":
        await state.set_state(TaskForm.selection_mode)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👤 Bitta user", callback_data="selectmode:single")],
            [InlineKeyboardButton(text="👥 Bir nechta user", callback_data="selectmode:multiple")],
        ])
        await call.message.edit_text("Ijrochilarni tanlash turini belgilang:", reply_markup=kb); return await call.answer()
    if value != "done":
        uid = int(value)
        selected = {uid} if mode == "single" else selected.symmetric_difference({uid})
        await state.update_data(selected=list(selected))
        await call.message.edit_reply_markup(reply_markup=await user_picker(selected, mode)); return await call.answer()
    if not selected: return await call.answer("Kamida bitta user tanlang", show_alert=True)
    groups = await db_all("SELECT chat_id,title FROM groups WHERE is_active=TRUE ORDER BY title")
    if not groups: return await call.answer("Avval guruhni /register_group orqali ro‘yxatdan o‘tkazing", show_alert=True)
    b = InlineKeyboardBuilder()
    for g in groups: b.button(text=g["title"], callback_data=f"group:{g['chat_id']}")
    b.adjust(1); await state.set_state(TaskForm.group)
    await call.message.edit_text("Topshiriq yuboriladigan guruhni tanlang:", reply_markup=b.as_markup()); await call.answer()


@router.callback_query(TaskForm.group, F.data.startswith("group:"))
async def pick_group(call: CallbackQuery, state: FSMContext):
    gid = int(call.data.split(":")[1]); await state.update_data(group_id=gid); data = await state.get_data()
    placeholders = ",".join("?" for _ in data["selected"])
    users = await db_all(f"SELECT tg_id,username,full_name FROM users WHERE tg_id IN ({placeholders})", data["selected"])
    mentions = " ".join(user_mention(u, 60) for u in users)
    mentions = mentions[:900]
    assigned_intro=render_template("task_assigned",task_name=data['name'],deadline=data['deadline'])
    text = (f"<b>{message_emoji('task')} {h(data['name'], 200)}</b>\n<i>{assigned_intro}</i>\n\n{h(data['description'], 2500)}\n\n"
            f"{message_emoji('deadline')} <b>Vaqti:</b> {h(data['deadline'], 200)}\n{message_emoji('group')} {mentions}")
    await state.update_data(task_text=text); await state.set_state(TaskForm.confirm)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="task:cancel"), InlineKeyboardButton(text="🚀 Yuborish", callback_data="task:send")]])
    await call.message.edit_text(text, reply_markup=kb); await call.answer()


@router.callback_query(TaskForm.confirm, F.data.startswith("task:"))
async def task_send(call: CallbackQuery, state: FSMContext, bot: Bot):
    if call.data == "task:cancel":
        await state.clear(); await call.message.edit_text("Topshiriq bekor qilindi."); return await call.answer()
    d = await state.get_data()
    task_id = await create_task(d, call.from_user.id)
    failures=[]
    try:
        group_message=await bot.send_message(d["group_id"], d["task_text"])
        await db_execute("UPDATE tasks SET group_message_id=? WHERE id=?",(group_message.message_id,task_id))
        with suppress(TelegramBadRequest,TelegramForbiddenError):
            await bot.pin_chat_message(d["group_id"],group_message.message_id,disable_notification=True);await db_execute("UPDATE tasks SET is_pinned=TRUE WHERE id=?",(task_id,))
    except (TelegramForbiddenError, TelegramBadRequest): failures.append(d["group_id"])
    done_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="▶️ Boshladim", callback_data=f"begin:{task_id}"),InlineKeyboardButton(text="📤 Natija topshirish", callback_data=f"done:{task_id}")]])
    for user_id in d["selected"]:
        try: await bot.send_message(user_id, d["task_text"], reply_markup=done_kb)
        except (TelegramForbiddenError, TelegramBadRequest): failures.append(user_id)
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer("✅ Topshiriq yuborildi." + (f"\nYetib bormagan chatlar: {failures}" if failures else ""))
    await audit(call.from_user.id,"task_created","task",task_id,d['name'])
    await state.clear(); await call.answer()


@router.callback_query(F.data.startswith("done:"))
async def complete_task(call: CallbackQuery, bot: Bot, state: FSMContext):
    task_id = int(call.data.split(":")[1])
    assignment = await db_one("SELECT status FROM task_users WHERE task_id=? AND user_id=?",(task_id,call.from_user.id))
    if not assignment: return await call.answer("Bu topshiriq sizga biriktirilmagan", show_alert=True)
    if assignment["status"] in {"submitted","approved","completed"}:return await call.answer("Natija allaqachon topshirilgan",show_alert=True)
    await state.update_data(result_task_id=task_id);await state.set_state(TaskResult.content)
    await call.answer("Natijani yuboring")
    await call.message.answer(f"📤 <b>#{task_id} natijasi</b>\nIzoh yozing yoki bitta fayl yuboring. Bekor qilish: /cancel")


@router.callback_query(F.data.startswith("begin:"))
async def begin_task(call:CallbackQuery):
    tid=int(call.data.split(':')[1]);row=await db_one("SELECT status FROM task_users WHERE task_id=? AND user_id=?",(tid,call.from_user.id))
    if not row:return await call.answer("Vazifa sizga tegishli emas",show_alert=True)
    if row['status']=='assigned':await db_execute("UPDATE task_users SET status='in_progress',opened_at=? WHERE task_id=? AND user_id=?",(datetime.now(timezone.utc).isoformat(timespec='seconds'),tid,call.from_user.id))
    await call.answer("Bajarilmoqda deb belgilandi",show_alert=True)


async def save_task_submission(message:Message,state:FSMContext,bot:Bot,text=None,file_id=None,file_name=None):
    tid=(await state.get_data())["result_task_id"];now=datetime.now(timezone.utc).isoformat(timespec="seconds")
    row=await db_one("""SELECT t.name,t.group_id,t.created_by,u.full_name FROM task_users tu JOIN tasks t ON t.id=tu.task_id JOIN users u ON u.tg_id=tu.user_id WHERE tu.task_id=? AND tu.user_id=?""",(tid,message.from_user.id))
    if not row:await state.clear();return await message.answer("Vazifa topilmadi.")
    await db_execute("UPDATE task_users SET status='submitted',result_text=?,result_file_id=?,result_file_name=?,submitted_at=? WHERE task_id=? AND user_id=?",(text,file_id,file_name,now,tid,message.from_user.id))
    await state.clear();await message.answer("✅ Natija tekshiruvga yuborildi.")
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Tasdiqlash",callback_data=f"result:approve:{tid}:{message.from_user.id}"),InlineKeyboardButton(text="🔁 Qayta ishlash",callback_data=f"result:rework:{tid}:{message.from_user.id}")]])
    notice=f"<b>👀 Yangi natija</b>\n📌 #{tid} · {h(row['name'],150)}\n👤 {h(row['full_name'],100)}\n🗒 {h(text or file_name or 'Fayl',1200)}"
    staff=await db_all("SELECT tg_id FROM users WHERE role IN ('superadmin','admin','manager')")
    for member in staff:
        with suppress(TelegramBadRequest,TelegramForbiddenError):
            await bot.send_message(member['tg_id'],notice,reply_markup=kb)
            if file_id:await bot.send_document(member['tg_id'],file_id,caption=f"📎 {h(file_name or 'Natija',150)}")
    await audit(message.from_user.id,"task_submitted","task",tid)


@router.message(TaskResult.content,F.text)
async def task_result_text(message:Message,state:FSMContext,bot:Bot):await save_task_submission(message,state,bot,text=message.text)


@router.message(TaskResult.content,F.document)
async def task_result_file(message:Message,state:FSMContext,bot:Bot):await save_task_submission(message,state,bot,file_id=message.document.file_id,file_name=message.document.file_name)


@router.callback_query(F.data.startswith("result:"))
async def review_task_result(call:CallbackQuery,bot:Bot):
    if not await is_staff(call.from_user.id):return await call.answer("Ruxsat yo‘q",show_alert=True)
    _,action,raw_tid,raw_uid=call.data.split(':');tid=int(raw_tid);uid=int(raw_uid)
    row=await db_one("SELECT status FROM task_users WHERE task_id=? AND user_id=?",(tid,uid))
    if not row or row['status']!='submitted':return await call.answer("Natija allaqachon ko‘rib chiqilgan",show_alert=True)
    if action=='approve':
        kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{'⭐'*score} {score}",callback_data=f"rate:{score}:{tid}:{uid}") for score in range(1,6)]])
        await call.message.edit_reply_markup(reply_markup=kb);return await call.answer("1–5 bahoni tanlang")
    status='approved' if action=='approve' else 'rework';now=datetime.now(timezone.utc).isoformat(timespec='seconds')
    await db_execute("UPDATE task_users SET status=?,completed_at=? WHERE task_id=? AND user_id=?",(status,now if status=='approved' else None,tid,uid))
    await call.message.edit_reply_markup(reply_markup=None);label="✅ Tasdiqlandi" if status=='approved' else "🔁 Qayta ishlashga yuborildi"
    with suppress(TelegramBadRequest,TelegramForbiddenError):await bot.send_message(uid,f"{label}\n📌 Vazifa #{tid}")
    await refresh_group_task_message(bot,tid)
    await audit(call.from_user.id,f"task_{status}","task",tid,f"user:{uid}");await call.answer(label,show_alert=True)


@router.callback_query(F.data.startswith("rate:"))
async def rate_task_result(call:CallbackQuery,bot:Bot,state:FSMContext):
    if not await is_actual_staff(call.from_user.id):return await call.answer("Ruxsat yo‘q",show_alert=True)
    _,raw_score,raw_tid,raw_uid=call.data.split(':');score=int(raw_score);tid=int(raw_tid);uid=int(raw_uid)
    if score not in range(1,6):return await call.answer("Baho noto‘g‘ri",show_alert=True)
    row=await db_one("SELECT status FROM task_users WHERE task_id=? AND user_id=?",(tid,uid))
    if not row or row['status']!='submitted':return await call.answer("Natija allaqachon ko‘rib chiqilgan",show_alert=True)
    now=datetime.now(timezone.utc).isoformat(timespec='seconds')
    await db_execute("UPDATE task_users SET status='approved',completed_at=?,rating=? WHERE task_id=? AND user_id=?",(now,score,tid,uid))
    await call.message.edit_reply_markup(reply_markup=None)
    with suppress(TelegramBadRequest,TelegramForbiddenError):await bot.send_message(uid,f"✅ Natija tasdiqlandi\n📌 Vazifa #{tid}\n⭐ Baho: {score}/5")
    await refresh_group_task_message(bot,tid);await audit(call.from_user.id,"task_approved","task",tid,f"user:{uid};rating:{score}")
    await state.set_state(TaskReviewForm.note);await state.update_data(review_task_id=tid,review_task_user_id=uid,review_task_rating=score)
    await call.message.answer("Bahoga qisqa izoh yozing yoki /skip yuboring.")
    await call.answer(f"Tasdiqlandi · {score}/5",show_alert=True)


@router.message(TaskReviewForm.note,F.text)
async def save_task_review_note(message:Message,state:FSMContext,bot:Bot):
    if not await is_actual_staff(message.from_user.id):await state.clear();return
    data=await state.get_data();tid=data.get('review_task_id');uid=data.get('review_task_user_id');score=data.get('review_task_rating')
    if not tid or not uid:await state.clear();return await message.answer("Baholash sessiyasi tugagan.")
    note="Izoh qoldirilmadi" if message.text=="/skip" else message.text.strip()
    await db_execute("UPDATE task_users SET review_note=? WHERE task_id=? AND user_id=?",(note,tid,uid))
    with suppress(TelegramBadRequest,TelegramForbiddenError):await bot.send_message(uid,f"💬 Vazifa #{tid} bo‘yicha admin izohi:\n{h(note,1800)}\n⭐ Baho: {score}/5")
    await audit(message.from_user.id,"task_review_note","task",tid,f"user:{uid};note:{note[:300]}");await state.clear();await message.answer("✅ Baho izohi saqlandi va userga yuborildi.")


async def refresh_group_task_message(bot:Bot,task_id:int):
    task=await db_one("SELECT name,description,deadline,group_id,group_message_id FROM tasks WHERE id=?",(task_id,))
    if not task or not task['group_message_id']:return
    users=await db_all("SELECT u.tg_id,u.full_name,u.username,tu.status FROM task_users tu JOIN users u ON u.tg_id=tu.user_id WHERE tu.task_id=? ORDER BY u.full_name",(task_id,))
    people="\n".join(f"{TASK_STATUS_LABELS.get(u['status'],'⏳')} {user_mention(u,80)}" for u in users)
    text=f"<b>📌 {h(task['name'],200)}</b>\n\n{h(task['description'],2200)}\n\n⏰ {h(task['deadline'],100)}\n\n{people}"
    with suppress(TelegramBadRequest,TelegramForbiddenError):await bot.edit_message_text(text,chat_id=task['group_id'],message_id=task['group_message_id'])
    if users and all(u['status'] in {'approved','completed'} for u in users):
        with suppress(TelegramBadRequest,TelegramForbiddenError):await bot.unpin_chat_message(task['group_id'],task['group_message_id'])


async def my_tasks_markup(user_id: int, completed: bool):
    statuses = "('approved','completed')" if completed else "('assigned','in_progress','submitted','rework')"
    rows = await db_all(f"""SELECT t.id,t.name,t.deadline,t.deadline_at,tu.status FROM task_users tu
      JOIN tasks t ON t.id=tu.task_id WHERE tu.user_id=? AND tu.status IN {statuses}
      ORDER BY t.id DESC LIMIT 50""", (user_id,))
    b = InlineKeyboardBuilder()
    kind = "completed" if completed else "active"
    for task in rows:
        overdue = bool(task['deadline_at'] and utc_datetime(task['deadline_at']) < datetime.now(timezone.utc) and not completed)
        b.button(text=f"{'⚠️ Kechikkan' if overdue else TASK_STATUS_LABELS.get(task['status'],'')} · #{task['id']} · {task['name'][:30]}", callback_data=f"mytask:{task['id']}:{kind}")
    b.button(text="🏠 Bosh sahifa", callback_data="nav:home", design_key="home")
    b.adjust(1)
    return b.as_markup(), len(rows)


async def my_tasks_list(message: Message, completed=False):
    profile = await db_one("SELECT status FROM users WHERE tg_id=?", (message.from_user.id,))
    if not profile or profile["status"] != "accepted":
        return await message.answer("Bu bo‘lim faqat arizasi qabul qilingan userlar uchun.")
    kb, total = await my_tasks_markup(message.from_user.id, completed)
    title = "✅ Tugallangan vazifalarim" if completed else "📥 Vazifalar"
    empty = "\nHozircha bu bo‘limda vazifa yo‘q." if not total else "\nKo‘rish uchun vazifani tanlang:"
    await message.answer(f"<b>{title}</b> — {total} ta{empty}", reply_markup=kb)


@router.message(F.text.in_(menu_texts("📥 Vazifalar")))
async def active_user_tasks(message: Message):
    await my_tasks_list(message, False)


@router.message(F.text.in_(menu_texts("✅ Tugallangan vazifalarim")))
async def completed_user_tasks(message: Message):
    await my_tasks_list(message, True)


@router.callback_query(F.data.startswith("mytask:"))
async def my_task_detail(call: CallbackQuery):
    _, raw_id, kind = call.data.split(":")
    task_id = int(raw_id)
    task = await db_one("""SELECT t.id,t.name,t.description,t.deadline,tu.status,tu.completed_at
      FROM task_users tu JOIN tasks t ON t.id=tu.task_id
      WHERE tu.task_id=? AND tu.user_id=?""", (task_id, call.from_user.id))
    if not task: return await call.answer("Vazifa topilmadi", show_alert=True)
    completed = task["status"] in {"approved","completed"}
    text = (f"<b>📌 #{task['id']} · {h(task['name'], 200)}</b>\n\n{h(task['description'], 2600)}\n\n"
            f"⏰ <b>Muddat:</b> {h(task['deadline'], 200)}\n"
            f"📊 <b>Holat:</b> {TASK_STATUS_LABELS.get(task['status'],task['status'])}")
    if completed and task["completed_at"]: text += f"\n✅ <b>Tugallangan vaqt:</b> {h(task['completed_at'], 100)}"
    back_action = "my_completed" if completed else "my_tasks"
    buttons = []
    if task["status"] in {"assigned","in_progress","rework"}:
        buttons.append([InlineKeyboardButton(text="📤 Natija topshirish", callback_data=f"done:{task_id}")])
        buttons.append([InlineKeyboardButton(text="💬 Savol berish", callback_data=f"asktask:{task_id}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Ro‘yxat", callback_data=f"menu:{back_action}")])
    await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)); await call.answer()


@router.callback_query(F.data.startswith("asktask:"))
async def ask_task_question(call:CallbackQuery,state:FSMContext):
    tid=int(call.data.split(':')[1]);row=await db_one("SELECT 1 ok FROM task_users WHERE task_id=? AND user_id=?",(tid,call.from_user.id))
    if not row:return await call.answer("Vazifa sizga tegishli emas",show_alert=True)
    await state.set_state(TaskQuestionForm.question);await state.update_data(question_task_id=tid)
    await call.message.answer("Vazifa bo‘yicha savolingizni yozing. Bekor qilish: /cancel");await call.answer()


@router.message(TaskQuestionForm.question,F.text)
async def submit_task_question(message:Message,state:FSMContext,bot:Bot):
    data=await state.get_data();tid=data.get('question_task_id')
    task=await db_one("SELECT name,created_by FROM tasks WHERE id=?",(tid,))
    if not task:await state.clear();return await message.answer("Vazifa topilmadi.")
    question=message.text.strip()
    if pg_pool:
        row=await db_one("INSERT INTO task_questions(task_id,user_id,question) VALUES(?,?,?) RETURNING id",(tid,message.from_user.id,question))
    else:
        await db_execute("INSERT INTO task_questions(task_id,user_id,question) VALUES(?,?,?)",(tid,message.from_user.id,question))
        row=await db_one("SELECT id FROM task_questions WHERE task_id=? AND user_id=? ORDER BY id DESC LIMIT 1",(tid,message.from_user.id))
    qid=row['id'];kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💬 Javob berish",callback_data=f"answerq:{qid}")]])
    with suppress(TelegramForbiddenError,TelegramBadRequest):await bot.send_message(task['created_by'],f"<b>💬 Vazifa savoli</b>\n📌 #{tid} · {h(task['name'],150)}\n👤 {h(message.from_user.full_name,100)}\n\n{h(question,2500)}",reply_markup=kb)
    await audit(message.from_user.id,"task_question","task",tid,f"question:{qid}");await state.clear();await message.answer("✅ Savolingiz topshiriq muallifiga yuborildi.")


@router.callback_query(F.data.startswith("answerq:"))
async def answer_task_question_start(call:CallbackQuery,state:FSMContext):
    if not await is_actual_staff(call.from_user.id):return await call.answer("Ruxsat yo‘q",show_alert=True)
    qid=int(call.data.split(':')[1]);q=await db_one("SELECT answer FROM task_questions WHERE id=?",(qid,))
    if not q or q['answer']:return await call.answer("Savolga javob berilgan",show_alert=True)
    await state.set_state(TaskQuestionForm.answer);await state.update_data(answer_question_id=qid)
    await call.message.answer("Javobingizni yozing:");await call.answer()


@router.message(TaskQuestionForm.answer,F.text)
async def answer_task_question(message:Message,state:FSMContext,bot:Bot):
    qid=(await state.get_data()).get('answer_question_id');q=await db_one("SELECT task_id,user_id,question FROM task_questions WHERE id=?",(qid,))
    if not q:await state.clear();return await message.answer("Savol topilmadi.")
    now=datetime.now(timezone.utc).isoformat(timespec='seconds')
    await db_execute("UPDATE task_questions SET answer=?,answered_by=?,answered_at=? WHERE id=?",(message.text,message.from_user.id,now,qid))
    with suppress(TelegramForbiddenError,TelegramBadRequest):await bot.send_message(q['user_id'],f"<b>💬 Savolingizga javob</b>\n📌 Vazifa #{q['task_id']}\n\n<b>Savol:</b> {h(q['question'],1200)}\n\n<b>Javob:</b> {h(message.text,1800)}")
    await audit(message.from_user.id,"task_question_answered","task",q['task_id'],f"question:{qid}");await state.clear();await message.answer("✅ Javob userga yuborildi.")


async def tasks_keyboard(page=0):
    total = (await db_one("SELECT COUNT(*) c FROM tasks"))["c"]
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE); page = max(0, min(page, pages - 1))
    rows = await db_all("""SELECT t.id,t.name,COUNT(tu.user_id) total,COUNT(*) FILTER (WHERE tu.status IN ('approved','completed')) done
      FROM tasks t LEFT JOIN task_users tu ON tu.task_id=t.id GROUP BY t.id ORDER BY t.id DESC LIMIT ? OFFSET ?""",
      (PAGE_SIZE, page * PAGE_SIZE))
    b = InlineKeyboardBuilder()
    for task in rows:
        b.button(text=f"#{task['id']} · {task['name'][:35]} · {task['done'] or 0}/{task['total']}", callback_data=f"taskview:{task['id']}:{page}")
    b.button(text="⬅️ Admin panel", callback_data="menu:panel")
    if page: b.button(text="⬅️", callback_data=f"tasks:{page-1}")
    b.button(text=f"{page+1}/{pages}", callback_data="noop")
    if page + 1 < pages: b.button(text="➡️", callback_data=f"tasks:{page+1}")
    b.adjust(*([1] * len(rows)), 1, 3)
    return b.as_markup(), total


@router.message(F.text.in_(menu_texts("📋 Topshiriqlar")))
async def tasks_list(message: Message):
    if not await is_staff(message.from_user.id): return
    kb, total = await tasks_keyboard()
    await message.answer(f"<b>📋 Topshiriqlar tarixi</b> — jami {total}", reply_markup=kb)


@router.callback_query(F.data.startswith("tasks:"))
async def tasks_page(call: CallbackQuery):
    if not await is_staff(call.from_user.id): return await call.answer("Ruxsat yo‘q", show_alert=True)
    page = int(call.data.split(":")[1]); kb, total = await tasks_keyboard(page)
    await call.message.edit_text(f"<b>📋 Topshiriqlar tarixi</b> — jami {total}", reply_markup=kb); await call.answer()


@router.callback_query(F.data.startswith("taskview:"))
async def task_detail(call: CallbackQuery):
    if not await is_staff(call.from_user.id): return await call.answer("Ruxsat yo‘q", show_alert=True)
    _, raw_id, page = call.data.split(":"); task_id = int(raw_id)
    task = await db_one("""SELECT t.*,g.title group_title,u.full_name creator FROM tasks t
      LEFT JOIN groups g ON g.chat_id=t.group_id LEFT JOIN users u ON u.tg_id=t.created_by WHERE t.id=?""", (task_id,))
    if not task: return await call.answer("Topshiriq topilmadi", show_alert=True)
    members = await db_all("""SELECT u.full_name,u.username,tu.status,tu.completed_at FROM task_users tu
      JOIN users u ON u.tg_id=tu.user_id WHERE tu.task_id=? ORDER BY tu.status,u.full_name""", (task_id,))
    people = "\n".join(f"{TASK_STATUS_LABELS.get(x['status'],'⏳')} {h(x['full_name'],60)}" for x in members[:20])
    if len(members) > 20: people += f"\n… va yana {len(members)-20} ta ijrochi"
    text = (f"<b>📌 #{task_id} · {h(task['name'],200)}</b>\n\n{h(task['description'],1800)}\n\n"
            f"⏰ {h(task['deadline'],200)}\n📂 {h(task['group_title'] or str(task['group_id']),200)}\n"
            f"👤 Yaratdi: {h(task['creator'] or str(task['created_by']),200)}\n\n<b>Ijrochilar:</b>\n{people}")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔔 Eslatma yuborish", callback_data=f"remind:{task_id}:{page}")],
        [InlineKeyboardButton(text="🧾 Shablon sifatida saqlash", callback_data=f"tasksave:{task_id}")],
        [InlineKeyboardButton(text="⬅️ Ro‘yxat", callback_data=f"tasks:{page}")],
    ])
    await call.message.edit_text(text, reply_markup=kb); await call.answer()


@router.callback_query(F.data.startswith("tasksave:"))
async def save_existing_task_template(call:CallbackQuery):
    if not await is_staff(call.from_user.id):return await call.answer("Ruxsat yo‘q",show_alert=True)
    tid=int(call.data.split(':')[1]);task=await db_one("SELECT name,description FROM tasks WHERE id=?",(tid,))
    if not task:return await call.answer("Topshiriq topilmadi",show_alert=True)
    await db_execute("INSERT INTO task_templates(name,description,created_by) VALUES(?,?,?)",(task['name'],task['description'],call.from_user.id));await audit(call.from_user.id,"template_created_from_task","task",tid);await call.answer("Shablon saqlandi",show_alert=True)


@router.callback_query(F.data=="submissions:show")
async def submissions_list(call:CallbackQuery):
    if not await is_staff(call.from_user.id):return await call.answer("Ruxsat yo‘q",show_alert=True)
    rows=await db_all("""SELECT t.id,t.name,u.tg_id,u.full_name FROM task_users tu JOIN tasks t ON t.id=tu.task_id JOIN users u ON u.tg_id=tu.user_id WHERE tu.status='submitted' ORDER BY tu.submitted_at DESC LIMIT 40""")
    b=InlineKeyboardBuilder()
    for x in rows:b.button(text=f"👀 #{x['id']} · {x['full_name'][:25]}",callback_data=f"submission:{x['id']}:{x['tg_id']}")
    b.button(text="⬅️ Panel",callback_data="menu:panel");b.adjust(1)
    await call.message.edit_text(f"<b>👀 Tekshiruvdagi natijalar</b> — {len(rows)} ta",reply_markup=b.as_markup());await call.answer()


@router.callback_query(F.data.startswith("submission:"))
async def submission_detail(call:CallbackQuery,bot:Bot):
    if not await is_staff(call.from_user.id):return await call.answer("Ruxsat yo‘q",show_alert=True)
    _,raw_tid,raw_uid=call.data.split(':');tid=int(raw_tid);uid=int(raw_uid)
    row=await db_one("""SELECT t.name,u.full_name,tu.result_text,tu.result_file_id,tu.result_file_name FROM task_users tu JOIN tasks t ON t.id=tu.task_id JOIN users u ON u.tg_id=tu.user_id WHERE tu.task_id=? AND tu.user_id=? AND tu.status='submitted'""",(tid,uid))
    if not row:return await call.answer("Natija topilmadi",show_alert=True)
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Tasdiqlash",callback_data=f"result:approve:{tid}:{uid}"),InlineKeyboardButton(text="🔁 Qayta ishlash",callback_data=f"result:rework:{tid}:{uid}")],[InlineKeyboardButton(text="⬅️ Natijalar",callback_data="submissions:show")]])
    await call.message.edit_text(f"<b>👀 #{tid} · {h(row['name'],160)}</b>\n👤 {h(row['full_name'],100)}\n\n🗒 {h(row['result_text'] or row['result_file_name'] or 'Fayl',2200)}",reply_markup=kb)
    if row['result_file_id']:
        with suppress(TelegramBadRequest,TelegramForbiddenError):await bot.send_document(call.message.chat.id,row['result_file_id'],caption=f"📎 {h(row['result_file_name'] or 'Natija',150)}")
    await call.answer()


@router.callback_query(F.data.startswith("remind:"))
async def remind_task_users(call: CallbackQuery, bot: Bot):
    if not await is_staff(call.from_user.id):
        return await call.answer("Ruxsat yo‘q", show_alert=True)
    _, raw_id, page = call.data.split(":")
    task_id = int(raw_id)
    task = await db_one("SELECT id,name,description,deadline,group_id FROM tasks WHERE id=?", (task_id,))
    if not task:
        return await call.answer("Topshiriq topilmadi", show_alert=True)
    users = await db_all("""SELECT u.tg_id,u.username,u.full_name FROM task_users tu
      JOIN users u ON u.tg_id=tu.user_id
      WHERE tu.task_id=? AND tu.status NOT IN ('approved','completed') ORDER BY u.full_name""", (task_id,))
    if not users:
        return await call.answer("Barcha ijrochilar topshiriqni bajargan", show_alert=True)

    mention_parts = []
    mention_length = 0
    for user in users:
        mention = user_mention(user, 60)
        if mention_length + len(mention) + 1 > 1750:
            mention_parts.append("…")
            break
        mention_parts.append(mention)
        mention_length += len(mention) + 1
    mentions = " ".join(mention_parts)
    reminder_intro=render_template("task_reminder",task_name=task['name'],deadline=task['deadline'],remaining="—")
    group_text = (f"{message_emoji('reminder')} <b>TOPSHIRIQ BO‘YICHA ESLATMA</b>\n<i>{reminder_intro}</i>\n\n"
                  f"{message_emoji('task')} {h(task['name'], 200)}\n{message_emoji('deadline')} Muddat: {h(task['deadline'], 200)}\n\n"
                  f"{mentions}\n\n{message_emoji('warning')} Ushbu topshiriqni belgilangan muddatda bajarishingiz talab qilinadi.")
    failures = []
    try:
        await bot.send_message(task["group_id"], group_text)
    except (TelegramForbiddenError, TelegramBadRequest):
        failures.append(task["group_id"])

    private_text = (f"{message_emoji('reminder')} <b>Topshiriq bo‘yicha eslatma</b>\n\n"
                    f"{message_emoji('task')} {h(task['name'], 200)}\n{h(task['description'], 2200)}\n\n"
                    f"{message_emoji('deadline')} <b>Muddat:</b> {h(task['deadline'], 200)}\n\n"
                    f"{message_emoji('warning')} Topshiriqni belgilangan muddatda bajarishingiz talab qilinadi.")
    done_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="▶️ Boshladim",callback_data=f"begin:{task_id}"),InlineKeyboardButton(text="📤 Natija topshirish", callback_data=f"done:{task_id}")]])
    delivered = 0
    for user in users:
        try:
            await bot.send_message(user["tg_id"], private_text, reply_markup=done_kb)
            delivered += 1
        except (TelegramForbiddenError, TelegramBadRequest):
            failures.append(user["tg_id"])

    result = f"🔔 Eslatma yuborildi.\n👥 Hali bajarmaganlar: {len(users)}\n📨 Shaxsiy xabar yetib bordi: {delivered}"
    if failures:
        result += f"\n⚠️ Yetib bormagan chatlar: {len(failures)}"
    await call.answer("Eslatma yuborildi", show_alert=True)
    await call.message.answer(result)


@router.message(Command("set_manager"))
async def set_manager(message: Message):
    if await effective_role(message.from_user.id) not in {"admin","superadmin"}: return
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit(): return await message.answer("Format: /set_manager TELEGRAM_ID")
    uid = int(parts[1])
    target = await db_one("SELECT role FROM users WHERE tg_id=?", (uid,))
    if target and target["role"] in {"admin","superadmin"}: return await message.answer("Admin yoki superadminni manager qilib bo‘lmaydi.")
    await db_execute("UPDATE users SET role='manager',status='accepted' WHERE tg_id=?", (uid,))
    await message.answer("✅ Manager tayinlandi.")


@router.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def capture_group_user(message: Message):
    """Keep Telegram names current when a person is active in a registered group."""
    if message.from_user and not message.from_user.is_bot:
        await ensure_user(message.from_user)


@router.message(Command("status"))
async def bot_status(message:Message):
    if not await is_actual_staff(message.from_user.id):return
    db_started=datetime.now(timezone.utc)
    db_ok=await db_one("SELECT 1 ok")
    latency=int((datetime.now(timezone.utc)-db_started).total_seconds()*1000)
    counts=await db_one("SELECT COUNT(*) users,COUNT(*) FILTER (WHERE status='pending') pending FROM users")
    uptime=datetime.now(timezone.utc)-STARTED_AT
    await message.answer(f"<b>🟢 Optima Team Bot V1 ishlayapti</b>\n\n🗄 Supabase: {'OK' if db_ok else 'Xato'} ({latency} ms)\n👥 Userlar: {counts['users']}\n⏳ Arizalar: {counts['pending']}\n⏱ Uptime: {str(uptime).split('.')[0]}\n🚀 Reliz: V1")


@router.errors()
async def notify_superadmins_about_error(event:ErrorEvent,bot:Bot):
    logging.exception("Unhandled bot error",exc_info=event.exception)
    update_id=getattr(event.update,"update_id","—")
    text=f"<b>🚨 V1 texnik xato</b>\nUpdate: <code>{h(update_id,30)}</code>\nXato: <code>{h(type(event.exception).__name__,100)}</code>\n{h(str(event.exception),1200)}"
    for uid in SUPERADMINS:
        with suppress(TelegramForbiddenError,TelegramBadRequest):await bot.send_message(uid,text)
    return True


async def automatic_reminders(bot:Bot):
    while True:
        try:
            rows=await db_all("""SELECT t.id,t.name,t.deadline,t.deadline_at,t.group_id,tu.user_id,tu.status,
              tu.reminded_24,tu.reminded_3,tu.reminded_1,u.full_name,u.username,u.tg_id
              FROM task_users tu JOIN tasks t ON t.id=tu.task_id JOIN users u ON u.tg_id=tu.user_id
              WHERE t.deadline_at IS NOT NULL AND tu.status NOT IN ('approved','completed','submitted')""")
            now=datetime.now(timezone.utc)
            for row in rows:
                hours=(utc_datetime(row['deadline_at'])-now).total_seconds()/3600
                flag=None;label=None
                if hours<=1 and not row['reminded_1']:flag='reminded_1';label="1 soatdan kam"
                elif hours<=3 and not row['reminded_3']:flag='reminded_3';label="3 soatdan kam"
                elif hours<=24 and not row['reminded_24']:flag='reminded_24';label="24 soatdan kam"
                if not flag:continue
                intro=render_template("task_reminder",task_name=row['name'],deadline=row['deadline'],remaining=label)
                text=(f"{message_emoji('reminder')} <b>Avtomatik eslatma</b>\n<i>{intro}</i>\n"
                      f"{message_emoji('task')} {h(row['name'],180)}\n"
                      f"{message_emoji('deadline')} {h(row['deadline'],100)}\n"
                      f"{message_emoji('warning')} Qolgan vaqt: {label}")
                with suppress(TelegramBadRequest,TelegramForbiddenError):await bot.send_message(row['user_id'],text,reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📤 Natija topshirish",callback_data=f"done:{row['id']}")]]))
                if row['group_id']:
                    with suppress(TelegramBadRequest,TelegramForbiddenError):await bot.send_message(row['group_id'],text+f"\n👤 {user_mention(row,80)}")
                await db_execute(f"UPDATE task_users SET {flag}=TRUE WHERE task_id=? AND user_id=?",(row['id'],row['user_id']))
        except Exception:logging.exception("Automatic reminder failed")
        await asyncio.sleep(300)


async def main():
    global APP_READY
    if not TOKEN: raise RuntimeError("BOT_TOKEN .env faylida ko‘rsatilmagan")
    if os.getenv("REQUIRE_DATABASE", "").lower() in {"1","true","yes"} and not DATABASE_URL:
        raise RuntimeError("Production rejimida DATABASE_URL majburiy")
    logging.basicConfig(level=logging.INFO)
    await init_db()
    bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage()); dp.include_router(router)
    await bot.set_my_commands([BotCommand(command="start", description="Botni boshlash"), BotCommand(command="panel", description="Admin panel"), BotCommand(command="status", description="V1 ishlash holati"), BotCommand(command="cancel", description="Joriy amalni bekor qilish"), BotCommand(command="register_group", description="Joriy guruhni ro‘yxatdan o‘tkazish"), BotCommand(command="add_group", description="Guruh ID orqali qo‘shish"), BotCommand(command="add_admin", description="ID orqali admin tayinlash"), BotCommand(command="remove_admin", description="ID orqali adminni olib tashlash")])
    runner = web.AppRunner(create_health_app())
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(os.getenv("PORT", "10000"))).start()
    await bot.delete_webhook(drop_pending_updates=False)
    APP_READY = True
    reminder_task=asyncio.create_task(automatic_reminders(bot))
    try:
        await dp.start_polling(bot)
    finally:
        reminder_task.cancel()
        with suppress(asyncio.CancelledError):await reminder_task
        APP_READY = False
        await runner.cleanup()
        if pg_pool: await pg_pool.close()


if __name__ == "__main__": asyncio.run(main())
