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

# set openai api key as env var
os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY

# initialise agent workhorse LLMs
llm = ChatOpenAI(
    model="gpt-4.1-nano",
    max_retries=10
    )

final_llm = ChatOpenAI(
    model="gpt-5-mini",
    reasoning_effort="low",
    max_retries=10
)

class State(TypedDict):
    """Define the state for the agent"""
    messages: Annotated[list[AnyMessage], add_messages]

today, day = get_current_date()

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

# LLM to determine if database access is required to answer user's query
DIRECT_RESPONSE_SYSTEM = """You are a helpful financial assistant.
Your only job is to determine if a user query requires access to their expense database.

If the question is a follow-up question (previous answer is provided), decide if you can answer the user's follow-up question based on the provided previous answer.
Only require additional expense data if you really have to.

If the query requires expense data (totals, history, breakdowns, etc.), respond EXACTLY with: 
"I'll need to check your expense data to answer this question."

If the query can be answered without database access (general questions, greetings, etc.), 
or if the previously provided answer contains enough information to answer the user's query,
respond EXACTLY with: 
"This question can be answered directly."
"""

direct_response_prompt = ChatPromptTemplate.from_messages([
    ("system", DIRECT_RESPONSE_SYSTEM),
    ("placeholder", "{messages}")
])

direct_response = direct_response_prompt | llm

async def direct_response_node(state: State, writer: StreamWriter):
    writer({"custom": "💭 Determining if I can answer directly..."})
    message = await direct_response.ainvoke(state)
    return {"messages": [message]}


# Query checker
QUERY_CHECK_SYSTEM = """You are a SQL expert with a strong attention to detail.
Double check the provided PostgreSQL query for common mistakes, including:
- Using NOT IN with NULL values
- Using UNION when UNION ALL should have been used
- Using BETWEEN for exclusive ranges
- Data type mismatch in predicates
- Using the correct number of arguments for functions
- Casting to the correct data type
- Using the proper columns for joins

Ensure that only rows belonging to the user_id specified in the query are queried. 

IMPORTANT: Always use single quotes (') for string literals in SQL queries, never double quotes ("). Double quotes in PostgreSQL are for identifiers only. 

DO NOT EVER:
- Convert user provided single quotes (') to double quotes (")
- Add escape characters like backslashes (\) before quotes

Examples of CORRECT formatting:
- WHERE user_id = '12345'
- AND category = 'Food'

Examples of INCORRECT formatting:
- WHERE user_id = "12345"  <- WRONG
- WHERE user_id = \"12345\" <- WRONG

If there are any of the above mistakes, rewrite the query. If there are no mistakes, just reproduce the original query.

You will call the appropriate tool to execute the query after running this check."""

query_check_prompt = ChatPromptTemplate.from_messages(
    [("system", QUERY_CHECK_SYSTEM), ("placeholder", "{messages}")]
)

query_check = query_check_prompt | llm.bind_tools([db_query_tool], tool_choice='any')


async def model_check_query(state: State, writer: StreamWriter) -> dict[str, list[AIMessage]]:
    """
    Use this tool to double-check if your query is correct before executing it.
    """
    writer({"custom": "🚦 Checking generated query for errors..."})
    response = await query_check.ainvoke({"messages": [state["messages"][-1]]})
    return {"messages": [response]}


# Generate a query based on the question and schema
QUERY_GEN_SYSTEM = f"""You are a SQL expert with a strong attention to detail.

Given an input question, output a syntactically correct PostgreSQL query to run.

Table name: 'expenses'
Schema: 
- Column('id', Integer(), primary_key=True)
- Column('user_id', UUID(), ForeignKey('users.id'))
- Column('price', Numeric())
- Column('category', String())
- Column('description', String())
- Column('date', Date())
- Column('currency', String())

When generating the query:
DO NOT format the text in the query.
DO NOT use double quotes. 
DO NOT use escape characters.

For example, instead of returning "SELECT\n  user_id,\n  SUM(price) AS total_spent\nFROM expenses\nWHERE\n  date BETWEEN "2025-03-01" AND "2025-03-31"\nGROUP BY\n  user_id\nORDER BY\n  total_spent DESC\nLIMIT 1;\n",
return "SELECT user_id, SUM(price) AS total_spent FROM expenses WHERE date BETWEEN '2025-03-01' AND '2025-03-31' GROUP BY user_id ORDER BY total_spent DESC LIMIT 1;"

Today's date is {today}. Today is {day}. Infer the date requested by the user based on today's date.

IMPORTANT:
Only query rows that belong to the user who made the query, based on the provided user_id in the query.
Use user_id only in WHERE for filtering; do not SELECT user_id or id unless strictly required for computation.
Use only the list of categories that are provided in the context. Do not make up or assume categories that are not listed.
Based on the user's query, determine which category to use in the query.
Use the ILIKE operator to match search terms case-insensitively.

You can order the results by a relevant column to return the most interesting examples in the database.
Never query for all the columns from a specific table, only the relevant columns given the question.
Always query for currency as that is important information.

If you get an error while executing a query, rewrite the query and try again.

If you get an empty result set, you should try to rewrite the query to get a non-empty result set. 

DO NOT make any DML statements (INSERT, UPDATE, DELETE, DROP etc.) to the database."""

