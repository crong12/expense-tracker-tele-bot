import json
import os
from typing import Annotated, Literal
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
llm = ChatOpenAI(
    model="gpt-5.4-mini",
    reasoning_effort="low",
    use_responses_api=True,
    max_retries=3
)

class State(TypedDict):
    """Define the state for the agent"""
    messages: Annotated[list[AnyMessage], add_messages]

#---------------------------------------------------------------------------------------------------
# Tools #

@tool
def db_query_tool(query: str) -> str:
    """
    Execute a SQL query against the database and get back the result.
    If the query is not correct, an error message will be returned.
    If an error is returned, rewrite the query, check the query, and try again.
    """
    session = SessionLocal()
    try:
        result = session.execute(text(query))
        results_as_dict = result.mappings().all()

        if results_as_dict:
            return json.dumps([dict(row) for row in results_as_dict], default=str)

        return "Query executed successfully, but no results were returned."
    except Exception as e:
        session.rollback()
        error_message = f"Database error: {e}"
        print(error_message)
        return error_message
    finally:
        session.close()

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
    chain = prompt | llm.bind_tools([db_query_tool, SubmitFinalAnswer])
    message = await chain.ainvoke(state)

    # Strip trailing newline from final answer if present
    if message.tool_calls and message.tool_calls[0]["name"] == "SubmitFinalAnswer":
        message.tool_calls[0]["args"]["final_answer"] = (
            message.tool_calls[0]["args"]["final_answer"].rstrip('\n')
        )

    return {"messages": [message]}

#---------------------------------------------------------------------------------------------------
# Conditional Edges #

def route_after_analyst(state: State) -> Literal["tools", "__end__"]:
    """Route to tools if db_query_tool was called, otherwise end (SubmitFinalAnswer or plain text)."""
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        if last_message.tool_calls[0]["name"] == "SubmitFinalAnswer":
            return "__end__"
        return "tools"
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
