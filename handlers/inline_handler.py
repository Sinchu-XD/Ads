from aiogram import Router, F
from aiogram.types import (
    InlineQuery, InlineQueryResultArticle, InputTextMessageContent,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from database.db import SessionLocal, UserSettings, BroadcastTemplate
from sqlalchemy import select
from utils.logger import logger
import json

router = Router()


@router.inline_query()
async def handle_inline_query(inline_query: InlineQuery):
    """Returns the user's saved broadcast template as an inline result."""

    query_text = inline_query.query.strip()

    # Extract user_id from query string (sent by background_broadcaster)
    # or fall back to the person typing inline
    if query_text.startswith("broadcast_"):
        try:
            user_id = int(query_text.replace("broadcast_", ""))
        except ValueError:
            user_id = inline_query.from_user.id
    else:
        user_id = inline_query.from_user.id

    async with SessionLocal() as db:
        try:
            settings_res = await db.execute(
                select(UserSettings).filter(UserSettings.telegram_user_id == user_id)
            )
            settings = settings_res.scalars().first()

            # FIX: Only block inline results when settings row EXISTS and is_broadcasting is
            # explicitly False. If settings is None (unlikely during background broadcast
            # because background_broadcaster already verified is_broadcasting=True), allow
            # through so we don't silently drop messages.
            if settings is not None and not settings.is_broadcasting:
                await inline_query.answer(
                    results=[],
                    switch_pm_text="🔴 Broadcasting is OFF. Tap to enable it.",
                    switch_pm_parameter="setup_broadcast",
                    cache_time=0
                )
                return

            res = await db.execute(
                select(BroadcastTemplate).filter(BroadcastTemplate.telegram_user_id == user_id)
            )
            template = res.scalars().first()

            if not template or not template.message_text:
                await inline_query.answer(
                    results=[],
                    switch_pm_text="⚠️ No broadcast message set! Tap to set one.",
                    switch_pm_parameter="setup_broadcast",
                    cache_time=0
                )
                return

            # Build inline keyboard from saved buttons JSON
            keyboard = None
            if template.buttons_json:
                try:
                    buttons_data = json.loads(template.buttons_json)
                    rows = [
                        [InlineKeyboardButton(text=btn["text"], url=btn["url"])]
                        for btn in buttons_data
                        if btn.get("text") and btn.get("url")
                    ]
                    if rows:
                        keyboard = InlineKeyboardMarkup(inline_keyboard=rows)
                except Exception as e:
                    logger.warning(f"[inline] Failed to parse buttons for user {user_id}: {e}")

            # Safe preview — strip HTML tags for description
            description = template.message_text[:120].replace("<", "").replace(">", "")

            result = InlineQueryResultArticle(
                id="broadcast_1",
                title="📢 Send Broadcast Message",
                description=description,
                input_message_content=InputTextMessageContent(
                    message_text=template.message_text,
                    parse_mode="HTML"
                ),
                reply_markup=keyboard
            )

            await inline_query.answer(
                results=[result],
                cache_time=0
            )

        except Exception as e:
            logger.error(f"[inline] Query error for user {user_id}: {e}")
            await inline_query.answer(results=[], cache_time=0)
