import csv
import re
import logging
from datetime import datetime
from sqlalchemy import select, extract
from database import SessionLocal, Users, Expenses

def get_or_create_user(telegram_id):
    """Checks if a user exists in the database; if not, creates a new one"""
    session = SessionLocal()
    try:
        user = session.query(Users)\
            .filter(Users.telegram_id == telegram_id).first()
        if user:
            return user.id

        new_user = Users(telegram_id=telegram_id)
        session.add(new_user)
        session.commit()
        session.refresh(new_user)
        return new_user.id
    finally:
        session.close()

def get_user_preferred_currency(user_id):
    """Retrieves the stored preferred currency for a user"""
    session = SessionLocal()
    try:
        user = session.query(Users).filter(Users.id == user_id).first()
        if user and user.preferred_currency:
            return user.preferred_currency
        return None
    finally:
        session.close()

def set_user_preferred_currency(user_id, currency):
    """Updates the user's preferred currency"""
    session = SessionLocal()
    try:
        user = session.query(Users).filter(Users.id == user_id).first()
        if user:
            logging.info("Updating preferred_currency for user %s from %s to %s", 
                        user_id, user.preferred_currency, currency)
            user.preferred_currency = currency
            session.commit()
            logging.info("Successfully committed preferred_currency update")
            return True
        else:
            logging.warning("User with id %s not found when updating preferred currency", user_id)
        return False
    except Exception as e: # pylint: disable=broad-except
        session.rollback()
        logging.error("Error updating preferred currency: %s", str(e))
        return False
    finally:
        session.close()

def get_categories(user_id):
    """Get all expense categories used by a specific user"""
    session = SessionLocal()
    try:
        categories = session.query(Expenses.category)\
            .filter(Expenses.user_id == user_id)\
            .distinct()\
            .all()
        return [category[0] for category in categories]
    finally:
        session.close()

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
        session.refresh(new_expense)

        return new_expense.id

    except Exception as e:  # pylint: disable=broad-except
        session.rollback()
        print("Error inserting expense: %s", str(e))

    finally:
        session.close()

def update_expense(expense_id, price, category, description, date, currency):
    """updates an existing expense record in the database"""
    session = SessionLocal()
    expense = session.query(Expenses)\
        .filter(Expenses.id == expense_id).first()

    expense.price = price
    expense.category = category
    expense.description = description
    expense.date = date
    expense.currency = currency

    try:
        session.commit()
        session.refresh(expense)
        return expense.id

    except Exception as e:  # pylint: disable=broad-except
        session.rollback()
        print(f"Error updating expense: {e}")
        return False

    finally:
        session.close()

def export_expenses_to_csv(user_id, tele_handle, time_range):
    """export user's expenses to CSV"""
    session = SessionLocal()
    file_path = f"expenses_{tele_handle}.csv"  # name the file based on user's telegram handle

    try:
        if time_range == 'this_month':
            # get current month and year
            current_month = datetime.now().month
            current_year = datetime.now().year
            # only get expenses for this month
            result = session.execute(
                select(Expenses)
                .where(Expenses.user_id == user_id)
                .where(extract('month', Expenses.date) == current_month)
                .where(extract('year', Expenses.date) == current_year)
                .order_by(Expenses.date))
        else:
            # get all expenses
            result = session.execute(
                select(Expenses)
                .where(Expenses.user_id == user_id)
                .order_by(Expenses.date))

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

    except Exception as e:  # pylint: disable=broad-except
        print("Error exporting expenses: %s", str(e))
        return None

    finally:
        session.close()

def exact_expense_matching(expense_text):
    """Find an expense in the database by matching its details."""
    session = SessionLocal()

    # extract details from the text
    currency_pattern = r"Currency: (\w+)"
    amount_pattern = r"Amount: ([\d.]+)"
    category_pattern = r"Category:\s*(.+)"
    description_pattern = r"Description:\s*(.+)"
    date_pattern = r"Date: (\d{4}-\d{2}-\d{2})"

    currency = re.search(currency_pattern, expense_text).group(1)
    amount = float(re.search(amount_pattern, expense_text).group(1))
    category = re.search(category_pattern, expense_text).group(1)
    description = re.search(description_pattern, expense_text).group(1)
    date = re.search(date_pattern, expense_text).group(1)

    date_obj = datetime.strptime(date, "%Y-%m-%d").date()  # convert string to date

    # Try to find a matching expense
    expense = session.query(Expenses).filter(
        Expenses.price == float(amount),
        Expenses.category == category,
        Expenses.description == description,
        Expenses.date == date_obj,
        Expenses.currency == currency
    ).first()

    session.close()

    return expense.id if expense else None

def delete_all_expenses(user_id):
    """delete all expenses for a specific user"""
    session = SessionLocal()

    try:
        session.query(Expenses)\
            .filter(Expenses.user_id == user_id).delete()
        session.commit()
        return True

    except Exception as e:  # pylint: disable=broad-except
        print("Error exporting expenses: %s", str(e))
        return False

    finally:
        session.close()

def delete_specific_expense(user_id, expense_id):
    """Deletes a specific expense associated with a user."""
    session = SessionLocal()

    try:
        expense = session.query(Expenses)\
            .filter(Expenses.user_id == user_id, Expenses.id == expense_id).first()

        if expense:
            session.delete(expense)
            session.commit()
            return True
        return False

    except Exception as e:  # pylint: disable=broad-except
        session.rollback()
        print("Error deleting expense: %s", str(e))
        return False

    finally:
        session.close()
