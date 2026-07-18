import uuid
import os
from datetime import datetime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine, Column, UUID, BigInteger, \
    String, Integer, ForeignKey, Numeric, Date, DateTime, Text
from sqlalchemy.engine import Engine
from config import get_settings

def _database_url():
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    settings = get_settings()
    return f"postgresql+psycopg2://{settings.db_user}:{settings.db_password}@{settings.db_host}:{settings.db_port}/{settings.db_name}"

DATABASE_URL = _database_url()

PERSISTENCE_URL = DATABASE_URL.replace("postgresql+psycopg2://", "postgresql://", 1)


def create_database_engine(url: str) -> Engine:
    """Create the application's PostgreSQL engine for an explicit URL."""
    return create_engine(url, pool_size=2, max_overflow=3, pool_pre_ping=True)


def create_session_factory(database_engine: Engine) -> sessionmaker:
    """Create a session factory bound to the supplied engine."""
    return sessionmaker(bind=database_engine)

# create connection engine
engine = create_database_engine(DATABASE_URL)
_session_factories = {DATABASE_URL: create_session_factory(engine)}

def SessionLocal():
    url = _database_url()
    if url not in _session_factories:
        _session_factories[url] = create_session_factory(create_database_engine(url))
    return _session_factories[url]()

Session = SessionLocal

# define tables (as ORM classes)
Base = declarative_base()

class Users(Base):
    """Users table"""
    __tablename__ = "users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    preferred_currency = Column(String(3), nullable=True, default=None)

class Expenses(Base):
    """Expenses table"""
    __tablename__ = "expenses"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    price = Column(Numeric(10,2), nullable=False)
    category = Column(String, nullable=False)
    description = Column(String, nullable=False)
    date = Column(Date, nullable=False)
    currency = Column(String, nullable=False)

class CategoryRules(Base):
    """Per-user keyword-to-category mapping rules"""
    __tablename__ = "category_rules"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    keyword = Column(String, nullable=False)
    category = Column(String, nullable=False)

class WhitelistedUsers(Base):
    """Whitelisted users table for access control"""
    __tablename__ = "whitelisted_users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String, unique=True, nullable=False)
    added_date = Column(DateTime, nullable=False, default=datetime.utcnow)
    notes = Column(Text, nullable=True)
