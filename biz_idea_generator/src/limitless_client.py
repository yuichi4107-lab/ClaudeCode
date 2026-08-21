import os
import requests
import datetime
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("LIMITLESS_API_KEY")
API_BASE = "https://api.limitless.ai/v1"
TIMEZONE = os.getenv("LIMITLESS_TIMEZONE", "Asia/Tokyo")


class LimitlessClient:
    def __init__(self, api_key=None):
        self.api_key = api_key or API_KEY
        if not self.api_key:
            raise ValueError("LIMITLESS_API_KEY not found in environment variables.")
        self.headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json"
        }

    def fetch_lifelogs(self, date=None, limit=10, include_contents=True):
        """
        Fetch lifelogs for a specific date.
        If date is None, defaults to yesterday.
        Returns a list of lifelog dicts.
        """
        if date is None:
            date = datetime.date.today() - datetime.timedelta(days=1)

        all_lifelogs = []
        params = {
            "timezone": TIMEZONE,
            "limit": limit,
            "includeMarkdown": "true",
            "includeHeadings": "true",
            "includeContents": str(include_contents).lower(),
        }
        if date is not False:
            params["date"] = date.strftime("%Y-%m-%d")

        cursor = None
        page = 0

        while True:
            page += 1
            if cursor:
                params["cursor"] = cursor

            print(f"  Fetching lifelogs page {page} (date={params.get('date', 'ALL')})...")
            response = requests.get(f"{API_BASE}/lifelogs", headers=self.headers, params=params)
            response.raise_for_status()
            data = response.json()

            items = data.get("data", {}).get("lifelogs", [])
            if not items:
                break

            all_lifelogs.extend(items)

            # Cursor pagination: meta.lifelogs.nextCursor
            next_cursor = data.get("meta", {}).get("lifelogs", {}).get("nextCursor")
            if next_cursor and next_cursor != cursor:
                cursor = next_cursor
            else:
                break

        print(f"  Total: {len(all_lifelogs)} lifelogs across {page} page(s).")
        return all_lifelogs

    def fetch_chats(self, limit=100):
        """Fetch chat history."""
        all_chats = []
        params = {
            "timezone": TIMEZONE,
            "limit": limit,
            "direction": "desc",
        }
        cursor = None
        page = 0

        while True:
            page += 1
            if cursor:
                params["cursor"] = cursor

            print(f"  Fetching chats page {page}...")
            response = requests.get(f"{API_BASE}/chats", headers=self.headers, params=params)
            response.raise_for_status()
            data = response.json()

            items = data.get("data", {}).get("chats", [])
            if not items:
                break

            all_chats.extend(items)

            next_cursor = data.get("meta", {}).get("chats", {}).get("nextCursor")
            if next_cursor and next_cursor != cursor:
                cursor = next_cursor
            else:
                break

        print(f"  Total: {len(all_chats)} chats across {page} page(s).")
        return all_chats

    def lifelog_to_markdown(self, lifelog):
        """Convert a single lifelog to markdown."""
        lines = []
        title = lifelog.get("title", "Untitled")
        start = lifelog.get("startTime", "")
        end = lifelog.get("endTime", "")
        lines.append(f"## {title}")
        lines.append(f"- **Start**: {start}")
        lines.append(f"- **End**: {end}")
        lines.append(f"- **Starred**: {lifelog.get('isStarred', False)}")
        lines.append("")

        # Use markdown field if available
        md = lifelog.get("markdown")
        if md:
            lines.append(md)
            return "\n".join(lines)

        # Fallback to contents
        for block in lifelog.get("contents", []):
            time_str = ""
            if "startTime" in block:
                try:
                    dt_obj = datetime.datetime.fromisoformat(block["startTime"])
                    time_str = f"[{dt_obj.strftime('%H:%M')}] "
                except (ValueError, TypeError):
                    pass

            speaker = ""
            if block.get("speakerName"):
                speaker = f"**{block['speakerName']}**: "

            content = block.get("content", "").strip()
            btype = block.get("type", "")

            if btype == "heading1":
                lines.append(f"### {content}")
            elif btype == "heading2":
                lines.append(f"#### {content}")
            elif btype == "blockquote":
                lines.append(f"> {time_str}{speaker}{content}")
            else:
                lines.append(f"{time_str}{speaker}{content}")

        return "\n".join(lines)

    def extract_text(self, item):
        """Extract readable text from a single lifelog item (legacy compat)."""
        if "contents" not in item:
            return ""
        parts = []
        for block in item["contents"]:
            time_str = ""
            if "startTime" in block:
                try:
                    dt_obj = datetime.datetime.fromisoformat(block["startTime"])
                    time_str = dt_obj.strftime("[%H:%M] ")
                except (ValueError, TypeError):
                    pass
            speaker = ""
            if block.get("speakerName"):
                speaker = f"({block['speakerName']}) "
            if block.get("content", "").strip():
                parts.append(f"{time_str}{speaker}{block['content']}")
        return "\n".join(parts)

    def get_log_stats(self, logs):
        """Return basic stats about fetched logs."""
        total_chars = sum(len(log) for log in logs)
        total_lines = sum(log.count("\n") + 1 for log in logs)
        return {
            "entries": len(logs),
            "total_chars": total_chars,
            "total_lines": total_lines,
        }


if __name__ == "__main__":
    client = LimitlessClient()
    yesterday = datetime.date.today() - datetime.timedelta(days=1)
    lifelogs = client.fetch_lifelogs(yesterday)
    print(f"Fetched {len(lifelogs)} lifelogs")
    if lifelogs:
        print("--- First entry (preview) ---")
        print(client.lifelog_to_markdown(lifelogs[0])[:500])
