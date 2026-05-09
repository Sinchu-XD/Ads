from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from utils.logger import logger
import asyncpg
from config import NEON_DB_URL

router = Router()

ADMIN_IDS = [6444277321]


def get_raw_db_url(url: str) -> str:
    """Convert SQLAlchemy URL to plain asyncpg URL."""
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    url = url.replace("postgres+asyncpg://", "postgresql://")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


FIX_QUERIES = [
    "ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS is_premium BOOLEAN DEFAULT FALSE;",
    "ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS is_broadcasting BOOLEAN DEFAULT FALSE;",
    "ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS trial_started_at TIMESTAMP WITH TIME ZONE DEFAULT NULL;",
    "ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS premium_granted_at TIMESTAMP WITH TIME ZONE DEFAULT NULL;",
    "ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS dm_broadcast_enabled BOOLEAN DEFAULT FALSE;",  # ✅ ADD THIS

    "ALTER TABLE user_accounts ADD COLUMN IF NOT EXISTS account_username TEXT DEFAULT NULL;",
    "ALTER TABLE user_accounts ADD COLUMN IF NOT EXISTS first_name TEXT DEFAULT NULL;",
]


def extract_col(query: str) -> str:
    try:
        return query.strip().split("ADD COLUMN IF NOT EXISTS")[1].strip().split()[0]
    except Exception:
        return "unknown"


@router.message(Command("fixdb"))
async def cmd_fixdb(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Not authorized.")
        return

    await message.answer("🔧 Running DB fix... please wait.")

    conn = None
    try:
        raw_url = get_raw_db_url(NEON_DB_URL)  # ✅ Fix URL before connecting
        conn = await asyncpg.connect(raw_url)
        results = []

        for query in FIX_QUERIES:
            col = extract_col(query)
            try:
                await conn.execute(query)
                results.append(f"✅ <code>{col}</code> — OK")
            except Exception as e:
                results.append(f"❌ <code>{col}</code> — {e}")

        await message.answer(
            "🛠 <b>DB Fix Complete!</b>\n\n" + "\n".join(results),
            parse_mode="HTML"
        )
        logger.info(f"[fixdb] Ran by {message.from_user.id}")

    except Exception as e:
        logger.error(f"[fixdb] Connection failed: {e}")
        await message.answer(
            f"❌ <b>Connection failed:</b>\n<code>{e}</code>",
            parse_mode="HTML"
        )
    finally:
        if conn:
            await conn.close()


@router.message(Command("checkdb"))
async def cmd_checkdb(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Not authorized.")
        return

    conn = None
    try:
        raw_url = get_raw_db_url(NEON_DB_URL)
        conn = await asyncpg.connect(raw_url)

        text = "🔍 <b>DB Column Check:</b>\n\n"
        for table in ["user_settings", "user_accounts"]:
            rows = await conn.fetch(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = $1 ORDER BY ordinal_position;",
                table
            )
            text += f"<b>📋 {table}:</b>\n"
            for row in rows:
                text += f"  • <code>{row['column_name']}</code> — {row['data_type']}\n"
            text += "\n"

        await message.answer(text, parse_mode="HTML")

    except Exception as e:
        await message.answer(f"❌ <b>Error:</b> <code>{e}</code>", parse_mode="HTML")
    finally:
        if conn:
            await conn.close()
