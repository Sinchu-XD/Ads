from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command, CommandObject
from database.db import SessionLocal, UserSettings
from sqlalchemy import select

router = Router()

ADMIN_ID = 6444277321

@router.message(Command("grantpremium"))
async def grant_premium_access(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        return

    if not command.args:
        await message.answer(
            "⚠️ <b>Format:</b> <code>/grantpremium user_id</code>\n"
            "Example: <code>/grantpremium 6444277321</code>",
            parse_mode="HTML"
        )
        return

    try:
        target_id = int(command.args.strip())
    except ValueError:
        await message.answer("❌ Invalid User ID. Must be numbers only.")
        return

    async with SessionLocal() as db:
        try:
            res = await db.execute(
                select(UserSettings).filter(
                    UserSettings.telegram_user_id == target_id
                )
            )
            settings = res.scalars().first()

            if not settings:
                settings = UserSettings(
                    telegram_user_id=target_id,
                    is_premium=True
                )
                db.add(settings)
            else:
                settings.is_premium = True

            await db.commit()
            await db.refresh(settings)  # ✅ Refresh to confirm saved state

            # ✅ Verify it actually saved
            if settings.is_premium:
                await message.answer(
                    f"✅ <b>Grand Pass Activated!</b>\n\n"
                    f"User <code>{target_id}</code> now has premium access.\n"
                    f"Status confirmed: <b>is_premium = True</b> ✅",
                    parse_mode="HTML"
                )
            else:
                await message.answer(
                    f"⚠️ Something went wrong. is_premium did not save correctly.",
                    parse_mode="HTML"
                )

        except Exception as e:
            await db.rollback()  # ✅ Rollback on error
            await message.answer(
                f"❌ Database error:\n<code>{str(e)}</code>",
                parse_mode="HTML"
            )
