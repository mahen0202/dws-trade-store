
import os
import asyncio
from datetime import date, timedelta
from unittest.mock import patch, MagicMock

from dotenv import load_dotenv
from sqlalchemy.exc import SQLAlchemyError

# Load local test configuration.
# GitHub Actions supplies DATABASE_URL through its workflow environment.
load_dotenv(".env.test")

if not os.getenv("DATABASE_URL"):
    test_database_url = os.getenv("TEST_DATABASE_URL")

    if not test_database_url:
        raise RuntimeError("TEST_DATABASE_URL is not configured")

    os.environ["DATABASE_URL"] = test_database_url

# Safety guard: never run automated tests against the development database.
if not os.environ["DATABASE_URL"].endswith("/trade_store_test"):
    raise RuntimeError(
        "Tests must run only against a database named trade_store_test!"
    )

# Import application modules only after database configuration.
import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.expiry import expire_matured_trades
from app.models import Trade
from app.schemas import TradeCreate
from app.services import save_trade
from app.main import app, lifespan


client = TestClient(app)


# --------------------------------------------------
# Database fixture
# --------------------------------------------------

@pytest.fixture(autouse=True)
def clean_database():
    """Clean the isolated test database before and after each test."""
    db = SessionLocal()

    try:
        db.query(Trade).delete()
        db.commit()
        yield
    finally:
        db.query(Trade).delete()
        db.commit()
        db.close()


# --------------------------------------------------
# Test data helper
# --------------------------------------------------

def sample_trade(trade_id="T1", version=1, **overrides):
    trade = {
        "trade_id": trade_id,
        "version": version,
        "counterparty_id": "CP-1",
        "portfolio_id": "PF-1",
        "maturity_date": (
            date.today() + timedelta(days=90)
        ).isoformat(),
        "created_date": date.today().isoformat(),
    }

    trade.update(overrides)
    return trade


# --------------------------------------------------
# Trade creation and version management
# --------------------------------------------------

def test_create_trade_successfully():
    response = client.post("/trades", json=sample_trade())

    assert response.status_code == 201
    assert response.json()["trade_id"] == "T1"
    assert response.json()["version"] == 1


def test_same_version_replaces_existing_trade():
    client.post("/trades", json=sample_trade())

    updated_trade = sample_trade(
        version=1,
        counterparty_id="CP-2",
        portfolio_id="PF-2",
    )

    response = client.post("/trades", json=updated_trade)

    assert response.status_code == 201
    assert response.json()["counterparty_id"] == "CP-2"
    assert response.json()["portfolio_id"] == "PF-2"


def test_higher_version_updates_existing_trade():
    client.post("/trades", json=sample_trade(version=1))

    response = client.post(
        "/trades",
        json=sample_trade(version=2),
    )

    assert response.status_code == 201
    assert response.json()["version"] == 2


def test_lower_version_is_rejected():
    client.post("/trades", json=sample_trade(version=2))

    response = client.post(
        "/trades",
        json=sample_trade(version=1),
    )

    assert response.status_code == 409


def test_version_3_rejects_version_2_without_changing_existing_trade():
    client.post(
        "/trades",
        json=sample_trade(trade_id="VERSION_TEST", version=3),
    )

    response = client.post(
        "/trades",
        json=sample_trade(
            trade_id="VERSION_TEST",
            version=2,
            counterparty_id="CP-OLD",
        ),
    )

    assert response.status_code == 409

    current = client.get("/trades/VERSION_TEST")

    assert current.status_code == 200
    assert current.json()["version"] == 3
    assert current.json()["counterparty_id"] == "CP-1"


# --------------------------------------------------
# Maturity date and expiry tests
# --------------------------------------------------

def test_past_maturity_date_is_rejected():
    response = client.post(
        "/trades",
        json=sample_trade(
            maturity_date=(
                date.today() - timedelta(days=1)
            ).isoformat()
        ),
    )

    assert response.status_code == 400


def test_trade_maturing_today_is_not_expired():
    response = client.post(
        "/trades",
        json=sample_trade(
            trade_id="SAME_DAY_TEST",
            maturity_date=date.today().isoformat(),
        ),
    )

    assert response.status_code == 201
    assert response.json()["expired"] is False


def test_new_trade_is_not_expired():
    response = client.post(
        "/trades",
        json=sample_trade(),
    )

    assert response.status_code == 201
    assert response.json()["expired"] is False


