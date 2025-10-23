"""Service for managing and checking whitelisted users"""
import logging
from typing import Optional
from database import SessionLocal, WhitelistedUsers

logger = logging.getLogger(__name__)

def is_user_whitelisted(username: str) -> bool:
    """
    Check if a username exists in the whitelist.
    
    Args:
        username: Telegram username (without @ symbol and lowercase)
    
    Returns:
        bool: True if user is whitelisted, False otherwise
    """
    if not username:
        logger.warning("Attempted whitelist check with empty username")
        return False

    # Normalize username by removing @ if present and converting to lowercase
    normalized_username = username.lstrip('@').lower()

    session = SessionLocal()
    try:
        whitelisted_user = session.query(WhitelistedUsers)\
            .filter(WhitelistedUsers.username == normalized_username)\
            .first()

        result = whitelisted_user is not None
        logger.info("Whitelist check for '%s': %s", normalized_username, result)
        return result
    except Exception as e:  # pylint: disable=broad-except
        logger.error("Error checking whitelist for username '%s': %s", normalized_username, e)
        return False
    finally:
        session.close()


def add_to_whitelist(username: str, notes: Optional[str] = None) -> bool:
    """
    Add a user to the whitelist.
    
    Args:
        username: Telegram username (without @ symbol)
        notes: Optional notes about this user
    
    Returns:
        bool: True if successfully added, False if already exists or error occurred
    """
    if not username:
        logger.warning("Attempted to add empty username to whitelist")
        return False

    # Normalize username by removing @ if present and converting to lowercase
    normalized_username = username.lstrip('@').lower()

    session = SessionLocal()
    try:
        # Check if user already exists
        existing_user = session.query(WhitelistedUsers)\
            .filter(WhitelistedUsers.username == normalized_username)\
            .first()

        if existing_user:
            logger.info("User '%s' already in whitelist", normalized_username)
            return False

        # Add new whitelisted user
        new_whitelisted_user = WhitelistedUsers(
            username=normalized_username,
            notes=notes
        )
        session.add(new_whitelisted_user)
        session.commit()

        logger.info("Added '%s' to whitelist", normalized_username)
        return True
    except Exception as e:  # pylint: disable=broad-except
        logger.error("Error adding username '%s' to whitelist: %s", normalized_username, e)
        session.rollback()
        return False
    finally:
        session.close()


def remove_from_whitelist(username: str) -> bool:
    """
    Remove a user from the whitelist.
    
    Args:
        username: Telegram username (without @ symbol)
    
    Returns:
        bool: True if successfully removed, False if not found or error occurred
    """
    if not username:
        logger.warning("Attempted to remove empty username from whitelist")
        return False

    # Normalize username by removing @ if present and converting to lowercase
    normalized_username = username.lstrip('@').lower()

    session = SessionLocal()
    try:
        whitelisted_user = session.query(WhitelistedUsers)\
            .filter(WhitelistedUsers.username == normalized_username)\
            .first()

        if not whitelisted_user:
            logger.info("User '%s' not found in whitelist", normalized_username)
            return False

        session.delete(whitelisted_user)
        session.commit()

        logger.info("Removed '%s' from whitelist", normalized_username)
        return True
    except Exception as e:  # pylint: disable=broad-except
        logger.error("Error removing username '%s' from whitelist: %s", normalized_username, e)
        session.rollback()
        return False
    finally:
        session.close()


def get_all_whitelisted_users() -> list:
    """
    Get all whitelisted users.
    
    Returns:
        list: List of dictionaries containing username, added_date, and notes
    """
    session = SessionLocal()
    try:
        whitelisted_users = session.query(WhitelistedUsers).all()

        result = [
            {
                'username': user.username,
                'added_date': user.added_date,
                'notes': user.notes
            }
            for user in whitelisted_users
        ]

        logger.info("Retrieved %d whitelisted users", len(result))
        return result
    except Exception as e:  # pylint: disable=broad-except
        logger.error("Error retrieving whitelisted users: %s", e)
        return []
    finally:
        session.close()
