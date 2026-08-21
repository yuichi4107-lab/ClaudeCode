import os
import requests
from dotenv import load_dotenv
import json

load_dotenv()

API_KEY = os.getenv("LIMITLESS_API_KEY")
API_URL = "https://api.limitless.ai/v1/lifelogs"

def inspect():
    headers = {"X-API-Key": API_KEY}
    
    # Check keys first
    gemini_key = os.getenv("GEMINI_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    
    with open("key_status.txt", "w") as f:
        f.write(f"GEMINI_API_KEY: {'Found' if gemini_key else 'Missing'}\n")
        f.write(f"OPENAI_API_KEY: {'Found' if openai_key else 'Missing'}\n")

    try:
        response = requests.get(API_URL, headers=headers)
        if response.status_code != 200:
            with open("inspection_result.txt", "w", encoding="utf-8") as f:
                f.write(f"Error: {response.status_code}\n{response.text}")
            return

        data = response.json()
        
        with open("inspection_result.txt", "w", encoding="utf-8") as f:
            f.write(f"Data Type: {type(data)}\n")
            
            if isinstance(data, list):
                f.write(f"Item Count: {len(data)}\n")
                if len(data) > 0:
                    f.write(f"First Item Keys: {list(data[0].keys())}\n")
                    f.write(f"Sample Item: {json.dumps(data[0], indent=2)[:1000]}\n")
            elif isinstance(data, dict):
                f.write(f"Keys: {list(data.keys())}\n")
                # Check for common wrapper keys
                if 'data' in data:
                    inner_data = data['data']
                    f.write(f"Inner Data Type: {type(inner_data)}\n")
                    
                    if isinstance(inner_data, dict):
                        f.write(f"Inner Data Keys: {list(inner_data.keys())}\n")
                        f.write(f"Inner Data Sample: {json.dumps(inner_data, indent=2)[:1000]}\n")
                    elif isinstance(inner_data, list):
                        f.write(f"Inner Data is List. Count: {len(inner_data)}\n")
                        if len(inner_data) > 0:
                            f.write(f"First Item Keys: {list(inner_data[0].keys())}\n")
                            f.write(f"Sample Inner Item: {json.dumps(inner_data[0], indent=2)[:1000]}\n")

                elif 'results' in data:
                    f.write(f"Inner Data (results) Type: {type(data['results'])}\n")
                    if isinstance(data['results'], list) and len(data['results']) > 0:
                         f.write(f"First Inner Item Keys: {list(data['results'][0].keys())}\n")

    except Exception as e:
        with open("inspection_result.txt", "w", encoding="utf-8") as f:
            f.write(f"Exception: {e}")

if __name__ == "__main__":
    inspect()
