import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("No GEMINI_API_KEY found.")
else:
    genai.configure(api_key=api_key)
    try:
        print("Listing available models...")
        with open("models_dump.txt", "w", encoding="utf-8") as f:
            for m in genai.list_models():
                if 'generateContent' in m.supported_generation_methods:
                    f.write(m.name + "\n")
                    print(m.name)
    except Exception as e:

        print(f"Error listing models: {e}")
