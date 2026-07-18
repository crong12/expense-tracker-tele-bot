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
