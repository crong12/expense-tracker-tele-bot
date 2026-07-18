import asyncio
import importlib.machinery
import importlib.util
import os
import sys
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from sqlalchemy.sql.elements import TextClause


pytestmark = pytest.mark.unit
SOURCE = Path(__file__).parents[2] / "services" / "sql_agent_svc.py"


@contextmanager
def isolated_sql_agent_service(session_factory=lambda: None):
    prior = {name: sys.modules.get(name) for name in ("config", "database", "services", "services.sql_agent_svc")}
    had_key = "OPENAI_API_KEY" in os.environ
    prior_key = os.environ.get("OPENAI_API_KEY")
    config = ModuleType("config")
    config.OPENAI_API_KEY = "inert-test-key"
    database = ModuleType("database")
    database.SessionLocal = session_factory
    services = ModuleType("services")
    services.__path__ = [str(SOURCE.parent)]
    sys.modules.update({"config": config, "database": database, "services": services})
    sys.modules.pop("services.sql_agent_svc", None)
    os.environ.pop("OPENAI_API_KEY", None)
    try:
        spec = importlib.util.spec_from_file_location("services.sql_agent_svc", SOURCE)
        service = importlib.util.module_from_spec(spec)
        sys.modules["services.sql_agent_svc"] = service
        spec.loader.exec_module(service)
        yield service
    finally:
        for name, module in prior.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        if had_key:
            os.environ["OPENAI_API_KEY"] = prior_key
        else:
            os.environ.pop("OPENAI_API_KEY", None)


@pytest.fixture
def sql_agent():
    with isolated_sql_agent_service() as service:
        yield service


def query(service, value):
    return service.db_query_tool.invoke({"query": value})


@pytest.mark.parametrize("sql", [
    "SELECT 1", "SELECT 'DROP; DELETE' AS note;", 'SELECT "semi;colon" FROM expenses',
    "SELECT $$; DROP TABLE expenses$$", "SELECT 1 -- ; DELETE\n", "SELECT /* DROP; */ 1",
    "WITH totals AS (SELECT 1 AS amount) SELECT amount FROM totals;",
])
def test_read_only_validator_allows_single_queries_and_masks_literals(sql_agent, sql):
    assert sql_agent._is_read_only_query(sql) is True


@pytest.mark.parametrize("sql", [
    None, "", "   ", "SELECT 1; SELECT 2", "SELECT 'unterminated", "SELECT /* unterminated",
    "INSERT INTO expenses VALUES (1)",
    "UPDATE expenses SET price = 1", "DELETE FROM expenses", "MERGE INTO expenses USING x ON true",
    "DROP TABLE expenses", "ALTER TABLE expenses ADD x int", "TRUNCATE expenses", "CREATE TABLE x (id int)",
    "COPY expenses TO '/tmp/x'", "CALL proc()", "DO $$ BEGIN END $$", "SET ROLE x", "RESET ROLE",
    "GRANT SELECT ON expenses TO x", "REVOKE SELECT ON expenses FROM x", "BEGIN", "COMMIT", "ROLLBACK",
    "VACUUM expenses", "ANALYZE expenses", "LOCK TABLE expenses", "WITH x AS (DELETE FROM expenses RETURNING *) SELECT * FROM x",
    "SELECT * FROM expenses FOR UPDATE", "SELECT * FROM expenses FOR SHARE", "SELECT * INTO archive FROM expenses",
    "SELECT nextval('seq')", "SELECT setval('seq', 1)", "SELECT pg_sleep(1)",
    "SELECT pg_terminate_backend(1)", "SELECT pg_cancel_backend(1)",
])
def test_read_only_validator_rejects_mutations_and_multiple_statements(sql_agent, sql):
    assert sql_agent._is_read_only_query(sql) is False


