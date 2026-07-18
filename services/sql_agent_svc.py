import json
import os
import re
from typing import Annotated, Any, Literal
from sqlalchemy.sql import text
from langchain_core.tools import tool
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field
from typing_extensions import TypedDict
from langgraph.graph import END, StateGraph, START
from langgraph.graph.message import AnyMessage, add_messages
from langgraph.types import StreamWriter
from database import SessionLocal
from utils import create_tool_node_with_fallback, get_current_date
from config import OPENAI_API_KEY

os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY

# Single model for both query generation and answer formulation
llm = None


def _llm():
    """Defer OpenAI construction until the analyst receives work."""
    global llm
    if llm is None:
        llm = ChatOpenAI(model="gpt-5.4-mini", reasoning_effort="low", use_responses_api=True, max_retries=3)
    return llm

class State(TypedDict):
    """Define the state for the agent"""
    messages: Annotated[list[AnyMessage], add_messages]

#---------------------------------------------------------------------------------------------------
# Tools #

_REJECTED_QUERY = "Query rejected: only a single read-only SELECT statement is allowed."


def _mask_sql_literals_and_comments(query: str) -> str:
    """Replace SQL literals/comments with whitespace while preserving SQL structure."""
    masked = list(query)
    index = 0
    length = len(query)

    def erase(start: int, end: int) -> None:
        for position in range(start, end):
            if masked[position] != "\n":
                masked[position] = " "

    while index < length:
        if query.startswith("--", index):
            end = query.find("\n", index)
            erase(index, length if end == -1 else end)
            index = length if end == -1 else end
        elif query.startswith("/*", index):
            end = index + 2
            depth = 1
            while end < length and depth:
                if query.startswith("/*", end):
                    depth += 1
                    end += 2
                elif query.startswith("*/", end):
                    depth -= 1
                    end += 2
                else:
                    end += 1
            if depth:
                return ""
            erase(index, end)
            index = end
        elif query[index] in "'\"":
            quote = query[index]
            prefix = index - 1
            escape_string = (
                quote == "'"
                and prefix >= 0
                and query[prefix] in "Ee"
                and (prefix == 0 or not (query[prefix - 1].isalnum() or query[prefix - 1] == "_"))
            )
            end = index + 1
            closed = False
            while end < length:
                if quote == "'" and query[end] == "\\":
                    if not escape_string or end + 1 >= length:
                        return ""
                    end += 2
                    continue
                if query[end] == quote:
                    if end + 1 < length and query[end + 1] == quote:
                        end += 2
                        continue
                    end += 1
                    closed = True
                    break
                end += 1
            if not closed:
                return ""
            erase(index, end)
            if quote == "\"":
                next_token = end
                while next_token < length and query[next_token].isspace():
                    next_token += 1
                if next_token < length and query[next_token] == "(":
                    return ""
            index = end
        elif query[index] == "$":
            delimiter = re.match(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$", query[index:])
            if delimiter:
                token = delimiter.group(0)
                end = query.find(token, index + len(token))
                if end == -1:
                    return ""
                end += len(token)
                erase(index, end)
                index = end
            else:
                index += 1
        else:
            index += 1
    return "".join(masked)


def _with_resolves_to_select(statement: str) -> bool:
    """Require a CTE's outer query form to be SELECT, not VALUES or TABLE."""
    depth = 0
    saw_cte_close = False
    for match in re.finditer(r"\(|\)|[A-Za-z_][A-Za-z0-9_]*", statement):
        token = match.group(0).upper()
        if token == "(":
            depth += 1
        elif token == ")":
            if depth == 0:
                return False
            depth -= 1
            saw_cte_close = saw_cte_close or depth == 0
        elif saw_cte_close and depth == 0 and token in {"SELECT", "VALUES", "TABLE"}:
            return token == "SELECT"
    return False


def _is_read_only_query(query: str) -> bool:
    """Conservatively allow one non-locking SELECT statement only."""
    if not isinstance(query, str) or not query.strip():
        return False
    masked = _mask_sql_literals_and_comments(query)
    statement = masked.strip()
    if statement.endswith(";"):
        statement = statement[:-1].rstrip()
    if not statement or ";" in statement:
        return False
    opening = re.match(r"^(SELECT|WITH)\b", statement, flags=re.IGNORECASE)
    if not opening:
        return False
    if opening.group(1).upper() == "WITH" and not _with_resolves_to_select(statement):
        return False
    forbidden = (
        "INSERT", "UPDATE", "DELETE", "MERGE", "DROP", "ALTER", "TRUNCATE", "CREATE",
        "COPY", "CALL", "DO", "SET", "RESET", "GRANT", "REVOKE", "BEGIN", "COMMIT",
        "ROLLBACK", "VACUUM", "ANALYZE", "LOCK",
    )
    if any(re.search(rf"\b{word}\b", statement, flags=re.IGNORECASE) for word in forbidden):
        return False
    if re.search(r"\bFOR\s+(?:UPDATE|NO\s+KEY\s+UPDATE|SHARE|KEY\s+SHARE)\b|\bSELECT\b[\s\S]*?\bINTO\b", statement, re.IGNORECASE):
        return False
    side_effect_functions = (
        "nextval|setval|set_config|pg_sleep|pg_terminate_backend|pg_cancel_backend|"
        "pg_advisory_[A-Za-z0-9_]*|pg_try_advisory_[A-Za-z0-9_]*|pg_notify|"
        "lo_import|lo_export|dblink_exec"
    )
    return not bool(re.search(rf"\b(?:{side_effect_functions})\s*\(", statement, re.IGNORECASE))

@tool
def db_query_tool(query: Any) -> str:
    """
    Execute a SQL query against the database and get back the result.
    If the query is not correct, an error message will be returned.
    If an error is returned, rewrite the query, check the query, and try again.
    """
    if not _is_read_only_query(query):
        return _REJECTED_QUERY

    session = None
    try:
        session = SessionLocal()
        session.connection(execution_options={"postgresql_readonly": True})
        result = session.execute(text(query))
        results_as_dict = result.mappings().all()

        if results_as_dict:
            return json.dumps([dict(row) for row in results_as_dict], default=str)

        return "Query executed successfully, but no results were returned."
    except Exception as e:
        if session is not None:
            try:
                session.rollback()
            except Exception as cleanup_error:
                print(f"Database cleanup error: {cleanup_error}")
        error_message = f"Database error: {e}"
        print(error_message)
        return error_message
    finally:
        if session is not None:
            try:
                session.close()
            except Exception as cleanup_error:
                print(f"Database cleanup error: {cleanup_error}")

class SubmitFinalAnswer(BaseModel):
    """Submit the final answer to the user based on the query results."""
    final_answer: str = Field(..., description="The final answer to the user")

#---------------------------------------------------------------------------------------------------
# Agent #

ANALYST_SYSTEM = """You are a helpful expert data analyst, SQL expert, and financial assistant.

You have two tools:
1. db_query_tool — execute a PostgreSQL query against the expenses database.
2. SubmitFinalAnswer — submit your final answer to the user. Call this ONLY when you have all the data you need.

Workflow:
- If the user's question can be answered without expense data (general questions, greetings, follow-ups already answered by previous context), call SubmitFinalAnswer directly.
- If the question requires expense data, generate and execute SQL queries using db_query_tool. You may call db_query_tool multiple times to gather all the data you need (e.g. totals, breakdowns, transaction lists). Once you have enough data, call SubmitFinalAnswer.
- NEVER call SubmitFinalAnswer with placeholder text like "preparing" or "calculating". Only submit when you have actual numbers and a complete answer.

SQL generation rules:
Double-check each query for common mistakes before calling db_query_tool:
- Using NOT IN with NULL values
- Using UNION when UNION ALL should have been used
- Using BETWEEN for exclusive ranges
- Data type mismatch in predicates
- Using the correct number of arguments for functions
- Casting to the correct data type
- Using the proper columns for joins

Table name: 'expenses'
Schema:
- Column('id', Integer(), primary_key=True)
- Column('user_id', UUID(), ForeignKey('users.id'))
- Column('price', Numeric())
- Column('category', String())
- Column('description', String())
- Column('date', Date())
- Column('currency', String())

Today's date is {today}. Today is {day}. Infer the date requested by the user based on today's date.

Query rules:
- Output the query as a single line — no newlines or formatting.
- Use single quotes (') for string literals, NEVER double quotes (").
- Do NOT use escape characters like backslashes before quotes.
- Only query rows belonging to the user_id provided in the context.
- Use user_id only in WHERE for filtering; do not SELECT user_id or id unless strictly required.
- Use only the list of categories provided in context. Do not make up categories.
- Use ILIKE for case-insensitive matching.
- Always query for currency.
- Never query all columns — only relevant ones.
- DO NOT make any DML statements (INSERT, UPDATE, DELETE, DROP etc.).
- If you get an error, rewrite the query and try again.
- If you get an empty result set, try to rewrite the query.

Answer formatting (for SubmitFinalAnswer):
- Reply in Markdown with short sections: "Summary", "Details", and (if helpful) "Next steps".
- Keep responses under 200 words unless the user requests more.
- Start with a concise answer to the user's question (what matters most first).
- If calculations are needed, perform them carefully and present only final figures.
- Include one useful comparison (trend, % change, or notable outlier), if relevant.
- Add 1–2 short, valuable observations that the user didn't explicitly ask for.
- Show final numbers only; don't reveal internal reasoning steps.

Safety and privacy:
- Do NOT include any internal identifiers or system details: no user_id, UUIDs, ids, chat_id, SQL text, table/column names, or tool function names.
- If such fields appear in tool outputs or prior messages, ignore them and never surface them.

Clarity and numerics:
- Use the currency codes present in the data; do not convert unless the user asks.
- Round monetary amounts to 2 decimal places and include the currency code.
- If the request is ambiguous or data is insufficient, ask exactly one concise clarifying question."""

analyst_prompt = ChatPromptTemplate.from_messages([
    ("system", ANALYST_SYSTEM),
    ("placeholder", "{messages}"),
])


async def analyst_node(state: State, writer: StreamWriter):
    today, day = get_current_date()

    # Send appropriate progress message based on whether we already have query results
    has_tool_results = any(
        getattr(msg, "type", None) == "tool" for msg in state["messages"]
    )
    if has_tool_results:
        writer({"custom": "📊 Formulating my answer..."})
    else:
        writer({"custom": "📝 Analysing query..."})

    prompt = analyst_prompt.partial(today=today, day=day)
    chain = prompt | _llm().bind_tools([db_query_tool, SubmitFinalAnswer])
    message = await chain.ainvoke(state)

    # Strip trailing newline from final answer if present
    tool_calls = getattr(message, "tool_calls", None)
    if isinstance(tool_calls, list) and tool_calls and isinstance(tool_calls[0], dict):
        first_call = tool_calls[0]
        args = first_call.get("args")
        if first_call.get("name") == "SubmitFinalAnswer" and isinstance(args, dict):
            final_answer = args.get("final_answer")
            if isinstance(final_answer, str):
                args["final_answer"] = final_answer.rstrip('\n')

    return {"messages": [message]}

#---------------------------------------------------------------------------------------------------
# Conditional Edges #

def route_after_analyst(state: State) -> Literal["tools", "__end__"]:
    """Route to tools if db_query_tool was called, otherwise end (SubmitFinalAnswer or plain text)."""
    messages = state.get("messages") if isinstance(state, dict) else None
    if not isinstance(messages, list) or not messages:
        return "__end__"
    tool_calls = getattr(messages[-1], "tool_calls", None)
    if isinstance(tool_calls, list):
        for tool_call in tool_calls:
            if not isinstance(tool_call, dict):
                continue
            name = tool_call.get("name")
            if not isinstance(name, str) or not name:
                continue
            return "tools" if name == "db_query_tool" else "__end__"
    return "__end__"

#---------------------------------------------------------------------------------------------------
# Building Workflow #

workflow = StateGraph(State)

workflow.add_node("analyst", analyst_node)
workflow.add_node("tools", create_tool_node_with_fallback([db_query_tool]))

workflow.add_edge(START, "analyst")
workflow.add_conditional_edges("analyst", route_after_analyst)
workflow.add_edge("tools", "analyst")

analyser_agent = workflow.compile()
