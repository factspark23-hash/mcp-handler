#!/usr/bin/env python3
"""MCP Hub entry point - handles path setup then runs main."""
import sys
import os

# Find the project root (where src/ lives)
# When installed editable, __file__ points to the project
# When installed normally, we need to find src relative to the package
_script_dir = os.path.dirname(os.path.abspath(__file__))

# Try common locations for src/
candidates = [
    os.path.join(_script_dir, "..", "src"),           # editable: bin/../src
    os.path.join(_script_dir, "..", "..", "src"),     # editable: deeper
    os.path.join(os.getcwd(), "src"),                  # cwd/src
]

# Also try the editable project location
try:
    import importlib.metadata
    dist = importlib.metadata.distribution("mcp-hub")
    if dist.read_text("direct_url.json"):
        import json
        direct = json.loads(dist.read_text("direct_url.json"))
        if "url" in direct and "file://" in direct["url"]:
            proj_dir = direct["url"].replace("file://", "")
            candidates.insert(0, os.path.join(proj_dir, "src"))
except Exception:
    pass

for candidate in candidates:
    if os.path.isdir(candidate) and os.path.exists(os.path.join(candidate, "server.py")):
        parent = os.path.dirname(candidate)
        if parent not in sys.path:
            sys.path.insert(0, parent)
        break

from src.server import main

if __name__ == "__main__":
    main()