query_gen_prompt = ChatPromptTemplate.from_messages(
    [("system", QUERY_GEN_SYSTEM), ("placeholder", "{messages}")]
)

async def query_gen_node(state: State, writer: StreamWriter):
    writer({"custom": "📝 Generating appropriate database query..."})

    # Create a new prompt with categories context
    prompt = ChatPromptTemplate.from_messages([
        ("system", QUERY_GEN_SYSTEM),
        ("placeholder", "{messages}")
    ])

    # Use the modified prompt
    query_gen = prompt | llm
    message = await query_gen.ainvoke(state)
    return {"messages": [message]}


# Add a node to formulate a final answer based on provided info
ANSWER_QUERY_SYSTEM = """You are a helpful expert data analyst and financial assistant. Answer the user’s query using only the information you have.
`
When SQL results are available:
1) Start with a concise answer to the user’s question (what matters most first).
2) If calculations are needed, perform them carefully and present only final figures.
3) Include one useful comparison (trend, % change, or notable outlier), if relevant.
4) Add 1–2 short, valuable observations that the user didn’t explicitly ask for.

When no SQL results are available:
- Answer the user’s question directly and helpfully without asking for data.

Formatting:
- Reply in Markdown with short sections: “Summary”, “Details”, and (if helpful) “Next steps”.
- Keep default responses under 200 words unless the user requests more.
- Show final numbers only; don’t reveal internal reasoning steps.

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
    # Create a new prompt with context from previous messages
    result = await answer_query.ainvoke(state)

    result.tool_calls[0]["args"]["final_answer"] = result.tool_calls[0]["args"]["final_answer"].rstrip('\n')

    return {"messages": [result]}

#---------------------------------------------------------------------------------------------------
# Conditional Edges #

def needs_database_access(state: State) -> Literal["query_gen", "answer_query"]:
    """
    Conditional edge function to route workflow between generating query or formulating final answer,
    based on whether database access is required to answer the question or not.
    """
    messages = state["messages"]
    last_message = messages[-1]

    # Check if the response indicates database access is needed
    if isinstance(last_message.content, str) and "I'll need to check your expense data" in last_message.content:
        return "query_gen"  # Route to query generation
    else:
        return "answer_query"  # No database access needed, proceed to answer query

# Define a conditional edge after execute_query
def route_after_execution(state: State) -> Literal["answer_query", "query_gen"]:
    """
    Conditional edge function to route workflow between re-generating query or formulating final answer,
    based on whether or not an error was returned in the database query
    """
    messages = state["messages"]
    last_message = messages[-1]

    # Check if the message contains an error
    if isinstance(last_message.content, str) and "error" in last_message.content.lower():
        return "query_gen"  # If there's an error, go back to query generation
    else:
        return "answer_query"  # Otherwise, analyze the results and answer the query
#---------------------------------------------------------------------------------------------------
# Building Workflow #

# Define a new graph
workflow = StateGraph(State)

# Add nodes
workflow.add_node("direct_response", direct_response_node)
workflow.add_node("query_gen", query_gen_node)
workflow.add_node("correct_query", model_check_query)
workflow.add_node("execute_query", create_tool_node_with_fallback([db_query_tool]))
workflow.add_node("answer_query", answer_query_node)

# Add edges
workflow.add_edge(START, "direct_response")
workflow.add_conditional_edges("direct_response", needs_database_access)
workflow.add_edge("query_gen", "correct_query")
workflow.add_edge("correct_query", "execute_query")
workflow.add_conditional_edges("execute_query", route_after_execution)
workflow.add_edge("answer_query", END)

# Compile the workflow
analyser_agent = workflow.compile()
