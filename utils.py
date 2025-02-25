import json
import csv
from dotenv import load_dotenv
import os
import uuid
from google.cloud.sql.connector import Connector
from sqlalchemy import create_engine, Column, UUID, BigInteger, String, Integer, ForeignKey, Numeric, Date, select
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

#---------------------------------------------------------------------------------------------------

def str_to_json(text: str):
    try:
        json_response = json.loads(text)
        return json_response
    
    except json.JSONDecodeError:
        return ("error: Failed to parse response as JSON")
    

# load database credentials from environment variables
load_dotenv()
PROJECT_ID = os.getenv("GCP_PROJECT_ID")
REGION = os.getenv("REGION")
INSTANCE_NAME = os.getenv("INSTANCE_NAME")
INSTANCE_CONNECTION_NAME = f"{PROJECT_ID}:{REGION}:{INSTANCE_NAME}"
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")
DB_PORT = os.getenv("DB_PORT")

connector = Connector()

def get_connection():
    conn = connector.connect(
        INSTANCE_CONNECTION_NAME,
        "pg8000",
        user=DB_USER,
        password=DB_PASSWORD,
        db=DB_NAME
    )
    return conn

# create connection pool 
pool = create_engine(
    "postgresql+pg8000://",
    creator=get_connection,
)
  
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=pool)

# create users table class
Base = declarative_base()
class Users(Base):
    __tablename__ = "users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)  # UUID for anonymity
    telegram_id = Column(BigInteger, unique=True, nullable=False)  # Telegram ID 
    

def get_or_create_user(telegram_id):
    """check if a user exists in the database; if not, create a new one"""
    session = SessionLocal()

    try:
        # Check if user already exists
        user = session.query(Users).filter(Users.telegram_id == telegram_id).first()
        if user:
            return user.id  # Return existing UUID

        # Create new user with UUID
        new_user = Users(telegram_id=telegram_id)
        session.add(new_user)
        session.commit()
        session.refresh(new_user)

        return new_user.id  # return the generated UUID

    except Exception as e:
        print(f"Database error: {e}")
        session.rollback()
    finally:
        session.close()  # connection is returned to the pool

# create expenses table class
class Expenses(Base):
    __tablename__ = "expenses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    price = Column(Numeric(10,2), nullable=False)
    category = Column(String, nullable=False)
    description = Column(String, nullable=False)
    date = Column(Date, nullable=False)
    currency = Column(String, nullable=False)
    
def insert_expense(user_id, price, category, description, date, currency):
    """insert a new expense record into the database."""
    session = SessionLocal()
    
    try:
        new_expense = Expenses(
            user_id=user_id,
            price=price,
            category=category,
            description=description,
            date=date,
            currency=currency
        )
        session.add(new_expense)
        session.commit()
    except Exception as e:
        print(f"Database error: {e}")
        session.rollback()
    finally:
        session.close()
        
def export_expenses_to_csv(user_id, tele_handle):
    """export user's expenses to CSV"""
    session = SessionLocal()
    file_path = f"expenses_{tele_handle}.csv"  # name the file based on user's telegram handle

    try:
        # only query rows that belong to the user
        result = session.execute(select(Expenses).where(Expenses.user_id == user_id))
        relevant_expenses = result.scalars().all()

        if not relevant_expenses:      # no expenses found
            return None

        # CSV column headers
        fieldnames = ["Date", "Description", "Category", "Price", "Currency"]

        # write data to CSV file
        with open(file_path, mode="w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()

            for expense in relevant_expenses:
                writer.writerow({
                    "Date": expense.date,
                    "Description": expense.description,
                    "Category": expense.category,
                    "Price": float(expense.price),
                    "Currency": expense.currency
                })

        return file_path  # Return the generated file path

    except Exception as e:
        print(f"Error exporting expenses: {e}")
        return None

    finally:
        session.close()