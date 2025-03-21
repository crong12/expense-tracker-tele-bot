import uuid
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine, Column, UUID, BigInteger, \
    String, Integer, ForeignKey, Numeric, Date
from config import DB_USER, DB_PASSWORD, DB_NAME, DB_HOST, DB_PORT

DATABASE_URL = f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# create connection engine
engine = create_engine(DATABASE_URL, poolclass=NullPool)
connection = engine.connect()
SessionLocal = sessionmaker(bind=engine)

# define tables (as ORM classes)
Base = declarative_base()

class Users(Base):
    """Users table"""
    __tablename__ = "users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    telegram_id = Column(BigInteger, unique=True, nullable=False)

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
