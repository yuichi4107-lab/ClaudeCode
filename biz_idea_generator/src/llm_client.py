import os
import google.generativeai as genai
from openai import OpenAI

class LLMClient:
    def __init__(self):
        self.gemini_key = os.getenv("GEMINI_API_KEY")
        self.openai_key = os.getenv("OPENAI_API_KEY")
        self.provider = None
        
        if self.gemini_key:
            self.provider = "gemini"
            genai.configure(api_key=self.gemini_key)
            self.model = genai.GenerativeModel('gemini-2.5-flash')
        elif self.openai_key:



            self.provider = "openai"
            self.client = OpenAI(api_key=self.openai_key)
        else:
            raise ValueError("No valid LLM API Key found (GEMINI_API_KEY or OPENAI_API_KEY).")

    def generate_business_plan(self, context_text):
        if not context_text.strip():
            return "No conversation data available to analyze."

        prompt = f"""あなたはプロのビジネスコンサルタントです。
ユーザーの1日の会話ログを分析し、ビジネスの種を見つけてください。

**ユーザーの事業領域（5つ）:**
1. 電子書籍の執筆・