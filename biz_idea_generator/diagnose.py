import sys
print("Step 1: Start", file=sys.stderr)
try:
    from dotenv import load_dotenv
    print("Step 2: Imported dotenv", file=sys.stderr)
    load_dotenv()
    print("Step 3: Loaded dotenv", file=sys.stderr)
    from src.limitless_client import LimitlessClient
    print("Step 4: Imported LimitlessClient", file=sys.stderr)
    import src.main
    print("Step 5: Imported main", file=sys.stderr)
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
