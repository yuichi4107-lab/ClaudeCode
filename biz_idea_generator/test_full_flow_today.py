import datetime
from src.limitless_client import LimitlessClient
from src.llm_client import LLMClient
from src.pdf_converter import convert_to_pdf
from src.notifier import send_email
from dotenv import load_dotenv
import os

def run_test_today():
    load_dotenv()
    
    # 1. Fetch Today's Logs
    target_date = datetime.date.today()
    print(f"Test Run: Fetching logs for TODAY: {target_date}")
    
    limitless = LimitlessClient()
    logs = limitless.fetch_logs(date=target_date)
    
    if not logs:
        print("No logs found for today yet.")
        return

    context_text = "\n".join(logs)
    print(f"Fetched {len(logs)} fragments.")

    # 2. Analyze
    print("Generating report...")
    llm = LLMClient()
    report_md = llm.generate_business_plan(context_text)
    
    # 3. PDF
    output_filename = f"reports/TargetTest_{target_date}.md"
    pdf_filename = output_filename.replace(".md", ".pdf")
    
    with open(output_filename, "w", encoding="utf-8") as f:
        f.write(report_md)
        
    print("Converting to PDF...")
    if convert_to_pdf(report_md, pdf_filename):
        print(f"PDF Success: {pdf_filename}")
        
        # 4. Email
        subject = f"【テスト成功】ビジネスの種 ({target_date})"
        body = "新しいAPIキーで、本日のデータ（2025-12-21）が正しく取得できました。\nレポートを添付します。"
        
        print("Sending Email...")
        if send_email(subject, body, pdf_filename):
            print("Email Sent Successfully!")
        else:
            print("Email Failed.")
    else:
        print("PDF Failed.")

if __name__ == "__main__":
    run_test_today()
