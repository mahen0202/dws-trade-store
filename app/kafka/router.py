import os

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.schemas import TradeCreate

router = APIRouter(tags=["Kafka Ingestion"])


class KafkaTradeResponse(BaseModel):
    status: str
    trade_id: str
    topic: str
    partition: int
    offset: int


@router.post(
    "/trades/kafka",
    response_model=KafkaTradeResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_trade_via_kafka(trade_data: TradeCreate):
    if os.getenv("KAFKA_ENABLED", "false").lower() != "true":
        raise HTTPException(
            status_code=503,
            detail="Kafka ingestion is disabled",
        )

    try:
        # Lazy import keeps the existing REST API independent
        # of the optional Kafka Python dependency.
        from app.kafka.producer import publish_trade

        return publish_trade(trade_data)

    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Kafka broker unavailable or message delivery failed",
        ) from exc
