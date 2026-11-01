import os
from pathlib import Path
from dotenv import load_dotenv

project_root = Path(__file__).resolve().parents[1]

load_dotenv(project_root / ".env.test", override=True)

test_database_url = os.getenv("TEST_DATABASE_URL")

if not test_database_url:
    raise RuntimeError("TEST_DATABASE_URL is missing from .env.test")

os.environ["DATABASE_URL"] = test_database_url