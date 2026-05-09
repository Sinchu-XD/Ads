import asyncio
import json
from datetime import datetime, timedelta, timezone
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from sqlalchemy import select
from pyrogram.enums import ChatType
from pyrogram.errors import (
    FloodWait,
    ChatWriteForbidden,
    UserBannedInChannel,
    ChatAdminRequired,
    ChannelPrivate,
    PeerIdInvalid,
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


# Errors that mean we should permanently skip this group (user can't post there)
SKIP_ERRORS = (
    ChatWriteForbidden,
    UserBannedInChannel,
    ChatAdminRequired,
    ChannelPrivate,
    PeerIdInvalid,
)


def build_pyrogram_keyboard(buttons_json: str | None) -> InlineKeyboardMarkup | None:
    """Build a Pyrogram InlineKeyboardMarkup from the stored JSON buttons."""
    if not buttons_json:
        return None
    try:
        buttons_data = json.loads(buttons_json)
        rows = [
            [InlineKeyboardButton(text=btn["text"], url=btn["url"])]
            for btn in buttons_data
            if btn.get("text") and btn.get("url")
        ]
        return InlineKeyboardMarkup(rows) if rows else None
    except Exception as e:
        logger.warning(f"[broadcaster] Failed to parse buttons JSON: {e}")
        return None


async def try_send_to_group(client, group, message_text: str, keyboard) -> bool:
    """
    Attempt to send a message to a single group.
    Returns True if sent successfully, False if the group should be skipped,
    and re-raises FloodWait so the caller can handle it.
    """
    try:
        await client.send_message(
            chat_id=group.id,
            text=message_text,
            reply_markup=keyboard,
        )
        return True

    except FloodWait:
        raise  # Let caller handle FloodWait

    except SKIP_ERRORS as e:
        logger.warning(
            f"[broadcaster] Skipping group '{group.title}' ({group.id}) — "
            f"{type(e).__name__}: {e}"
        )
        return False  # Skip this group, advance index anyway

    except Exception as e:
        logger.error(
            f"[broadcaster] Unexpected error sending to '{group.title}' ({group.id}): {e}"
        )
        return False


async def send_broadcast_for_user(bot: Bot, user: UserSettings):
    """
    Handles one broadcast cycle for a single user.
    - Uses a fresh DB session to avoid cross-user session contamination.
    - Tries all linked accounts, not just the first.
    - Sends directly with buttons built from stored JSON (no inline query).
    - Skips groups where the user is banned or has no write permission.
    """
    async with SessionLocal() as db:
        try:
            # Re-fetch settings fresh to avoid stale cached state
            res = await db.execute(
                select(UserSettings).filter(
                    UserSettings.telegram_user_id == user.telegram_user_id
                )
            )
            fresh_user = res.scalars().first()
            if not fresh_user or not fresh_user.is_broadcasting:
                return

            now = datetime.now(timezone.utc)

            # 9-HOUR TRIAL CHECK
            if not fresh_user.is_premium and fresh_user.trial_started_at:
                if now > fresh_user.trial_started_at + timedelta(hours=9):
                    fresh_user.is_broadcasting = False
                    await db.commit()
                    try:
                        await bot.send_message(
                            chat_id=fresh_user.telegram_user_id,
                            text=(
                                "⏳ <b>Your 9-Hour Free Trial has Ended!</b>\n\n"
                                "Your broadcasts have been paused.\n"
                                "👑 Tap <b>Grand Pass</b> in the menu to continue 24/7!"
                            ),
                            parse_mode="HTML",
                        )
                    except Exception:
                        pass
                    return

            # Fetch ALL accounts for this user, not just the first
            acc_res = await db.execute(
                select(UserAccount).filter(
                    UserAccount.telegram_user_id == fresh_user.telegram_user_id
                )
            )
            accounts = acc_res.scalars().all()
            if not accounts:
                return

            # Fetch broadcast template
            tmpl_res = await db.execute(
                select(BroadcastTemplate).filter(
                    BroadcastTemplate.telegram_user_id == fresh_user.telegram_user_id
                )
            )
            template = tmpl_res.scalars().first()
            if not template or not template.message_text:
                return

            # Try each account until one connects successfully
            client = None
            for account in accounts:
                try:
                    client = await client_manager.get_client(account.id, db)
                    break
                except Exception as e:
                    logger.warning(
                        f"[broadcaster] Account {account.id} unavailable for user "
                        f"{fresh_user.telegram_user_id}: {e}"
                    )

            if client is None:
                logger.error(
                    f"[broadcaster] No working account for user {fresh_user.telegram_user_id}"
                )
                return

            # Fetch the user's groups
            groups = []
            try:
                async for dialog in client.get_dialogs():
                    if dialog.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
                        groups.append(dialog.chat)
            except Exception as e:
                logger.error(
                    f"[broadcaster] get_dialogs failed for user "
                    f"{fresh_user.telegram_user_id}: {e}"
                )
                return

            if not groups:
                logger.info(
                    f"[broadcaster] No groups found for user {fresh_user.telegram_user_id}"
                )
                return

            # Cycle through groups starting at last saved index
            index = fresh_user.last_target_index
            if index >= len(groups):
                index = 0

            target_group = groups[index]

            # Build keyboard once from stored JSON — no inline query needed
            keyboard = build_pyrogram_keyboard(template.buttons_json)

            # Send directly to the group
            try:
                sent = await try_send_to_group(
                    client, target_group, template.message_text, keyboard
                )
                if sent:
                    logger.info(
                        f"✅ Sent to '{target_group.title}' "
                        f"for user {fresh_user.telegram_user_id}"
                    )
                # Whether sent or skipped (banned/forbidden), advance to next group
                fresh_user.last_target_index = index + 1
                await db.commit()

            except FloodWait as e:
                logger.warning(
                    f"[broadcaster] FloodWait {e.value}s for user "
                    f"{fresh_user.telegram_user_id} on '{target_group.title}'"
                )
                await asyncio.sleep(e.value + 2)
                # Do NOT advance index — retry same group next cycle

            # DM BROADCAST — if user has it enabled
            if fresh_user.dm_broadcast_enabled:
                try:
                    dm_contacts = []
                    async for dialog in client.get_dialogs():
                        if (
                            dialog.chat.type == ChatType.PRIVATE
                            and not dialog.chat.is_self
                        ):
                            dm_contacts.append(dialog.chat)
                        if len(dm_contacts) >= 10:
                            break

                    for contact in dm_contacts:
                        try:
                            await client.send_message(
                                chat_id=contact.id,
                                text=template.message_text,
                                reply_markup=keyboard,
                            )
                            await asyncio.sleep(2)
                        except FloodWait as e:
                            await asyncio.sleep(e.value + 2)
                        except Exception as dm_err:
                            logger.warning(
                                f"[broadcaster] DM to {contact.id} failed: {dm_err}"
                            )

                    logger.info(
                        f"✅ DM broadcast done for user {fresh_user.telegram_user_id}"
                    )
                except Exception as e:
                    logger.warning(
                        f"[broadcaster] DM broadcast error for "
                        f"{fresh_user.telegram_user_id}: {e}"
                    )

        except Exception as e:
            logger.error(
                f"[broadcaster] Error processing user {user.telegram_user_id}: {e}"
            )


async def background_broadcaster(bot: Bot):
    """Background worker: sends broadcast via userbot every 5 minutes."""
    while True:
        try:
            async with SessionLocal() as db:
                result = await db.execute(
                    select(UserSettings).filter(UserSettings.is_broadcasting == True)
                )
                active_users = result.scalars().all()

            for user in active_users:
                await send_broadcast_for_user(bot, user)
                await asyncio.sleep(3)  # Brief pause between users

        except Exception as e:
            logger.error(f"[broadcaster] Background worker error: {e}")

        await asyncio.sleep(300)


async def main():
    await init_db()

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
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
