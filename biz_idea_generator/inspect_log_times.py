import os
import requests
import datetime
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("LIMITLESS_API_KEY")

if __name__ == "__main__":
    output = []
    def log(s):
        print(s)
        output.append(s)

    if not API_KEY:
        log("Error: API Key not found in .env")
    else:
        # Check LifeLogs
        url = "https://api.limitless.ai/v1/lifelogs"
        log(f"--- Checking LifeLogs ({url}) ---")
        try:
            r = requests.get(url, headers={"X-API-Key": API_KEY}, params={'limit': 5})
            log(f"Status: {r.status_code}")
            if r.status_code == 200:
                data = r.json()
                items = data.get('data', {}).get('lifelogs', [])
                log(f"Items: {len(items)}")
                for i in items:
                    log(f"TS: {i.get('startTime', 'N/A')}")
            else:
                log(f"Error: {r.text[:100]}")
        except Exception as e:
            log(f"Exc: {e}")

        # Check Meetings
        url = "https://api.limitless.ai/v1/meetings"
        log(f"\n--- Checking Meetings ({url}) ---")
        try:
            r = requests.get(url, headers={"X-API-Key": API_KEY}, params={'limit': 5})
            log(f"Status: {r.status_code}")
            if r.status_code == 200:
                data = r.json()
                items = data.get('data', {}).get('meetings', [])
                # Or maybe direct list?
                if isinstance(data.get('data'), list): items = data['data']
                
                log(f"Items: {len(items)}")
                for i in items:
                    log(f"Title: {i.get('title', 'N/A')} TS: {i.get('startTime', 'N/A')}")
            else:
                log(f"Error: {r.text[:100]}")
        except Exception as e:
            log(f"Exc: {e}")

    with open("diagnostic_report.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(output))
