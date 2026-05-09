from pyrogram import Client
from pyrogram.errors import FloodWait, AuthKeyUnregistered, SessionRevoked
from config import API_ID, API_HASH
from utils.encryption import decrypt_session
from utils.logger import logger
from database.db import UserAccount, SessionLocal
import asyncio
from sqlalchemy import select

MAX_FLOOD_RETRIES = 3


class UserbotClientManager:
    """Manages Pyrogram clients from encrypted sessions."""

    def __init__(self):
        self.clients: dict[int, Client] = {}

    # ==========================================
    # GET OR CREATE CLIENT
    # ==========================================
    async def get_client(self, account_id: int, db_session=None) -> Client:
        """Get or create a Pyrogram client from DB session string."""

        # ✅ Return cached client if still alive
        if account_id in self.clients:
            if await self._is_client_alive(self.clients[account_id]):
                return self.clients[account_id]
            else:
                self.clients.pop(account_id, None)  # ✅ Remove dead client from cache

        # ✅ Use provided session or create a scoped one
        if db_session is not None:
            return await self._load_and_start_client(account_id, db_session)

        async with SessionLocal() as db:
            return await self._load_and_start_client(account_id, db)

    async def _load_and_start_client(self, account_id: int, db_session) -> Client:
        """Internal: load account from DB, start Pyrogram client."""
        try:
            result = await db_session.execute(
                select(UserAccount).filter(UserAccount.id == account_id)
            )
            account = result.scalars().first()

            if not account:
                raise ValueError(f"Account {account_id} not found in DB")

            session_string = decrypt_session(account.session_string_encrypted)

            client = Client(
                name=f"adbot_{account_id}",
                api_id=API_ID,
                api_hash=API_HASH,
                session_string=session_string,
                in_memory=True,
                workdir="sessions",
                device_model="AdBroadcastBot",
                system_version="1.0",
                app_version="1.0",
                no_updates=True,
            )

            await client.start()

            # ✅ Cache peers to prevent 'Peer id invalid' errors
            try:
                logger.info(f"[client_manager] Caching peers for account {account_id}...")
                async for _ in client.get_dialogs(limit=20):
                    pass
                logger.info(f"[client_manager] ✅ Peers cached for account {account_id}")
            except Exception as e:
                logger.warning(f"[client_manager] Peer cache warning for {account_id}: {e}")

            self.clients[account_id] = client
            logger.info(
                f"[client_manager] ✅ Client started for account {account_id} "
                f"(@{account.account_username or 'unknown'})"
            )

            return client

        except (AuthKeyUnregistered, SessionRevoked) as e:
            logger.error(f"[client_manager] ❌ Session invalid for account {account_id}: {e}")
            self.clients.pop(account_id, None)  # ✅ Remove from cache if session is dead
            raise
        except Exception as e:
            logger.error(f"[client_manager] ❌ Failed to start client {account_id}: {e}")
            raise

    # ==========================================
    # HEALTH CHECK
    # ==========================================
    async def _is_client_alive(self, client: Client) -> bool:
        """Check if the Pyrogram client is still connected."""
        try:
            if not client.is_connected:
                return False
            await client.get_me()
            return True
        except Exception:
            return False

    # ==========================================
    # STOP CLIENT
    # ==========================================
    async def stop_client(self, account_id: int):
        """Stop and remove a client from the cache."""
        client = self.clients.pop(account_id, None)
        if client:
            try:
                await client.stop()
                logger.info(f"[client_manager] 🛑 Client stopped for account {account_id}")
            except Exception as e:
                logger.warning(f"[client_manager] Error stopping client {account_id}: {e}")

    async def stop_all_clients(self):
        """Stop all active clients — call on bot shutdown."""
        account_ids = list(self.clients.keys())
        for account_id in account_ids:
            await self.stop_client(account_id)
        logger.info("[client_manager] 🛑 All clients stopped")

    # ==========================================
    # SEND BROADCAST MESSAGE
    # ==========================================
    async def send_broadcast_message(
        self,
        account_id: int,
        chat_id: int,
        message,
        _retry: int = 0  # ✅ Tracked retry — no infinite recursion
    ):
        """Send one broadcast message safely using the userbot."""
        if _retry >= MAX_FLOOD_RETRIES:
            logger.error(f"[client_manager] Max FloodWait retries reached for account {account_id}")
            return None

        client = await self.get_client(account_id)

        try:
            if hasattr(message, "copy"):
                return await message.copy(chat_id)
            else:
                return await client.send_message(
                    chat_id=chat_id,
                    text=message.text if hasattr(message, "text") else str(message),
                    reply_markup=message.reply_markup if hasattr(message, "reply_markup") else None
                )

        except FloodWait as e:
            wait_time = e.value + 5
            logger.warning(
                f"[client_manager] FloodWait {wait_time}s for account {account_id}, "
                f"retry {_retry + 1}/{MAX_FLOOD_RETRIES}"
            )
            await asyncio.sleep(wait_time)
            return await self.send_broadcast_message(
                account_id, chat_id, message, _retry=_retry + 1
            )

        except Exception as e:
            logger.error(
                f"[client_manager] Failed to send to {chat_id} "
                f"from account {account_id}: {e}"
            )
            raise


# Global singleton
client_manager = UserbotClientManager()
