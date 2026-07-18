from types import SimpleNamespace

import config


def test_explicit_project_is_used_for_missing_secrets_without_adc_project_lookup(monkeypatch):
    requests = []
    monkeypatch.setattr("google.auth.default", lambda: (_ for _ in ()).throw(AssertionError("ADC called")))
    client = SimpleNamespace(access_secret_version=lambda *, request: requests.append(request) or SimpleNamespace(
        payload=SimpleNamespace(data=b"value")))
    monkeypatch.setattr("google.cloud.secretmanager.SecretManagerServiceClient", lambda: client)
    project, values = config._production_secrets(["DB_PASSWORD"], project_id="explicit-project")
    assert project == "explicit-project" and values == {"DB_PASSWORD": "value"}
    assert requests == [{"name": "projects/explicit-project/secrets/DB_PASSWORD/versions/latest"}]


def test_database_url_dispatches_by_scoped_settings_without_explicit_environment(monkeypatch):
    import database
    monkeypatch.delenv("DATABASE_URL", raising=False)
    values = ["t", "r", "r", "a", "p", "d", "h", "1", "o", "l", "x"]
    a = config.Settings(*values)
    values[3] = "b"
    b = config.Settings(*values)
    with config.settings_context(a): first = database._database_url()
    with config.settings_context(b): second = database._database_url()
    assert first != second and "://a:" in first and "://b:" in second
