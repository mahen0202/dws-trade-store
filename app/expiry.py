from datetime import date

from sqlalchemy import update

from app.database import SessionLocal
from app.models import Trade


def expire_matured_trades():
    db = SessionLocal()

    try:
        result = db.execute(
            update(Trade)
            .where(
                Trade.maturity_date < date.today(),
                Trade.expired.is_(False),
            )
            .values(expired=True)
        )

        db.commit()

        print(f"Expired trades updated: {result.rowcount}")

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()