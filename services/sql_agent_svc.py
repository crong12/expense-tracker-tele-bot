import json
from datetime import datetime
from typing import Annotated, Literal
from langchain_core.tools import tool
from sqlalchemy.sql import text
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import AIMessage
from langchain_google_vertexai import ChatVertexAI
from pydantic import BaseModel, Field
from typing_extensions import TypedDict
from langgraph.graph import END, StateGraph, START
from langgraph.graph.message import AnyMessage, add_messages
from langgraph.types import StreamWriter
from langsmith import traceable
from database import SessionLocal
from utils import create_tool_node_with_fallback
from config import MODEL_NAME, REGION2, TEMPERATURE


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


# query checker
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


query_check = query_check_prompt | ChatVertexAI(model=MODEL_NAME, temperature=TEMPERATURE, location=REGION2, max_retries=10).bind_tools([db_query_tool], tool_choice='any')


# Define the state for the agent
class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


# Define a new graph
workflow = StateGraph(State)

@traceable(
  project_name="expense-tracking-tele-bot"
)
async def model_check_query(state: State, writer: StreamWriter) -> dict[str, list[AIMessage]]:
    """
    Use this tool to double-check if your query is correct before executing it.
    """
    writer({"custom": "🚦 Checking generated query for errors..."})
    response = await query_check.ainvoke({"messages": [state["messages"][-1]]})
    return {"messages": [response]}


# Describe a tool to represent the end state
class SubmitFinalAnswer(BaseModel):
    """Submit the final answer to the user based on the query results."""
    final_answer: str = Field(..., description="The final answer to the user")


today = datetime.today().strftime("%Y-%m-%d")
day = datetime.today().strftime("%A")

# Add a node for a model to generate a query based on the question and schema
QUERY_GEN_SYSTEM = f"""You are a SQL expert with a strong attention to detail.

Given an input question, output a syntactically correct PostgreSQL query to run, then look at the results of the query and return the answer.

Table name: 'expenses'

Schema: 
- Column('id', Integer(), primary_key=True, nullable=False),
- Column('user_id', UUID(), ForeignKey('users.id'), nullable=False),
- Column('price', Numeric(), nullable=False),
- Column('category', String(), nullable=False),
- Column('description', String(), nullable=False),
- Column('date', Date(), nullable=False),
- Column('currency', String(), nullable=False)

When generating the query:

DO NOT format the text in the query.
DO NOT use double quotes. 
DO NOT use escape characters.

For example, instead of returning "SELECT\n  user_id,\n  SUM(price) AS total_spent\nFROM expenses\nWHERE\n  date BETWEEN "2025-03-01" AND "2025-03-31"\nGROUP BY\n  user_id\nORDER BY\n  total_spent DESC\nLIMIT 1;\n",
return "SELECT user_id, SUM(price) AS total_spent FROM expenses WHERE date BETWEEN '2025-03-01' AND '2025-03-31' GROUP BY user_id ORDER BY total_spent DESC LIMIT 1;"

Today's date is {today}. Today is {day}. Infer the date requested by the user based on today's date.

Only query rows that belong to the user who made the query, based on the provided user_id in the query.

Category and description items should be in Title Case.

You can order the results by a relevant column to return the most interesting examples in the database.
Never query for all the columns from a specific table, only the relevant columns given the question.
Always query for currency as that is important information.

If you get an error while executing a query, rewrite the query and try again.

If you get an empty result set, you should try to rewrite the query to get a non-empty result set. 
NEVER make stuff up if you don't have enough information to answer the query... just say you don't have enough information.

DO NOT make any DML statements (INSERT, UPDATE, DELETE, DROP etc.) to the database."""

query_gen_prompt = ChatPromptTemplate.from_messages(
    [("system", QUERY_GEN_SYSTEM), ("placeholder", "{messages}")]
)
query_gen = query_gen_prompt | ChatVertexAI(model=MODEL_NAME,
                                            temperature=TEMPERATURE,
                                            location=REGION2,
                                            max_retries=10)

@traceable(
  project_name="expense-tracking-tele-bot"
)
async def query_gen_node(state: State, writer: StreamWriter):
    writer({"custom": "📝 Generating appropriate database query..."})
    message = await query_gen.ainvoke(state)
    return {"messages": [message]}


# Add a node to analyze query results and formulate a final answer
ANALYZE_RESULTS_SYSTEM = """You are a helpful SQL expert assistant that helps analyze query results.

When reviewing the SQL query and its results:
1. First, directly answer the user's original question with clear, actionable insights
2. Present the most important findings upfront in a concise summary
3. For financial/metric analysis, include relevant comparisons (% changes, trends, outliers)
4. Provide 1-2 unexpected or valuable observations from the data that the user may not have specifically asked for
5. Use a friendly, enthusiastic tone while maintaining professionalism

Format your response in Markdown. 
Do not return one long paragraph. Break it up into readable paragraph lengths.

For empty results, tell the user that something went wrong and to try again.

Remember that the user is looking for both answers and insights - help them understand what the data really means for their financial planning.
"""

analyze_results_prompt = ChatPromptTemplate.from_messages([
    ("system", ANALYZE_RESULTS_SYSTEM),
    ("placeholder", "{messages}"),
])

analyze_results = analyze_results_prompt | ChatVertexAI(model=MODEL_NAME,
                                                        max_tokens=512,
                                                        location=REGION2).bind_tools([SubmitFinalAnswer],
                                                                                    tool_choice='SubmitFinalAnswer')

@traceable(
  project_name="expense-tracking-tele-bot"
)
async def analyze_results_node(state: State, writer: StreamWriter):
    writer({"custom": "📊 Analyzing results to provide you an answer..."})
    # Create a new prompt with context from previous messages
    result = await analyze_results.ainvoke(state)

    result.tool_calls[0]["args"]["final_answer"] = result.tool_calls[0]["args"]["final_answer"].rstrip('\n')

    return {"messages": [result]}

# Add nodes to the workflow
workflow.add_node("query_gen", query_gen_node)
workflow.add_node("correct_query", model_check_query)
workflow.add_node("execute_query", create_tool_node_with_fallback([db_query_tool]))
workflow.add_node("analyze_results", analyze_results_node)


# Define a conditional edge after execute_query
def route_after_execution(state: State) -> Literal["analyze_results", "query_gen"]:
    messages = state["messages"]
    last_message = messages[-1]

    # Check if the message contains an error
    if isinstance(last_message.content, str) and "error" in last_message.content.lower():
        return "query_gen"  # If there's an error, go back to query generation
    else:
        return "analyze_results"  # Otherwise, analyze the results

# Specify the edges between the nodes
workflow.add_edge(START, "query_gen")
workflow.add_edge("query_gen", "correct_query")
workflow.add_edge("correct_query", "execute_query")
workflow.add_conditional_edges("execute_query", route_after_execution)
workflow.add_edge("analyze_results", END)

# Compile the workflow into a runnable
analyser_agent = workflow.compile()
