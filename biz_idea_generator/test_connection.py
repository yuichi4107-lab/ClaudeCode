import os
import requests
from dotenv import load_dotenv
import datetime

# Load environment variables
load_dotenv()

API_KEY = os.getenv("LIMITLESS_API_KEY")
API_URL = "https://api.limitless.ai/v1/lifelogs" # Hypothetical URL based on search, needs verification

def test_connection():
    if not API_KEY:
        print("Error: LIMITLESS_API_KEY not found in .env file.")
        return

    print(f"Testing connection with API Key: {API_KEY[:4]}...")

    headers = {
        "X-API-Key": API_KEY,  # Changed from Authorization: Bearer
        "Content-Type": "application/json"
    }

    # Try to fetch logs from the last 24 hours
    try:
        response = requests.get(API_URL, headers=headers)
        
        if response.status_code == 200:
            print("Successfully connected to Limitless API!")
            data = response.json()
            # print(f"Retrieved {len(data)} records (or raw response structure).") # len() might fail if not list
            print("--- Sample Data ---")
            print(str(data)[:500]) # Print first 500 chars to avoid huge logs
        else:
            print(f"Failed to connect. Status Code: {response.status_code}")
            print(f"Response: {response.text}")
            
    except Exception as e:
        print(f"An error occurred: {e}")

    # Check for LLM keys
    gemini_key = os.getenv("GEMINI_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    
    print("\n--- LLM Key Check ---")
    if gemini_key:
        print(f"Gemini API Key found: {gemini_key[:4]}...")
    else:
        print("Gemini API Key NOT found.")

    if openai_key:
        print(f"OpenAI API Key found: {openai_key[:4]}...")
    else:
        print("OpenAI API Key NOT found.")


if __name__ == "__main__":
    test_connection()
