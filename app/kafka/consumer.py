
import json
import logging
import os
import signal
import time
from datetime import datetime, timezone

from confluent_kafka import Consumer, KafkaException
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.database import SessionLocal
from app.kafka.producer import get_producer
from app.schemas import TradeCreate
from app.services import save_trade

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

running = True


def stop_consumer(signum, frame):
    global running
    running = False


def publish_rejection(message, error):
    """Send rejected trade to DLQ and confirm Kafka delivery."""

    producer = get_producer()
    topic = os.getenv("KAFKA_DLQ_TOPIC", "trades.rejected")

    rejection = {
        "original_topic": message.topic(),
        "original_partition": message.partition(),
        "original_offset": message.offset(),
        "trade_key": (
            message.key().decode("utf-8", errors="replace")
            if message.key() else None
        ),
        "payload": message.value().decode(
            "utf-8", errors="replace"
        ),
        "reason": str(error),
        "rejected_at": datetime.now(timezone.utc).isoformat(),
    }

    delivery = {}

    def on_delivery(err, msg):
        if err is not None:
            delivery["error"] = str(err)
        else:
            delivery["offset"] = msg.offset()

    producer.produce(
        topic=topic,
        key=message.key(),
        value=json.dumps(rejection).encode("utf-8"),
        on_delivery=on_delivery,
    )

    remaining = producer.flush(timeout=15)

    if remaining or "error" in delivery or "offset" not in delivery:
        raise RuntimeError(
            "Failed to publish rejected trade to DLQ: "
            + delivery.get("error", "delivery timeout")
        )

    logger.warning(
        "Trade rejected and sent to DLQ: partition=%s offset=%s reason=%s",
        message.partition(),
        message.offset(),
        error,
    )


def process_message(message):
    """Save a valid trade or durably record its rejection."""

    try:
        payload = json.loads(message.value())
        trade = TradeCreate.model_validate(payload)

        with SessionLocal() as db:
            save_trade(db, trade)

        logger.info(
            "Trade saved: %s | partition=%s | offset=%s",
            trade.trade_id,
            message.partition(),
            message.offset(),
        )

    except (HTTPException, ValidationError, ValueError, TypeError) as exc:
        # Known invalid input or business-rule rejection.
        publish_rejection(message, exc)


def run_consumer():
    global running
    running = True

    signal.signal(signal.SIGINT, stop_consumer)
    signal.signal(signal.SIGTERM, stop_consumer)

    consumer = Consumer({
        "bootstrap.servers": os.getenv(
            "KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:9092"
        ),
        "group.id": "trade-store-consumers",
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
        "enable.auto.offset.store": False,
    })

    topic = os.getenv("KAFKA_TOPIC", "trades.incoming")
    consumer.subscribe([topic])

    logger.info("Kafka consumer started. Topic: %s", topic)

    try:
        while running:
            message = consumer.poll(1.0)

            if message is None:
                continue

            if message.error():
                logger.error("Kafka consumer error: %s", message.error())
                time.sleep(2)
                continue

            try:
                process_message(message)

                # Commit only after successful DB save
                # or confirmed DLQ delivery.
                consumer.commit(
                    message=message,
                    asynchronous=False,
                )

            except (SQLAlchemyError, KafkaException, RuntimeError):
                logger.exception(
                    "Processing failed; offset not committed. "
                    "Retrying the same message."
                )

                # Seek back so we retry the failed message.
                from confluent_kafka import TopicPartition

                consumer.seek(
                    TopicPartition(
                        message.topic(),
                        message.partition(),
                        message.offset(),
                    )
                )

                time.sleep(3)

            except Exception:
                logger.exception(
                    "Unexpected processing failure; stopping consumer "
                    "without committing the offset."
                )
                raise

    finally:
        consumer.close()
        logger.info("Kafka consumer stopped.")


if __name__ == "__main__":
    run_consumer()
