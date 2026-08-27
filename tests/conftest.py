import os
import tempfile
from pathlib import Path

TEST_DATA = Path(tempfile.mkdtemp(prefix="receipt-ledger-tests-"))
os.environ["DATA_DIR"] = str(TEST_DATA)
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DATA / 'test.db'}"
os.environ["APP_PASSWORD"] = "correct-horse-battery-staple"
os.environ["SESSION_SECRET"] = "test-session-secret-that-is-long-enough"
os.environ["AI_PROVIDER"] = "openai"
# Empty environment values override any developer credentials in the local
# .env file so tests can never make live provider calls.
os.environ["OPENAI_API_KEY"] = ""
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["GEMINI_API_KEY"] = ""
