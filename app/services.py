
from datetime import date

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import Trade
from app.schemas import TradeCreate


def save_trade(db: Session, trade_data: TradeCreate):

    # Rule 1: Reject trades with maturity dates in the past.
    if trade_data.maturity_date < date.today():
        raise HTTPException(
            status_code=400,
            detail="Trade maturity date cannot be in the past",
        )

    try:
        # Rule 2: Find an existing trade using Trade ID.
        existing_trade = db.execute(
            select(Trade)
            .where(Trade.trade_id == trade_data.trade_id)
            .with_for_update()
        ).scalar_one_or_none()

        # Rule 3: Reject lower versions.
        if existing_trade and trade_data.version < existing_trade.version:
            raise HTTPException(
                status_code=409,
                detail="Lower trade version rejected",
            )

        # Rule 4: Create or update the trade.
        if existing_trade:
            existing_trade.version = trade_data.version
            existing_trade.counterparty_id = trade_data.counterparty_id
            existing_trade.portfolio_id = trade_data.portfolio_id
            existing_trade.maturity_date = trade_data.maturity_date
            existing_trade.created_date = trade_data.created_date
            existing_trade.expired = trade_data.maturity_date < date.today()

            trade = existing_trade

        else:
            trade = Trade(
                trade_id=trade_data.trade_id,
                version=trade_data.version,
                counterparty_id=trade_data.counterparty_id,
                portfolio_id=trade_data.portfolio_id,
                maturity_date=trade_data.maturity_date,
                created_date=trade_data.created_date,
                expired=False,
            )
            db.add(trade)

        db.commit()
        db.refresh(trade)

        return trade

    except SQLAlchemyError:
        db.rollback()
        raise
