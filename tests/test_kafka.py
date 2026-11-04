
import json
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.kafka.producer import publish_trade
from app.kafka.consumer import process_message, publish_rejection
from app.schemas import TradeCreate


def make_trade():
    return TradeCreate(
        trade_id="KAFKA-UNIT-001",
        version=1,
        counterparty_id="CP-001",
        portfolio_id="PF-001",
        maturity_date=date.today() + timedelta(days=30),
        created_date=date.today(),
    )


def make_message(payload):
    message = MagicMock()
    message.value.return_value = json.dumps(payload).encode()
    message.key.return_value = b"KAFKA-UNIT-001"
    message.topic.return_value = "trades.incoming"
    message.partition.return_value = 0
    message.offset.return_value = 10
    return message


def test_producer_success():
    producer = MagicMock()

    def produce(**kwargs):
        delivered = MagicMock()
        delivered.partition.return_value = 0
        delivered.offset.return_value = 10
        kwargs["on_delivery"](None, delivered)

    producer.produce.side_effect = produce
    producer.flush.return_value = 0

    with patch("app.kafka.producer.get_producer", return_value=producer):
        result = publish_trade(make_trade())

    assert result["status"] == "ACCEPTED"
    assert result["offset"] == 10
    assert producer.produce.call_args.kwargs["key"] == b"KAFKA-UNIT-001"


def test_producer_delivery_failure():
    producer = MagicMock()

    def produce(**kwargs):
        kwargs["on_delivery"](Exception("broker failure"), None)

    producer.produce.side_effect = produce
    producer.flush.return_value = 0

    with patch("app.kafka.producer.get_producer", return_value=producer):
        with pytest.raises(RuntimeError, match="broker failure"):
            publish_trade(make_trade())


def test_producer_timeout():
    producer = MagicMock()

    with (
        patch("app.kafka.producer.get_producer", return_value=producer),
        patch("app.kafka.producer.start_producer_polling"),
        patch("app.kafka.producer.threading.Event") as mock_event,
    ):
        mock_event.return_value.wait.return_value = False

        with pytest.raises(
            RuntimeError,
            match="Kafka delivery acknowledgment timed out",
        ):
            publish_trade(make_trade())

    producer.produce.assert_called_once()
    mock_event.return_value.wait.assert_called_once_with(timeout=15)


def test_consumer_valid_trade():
    trade = make_trade()
    message = make_message(trade.model_dump(mode="json"))

    with (
        patch("app.kafka.consumer.SessionLocal") as session,
        patch("app.kafka.consumer.save_trade") as save,
    ):
        process_message(message)

    save.assert_called_once()
    assert save.call_args.args[1].trade_id == trade.trade_id
    session.assert_called_once()


def test_consumer_invalid_json_goes_to_dlq():
    message = make_message({})
    message.value.return_value = b"invalid-json"

    with patch("app.kafka.consumer.publish_rejection") as reject:
        process_message(message)

    reject.assert_called_once()


def test_consumer_business_rejection_goes_to_dlq():
    trade = make_trade()
    message = make_message(trade.model_dump(mode="json"))

    with (
        patch("app.kafka.consumer.SessionLocal"),
        patch(
            "app.kafka.consumer.save_trade",
            side_effect=HTTPException(status_code=409, detail="Stale version"),
        ),
        patch("app.kafka.consumer.publish_rejection") as reject,
    ):
        process_message(message)

    reject.assert_called_once()


def test_consumer_database_failure_propagates():
    from sqlalchemy.exc import OperationalError

    trade = make_trade()
    message = make_message(trade.model_dump(mode="json"))

    with (
        patch("app.kafka.consumer.SessionLocal"),
        patch(
            "app.kafka.consumer.save_trade",
            side_effect=OperationalError("INSERT", {}, Exception("DB down")),
        ),
    ):
        with pytest.raises(OperationalError):
            process_message(message)


def test_dlq_delivery_failure():
    message = make_message({})

    producer = MagicMock()
    producer.flush.return_value = 1

    with patch("app.kafka.consumer.get_producer", return_value=producer):
        with pytest.raises(RuntimeError, match="Failed to publish"):
            publish_rejection(message, ValueError("Invalid trade"))



from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_kafka_router_disabled(monkeypatch):
    monkeypatch.setenv("KAFKA_ENABLED", "false")

    response = client.post(
        "/trades/kafka",
        json=make_trade().model_dump(mode="json"),
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Kafka ingestion is disabled"


def test_kafka_router_success(monkeypatch):
    monkeypatch.setenv("KAFKA_ENABLED", "true")

    expected = {
        "status": "ACCEPTED",
        "trade_id": "KAFKA-UNIT-001",
        "topic": "trades.incoming",
        "partition": 2,
        "offset": 15,
    }

    with patch(
        "app.kafka.producer.publish_trade",
        return_value=expected,
    ) as publish:
        response = client.post(
            "/trades/kafka",
            json=make_trade().model_dump(mode="json"),
        )

    assert response.status_code == 202
    assert response.json() == expected
    publish.assert_called_once()


def test_kafka_router_broker_failure(monkeypatch):
    monkeypatch.setenv("KAFKA_ENABLED", "true")

    with patch(
        "app.kafka.producer.publish_trade",
        side_effect=RuntimeError("Kafka unavailable"),
    ):
        response = client.post(
            "/trades/kafka",
            json=make_trade().model_dump(mode="json"),
        )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Kafka broker unavailable or message delivery failed"
    )



