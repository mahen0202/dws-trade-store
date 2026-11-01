from datetime import date

from fastapi import HTTPException
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import Trade
from app.schemas import TradeCreate


def save_trade(db: Session, trade_data: TradeCreate):

    # Reject trades whose maturity date is in the past.
    if trade_data.maturity_date < date.today():
        raise HTTPException(
            status_code=400,
            detail="Trade maturity date cannot be in the past"
        )

    try:
        statement = insert(Trade).values(
            trade_id=trade_data.trade_id,
            version=trade_data.version,
            counterparty_id=trade_data.counterparty_id,
            portfolio_id=trade_data.portfolio_id,
            maturity_date=trade_data.maturity_date,
            created_date=trade_data.created_date,
            expired=False,
        )

        statement = statement.on_conflict_do_update(
            index_elements=[Trade.trade_id],
            set_={
                "version": statement.excluded.version,
                "counterparty_id": statement.excluded.counterparty_id,
                "portfolio_id": statement.excluded.portfolio_id,
                "maturity_date": statement.excluded.maturity_date,
                "created_date": statement.excluded.created_date,
                "expired": statement.excluded.expired,
            },
            where=Trade.version <= statement.excluded.version,
        ).returning(Trade)

        result = db.execute(
            statement.execution_options(populate_existing=True)
        )

        trade = result.scalar_one_or_none()

        if trade is None:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail="Lower trade version rejected"
            )

        db.commit()
        db.refresh(trade)

        return trade

    except SQLAlchemyError:
        db.rollback()
        raise