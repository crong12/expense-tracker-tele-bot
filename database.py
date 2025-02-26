import uuid
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from google.cloud.sql.connector import Connector
from sqlalchemy import create_engine, Column, UUID, BigInteger, String, Integer, ForeignKey, Numeric, Date
from config import INSTANCE_CONNECTION_NAME, DB_USER, DB_PASSWORD, DB_NAME


connector = Connector()

def get_connection():
    return connector.connect(
        INSTANCE_CONNECTION_NAME,
        "pg8000",
        user=DB_USER,
        password=DB_PASSWORD,
        db=DB_NAME
    )

# create connection pool
pool = create_engine(
    "postgresql+pg8000://",
    creator=get_connection,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=pool)

# define tables (as ORM classes)
Base = declarative_base()

class Users(Base):
    __tablename__ = "users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    telegram_id = Column(BigInteger, unique=True, nullable=False)

class Expenses(Base):
    __tablename__ = "expenses"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    price = Column(Numeric(10,2), nullable=False)
    category = Column(String, nullable=False)
    description = Column(String, nullable=False)
    date = Column(Date, nullable=False)
    currency = Column(String, nullable=False)