from unittest.mock import call

from confluent_kafka import KafkaException
from sqlalchemy.exc import OperationalError

from app.kafka import consumer as kafka_consumer


def test_consumer_commits_after_success(monkeypatch):
    message = make_message(make_trade().model_dump(mode="json"))
    message.error.return_value = None

    broker = MagicMock()
    broker.poll.side_effect = [message, None]

    def stop_after_processing(seconds):
        kafka_consumer.running = False

    monkeypatch.setattr(kafka_consumer, "Consumer", lambda config: broker)
    monkeypatch.setattr(kafka_consumer.signal, "signal", lambda *args: None)

    with patch.object(kafka_consumer, "process_message") as process:
        def poll_once(timeout):
            kafka_consumer.running = False
            return message

        broker.poll.side_effect = poll_once
        kafka_consumer.run_consumer()

    process.assert_called_once_with(message)
    broker.commit.assert_called_once_with(
        message=message,
        asynchronous=False,
    )
    broker.close.assert_called_once()


def test_consumer_retries_database_failure(monkeypatch):
    message = make_message(make_trade().model_dump(mode="json"))
    message.error.return_value = None

    broker = MagicMock()

    def poll_once(timeout):
        kafka_consumer.running = False
        return message

    broker.poll.side_effect = poll_once

    monkeypatch.setattr(kafka_consumer, "Consumer", lambda config: broker)
    monkeypatch.setattr(kafka_consumer.signal, "signal", lambda *args: None)
    monkeypatch.setattr(kafka_consumer.time, "sleep", lambda _: None)

    failure = OperationalError("INSERT", {}, Exception("DB down"))

    with patch.object(
        kafka_consumer,
        "process_message",
        side_effect=failure,
    ):
        kafka_consumer.run_consumer()

    broker.commit.assert_not_called()
    broker.seek.assert_called_once()
    broker.close.assert_called_once()


def test_consumer_skips_poll_timeout(monkeypatch):
    broker = MagicMock()

    def poll_once(timeout):
        kafka_consumer.running = False
        return None

    broker.poll.side_effect = poll_once

    monkeypatch.setattr(kafka_consumer, "Consumer", lambda config: broker)
    monkeypatch.setattr(kafka_consumer.signal, "signal", lambda *args: None)

    kafka_consumer.run_consumer()

    broker.commit.assert_not_called()
    broker.close.assert_called_once()


def test_consumer_unexpected_error_stops(monkeypatch):
    message = make_message({})
    message.error.return_value = None

    broker = MagicMock()
    broker.poll.return_value = message

    monkeypatch.setattr(kafka_consumer, "Consumer", lambda config: broker)
    monkeypatch.setattr(kafka_consumer.signal, "signal", lambda *args: None)

    with patch.object(
        kafka_consumer,
        "process_message",
        side_effect=KeyError("unexpected"),
    ):
        with pytest.raises(KeyError):
            kafka_consumer.run_consumer()

    broker.commit.assert_not_called()
    broker.close.assert_called_once()


def test_consumer_stop_signal():
    kafka_consumer.running = True
    kafka_consumer.stop_consumer(None, None)
    assert kafka_consumer.running is False


def test_dlq_delivery_success():
    message = make_message({})
    producer = MagicMock()

    def produce(**kwargs):
        delivered = MagicMock()
        delivered.offset.return_value = 25
        kwargs["on_delivery"](None, delivered)

    producer.produce.side_effect = produce
    producer.flush.return_value = 0

    with patch("app.kafka.consumer.get_producer", return_value=producer):
        publish_rejection(message, ValueError("Invalid trade"))

    assert producer.produce.call_args.kwargs["topic"] == "trades.rejected"


def test_dlq_delivery_callback_error():
    message = make_message({})
    producer = MagicMock()

    def produce(**kwargs):
        kwargs["on_delivery"](Exception("DLQ unavailable"), None)

    producer.produce.side_effect = produce
    producer.flush.return_value = 0

    with patch("app.kafka.consumer.get_producer", return_value=producer):
        with pytest.raises(RuntimeError, match="DLQ unavailable"):
            publish_rejection(message, ValueError("Invalid trade"))


def test_consumer_broker_poll_error(monkeypatch):
    message = MagicMock()
    message.error.return_value = Exception("Broker temporarily unavailable")

    broker = MagicMock()

    def poll_once(timeout):
        kafka_consumer.running = False
        return message

    broker.poll.side_effect = poll_once

    monkeypatch.setattr(kafka_consumer, "Consumer", lambda config: broker)
    monkeypatch.setattr(kafka_consumer.signal, "signal", lambda *args: None)
    monkeypatch.setattr(kafka_consumer.time, "sleep", lambda _: None)

    kafka_consumer.run_consumer()

    broker.commit.assert_not_called()
    broker.close.assert_called_once()

