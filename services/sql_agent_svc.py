import json
import os
import re
from datetime import datetime
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
from utils import create_tool_node_with_fallback    
from config import OPENAI_API_KEY
from .expenses_svc import get_categories


# set openai api key as env var
os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY

# initialise agent workhorse LLMs
llm = ChatOpenAI(
    model="gpt-5-nano",
    max_retries=10
    )

final_llm = ChatOpenAI(
    model="gpt-5-mini",      
    max_retries=10
)

class State(TypedDict):
    """Define the state for the agent"""
    messages: Annotated[list[AnyMessage], add_messages]

today = datetime.today().strftime("%Y-%m-%d")
day = datetime.today().strftime("%A")

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

Given an input question, output a syntactically correct PostgreSQL query to run, then look at the results of the query and return the answer.

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
ANSWER_QUERY_SYSTEM = """You are a helpful expert data analyst and financial assistant that helps answer the user's query with all the information you have.

If SQL results are received, when reviewing its results:
1. First, directly answer the user's original question with clear, actionable insights
2. If calculations are needed, perform them carefully one by one.
2. Present the most important findings upfront in a concise summary
3. For financial/metric analysis, include relevant comparisons (% changes, trends, outliers)
4. Provide 1-2 unexpected or valuable observations from the data that the user may not have specifically asked for
5. Use a friendly, enthusiastic tone while maintaining professionalism

If no SQL results are received, then the user's query did not warrant a database query. In that case, simply answer the user's query in a friendly and helpful manner.

Format your response in Markdown. 

Remember that the user is looking for both answers and insights - help them understand what the data really means for their financial planning.
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