@pytest.mark.parametrize("sql", [
    "SELECT 1 /* outer /* inner */ still-comment",
    r"SELECT E'unterminated escape\' harmless",
    "SELECT 1 FOR NO KEY UPDATE",
    "SELECT 1 FOR KEY SHARE",
    "SELECT pg_advisory_lock(1)",
    "SELECT pg_advisory_xact_lock(1)",
    "SELECT pg_notify('channel', 'payload')",
    "WITH item AS (SELECT 1) VALUES (1)",
    "WITH item AS (SELECT 1) TABLE item",
])
def test_read_only_validator_rejects_nested_or_escape_ambiguity_and_other_side_effects(sql_agent, sql):
    assert sql_agent._is_read_only_query(sql) is False


@pytest.mark.parametrize("sql", [
    r"SELECT 'ordinary\backslash'",
    "SELECT pg_try_advisory_lock(1)",
    "SELECT pg_try_advisory_xact_lock(1)",
    "SELECT set_config('work_mem', '1MB', false)",
    "SELECT lo_import('/tmp/input')",
    "SELECT lo_export(1, '/tmp/output')",
    "SELECT dblink_exec('connection', 'statement')",
    'SELECT "pg_notify"(\'channel\', \'payload\')',
])
def test_read_only_validator_rejects_ambiguous_strings_and_state_changing_calls(sql_agent, sql):
    assert sql_agent._is_read_only_query(sql) is False


def test_read_only_validator_allows_well_formed_escape_string(sql_agent):
    assert sql_agent._is_read_only_query(r"SELECT E'escaped\\backslash'") is True


def test_rejected_query_never_constructs_a_session(sql_agent):
    calls = 0
    def fail_session():
        nonlocal calls
        calls += 1
        raise AssertionError("session must not be made")
    sql_agent.SessionLocal = fail_session
    assert query(sql_agent, "DELETE FROM expenses") == "Query rejected: only a single read-only SELECT statement is allowed."
    assert calls == 0


def test_query_requires_authenticated_tenant_context(sql_agent):
    calls = []
    sql_agent.SessionLocal = lambda: calls.append(True)
    assert query(sql_agent, "SELECT * FROM expenses") == "Query rejected: no authenticated tenant context."
    assert calls == []


@pytest.mark.parametrize("sql", [
    "SELECT count(*) FROM expenses", "SELECT round(sum(price), 2) FROM expenses",
    "SELECT date_trunc('month', date), avg(price) FROM expenses GROUP BY date_trunc('month', date)",
    "SELECT lower(category) FROM expenses WHERE category IN ('Food', 'Travel')",
])
def test_tenant_tool_allows_documented_pure_analytics_functions(sql_agent, sql):
    assert sql_agent._uses_only_safe_analytics_functions(sql) is True


@pytest.mark.parametrize("sql", [
    "SELECT * FROM users", "SELECT * FROM public.expenses", "SELECT * FROM generate_series(1, 2)",
    "SELECT pg_read_file('postgresql.conf')", "SELECT current_setting('data_directory')",
    'SELECT * FROM expenses, users', 'SELECT * FROM expenses, "public"."users"',
    "SELECT query_to_xml('SELECT * FROM users', true, false, '') FROM expenses",
    "SELECT pg_read_file('postgresql.conf') FROM expenses",
    "SELECT current_setting('data_directory') FROM expenses",
    "SELECT public.pg_read_file('postgresql.conf') FROM expenses",
    'SELECT "pg_read_file"(\'postgresql.conf\') FROM expenses',
])
def test_tenant_tool_rejects_non_expense_and_relation_free_bypasses(sql_agent, sql):
    calls = []
    sql_agent.SessionLocal = lambda: calls.append(True)
    with sql_agent.tenant_context("tenant-1"):
        assert query(sql_agent, sql).startswith("Query rejected:")
    assert calls == []


@pytest.mark.parametrize("value", [None, 42, ["SELECT 1"], {"query": "SELECT 1"}])
def test_public_tool_rejects_non_string_values_without_constructing_session(sql_agent, value):
    calls = []
    sql_agent.SessionLocal = lambda: calls.append(True)
    assert query(sql_agent, value) == "Query rejected: only a single read-only SELECT statement is allowed."
    assert calls == []


