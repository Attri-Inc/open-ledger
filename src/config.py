from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = os.getenv("OPENLEDGER_DB", str(BASE_DIR / "data" / "openledger.db"))
MCP_PORT = int(os.getenv("MCP_PORT", "8791"))
