import os
from pathlib import Path
from dotenv import load_dotenv

project_root = Path(__file__).resolve().parents[1]

# Use TEST_DATABASE_URL if explicitly provided.
test_database_url = os.getenv("TEST_DATABASE_URL")

# Otherwise, use DATABASE_URL supplied by CI.
if not test_database_url:
    test_database_url = os.getenv("DATABASE_URL")

# If neither variable exists, load the local .env.test file.
if not test_database_url:
    load_dotenv(project_root / ".env.test", override=True)
    test_database_url = os.getenv("TEST_DATABASE_URL")

if not test_database_url:
    raise RuntimeError(
        "Test database URL is missing. Configure TEST_DATABASE_URL "
        "or DATABASE_URL, or provide .env.test."
    )

# Safety check: never run tests against the production database.
database_name = test_database_url.rsplit("/", 1)[-1].split("?")[0]

if database_name != "trade_store_test":
    raise RuntimeError(
        f"Tests must run only against trade_store_test! "
        f"Configured database: {database_name}"
    )

os.environ["DATABASE_URL"] = test_database_url