def test_query_serializes_mapping_rows_and_closes_session(sql_agent):
    result = SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: [{"amount": Decimal("12.50"), "day": date(2026, 7, 18)}]))
    session = SimpleNamespace(execute=lambda statement: result, close=lambda: None, rollback=lambda: None)
    executed, connection_options, closed, rolled_back = [], [], [], []
    session.execute = lambda statement, parameters: (executed.append((statement, parameters)), result)[1]
    session.connection = lambda **kwargs: connection_options.append(kwargs)
    session.close = lambda: closed.append(True)
    session.rollback = lambda: rolled_back.append(True)
    sql_agent.SessionLocal = lambda: session
    with sql_agent.tenant_context("tenant-1"):
        assert query(sql_agent, "SELECT amount, day FROM expenses") == '[{"amount": "12.50", "day": "2026-07-18"}]'
    assert all(isinstance(statement, TextClause) for statement, _ in executed)
    assert [str(statement) for statement, _ in executed] == ["WITH expenses AS (SELECT id, user_id, price, category, description, date, currency FROM expenses WHERE user_id = :tenant_user_id) SELECT amount, day FROM expenses"]
    assert [parameters for _, parameters in executed] == [{"tenant_user_id": "tenant-1"}]
    assert connection_options == [{"execution_options": {"postgresql_readonly": True}}]
    assert closed == [True] and not rolled_back


def test_empty_result_closes_without_rollback(sql_agent):
    session = SimpleNamespace(execute=lambda *_: SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: [])))
    session.connection = lambda **_: None
    closed, rolled_back = [], []
    session.close = lambda: closed.append(True)
    session.rollback = lambda: rolled_back.append(True)
    sql_agent.SessionLocal = lambda: session
    with sql_agent.tenant_context("tenant-1"):
        assert query(sql_agent, "SELECT 1 WHERE false") == "Query executed successfully, but no results were returned."
    assert closed == [True] and not rolled_back


def test_query_exception_rolls_back_and_closes_once(sql_agent):
    session = SimpleNamespace(execute=lambda *_: (_ for _ in ()).throw(RuntimeError("broken")))
    session.connection = lambda **_: None
    rolled_back, closed = [], []
    session.rollback = lambda: rolled_back.append(True)
    session.close = lambda: closed.append(True)
    sql_agent.SessionLocal = lambda: session
    with sql_agent.tenant_context("tenant-1"):
        assert query(sql_agent, "SELECT 1") == "Database error: broken"
    assert rolled_back == [True] and closed == [True]


def test_cleanup_exceptions_do_not_replace_database_error_or_success_response(sql_agent):
    failing = SimpleNamespace(execute=lambda *_: (_ for _ in ()).throw(RuntimeError("broken")))
    failing.connection = lambda **_: None
    failing.rollback = lambda: (_ for _ in ()).throw(RuntimeError("rollback failed"))
    failing.close = lambda: (_ for _ in ()).throw(RuntimeError("close failed"))
    sql_agent.SessionLocal = lambda: failing
    with sql_agent.tenant_context("tenant-1"):
        assert query(sql_agent, "SELECT 1") == "Database error: broken"

    successful = SimpleNamespace(execute=lambda *_: SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: [])))
    successful.connection = lambda **_: None
    successful.close = lambda: (_ for _ in ()).throw(RuntimeError("close failed"))
    successful.rollback = lambda: None
    sql_agent.SessionLocal = lambda: successful
    with sql_agent.tenant_context("tenant-1"):
        assert query(sql_agent, "SELECT 1") == "Query executed successfully, but no results were returned."


def test_session_construction_error_returns_database_error(sql_agent):
    sql_agent.SessionLocal = lambda: (_ for _ in ()).throw(RuntimeError("unavailable"))
    with sql_agent.tenant_context("tenant-1"):
        assert query(sql_agent, "SELECT 1") == "Database error: unavailable"


