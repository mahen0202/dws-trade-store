
from contextlib import asynccontextmanager
from datetime import date
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Trade
from app.schemas import TradeCreate, TradeResponse
from app.services import save_trade
from app.expiry import expire_matured_trades


scheduler = BackgroundScheduler(timezone=ZoneInfo("Asia/Kolkata"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Run immediately when the application starts.
    expire_matured_trades()

    # Schedule daily execution at 12:01 AM.
    scheduler.add_job(
        expire_matured_trades,
        trigger="cron",
        hour=0,
        minute=1,
        id="trade_expiry_job",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )

    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(
    title="Deutsche Bank Trade Store",
    lifespan=lifespan,
)


@app.post("/trades", response_model=TradeResponse, status_code=201)
def create_trade(
    trade_data: TradeCreate,
    db: Session = Depends(get_db),
):
    return save_trade(db, trade_data)


# Shared filtering and pagination logic.
def get_trade_records(
    db: Session,
    skip: int,
    limit: int,
    include_expired: bool,
):
    query = select(Trade)

    if not include_expired:
        query = query.where(
            Trade.expired.is_(False),
            Trade.maturity_date >= date.today(),
        )

    # Consistent ordering before pagination.
    query = query.order_by(Trade.trade_id)
    query = query.offset(skip).limit(limit)

    return db.execute(query).scalars().all()


@app.get("/trades", response_model=list[TradeResponse])
def get_all_trades(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=10, ge=1, le=100),
    include_expired: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    return get_trade_records(db, skip, limit, include_expired)


@app.get("/trades/{trade_id}", response_model=TradeResponse)
def get_trade(
    trade_id: str,
    db: Session = Depends(get_db),
):
    trade = db.execute(
        select(Trade).where(Trade.trade_id == trade_id)
    ).scalar_one_or_none()

    if trade is None:
        raise HTTPException(status_code=404, detail="Trade not found")

    # Update expiry immediately when a matured trade is requested.
    if trade.maturity_date < date.today() and not trade.expired:
        trade.expired = True
        db.commit()
        db.refresh(trade)

    # Do not return expired trades.
    if trade.expired:
        raise HTTPException(status_code=404, detail="Trade has expired")

    return trade


@app.get("/health")
def health_check():
    return {"status": "UP"}
