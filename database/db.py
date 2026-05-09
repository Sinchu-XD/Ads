from sqlalchemy import Column, Integer, String, BigInteger, Text, DateTime, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.sql import func
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

from config import NEON_DB_URL
from utils.logger import logger

if not NEON_DB_URL or NEON_DB_URL.strip() == "":
    raise EnvironmentError(
        "\n\n❌  NEON_DB_URL is not set!\n\n"
        "Open config.py and fill in your NeonDB PostgreSQL connection string:\n"
        "  NEON_DB_URL = \"postgresql://user:password@host/dbname?sslmode=require\"\n\n"
        "Or set it as an environment variable before running:\n"
        "  export NEON_DB_URL='postgresql://user:password@host/dbname?sslmode=require'\n"
    )

DATABASE_URL = NEON_DB_URL.strip()
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
if not DATABASE_URL.startswith("postgresql+asyncpg://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

Base = declarative_base()

class UserAccount(Base):
    __tablename__ = "user_accounts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_user_id = Column(BigInteger, nullable=False, index=True)
    phone_number = Column(String(20), nullable=False)
    session_string_encrypted = Column(Text, nullable=False)
    account_username = Column(String(100), nullable=True)
    first_name = Column(String(100), nullable=True)
    bio_set = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class UserSettings(Base):
    __tablename__ = "user_settings"
    telegram_user_id = Column(BigInteger, primary_key=True, index=True)
    is_broadcasting = Column(Boolean, default=False, nullable=False)
    broadcast_text = Column(Text, nullable=True)
    last_target_index = Column(Integer, default=0, nullable=False)
    is_premium = Column(Boolean, default=False, nullable=False)
    trial_started_at = Column(DateTime(timezone=True), server_default=func.now())
    premium_granted_at = Column(DateTime(timezone=True), nullable=True)
    dm_broadcast_enabled = Column(Boolean, default=False)

class BroadcastTemplate(Base):
    __tablename__ = "broadcast_templates"
    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_user_id = Column(BigInteger, nullable=False, unique=True, index=True)
    message_text = Column(Text, nullable=True)
    buttons_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"ssl": "require", "statement_cache_size": 0},
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10
)

SessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

async def init_db():
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("[db] Database tables initialized successfully")
    except Exception as e:
        logger.error(f"[db] Init error: {e}")
        raise