def test_read_only_connection_option_failure_rolls_back_and_closes_without_executing_query(sql_agent):
    executed, rolled_back, closed = [], [], []
    session = SimpleNamespace(
        connection=lambda **_: (_ for _ in ()).throw(RuntimeError("read-only setup failed")),
        execute=lambda statement: executed.append(statement),
        rollback=lambda: rolled_back.append(True),
        close=lambda: closed.append(True),
    )
    sql_agent.SessionLocal = lambda: session
    with sql_agent.tenant_context("tenant-1"):
        assert query(sql_agent, "SELECT 1") == "Database error: read-only setup failed"
    assert executed == []
    assert rolled_back == [True] and closed == [True]


def test_isolated_import_uses_real_source_and_restores_exact_registry_and_environment():
    prior = {name: sys.modules.get(name) for name in ("config", "database", "services", "services.sql_agent_svc")}
    had_key, prior_key = "OPENAI_API_KEY" in os.environ, os.environ.get("OPENAI_API_KEY")
    sentinels = {name: ModuleType("prior_" + name.replace(".", "_")) for name in prior}
    sys.modules.update(sentinels)
    os.environ["OPENAI_API_KEY"] = "prior-key"
    try:
        with isolated_sql_agent_service() as service:
            assert Path(service.__file__).resolve() == SOURCE.resolve()
            assert os.environ["OPENAI_API_KEY"] == "inert-test-key"
        assert all(sys.modules[name] is sentinels[name] for name in sentinels)
        assert os.environ["OPENAI_API_KEY"] == "prior-key"
    finally:
        for name, module in prior.items():
            if module is None: sys.modules.pop(name, None)
            else: sys.modules[name] = module
        if had_key: os.environ["OPENAI_API_KEY"] = prior_key
        else: os.environ.pop("OPENAI_API_KEY", None)


def test_isolated_import_restores_registry_and_environment_when_loading_fails(monkeypatch):
    names = ("config", "database", "services", "services.sql_agent_svc")
    prior = {name: sys.modules.get(name) for name in names}
    had_key, prior_key = "OPENAI_API_KEY" in os.environ, os.environ.get("OPENAI_API_KEY")
    sentinels = {name: ModuleType("sentinel_" + name.replace(".", "_")) for name in names}
    sys.modules.update(sentinels)
    os.environ["OPENAI_API_KEY"] = "prior-failure-key"
    def fail_load(self, module):
        raise RuntimeError("forced import failure")
    monkeypatch.setattr(importlib.machinery.SourceFileLoader, "exec_module", fail_load)
    try:
        with pytest.raises(RuntimeError, match="forced import failure"):
            with isolated_sql_agent_service():
                pass
        assert all(sys.modules[name] is sentinels[name] for name in names)
        assert os.environ["OPENAI_API_KEY"] == "prior-failure-key"
    finally:
        for name, module in prior.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        if had_key:
            os.environ["OPENAI_API_KEY"] = prior_key
        else:
            os.environ.pop("OPENAI_API_KEY", None)


@pytest.mark.parametrize(("messages", "expected"), [
    ([], "__end__"), ([SimpleNamespace()], "__end__"), ([SimpleNamespace(tool_calls=[])], "__end__"),
    ([SimpleNamespace(tool_calls=[{"name": "SubmitFinalAnswer"}])], "__end__"),
    ([SimpleNamespace(tool_calls=[{"name": "unknown"}])], "__end__"),
    ([SimpleNamespace(tool_calls=[{}])], "__end__"), ([SimpleNamespace(tool_calls="bad")], "__end__"),
    ([SimpleNamespace(tool_calls=[{}, {"name": "db_query_tool"}])], "tools"),
    ([SimpleNamespace(tool_calls=[None, {"name": "SubmitFinalAnswer"}, {"name": "db_query_tool"}])], "__end__"),
    ([SimpleNamespace(tool_calls=[{"name": "unknown"}, {"name": "db_query_tool"}])], "__end__"),
    ([SimpleNamespace(tool_calls=[{"name": "db_query_tool"}, {"name": "unknown"}])], "tools"),
])
def test_routing_handles_missing_malformed_and_first_tool_call(sql_agent, messages, expected):
    assert sql_agent.route_after_analyst({"messages": messages}) == expected


class FakePrompt:
    def __init__(self): self.partial_args = None
    def partial(self, **kwargs): self.partial_args = kwargs; return self
    def __or__(self, bound): self.bound = bound; return bound


