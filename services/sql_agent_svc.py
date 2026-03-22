import json
import os
from typing import Annotated, Literal
from sqlalchemy.sql import text
from langchain_core.tools import tool
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import AIMessage
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

# initialise agent workhorse LLMs
llm = ChatOpenAI(
    model="gpt-4.1-nano",
    max_retries=3
)

final_llm = ChatOpenAI(
    model="gpt-5-mini",
    reasoning_effort="low",
    max_retries=3
)

class State(TypedDict):
    """Define the state for the agent"""
    messages: Annotated[list[AnyMessage], add_messages]

#---------------------------------------------------------------------------------------------------
# Tools #

# define tool to query database
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

        # Convert results to a string format
        if results_as_dict:
            # Format the results as a JSON string
            return json.dumps([dict(row) for row in results_as_dict], default=str)

        return "Query executed successfully, but no results were returned."
    except Exception as e:
        session.rollback()
        error_message = f"Database error: {e}"
        print(error_message)
        return error_message  # Return the error as a string
    finally:
        session.close()

# Describe a tool to represent the end state
class SubmitFinalAnswer(BaseModel):
    """Submit the final answer to the user based on the query results."""
    final_answer: str = Field(..., description="The final answer to the user")

#---------------------------------------------------------------------------------------------------
# Agents #

# Query generation node — also handles "can I answer directly?" routing and self-checks the query
QUERY_GEN_SYSTEM = """You are a SQL expert and helpful financial assistant.

STEP 1 — Decide if database access is needed:
- If the user's question can be answered without expense data (general questions, greetings, follow-ups that are already answered by previous context), respond with a plain text message (do NOT call the db_query_tool).
- If the question requires expense data (totals, history, breakdowns, etc.), proceed to generate a query.

STEP 2 — Generate and self-check a PostgreSQL query:
When generating a query, also double-check it for common mistakes before calling the tool:
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

After verifying the query, call the db_query_tool to execute it."""

query_gen_prompt = ChatPromptTemplate.from_messages(
    [("system", QUERY_GEN_SYSTEM), ("placeholder", "{messages}")]
)


async def query_gen_node(state: State, writer: StreamWriter):
    today, day = get_current_date()
    writer({"custom": "📝 Analysing query..."})

    prompt = query_gen_prompt.partial(today=today, day=day)
    query_gen = prompt | llm.bind_tools([db_query_tool])
    message = await query_gen.ainvoke(state)
    return {"messages": [message]}


# Add a node to formulate a final answer based on provided info
ANSWER_QUERY_SYSTEM = """You are a helpful expert data analyst and financial assistant. Answer the user's query using only the information you have.

When SQL results are available:
1) Start with a concise answer to the user's question (what matters most first).
2) If calculations are needed, perform them carefully and present only final figures.
3) Include one useful comparison (trend, % change, or notable outlier), if relevant.
4) Add 1–2 short, valuable observations that the user didn't explicitly ask for.

When no SQL results are available:
- Answer the user's question directly and helpfully without asking for data.

Formatting:
- Reply in Markdown with short sections: "Summary", "Details", and (if helpful) "Next steps".
- Keep default responses under 200 words unless the user requests more.
- Show final numbers only; don't reveal internal reasoning steps.

Safety and privacy:
- Do NOT include any internal identifiers or system details: no user_id, UUIDs, ids, chat_id, SQL text, table/column names, or tool function names.
- If such fields appear in tool outputs or prior messages, ignore them and never surface them.

Clarity and numerics:
- Use the currency codes present in the data; do not convert unless the user asks.
- Round monetary amounts to 2 decimal places and include the currency code.
- If the request is ambiguous or data is insufficient, ask exactly one concise clarifying question.

Your goal is to give accurate, high-signal insights without exposing internal identifiers or implementation details.
"""

answer_query_prompt = ChatPromptTemplate.from_messages([
    ("system", ANSWER_QUERY_SYSTEM),
    ("placeholder", "{messages}"),
])

answer_query = answer_query_prompt | final_llm.bind_tools([SubmitFinalAnswer],
                                                          tool_choice='SubmitFinalAnswer')


async def answer_query_node(state: State, writer: StreamWriter):
    writer({"custom": "📊 Formulating my answer..."})
    result = await answer_query.ainvoke(state)

    result.tool_calls[0]["args"]["final_answer"] = result.tool_calls[0]["args"]["final_answer"].rstrip('\n')

    return {"messages": [result]}

#---------------------------------------------------------------------------------------------------
# Conditional Edges #

def route_after_query_gen(state: State) -> Literal["execute_query", "answer_query"]:
    """Route based on whether query_gen produced a tool call (needs DB) or plain text (no DB needed)."""
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "execute_query"
    return "answer_query"

def route_after_execution(state: State) -> Literal["answer_query", "query_gen"]:
    """Route back to query_gen on error, otherwise proceed to answer."""
    last_message = state["messages"][-1]
    if isinstance(last_message.content, str) and "error" in last_message.content.lower():
        return "query_gen"
    return "answer_query"

#---------------------------------------------------------------------------------------------------
# Building Workflow #

workflow = StateGraph(State)

# Add nodes (3 nodes instead of 5)
workflow.add_node("query_gen", query_gen_node)
workflow.add_node("execute_query", create_tool_node_with_fallback([db_query_tool]))
workflow.add_node("answer_query", answer_query_node)

# Add edges
workflow.add_edge(START, "query_gen")
workflow.add_conditional_edges("query_gen", route_after_query_gen)
workflow.add_conditional_edges("execute_query", route_after_execution)
workflow.add_edge("answer_query", END)

# Compile the workflow
analyser_agent = workflow.compile()
