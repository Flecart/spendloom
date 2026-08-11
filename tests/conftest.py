import os
import tempfile
from pathlib import Path

TEST_DATA = Path(tempfile.mkdtemp(prefix="receipt-ledger-tests-"))
os.environ["DATA_DIR"] = str(TEST_DATA)
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DATA / 'test.db'}"
os.environ["APP_PASSWORD"] = "correct-horse-battery-staple"
os.environ["SESSION_SECRET"] = "test-session-secret-that-is-long-enough"
os.environ.pop("OPENAI_API_KEY", None)
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("GEMINI_API_KEY", None)