class FakeLlm:
    def __init__(self, chain): self.chain = chain; self.tools = None
    def bind_tools(self, tools): self.tools = tools; return self.chain


class FakeChain:
    def __init__(self, outcome): self.outcome = outcome; self.states = []
    async def ainvoke(self, state):
        self.states.append(state)
        return self.outcome

@pytest.mark.asyncio
async def test_analyst_binds_prompt_tools_emits_progress_and_normalizes_only_final_answer(sql_agent):
    message = SimpleNamespace(type="ai", tool_calls=[{"name": "SubmitFinalAnswer", "args": {"final_answer": "  answer\n\n"}}])
    chain = FakeChain(message)
    prompt, llm, events = FakePrompt(), FakeLlm(chain), []
    sql_agent.analyst_prompt, sql_agent.llm = prompt, llm
    sql_agent.get_current_date = lambda: ("2026-07-18", "Saturday")
    state = {"messages": [SimpleNamespace(type="human")]}
    assert await sql_agent.analyst_node(state, events.append) == {"messages": [message]}
    assert events == [{"custom": "\U0001f4dd Analysing query..."}]
    assert prompt.partial_args == {"today": "2026-07-18", "day": "Saturday"}
    assert llm.tools == [sql_agent.db_query_tool, sql_agent.SubmitFinalAnswer] and chain.states == [state]
    assert message.tool_calls[0]["args"]["final_answer"] == "  answer"


@pytest.mark.asyncio
async def test_analyst_formulates_after_tool_result_and_survives_malformed_or_plain_messages(sql_agent):
    plain = SimpleNamespace(type="ai", tool_calls=[])
    chain = FakeChain(plain)
    async def invoke(state): chain.states.append(state); return plain
    chain.ainvoke = invoke
    sql_agent.analyst_prompt, sql_agent.llm = FakePrompt(), FakeLlm(chain)
    events, state = [], {"messages": [SimpleNamespace(type="tool"), SimpleNamespace(type="human")]}
    assert await sql_agent.analyst_node(state, events.append) == {"messages": [plain]}
    assert events == [{"custom": "\U0001f4ca Formulating my answer..."}] and chain.states == [state]


@pytest.mark.asyncio
async def test_analyst_leaves_db_query_calls_unchanged(sql_agent):
    message = SimpleNamespace(type="ai", tool_calls=[{"name": "db_query_tool", "args": {"query": "SELECT 1\n"}}])
    chain = FakeChain(message)
    sql_agent.analyst_prompt, sql_agent.llm = FakePrompt(), FakeLlm(chain)
    assert await sql_agent.analyst_node({"messages": []}, lambda _: None) == {"messages": [message]}
    assert message.tool_calls == [{"name": "db_query_tool", "args": {"query": "SELECT 1\n"}}]


@pytest.mark.asyncio
async def test_analyst_does_not_crash_or_mutate_malformed_final_answer_args(sql_agent):
    message = SimpleNamespace(type="ai", tool_calls=[{"name": "SubmitFinalAnswer", "args": None}])
    chain = FakeChain(message)
    async def invoke(state): return message
    chain.ainvoke = invoke
    sql_agent.analyst_prompt, sql_agent.llm = FakePrompt(), FakeLlm(chain)
    original = message.tool_calls[0]["args"]
    assert await sql_agent.analyst_node({"messages": []}, lambda _: None) == {"messages": [message]}
    assert message.tool_calls[0]["args"] is original


@pytest.mark.asyncio
async def test_analyst_propagates_chain_error_after_initial_progress(sql_agent):
    chain = FakeChain(None)
    async def invoke(state): raise RuntimeError("model failed")
    chain.ainvoke = invoke
    sql_agent.analyst_prompt, sql_agent.llm = FakePrompt(), FakeLlm(chain)
    events = []
    with pytest.raises(RuntimeError, match="model failed"):
        await sql_agent.analyst_node({"messages": []}, events.append)
    assert events == [{"custom": "\U0001f4dd Analysing query..."}]
