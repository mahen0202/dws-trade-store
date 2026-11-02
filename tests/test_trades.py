
import os
import asyncio
import importlib

from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch, MagicMock

from fastapi import HTTPException
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

    #db.execute.return_value.scalar_one_or_none.return_value = None
    db.execute.return_value.scalar_one_or_none.return_value = Trade(
    trade_id="ROLLBACK_TEST",
    version=1,
    counterparty_id="CP-TEST",
    portfolio_id="PF-TEST",
    maturity_date=date.today() + timedelta(days=30),
    created_date=date.today(),
    expired=False,
    )


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


# --------------------------------------------------
# Database dependency cleanup test
# --------------------------------------------------

def test_get_db_closes_session_after_use():
    from app.database import get_db

    mock_db = MagicMock()

    with patch("app.database.SessionLocal", return_value=mock_db):
        db_generator = get_db()

        db = next(db_generator)
        assert db is mock_db

        db_generator.close()

        mock_db.close.assert_called_once()


# --------------------------------------------------
# Concurrent trade creation and update tests
# --------------------------------------------------

def test_concurrent_creation_of_same_trade_id_creates_one_record():
    barrier = Barrier(2)

    def create_trade(version):
        trade_data = TradeCreate(
            trade_id="CONCURRENT-001",
            version=version,
            counterparty_id=f"CP-{version}",
            portfolio_id=f"PF-{version}",
            maturity_date=date.today() + timedelta(days=30),
            created_date=date.today(),
        )

        with SessionLocal() as db:
            barrier.wait()
            return save_trade(db, trade_data)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(create_trade, 1),
            executor.submit(create_trade, 2),
        ]

        results = []
        for future in futures:
            try:
                results.append(future.result())
            except HTTPException as exc:
                results.append(exc.status_code)

    with SessionLocal() as db:
        stored = db.query(Trade).filter_by(
            trade_id="CONCURRENT-001"
        ).all()

    assert len(stored) == 1
    assert stored[0].version == 2
    assert all(
        isinstance(result, Trade) or result == 409
        for result in results
    )


def test_concurrent_updates_leave_highest_version():
    initial_trade = TradeCreate(
        trade_id="CONCURRENT-002",
        version=1,
        counterparty_id="CP-1",
        portfolio_id="PF-1",
        maturity_date=date.today() + timedelta(days=30),
        created_date=date.today(),
    )

    with SessionLocal() as db:
        save_trade(db, initial_trade)

    barrier = Barrier(2)

    def update_trade(version):
        trade_data = TradeCreate(
            trade_id="CONCURRENT-002",
            version=version,
            counterparty_id=f"CP-{version}",
            portfolio_id=f"PF-{version}",
            maturity_date=date.today() + timedelta(days=30),
            created_date=date.today(),
        )

        with SessionLocal() as db:
            barrier.wait()
            return save_trade(db, trade_data)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(update_trade, 2),
            executor.submit(update_trade, 3),
        ]

        results = []
        for future in futures:
            try:
                results.append(future.result())
            except HTTPException as exc:
                results.append(exc.status_code)

    with SessionLocal() as db:
        stored = db.get(Trade, "CONCURRENT-002")

    assert stored is not None
    assert stored.version == 3
    assert stored.counterparty_id == "CP-3"
    assert stored.portfolio_id == "PF-3"
    assert all(
        isinstance(result, Trade) or result == 409
        for result in results
    )


def test_concurrent_lower_version_cannot_overwrite_higher_version():
    initial_trade = TradeCreate(
        trade_id="CONCURRENT-003",
        version=3,
        counterparty_id="CP-3",
        portfolio_id="PF-3",
        maturity_date=date.today() + timedelta(days=30),
        created_date=date.today(),
    )

    with SessionLocal() as db:
        save_trade(db, initial_trade)

    barrier = Barrier(2)

    def update_trade(version):
        trade_data = TradeCreate(
            trade_id="CONCURRENT-003",
            version=version,
            counterparty_id=f"CP-{version}",
            portfolio_id=f"PF-{version}",
            maturity_date=date.today() + timedelta(days=30),
            created_date=date.today(),
        )

        with SessionLocal() as db:
            barrier.wait()
            return save_trade(db, trade_data)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(update_trade, 4),
            executor.submit(update_trade, 2),
        ]

        results = []
        for future in futures:
            try:
                results.append(future.result())
            except HTTPException as exc:
                results.append(exc.status_code)

    with SessionLocal() as db:
        stored = db.get(Trade, "CONCURRENT-003")

    assert stored is not None
    assert stored.version == 4
    assert stored.counterparty_id == "CP-4"
    assert stored.portfolio_id == "PF-4"
    assert 409 in results

