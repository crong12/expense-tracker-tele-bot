from google.cloud import secretmanager
import google.auth

def get_project_id():
    """Automatically retrieves the Google Cloud Project ID."""
    _, project = google.auth.default()
    return project

PROJECT_ID = get_project_id()  # Use this instead of hardcoding it

def get_secret(secret_name):
    """function to retrieve secret from google secret manager"""
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{PROJECT_ID}/secrets/{secret_name}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8").strip()

BOT_TOKEN = get_secret("TELE_BOT_TOKEN")
REGION = get_secret("REGION")
INSTANCE_NAME = get_secret("INSTANCE_NAME")
DB_USER = get_secret("DB_USER")
DB_PASSWORD = get_secret("DB_PASSWORD")
DB_NAME = get_secret("DB_NAME")
INSTANCE_CONNECTION_NAME = f"{PROJECT_ID}:{REGION}:{INSTANCE_NAME}"

# Gemini Model Config
MODEL_NAME = "gemini-1.5-flash-002"
TEMPERATURE = 0.2

# Conversation states
WAITING_FOR_EXPENSE, AWAITING_CONFIRMATION, AWAITING_REFINEMENT = range(3)
