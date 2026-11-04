
import argparse
import json
import os
import time
import uuid
from datetime import date
from threading import Event

from confluent_kafka import Producer
from sqlalchemy import text

from app.database import SessionLocal


def count_trades(prefix):
    with SessionLocal() as db:
        return db.execute(
            text("""
                SELECT COUNT(*)
                FROM trades
                WHERE trade_id LIKE :prefix
            """),
            {"prefix": prefix + "%"},
        ).scalar_one()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=10000)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--poll-interval", type=float, default=0.25)
    args = parser.parse_args()

    if args.count < 1 or args.timeout < 1 or args.poll_interval <= 0:
        parser.error("count, timeout and poll-interval must be positive")

    broker = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:9092")
    topic = os.getenv("KAFKA_TOPIC", "trades.incoming")

    run_id = uuid.uuid4().hex[:8]
    prefix = f"BENCH-{run_id}-"

    producer = Producer({
        "bootstrap.servers": broker,
        "acks": "all",
        "enable.idempotence": True,
    })

    delivered = 0
    delivery_errors = []
    completed = Event()

    def on_delivery(error, message):
        nonlocal delivered

        if error:
            delivery_errors.append(str(error))
        else:
            delivered += 1

        if delivered + len(delivery_errors) == args.count:
            completed.set()

    print(f"Run ID: {run_id}")
    print(f"Broker: {broker}")
    print(f"Topic: {topic}")
    print(f"Trades: {args.count}")
    print(f"Initial matching DB records: {count_trades(prefix)}")
    print("Publishing directly to Kafka...", flush=True)

    start = time.perf_counter()

    for i in range(args.count):
        trade_id = f"{prefix}{i:06d}"

        trade = {
            "trade_id": trade_id,
            "version": 1,
            "counterparty_id": "BENCH-CP",
            "portfolio_id": "BENCH-PORT",
            "maturity_date": "2030-12-31",
            "created_date": date.today().isoformat(),
        }

        payload = json.dumps(trade).encode("utf-8")

        while True:
            try:
                producer.produce(
                    topic,
                    key=trade_id.encode("utf-8"),
                    value=payload,
                    callback=on_delivery,
                )
                break
            except BufferError:
                producer.poll(0.1)

        producer.poll(0)

    remaining = max(0, args.timeout - (time.perf_counter() - start))
    outstanding = producer.flush(remaining)

    publish_end = time.perf_counter()
    publish_seconds = publish_end - start

    if outstanding or delivery_errors or delivered != args.count:
        print(
            f"FAILED: delivered={delivered}, "
            f"errors={len(delivery_errors)}, "
            f"outstanding={outstanding}"
        )
        if delivery_errors:
            print("First delivery error:", delivery_errors[0])
        raise SystemExit(1)

    print(f"Published: {delivered}")
    print(f"Publish duration: {publish_seconds:.2f}s")
    print(f"Publish throughput: {delivered / publish_seconds:.2f} trades/sec")
    print("Waiting for PostgreSQL persistence...", flush=True)


    deadline = start + args.timeout
    persisted = 0
    last_report = time.perf_counter()

    while True:
        persisted = count_trades(prefix)
        now = time.perf_counter()

        if persisted == args.count:
            break

        if now - last_report >= 5:
            elapsed = now - start
            remaining = args.count - persisted

            print(
                f"[{elapsed:.1f}s] "
                f"Persisted={persisted}/{args.count}, "
                f"Remaining={remaining}, "
                f"Average rate={persisted / elapsed:.2f}/sec",
                flush=True,
            )
            last_report = now

        if now >= deadline:
            break

        time.sleep(min(args.poll_interval, max(0, deadline - now)))

    end = time.perf_counter()
    total_seconds = end - start
    consumer_drain_seconds = end - publish_end


    print()
    print("========== BENCHMARK RESULTS ==========")
    print(f"Run ID:                 {run_id}")
    print(f"Requested trades:       {args.count}")
    print(f"Kafka delivered:        {delivered}")
    print(f"PostgreSQL persisted:   {persisted}")
    print(f"Publish duration:       {publish_seconds:.2f}s")
    print(f"Total elapsed:          {total_seconds:.2f}s")
    print(f"Post-publish drain:     {consumer_drain_seconds:.2f}s")
    print(f"End-to-end throughput:  {persisted / total_seconds:.2f} trades/sec")
    print("=======================================")

    if persisted != args.count:
        print("FAILED: Not all trades persisted before timeout.")
        raise SystemExit(1)

    print("SUCCESS: All benchmark trades persisted.")


if __name__ == "__main__":
    main()