def test_database_url_missing_raises_runtime_error(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with patch("dotenv.load_dotenv"):
        with pytest.raises(
            RuntimeError,
            match="DATABASE_URL environment variable is not configured"
        ):
            importlib.reload(importlib.import_module("app.database"))


# --------------------------------------------------
# GET all trades: filtering and pagination
# --------------------------------------------------

def test_get_all_trades_returns_active_trades():
    client.post("/trades", json=sample_trade(trade_id="GET-001"))
    client.post("/trades", json=sample_trade(trade_id="GET-002"))

    response = client.get("/trades")

    assert response.status_code == 200
    assert len(response.json()) == 2
    assert all(trade["expired"] is False for trade in response.json())


def test_get_all_trades_returns_empty_list():
    response = client.get("/trades")

    assert response.status_code == 200
    assert response.json() == []


def test_get_all_trades_includes_expired_trades():
    db = SessionLocal()

    try:
        expired_trade = Trade(
            trade_id="GET-EXPIRED",
            version=1,
            counterparty_id="CP-1",
            portfolio_id="PF-1",
            maturity_date=date.today() - timedelta(days=1),
            created_date=date.today() - timedelta(days=10),
            expired=True,
        )

        db.add(expired_trade)
        db.commit()
    finally:
        db.close()

    client.post("/trades", json=sample_trade(trade_id="GET-ACTIVE"))

    response = client.get("/trades?include_expired=true")

    assert response.status_code == 200

    records = response.json()

    assert len(records) == 2
    assert any(trade["expired"] is True for trade in records)
    assert any(trade["expired"] is False for trade in records)


def test_get_all_trades_excludes_expired_trades():
    db = SessionLocal()

    try:
        expired_trade = Trade(
            trade_id="GET-EXPIRED",
            version=1,
            counterparty_id="CP-1",
            portfolio_id="PF-1",
            maturity_date=date.today() - timedelta(days=1),
            created_date=date.today() - timedelta(days=10),
            expired=True,
        )

        db.add(expired_trade)
        db.commit()
    finally:
        db.close()

    client.post("/trades", json=sample_trade(trade_id="GET-ACTIVE"))

    response = client.get("/trades?include_expired=false")

    assert response.status_code == 200

    records = response.json()

    assert len(records) == 1
    assert records[0]["trade_id"] == "GET-ACTIVE"


def test_get_all_trades_pagination():
    for trade_id in ["PAGE-001", "PAGE-002", "PAGE-003"]:
        client.post("/trades", json=sample_trade(trade_id=trade_id))

    response = client.get("/trades?skip=1&limit=1")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["trade_id"] == "PAGE-002"


def test_get_all_trades_rejects_invalid_pagination():
    response = client.get("/trades?skip=-1")

    assert response.status_code == 422

    response = client.get("/trades?limit=101")

    assert response.status_code == 422


# --------------------------------------------------
# GET trade: expiry handling
# --------------------------------------------------

def test_get_matured_trade_marks_it_expired_and_returns_404():
    db = SessionLocal()

    try:
        matured_trade = Trade(
            trade_id="GET-MATURED",
            version=1,
            counterparty_id="CP-1",
            portfolio_id="PF-1",
            maturity_date=date.today() - timedelta(days=1),
            created_date=date.today() - timedelta(days=10),
            expired=False,
        )

        db.add(matured_trade)
        db.commit()
    finally:
        db.close()

    response = client.get("/trades/GET-MATURED")

    assert response.status_code == 404
    assert response.json()["detail"] == "Trade has expired"

    with SessionLocal() as db:
        stored_trade = db.get(Trade, "GET-MATURED")
        assert stored_trade.expired is True


def test_get_already_expired_trade_returns_404():
    db = SessionLocal()

    try:
        expired_trade = Trade(
            trade_id="GET-ALREADY-EXPIRED",
            version=1,
            counterparty_id="CP-1",
            portfolio_id="PF-1",
            maturity_date=date.today() - timedelta(days=1),
            created_date=date.today() - timedelta(days=10),
            expired=True,
        )

        db.add(expired_trade)
        db.commit()
    finally:
        db.close()

    response = client.get("/trades/GET-ALREADY-EXPIRED")

    assert response.status_code == 404
    assert response.json()["detail"] == "Trade has expired"