def test_matured_trade_is_marked_expired():
    db = SessionLocal()

    try:
        matured_trade = Trade(
            trade_id="EXPIRY_AUTO_TEST",
            version=1,
            counterparty_id="CP-TEST",
            portfolio_id="PF-TEST",
            maturity_date=date.today() - timedelta(days=1),
            created_date=date.today() - timedelta(days=10),
            expired=False,
        )

        db.add(matured_trade)
        db.commit()

        expire_matured_trades()

        db.refresh(matured_trade)

        assert matured_trade.expired is True

    finally:
        db.rollback()
        db.close()


def test_expiry_job_can_run_multiple_times():
    db = SessionLocal()

    try:
        trade = Trade(
            trade_id="EXPIRY_IDEMPOTENT_TEST",
            version=1,
            counterparty_id="CP-TEST",
            portfolio_id="PF-TEST",
            maturity_date=date.today() - timedelta(days=1),
            created_date=date.today() - timedelta(days=10),
            expired=False,
        )

        db.add(trade)
        db.commit()

        expire_matured_trades()
        expire_matured_trades()

        db.refresh(trade)

        assert trade.expired is True

    finally:
        db.rollback()
        db.close()


def test_expiry_failure_rolls_back_and_closes_database():
    mock_db = MagicMock()

    mock_db.execute.side_effect = SQLAlchemyError(
        "Simulated expiry failure"
    )

    with patch(
        "app.expiry.SessionLocal",
        return_value=mock_db,
    ):
        with pytest.raises(SQLAlchemyError):
            expire_matured_trades()

    mock_db.rollback.assert_called_once()
    mock_db.close.assert_called_once()


# --------------------------------------------------
# Trade retrieval tests
# --------------------------------------------------

def test_get_existing_trade():
    client.post("/trades", json=sample_trade())

    response = client.get("/trades/T1")

    assert response.status_code == 200
    assert response.json()["trade_id"] == "T1"


def test_get_nonexistent_trade():
    response = client.get("/trades/UNKNOWN")

    assert response.status_code == 404


# --------------------------------------------------
# Database transaction rollback test
# --------------------------------------------------

def test_database_commit_failure_triggers_rollback():
    db = MagicMock()

    db.execute.return_value.scalar_one_or_none.return_value = None
    db.commit.side_effect = SQLAlchemyError(
        "Simulated database failure"
    )

    trade_data = TradeCreate(
        trade_id="ROLLBACK_TEST",
        version=1,
        counterparty_id="CP-TEST",
        portfolio_id="PF-TEST",
        maturity_date=date.today() + timedelta(days=30),
        created_date=date.today(),
    )

    with pytest.raises(SQLAlchemyError):
        save_trade(db, trade_data)

    db.rollback.assert_called_once()


# --------------------------------------------------
# API input validation tests
# --------------------------------------------------

def test_trade_with_invalid_version_is_rejected():
    response = client.post(
        "/trades",
        json=sample_trade(version=0),
    )

    assert response.status_code == 422


def test_trade_with_missing_required_field_is_rejected():
    trade = sample_trade()
    trade.pop("counterparty_id")

    response = client.post("/trades", json=trade)

    assert response.status_code == 422


def test_trade_with_invalid_maturity_date_is_rejected():
    response = client.post(
        "/trades",
        json=sample_trade(
            maturity_date="not-a-valid-date"
        ),
    )

    assert response.status_code == 422


def test_trade_with_empty_trade_id_is_rejected():
    response = client.post(
        "/trades",
        json=sample_trade(trade_id=""),
    )

    assert response.status_code == 422


def test_trade_with_counterparty_id_exceeding_max_length_is_rejected():
    response = client.post(
        "/trades",
        json=sample_trade(counterparty_id="C" * 101),
    )

    assert response.status_code == 422


def test_trade_with_empty_portfolio_id_is_rejected():
    response = client.post(
        "/trades",
        json=sample_trade(portfolio_id=""),
    )

    assert response.status_code == 422


# --------------------------------------------------
# Health endpoint test
# --------------------------------------------------

def test_health_endpoint_returns_up():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "UP"}


# --------------------------------------------------
# Application scheduler lifecycle test
# --------------------------------------------------

def test_application_lifespan_starts_and_stops_scheduler():
    mock_app = MagicMock()

    with (
        patch("app.main.expire_matured_trades") as mock_expiry,
        patch("app.main.scheduler") as mock_scheduler,
    ):

        async def run_lifespan():
            async with lifespan(mock_app):
                mock_expiry.assert_called_once()
                mock_scheduler.add_job.assert_called_once()
                mock_scheduler.start.assert_called_once()

            mock_scheduler.shutdown.assert_called_once()

        asyncio.run(run_lifespan())
