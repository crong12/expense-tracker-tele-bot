import vertexai
from vertexai.generative_models import GenerativeModel, GenerationConfig
from tenacity import retry, wait_random_exponential
from datetime import datetime
from config import PROJECT_ID, REGION, MODEL_NAME, TEMPERATURE

vertexai.init(project=PROJECT_ID, location=REGION)

model = GenerativeModel(MODEL_NAME)

expense_schema = {
        "type": "OBJECT",
        "properties": {
            "currency": {"type": "STRING"},
            "price": {"type": "NUMBER"},
            "category": {"type": "STRING"},
            "description": {"type": "STRING"},
            "date": {"type": "STRING"},
        },
}

expense_config = GenerationConfig(temperature=TEMPERATURE,
                                  response_mime_type="application/json",
                                  response_schema=expense_schema)

# to convert relative date into actual date
today = datetime.today().strftime("%Y-%m-%d")
day = datetime.today().strftime("%A")

# function to call gemini to process expense text
# implement exponential backoff for load handling
@retry(wait=wait_random_exponential(multiplier=1, max=60))
async def process_expense_text(input_text: str):
    """parses expense details from plain text input
    Args:
        input_text (str): user input
    """
    prompt = f"""
    Extract structured expense details from this text: {input_text}. 
    
    Today's date is {today}. Today is {day}.
    Extrapolate the expense date based on today's date.
    
    Make sure to include: 
    CURRENCY (if unspecified, default is SGD. Assume that $ is SGD, not USD. Make sure to return only the 3-letter symbol (example: GBP, SGD, EUR, JPY, MYR, RMB))
    PRICE (return 2 decimal places AT ALL TIMES, even if an integer price is provided), 
    CATEGORY (think about what it should be based on the item or place provided), 
    DESCRIPTION (this can just be the place or store name, if specified. Output should be in Title Case), and 
    DATE (be extra careful if the user inputs terms like "last Tuesday" or "last Monday". Count backwards carefully to find the exact date from today's date).
    """
    response = await model.generate_content_async(
        contents=prompt, generation_config=expense_config
    )
    return response.text

# function to refine extracted expense details
# implement exponential backoff for load handling
@retry(wait=wait_random_exponential(multiplier=1, max=60))
async def refine_expense_details(original_details, user_feedback):
    """Refines the parsed expense details based on user corrections."""
    prompt = f"""
    Here are the originally parsed expense details:
    {original_details}
    
    The user has provided the following feedback for correction:
    {user_feedback}
    
    Please refine the expense details accordingly while keeping other details unchanged.
    """
    response = await model.generate_content_async(
        contents=prompt, generation_config=expense_config
    )
    return response.text