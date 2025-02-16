import json
from dotenv import load_dotenv
import os
import uuid
from google.cloud.sql.connector import Connector
from sqlalchemy import create_engine, Column, UUID, BigInteger, String, Integer, ForeignKey, Numeric, Date
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker


def str_to_json(text: str):
    try:
        json_response = json.loads(text)
        return json_response
    
    except json.JSONDecodeError:
        return ("error: Failed to parse response as JSON")
    

# def access_secret(secret_name):
#     """Retrieve secret value from Google Secret Manager."""
#     project_id = os.getenv("GCP_PROJECT_ID")  
#     client = secretmanager.SecretManagerServiceClient()

#     secret_path = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
#     response = client.access_secret_version(request={"name": secret_path})

#     return response.payload.data.decode("UTF-8")

'''database connection'''

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

# create connection pool with 'creator' argument to our connection object function
pool = create_engine(
    "postgresql+pg8000://",
    creator=get_connection,
)
  
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=pool)

# users table
Base = declarative_base()
class Users(Base):
    __tablename__ = "users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)  # UUID for anonymity
    telegram_id = Column(BigInteger, unique=True, nullable=False)  # Telegram ID 
    

def get_or_create_user(telegram_id):
    """Check if a user exists in the database; if not, create a new one."""
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

# expenses table
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