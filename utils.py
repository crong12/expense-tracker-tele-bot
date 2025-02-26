import json

def str_to_json(text: str):
    try:
        json_response = json.loads(text)
        return json_response
    
    except json.JSONDecodeError:
        return ("error: Failed to parse response as JSON")