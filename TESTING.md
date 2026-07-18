# Testing

Install the test dependencies:

```bash
python -m pip install -r requirements-test.txt
```

## Test commands

| Purpose | Command |
| --- | --- |
| Fast (no database or live tests) | `python -m pytest -m "not integration and not live" -q` |
| Smoke application checks | `python -m pytest -m smoke -q` |
| PostgreSQL integration | `python -m pytest -m integration -q` |
| Full required non-live suite | `python -m pytest -m "not live" -q` |
| Branch coverage | `python -m pytest -m "not live" --cov --cov-branch --cov-report=term-missing -q` |

## PostgreSQL integration setup

Start a disposable PostgreSQL 16 instance:

```bash
docker run --rm -p 5432:5432 -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=expense_test postgres:16
```

Set `TEST_DATABASE_URL` to:

```text
postgresql+psycopg2://postgres:postgres@localhost:5432/expense_test
```

Set `DATABASE_URL` to the same value when running the whole suite. PowerShell example:

```powershell
$env:TEST_DATABASE_URL='postgresql+psycopg2://postgres:postgres@localhost:5432/expense_test'
$env:DATABASE_URL=$env:TEST_DATABASE_URL
```

## Markers and isolation

- `unit`: fast behavior isolated from external systems
- `smoke`: critical application wiring
- `integration`: tests that use real PostgreSQL
- `live`: tests explicitly permitted to access live external systems

Live tests are optional and excluded from required CI jobs. Network sockets are denied by default, so tests must use injected boundaries instead of vendor services. Shared Telegram doubles live in `tests/fakes/telegram.py`.
