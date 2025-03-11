from datetime import datetime
import vertexai
from vertexai.generative_models import GenerativeModel, GenerationConfig, Part
from tenacity import retry, wait_random_exponential
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
    
    Today's date is {today}. Today is {day}. Extrapolate the expense date based on today's date.
    
    Make sure to include: 
    CURRENCY (if unspecified, default is SGD. Assume that $ is SGD, not USD. Make sure to return only the 3-letter symbol (example: GBP, SGD, EUR, JPY, MYR, RMB));
    PRICE (return 2 DECIMAL PLACES AT ALL TIMES, even if an integer price is provided);
    CATEGORY (think about what it should be based on the item or place provided);
    DESCRIPTION (this can just be the place or store name, if specified. If a shop name is not specified or is unclear, be more detailed in the description, 
    but make sure to only include whatever is already in the user input. return output in Title Case); 
    DATE (be extra careful if the user inputs terms like "last Tuesday" or "last Monday". Count backwards carefully to find the exact date from today's date).
    """
    response = await model.generate_content_async(
        contents=prompt, generation_config=expense_config
    )
    return response.text

# function to call gemini to process expense (e.g. receipt) image
# implement exponential backoff for load handling
@retry(wait=wait_random_exponential(multiplier=1, max=60))
async def process_expense_image(image_path: str):
    """parses expense details from image input
    Args:
        image_path (str): path to image sent by user
    """
    prompt = f"""
    Extract structured expense details from the image.
    
    Instructions:
    - Look for the TOTAL amount (usually near the bottom, labeled as "TOTAL", "GRAND TOTAL", "AMOUNT DUE", etc.). Return 2 DECIMAL PLACES AT ALL TIMES, even if an integer price is provided.
    - Today's date is {today}. Today is {day}. Extrapolate the expense date based on today's date. 
    - Use receipt date if available; otherwise, infer a reasonable date based on context.
    - Be extra careful if the user inputs terms like "last Tuesday" or "last Monday". Count backwards carefully to find the exact date from today's date.
    - For currency, default to SGD if unspecified. Assume $ means SGD unless context suggests otherwise.
    - Make sure to return only the 3-letter symbol (example: GBP, SGD, EUR, JPY, MYR, RMB).
    - For description, use the store/vendor name or a summary of the main purchase. Return output in Title Case.
    - For category, determine a suitable category based on the vendor or purchased items.
    """

    with open(image_path, "rb") as img_file:
        image_bytes = img_file.read()

    image_part = Part.from_data(
        mime_type="image/png",
        data=image_bytes
    )

    response = await model.generate_content_async(
        contents=[image_part, prompt],
        generation_config=expense_config
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
