from aiogram import Bot
from utils.logger import logger
import html

LOGS_CHANNEL_ID = -1003795731089


async def log_new_user(bot: Bot, user_id: int, username: str | None, full_name: str):
    """Sends a new user notification to the logs channel."""
    username_text = f"@{username}" if username else "No username"
    safe_name = html.escape(full_name)  # ✅ Escape special chars in name

    message = (
        f"👤 #new_user\n\n"
        f"🆔 User ID: <code>{user_id}</code>\n"
        f"📛 Name: {safe_name}\n"
        f"🔗 Username: {username_text}\n"
        f"🤖 Profile: <a href='tg://user?id={user_id}'>Open Profile</a>"
    )

    try:
        await bot.send_message(
            chat_id=LOGS_CHANNEL_ID,
            text=message,
            parse_mode="HTML"
        )
        logger.info(f"[starter] Logged new user {user_id}")
    except Exception as e:
        logger.warning(f"[starter] Failed to send log for user {user_id}: {e}")
