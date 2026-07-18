"""Application configuration with an environment-first, import-safe loader."""

from dataclasses import dataclass
import os


MODEL_NAME = "gemini-3.1-flash-lite"
WAITING_FOR_EXPENSE, AWAITING_CONFIRMATION, AWAITING_REFINEMENT, AWAITING_EDIT, \
AWAITING_DELETE_REQUEST, AWAITING_DELETE_CONFIRMATION, AWAITING_QUERY, \
AWAITING_EXPORT_CONFIRMATION, AWAITING_CATEGORY_RULE = range(9)

_REQUIRED = ("TELE_BOT_TOKEN", "REGION", "REGION2", "DB_USER", "DB_PASSWORD", "DB_NAME",
             "DB_HOST", "DB_PORT", "OPENAI_API_KEY", "LANGSMITH_API_KEY")


@dataclass(frozen=True)
class Settings:
    bot_token: str
    region: str
    region2: str
    db_user: str
    db_password: str
    db_name: str
    db_host: str
    db_port: str
    openai_api_key: str
    langsmith_api_key: str
    project_id: str


def _production_secrets(names):
    import google.auth
    from google.cloud import secretmanager

    _, project = google.auth.default()
    client = secretmanager.SecretManagerServiceClient()
    return project, {name: client.access_secret_version(
        request={"name": f"projects/{project}/secrets/{name}/versions/latest"}
    ).payload.data.decode("UTF-8").strip() for name in names}


def load_settings(environ=None, *, allow_production_defaults=True) -> Settings:
    """Load explicit environment values before requesting production secrets."""
    environ = os.environ if environ is None else environ
    values = {name: environ.get(name) for name in _REQUIRED}
    missing = [name for name, value in values.items() if not value]
    project_id = environ.get("GOOGLE_CLOUD_PROJECT")
    if missing and allow_production_defaults:
        project_id, secrets = _production_secrets(missing)
        values.update(secrets)
        missing = [name for name, value in values.items() if not value]
    if missing:
        raise RuntimeError("Missing required configuration: " + ", ".join(missing))
    if not project_id:
        if allow_production_defaults:
            import google.auth
            _, project_id = google.auth.default()
        else:
            raise RuntimeError("Missing required configuration: GOOGLE_CLOUD_PROJECT")
    return Settings(*(values[name] for name in _REQUIRED), project_id)


_settings = load_settings()
BOT_TOKEN = _settings.bot_token
REGION = _settings.region
REGION2 = _settings.region2
DB_USER = _settings.db_user
DB_PASSWORD = _settings.db_password
DB_NAME = _settings.db_name
DB_HOST = _settings.db_host
DB_PORT = _settings.db_port
OPENAI_API_KEY = _settings.openai_api_key
LANGSMITH_API_KEY = _settings.langsmith_api_key
PROJECT_ID = _settings.project_id
