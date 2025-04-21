import json
from datetime import datetime
from typing import Any
from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableLambda, RunnableWithFallbacks
from langgraph.prebuilt import ToolNode

def str_to_json(text: str) -> dict:
    """
    Converts given string to json format and formats output.
    Args:
        text (str): The string to be converted to json format.
    Returns:
        dict: The formatted json object.
    """
    try:
        json_response = json.loads(text)
        
        # Format dict fields
        json_response["currency"] = json_response["currency"].upper()
        json_response["category"] = json_response["category"].title()
        json_response["description"] = json_response["description"].title()
        return json_response

    except json.JSONDecodeError:
        return "error: Failed to parse response as JSON"

def get_current_date():
    """Get current date for LLM to infer actual expense date from relative date provided by user
    Returns:
        today's date (str): e.g. '2025-03-14'
        day associated with today's date (str): e.g. 'Friday'
    """
    now = datetime.today()
    return now.strftime('%Y-%m-%d'), now.strftime('%A')

# define util functions
def create_tool_node_with_fallback(tools: list) -> RunnableWithFallbacks[Any, dict]:
    """
    Create a ToolNode with a fallback to handle errors and surface them to the agent.
    """
    return ToolNode(tools).with_fallbacks(
        [RunnableLambda(handle_tool_error)], exception_key="error"
    )


def handle_tool_error(state) -> dict:
    """
    Surfaces error messages to the agent
    Returns:
        json object with error message to be passed to the agent
    """
    error = state.get("error")
    tool_calls = state["messages"][-1].tool_calls
    return {
        "messages": [
            ToolMessage(
                content=f"Error: {repr(error)}\n please fix your mistakes.",
                tool_call_id=tc["id"],
            )
            for tc in tool_calls
        ]
    }
