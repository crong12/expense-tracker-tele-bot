import csv
from sqlalchemy import select
from database import SessionLocal, Users, Expenses

def get_or_create_user(telegram_id):
    """Checks if a user exists in the database; if not, creates a new one"""
    session = SessionLocal()
    user = session.query(Users).filter(Users.telegram_id == telegram_id).first()
    if user:
        return user.id

    new_user = Users(telegram_id=telegram_id)
    session.add(new_user)
    session.commit()
    session.refresh(new_user)
    return new_user.id

def insert_expense(user_id, price, category, description, date, currency):
    """Inserts a new expense record into the database"""
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
        session.rollback()
        print(f"Error inserting expense: {e}")

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

        if not relevant_expenses:    # no expenses found
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
