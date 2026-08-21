import os
import json
import datetime
from dotenv import load_dotenv
from src.limitless_client import LimitlessClient
from src.llm_client import LLMClient

# Load env vars
load_dotenv()

# Minimum thresholds for meaningful report generation
MIN_LOG_ENTRIES = 3
MIN_LOG_CHARS = 200

def main():
    print("Starting Daily Business Idea Generator...")

    # 1. Determine Target Date (Yesterday, assuming run in morning)
    target_date = datetime.date.today() - datetime.timedelta(days=1)
    print(f"Target Date: {target_date}")

    # 2. Fetch Logs
    try:
        limitless = LimitlessClient()
        logs = limitless.fetch_logs(date=target_date)
        stats = limitless.get_log_stats(logs)
        print(f"Fetched {stats['entries']} entries ({stats['total_chars']} chars, {stats['total_lines']} lines)")
    except Exception as e:
        print(f"Error fetching logs: {e}")
        return

    if not logs:
        print("No logs found for the target date. Skipping report generation.")
        return

    # 3. Quality gate: skip if data is too thin
    if stats['entries'] < MIN_LOG_ENTRIES or stats['total_chars'] < MIN_LOG_CHARS:
        print(f"Data too thin (entries={stats['entries']}, chars={stats['total_chars']}). "
              f"Minimum: entries>={MIN_LOG_ENTRIES}, chars>={MIN_LOG_CHARS}. Skipping.")
        return

    # 4. Combine Logs
    combined_text = "\n---\n".join(logs)

    # 5. Generate Business Plan
    try:
        llm = LLMClient()
        print("Analyzing with AI...")
        plan_content = llm.generate_business_plan(combined_text)
    except Exception as e:
        print(f"Error interacting with LLM: {e}")
        return

    # 6. Save Output
    output_dir = "reports"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    filename = f"BusinessPlan_{target_date}.md"
    file_path = os.path.join(output_dir, filename)
    
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(plan_content)
        
    print(f"Report saved to: {file_path}")

    # 7. Generate proposals for high-potential ideas (★4+)
    proposals_dir = os.path.join(output_dir, "proposals")
    if not os.path.exists(proposals_dir):
        os.makedirs(proposals_dir)

    print("Extracting top ideas for proposal generation...")
    try:
        ideas_json = llm.extract_top_ideas(plan_content)
        # Parse JSON from LLM response (strip markdown fences if present)
        cleaned = ideas_json.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()
        ideas = json.loads(cleaned)
        print(f"Found {len(ideas)} high-potential idea(s) (★4+).")
    except (json.JSONDecodeError, TypeError) as e:
        print(f"Could not parse ideas JSON: {e}")
        ideas = []

    for i, idea in enumerate(ideas):
        idea_name = idea.get("name", f"idea-{i+1}")
        safe_name = idea_name.replace(" ", "-").replace("/", "-")[:50]
        proposal_filename = f"{target_date}_{safe_name}.md"
        proposal_path = os.path.join(proposals_dir, proposal_filename)

        print(f"  Generating proposal: {idea_name}...")
        try:
            proposal_content = llm.generate_proposal(idea, combined_text)
            with open(proposal_path, "w", encoding="utf-8") as f:
                f.write(proposal_content)
            print(f"  Saved: {proposal_path}")
        except Exception as e:
            print(f"  Error generating proposal for '{idea_name}': {e}")

    # 8. Convert to PDF
    from src.pdf_converter import convert_to_pdf
    pdf_filename = filename.replace(".md", ".pdf")
    pdf_path = os.path.join(output_dir, pdf_filename)
    
    print("Converting to PDF...")
    if convert_to_pdf(plan_content, pdf_path):
        print(f"PDF saved to: {pdf_path}")
        attachment = pdf_path
    else:
        print("PDF conversion failed. Sending Markdown only.")
        attachment = None

    # 8. Notify User
    from src.notifier import send_line_notify, send_email
    
    proposal_count = len(ideas) if ideas else 0
    notify_msg = f"【ビジネスアイデア自動生成】\n日付: {target_date}\nログ: {stats['entries']}件 ({stats['total_chars']}文字)\nレポート生成完了。\n新規事業企画書: {proposal_count}件生成。\n内容はメール添付のPDF、または保存先フォルダをご確認ください。"
    
    print("Sending notifications...")
    send_line_notify(notify_msg) # LINE Notify doesn't support PDF upload easily
    
    email_subject = f"Business Idea Report: {target_date}"
    send_email(email_subject, "添付のビジネスプランレポートをご確認ください。", attachment)

    print("Done!")

if __name__ == "__main__":
    main()
