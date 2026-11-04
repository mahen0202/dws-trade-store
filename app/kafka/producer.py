
import json
import os
import threading
import time
from functools import lru_cache

from confluent_kafka import Producer

from app.schemas import TradeCreate


@lru_cache(maxsize=1)
def get_producer() -> Producer:
    return Producer({
        "bootstrap.servers": os.getenv(
            "KAFKA_BOOTSTRAP_SERVERS",
            "127.0.0.1:9092",
        ),
        "acks": "all",
        "enable.idempotence": True,
        "message.timeout.ms": 15000,
    })


_poll_stop = threading.Event()
_poll_lock = threading.Lock()
_poll_thread = None


def _poll_loop(producer):
    while not _poll_stop.is_set():
        producer.poll(0.1)


def start_producer_polling():
    global _poll_thread

    with _poll_lock:
        if _poll_thread is not None and _poll_thread.is_alive():
            return

        _poll_stop.clear()
        producer = get_producer()

        _poll_thread = threading.Thread(
            target=_poll_loop,
            args=(producer,),
            name="kafka-producer-poller",
            daemon=True,
        )
        _poll_thread.start()


def stop_producer_polling():
    global _poll_thread

    with _poll_lock:
        if _poll_thread is None:
            return

        _poll_stop.set()
        _poll_thread.join(timeout=2)
        _poll_thread = None


def publish_trade(trade: TradeCreate) -> dict:
    start_producer_polling()

    producer = get_producer()
    topic = os.getenv("KAFKA_TOPIC", "trades.incoming")

    delivered = threading.Event()
    delivery = {}

    def on_delivery(error, message):
        if error is not None:
            delivery["error"] = str(error)
        else:
            delivery["partition"] = message.partition()
            delivery["offset"] = message.offset()

        delivered.set()

    try:
        producer.produce(
            topic=topic,
            key=trade.trade_id.encode("utf-8"),
            value=json.dumps(
                trade.model_dump(mode="json")
            ).encode("utf-8"),
            on_delivery=on_delivery,
        )
    except BufferError as exc:
        raise RuntimeError("Kafka producer queue is full") from exc

    if not delivered.wait(timeout=15):
        raise RuntimeError("Kafka delivery acknowledgment timed out")

    if "error" in delivery:
        raise RuntimeError(
            f"Kafka delivery failed: {delivery['error']}"
        )

    return {
        "status": "ACCEPTED",
        "trade_id": trade.trade_id,
        "topic": topic,
        "partition": delivery["partition"],
        "offset": delivery["offset"],
    }
