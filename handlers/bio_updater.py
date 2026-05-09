"""
from pyrogram import Client
from pyrogram.errors import FloodWait
from config import AUTO_BIO_TEMPLATE, BOT_USERNAME
from utils.logger import logger
import asyncio

AD_NAME_SUFFIX = f"via {BOT_USERNAME}"
MAX_RETRIES = 3


async def set_ad_bio(client: Client, telegram_user_id: int, _retry: int = 0):
   """ """Updates the Telegram account's bio and name to the promotional template."""
"""
    if _retry >= MAX_RETRIES:
        logger.error(f"❌ Max retries reached for set_ad_bio on account {telegram_user_id}")
        return

    try:
        me = await client.get_me()
        # ✅ get_me() is faster & more reliable than get_chat("me") for profile info
        current_first_name = me.first_name or ""

        # ✅ Fetch bio separately — get_me() doesn't return bio
        chat = await client.get_chat("me")
        current_bio = chat.bio or ""

        needs_bio_update = current_bio != AUTO_BIO_TEMPLATE
        needs_name_update = AD_NAME_SUFFIX not in current_first_name

        if needs_bio_update or needs_name_update:
            base_name = current_first_name.replace(f" {AD_NAME_SUFFIX}", "").strip()
            new_name = f"{base_name} {AD_NAME_SUFFIX}" if base_name else AD_NAME_SUFFIX

            await client.update_profile(
                first_name=new_name,
                bio=AUTO_BIO_TEMPLATE
            )
            logger.info(f"✅ Bio and name updated for account {telegram_user_id}")
        else:
            logger.info(f"⚡ Bio and name already up-to-date for account {telegram_user_id}")

    except FloodWait as e:
        wait_time = e.value + 5
        logger.warning(f"⏳ FloodWait {wait_time}s for account {telegram_user_id}, retrying...")
        await asyncio.sleep(wait_time)
        await set_ad_bio(client, telegram_user_id, _retry=_retry + 1)  # ✅ Tracked retry

    except Exception as e:
        logger.error(f"❌ Failed to set bio/name for account {telegram_user_id}: {e}")
"""
