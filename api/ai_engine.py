# api/ai_engine.py
import os
import json
from google import genai
from google.genai import types
from dotenv import load_dotenv

# 1. Load Environment Variables
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY is missing! Check your .env file.")

# 2. Initialize the new Client format
client = genai.Client(api_key=GEMINI_API_KEY)

def analyze_crop_image(image_file):
    """Sends the image to Gemini Vision to dynamically generate disease & treatment data."""
    try:
        # Read the raw bytes and mime type directly from Django's uploaded file object
        image_bytes = image_file.read()
        mime_type = image_file.content_type or 'image/jpeg'
        
        # The System Prompt
        prompt = """
        You are an expert, highly experienced agronomist. Analyze this image of a crop.
        Identify if there is a disease, pest, or nutrient deficiency.
        
        Return ONLY a valid JSON object.
        The JSON must contain exactly these 4 keys:
        {
            "disease": "Name of the crop and the issue (e.g. 'Tomato Late Blight', or 'Healthy Crop')",
            "severity": integer from 1 to 5 (1 = Healthy, 5 = Critical/Severe),
            "confidence": integer from 1 to 100 representing your confidence percentage,
            "treatment": "A detailed, actionable, 2-3 sentence treatment plan for the farmer. If healthy, provide maintenance advice."
        }
        """

        # Call the Vision API using the new Client format and strict JSON config
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[
                prompt,
                types.Part.from_bytes(
                    data=image_bytes,
                    mime_type=mime_type
                )
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json", # Forces perfect JSON output!
            )
        )

        # Parse the dynamically generated JSON natively
        ai_result = json.loads(response.text)

        # Validate the keys exist so the React frontend doesn't crash
        required_keys = ["disease", "severity", "confidence", "treatment"]
        for key in required_keys:
            if key not in ai_result:
                raise ValueError(f"AI failed to generate the required key: {key}")

        return ai_result

    except json.JSONDecodeError:
        print(f"Failed to parse AI response: {response.text}")
        raise ValueError("AI returned invalid data format. Please try again.")
    except Exception as e:
        print(f"Generative AI Engine Error: {e}")
        raise ValueError(str(e))