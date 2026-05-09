import asyncio
import json
from datetime import datetime, timedelta, timezone
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from sqlalchemy import select
from pyrogram.enums import ChatType
from pyrogram.errors import (
    FloodWait, ChatWriteForbidden, UserBannedInChannel,
    ChatAdminRequired, ChannelPrivate, PeerIdInvalid,
)
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import BOT_TOKEN
from utils.logger import logger
from handlers.premium import router as premium_router
from handlers.db_fix import router as db_fix_router
from database.db import init_db, SessionLocal, UserSettings, UserAccount, BroadcastTemplate
from userbot.client_manager import client_manager
from handlers.start import router as start_router
from handlers.accounts import router as accounts_router
from handlers.broadcast import router as broadcast_router
from handlers.grand_pass import router as grand_pass_router
from handlers.inline_handler import router as inline_router

SKIP_ERRORS = (ChatWriteForbidden, UserBannedInChannel, ChatAdminRequired, ChannelPrivate, PeerIdInvalid)

def build_pyrogram_keyboard(buttons_json):
    if not buttons_json:
        return None
    try:
        buttons_data = json.loads(buttons_json)
        rows = [
            [InlineKeyboardButton(text=btn["text"], url=btn["url"])]
            for btn in buttons_data if btn.get("text") and btn.get("url")
        ]
        return InlineKeyboardMarkup(rows) if rows else None
    except Exception as e:
        logger.warning(f"[broadcaster] Failed to parse buttons JSON: {e}")
        return None

async def try_send_to_group(client, group, message_text, keyboard):
    try:
        await client.send_message(chat_id=group.id, text=message_text, reply_markup=keyboard)
        return True
    except FloodWait:
        raise
    except SKIP_ERRORS as e:
        logger.warning(f"[broadcaster] Skipping '{group.title}' — {type(e).__name__}: {e}")
        return False
    except Exception as e:
        logger.error(f"[broadcaster] Error sending to '{group.title}': {e}")
        return False

async def send_broadcast_for_user(bot, user):
    async with SessionLocal() as db:
        try:
            res = await db.execute(select(UserSettings).filter(UserSettings.telegram_user_id == user.telegram_user_id))
            fresh_user = res.scalars().first()
            if not fresh_user or not fresh_user.is_broadcasting:
                return

            now = datetime.now(timezone.utc)

            if not fresh_user.is_premium and fresh_user.trial_started_at:
                if now > fresh_user.trial_started_at + timedelta(hours=9):
                    fresh_user.is_broadcasting = False
                    await db.commit()
                    try:
                        await bot.send_message(
                            chat_id=fresh_user.telegram_user_id,
                            text="⏳ <b>Your 9-Hour Free Trial has Ended!</b>\n\nYour broadcasts have been paused.\n👑 Tap <b>Grand Pass</b> in the menu to continue 24/7!",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass
                    return

            acc_res = await db.execute(select(UserAccount).filter(UserAccount.telegram_user_id == fresh_user.telegram_user_id))
            accounts = acc_res.scalars().all()
            if not accounts:
                return

            tmpl_res = await db.execute(select(BroadcastTemplate).filter(BroadcastTemplate.telegram_user_id == fresh_user.telegram_user_id))
            template = tmpl_res.scalars().first()
            if not template or not template.message_text:
                return

            client = None
            for account in accounts:
                try:
                    client = await client_manager.get_client(account.id, db)
                    break
                except Exception as e:
                    logger.warning(f"[broadcaster] Account {account.id} unavailable: {e}")

            if client is None:
                logger.error(f"[broadcaster] No working account for user {fresh_user.telegram_user_id}")
                return

            groups = []
            try:
                async for dialog in client.get_dialogs():
                    if dialog.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
                        groups.append(dialog.chat)
            except Exception as e:
                logger.error(f"[broadcaster] get_dialogs failed: {e}")
                return

            if not groups:
                return

            index = fresh_user.last_target_index
            if index >= len(groups):
                index = 0

            target_group = groups[index]
            keyboard = build_pyrogram_keyboard(template.buttons_json)

            try:
                sent = await try_send_to_group(client, target_group, template.message_text, keyboard)
                if sent:
                    logger.info(f"✅ Sent to '{target_group.title}' for user {fresh_user.telegram_user_id}")
                fresh_user.last_target_index = index + 1
                await db.commit()
            except FloodWait as e:
                logger.warning(f"[broadcaster] FloodWait {e.value}s for user {fresh_user.telegram_user_id}")
                await asyncio.sleep(e.value + 2)

            if fresh_user.dm_broadcast_enabled:
                try:
                    dm_contacts = []
                    async for dialog in client.get_dialogs():
                        if dialog.chat.type == ChatType.PRIVATE and not dialog.chat.is_self:
                            dm_contacts.append(dialog.chat)
                        if len(dm_contacts) >= 10:
                            break
                    for contact in dm_contacts:
                        try:
                            await client.send_message(chat_id=contact.id, text=template.message_text, reply_markup=keyboard)
                            await asyncio.sleep(2)
                        except FloodWait as e:
                            await asyncio.sleep(e.value + 2)
                        except Exception as dm_err:
                            logger.warning(f"[broadcaster] DM to {contact.id} failed: {dm_err}")
                except Exception as e:
                    logger.warning(f"[broadcaster] DM broadcast error: {e}")

        except Exception as e:
            logger.error(f"[broadcaster] Error for user {user.telegram_user_id}: {e}")

async def background_broadcaster(bot):
    while True:
        try:
            async with SessionLocal() as db:
                result = await db.execute(select(UserSettings).filter(UserSettings.is_broadcasting == True))
                active_users = result.scalars().all()
            for user in active_users:
                await send_broadcast_for_user(bot, user)
                await asyncio.sleep(3)
        except Exception as e:
            logger.error(f"[broadcaster] Worker error: {e}")
        await asyncio.sleep(300)

async def main():
    await init_db()
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(start_router)
    dp.include_router(accounts_router)
    dp.include_router(broadcast_router)
    dp.include_router(grand_pass_router)
    dp.include_router(inline_router)
    dp.include_router(db_fix_router)
    dp.include_router(premium_router)
    asyncio.create_task(background_broadcaster(bot))
    logger.info("🚀 Ad Broadcast Bot started...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
