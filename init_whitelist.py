"""
Initialization script to create the whitelist table and add initial users.

Usage:
    python init_whitelist.py

This script will:
1. Create the whitelisted_users table if it doesn't exist
2. Optionally add initial users to the whitelist

To add users, modify the INITIAL_USERS list below with usernames to whitelist.
"""

import logging
from database import Base, engine
from services import add_to_whitelist, get_all_whitelisted_users

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Add whitelisted usernames here (without @)
# Format: (username, optional_notes)
INITIAL_USERS = [
    ("chrxmium", "Owner"),
    ("marcusooi99", "Friend")
]

def create_tables():
    """Create all tables in the database"""
    try:
        Base.metadata.create_all(engine)
        logger.info("Database tables created successfully")
        return True
    except Exception as e:  # pylint: disable=broad-except
        logger.error("Error creating tables: %s", e)
        return False

def add_initial_users():
    """Add initial users to the whitelist"""
    if not INITIAL_USERS:
        logger.info("No initial users configured in INITIAL_USERS list")
        return

    logger.info("Adding %d initial users to whitelist...", len(INITIAL_USERS))

    for username, notes in INITIAL_USERS:
        success = add_to_whitelist(username, notes)
        if success:
            logger.info("✓ Added '%s' to whitelist", username)
        else:
            logger.warning("✗ Could not add '%s' (may already exist)", username)

def display_whitelisted_users():
    """Display all currently whitelisted users"""
    users = get_all_whitelisted_users()

    if not users:
        logger.info("No users currently whitelisted")
        return

    logger.info("\nCurrently whitelisted users (%d):", len(users))
    logger.info("-" * 60)
    for user in users:
        notes_str = " - " + user['notes'] if user['notes'] else ""
        logger.info("  @'%s' (added: %s)%s", user['username'], \
            user['added_date'].strftime('%Y-%m-%d %H:%M:%S'), notes_str)
    logger.info("-" * 60)

def main():
    """Main initialization function"""
    logger.info("Starting whitelist initialization...")
    logger.info("=" * 60)

    # Step 1: Create tables
    logger.info("Step 1: Creating database tables...")
    if not create_tables():
        logger.error("Failed to create tables. Exiting.")
        return

    # Step 2: Add initial users
    logger.info("\nStep 2: Adding initial users...")
    add_initial_users()

    # Step 3: Display current whitelist
    logger.info("\nStep 3: Current whitelist status:")
    display_whitelisted_users()

    logger.info("\n%s", "=" * 60)
    logger.info("Whitelist initialization complete!")
    logger.info("\nTo add more users later, you can:")
    logger.info("1. Add them to INITIAL_USERS in this script and run it again")
    logger.info("2. Use the whitelist service functions directly in Python:")
    logger.info("   from services import add_to_whitelist")
    logger.info("   add_to_whitelist('username', 'optional notes')")

if __name__ == "__main__":
    main()
