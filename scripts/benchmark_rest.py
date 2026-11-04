
import argparse
import asyncio
import time
import uuid
from datetime import date, timedelta

import httpx
from sqlalchemy import text

from app.database import SessionLocal


def count_trades(prefix):
    with SessionLocal() as db:
        return db.execute(
            text("SELECT COUNT(*) FROM trades WHERE trade_id LIKE :prefix"),
            {"prefix": prefix + "%"},
        ).scalar_one()


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=10000)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--url", default="http://127.0.0.1:8000/trades")
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()

    if args.count < 1 or args.concurrency < 1:
        parser.error("--count and --concurrency must be positive")

    run_id = uuid.uuid4().hex[:8]
    prefix = f"REST-BENCH-{run_id}-"

    maturity = (date.today() + timedelta(days=365)).isoformat()
    created = date.today().isoformat()

    semaphore = asyncio.Semaphore(args.concurrency)
    successful = 0
    failed = 0
    errors = {}
    latencies = []

    print(f"Run ID: {run_id}")
    print(f"Endpoint: {args.url}")
    print(f"Requests: {args.count}")
    print(f"Concurrency: {args.concurrency}")

    async with httpx.AsyncClient(
        timeout=args.timeout,
        limits=httpx.Limits(
            max_connections=args.concurrency,
            max_keepalive_connections=args.concurrency,
        ),
    ) as client:

        async def send_trade(i):
            nonlocal successful, failed

            payload = {
                "trade_id": f"{prefix}{i:06d}",
                "version": 1,
                "counterparty_id": "CP-REST",
                "portfolio_id": "PF-REST",
                "maturity_date": maturity,
                "created_date": created,
            }

            async with semaphore:
                request_start = time.perf_counter()
                try:
                    response = await client.post(args.url, json=payload)
                    elapsed = time.perf_counter() - request_start
                    latencies.append(elapsed)

                    if 200 <= response.status_code < 300:
                        successful += 1
                    else:
                        failed += 1
                        key = f"HTTP {response.status_code}"
                        errors[key] = errors.get(key, 0) + 1

                except httpx.RequestError as exc:
                    failed += 1
                    key = type(exc).__name__
                    errors[key] = errors.get(key, 0) + 1

        start = time.perf_counter()

        batch_size = max(args.concurrency * 10, 1)

        for batch_start in range(0, args.count, batch_size):
            tasks = [
                send_trade(i)
                for i in range(
                    batch_start,
                    min(batch_start + batch_size, args.count),
                )
            ]
            await asyncio.gather(*tasks)

            completed = successful + failed
            if completed % 1000 == 0 or completed == args.count:
                print(
                    f"Completed: {completed}/{args.count}, "
                    f"Success: {successful}, Failed: {failed}",
                    flush=True,
                )

    duration = time.perf_counter() - start
    persisted = count_trades(prefix)

    latencies.sort()

    def percentile(p):
        if not latencies:
            return 0.0
        index = min(
            len(latencies) - 1,
            max(0, int((len(latencies) - 1) * p)),
        )
        return latencies[index] * 1000

    print("\n========== REST BENCHMARK ==========")
    print(f"Run ID:             {run_id}")
    print(f"Requests:           {args.count}")
    print(f"Concurrency:        {args.concurrency}")
    print(f"HTTP successful:    {successful}")
    print(f"HTTP failed:        {failed}")
    print(f"PostgreSQL saved:   {persisted}")
    print(f"Total duration:     {duration:.2f}s")
    print(f"HTTP throughput:    {args.count / duration:.2f} req/sec")
    print(f"Successful rate:    {successful / duration:.2f} req/sec")
    print(f"Latency P50:        {percentile(0.50):.2f}ms")
    print(f"Latency P95:        {percentile(0.95):.2f}ms")
    print(f"Latency P99:        {percentile(0.99):.2f}ms")
    print(f"Errors:             {errors}")
    print("====================================")

    if failed or persisted != args.count:
        raise SystemExit("FAILED: Check HTTP errors and DB persistence.")

    print("SUCCESS: All REST trades persisted.")


if __name__ == "__main__":
    asyncio.run(main())
