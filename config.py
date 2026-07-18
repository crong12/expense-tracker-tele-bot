"""Import-safe application configuration."""

from dataclasses import dataclass
import os

MODEL_NAME = "gemini-3.1-flash-lite"
WAITING_FOR_EXPENSE, AWAITING_CONFIRMATION, AWAITING_REFINEMENT, AWAITING_EDIT, \
AWAITING_DELETE_REQUEST, AWAITING_DELETE_CONFIRMATION, AWAITING_QUERY, \
AWAITING_EXPORT_CONFIRMATION, AWAITING_CATEGORY_RULE = range(9)

_REQUIRED = ("TELE_BOT_TOKEN", "REGION", "REGION2", "DB_USER", "DB_PASSWORD", "DB_NAME",
             "DB_HOST", "DB_PORT", "OPENAI_API_KEY", "LANGSMITH_API_KEY")
_LEGACY = {name: field for name, field in zip(_REQUIRED, (
    "bot_token", "region", "region2", "db_user", "db_password", "db_name", "db_host",
    "db_port", "openai_api_key", "langsmith_api_key"))}
_LEGACY["PROJECT_ID"] = "project_id"


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


_cached_settings = None


def install_settings(settings: Settings | None) -> None:
    global _cached_settings
    _cached_settings = settings


def _production_secrets(names):
    import google.auth
    from google.cloud import secretmanager
    _, project = google.auth.default()
    client = secretmanager.SecretManagerServiceClient()
    values = {name: client.access_secret_version(
        request={"name": f"projects/{project}/secrets/{name}/versions/latest"}
    ).payload.data.decode("UTF-8").strip() for name in names}
    return project, values


def load_settings(environ=None, *, allow_production_defaults=True) -> Settings:
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
        if not allow_production_defaults:
            raise RuntimeError("Missing required configuration: GOOGLE_CLOUD_PROJECT")
        import google.auth
        _, project_id = google.auth.default()
    return Settings(*(values[name] for name in _REQUIRED), project_id)


def get_settings() -> Settings:
    global _cached_settings
    if _cached_settings is None:
        _cached_settings = load_settings()
    return _cached_settings


def __getattr__(name):
    field = _LEGACY.get(name)
    if field:
        return getattr(get_settings(), field)
    raise AttributeError(name)
