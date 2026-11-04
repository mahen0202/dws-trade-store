
import argparse
import concurrent.futures
import json
import statistics
import time
import uuid
from datetime import date, timedelta
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def submit_trade(args):
    index, endpoint, prefix = args
    trade_id = f"{prefix}-{index:05d}"

    payload = {
        "trade_id": trade_id,
        "version": 1,
        "counterparty_id": "CP-LOAD",
        "portfolio_id": "PF-LOAD",
        "maturity_date": (date.today() + timedelta(days=30)).isoformat(),
        "created_date": date.today().isoformat(),
    }

    request = Request(
        f"http://127.0.0.1:8000{endpoint}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    start = time.perf_counter()

    try:
        with urlopen(request, timeout=60) as response:
            status = response.status
            response.read()
        error = ""
    except HTTPError as exc:
        status = exc.code
        error = exc.read().decode()[:200]
    except (URLError, TimeoutError, OSError) as exc:
        status = 0
        error = str(exc)

    elapsed_ms = (time.perf_counter() - start) * 1000
    return trade_id, status, elapsed_ms, error


def percentile(values, pct):
    values = sorted(values)
    position = (len(values) - 1) * pct / 100
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    fraction = position - lower
    return values[lower] * (1 - fraction) + values[upper] * fraction


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["rest", "kafka"], required=True)
    parser.add_argument("--count", type=int, default=10000)
    parser.add_argument("--workers", type=int, default=20)
    args = parser.parse_args()

    endpoint = "/trades" if args.mode == "rest" else "/trades/kafka"
    expected_status = 201 if args.mode == "rest" else 202
    prefix = f"LOAD-{args.mode.upper()}-{uuid.uuid4().hex[:8]}"

    jobs = [(i, endpoint, prefix) for i in range(args.count)]

    print(f"Mode: {args.mode}")
    print(f"Trades: {args.count}")
    print(f"Concurrent workers: {args.workers}")
    print(f"Trade prefix: {prefix}")

    start = time.perf_counter()

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=args.workers
    ) as executor:
        results = list(executor.map(submit_trade, jobs))

    duration = time.perf_counter() - start

    successes = [
        r for r in results if r[1] == expected_status
    ]
    failures = [
        r for r in results if r[1] != expected_status
    ]
    latencies = [r[2] for r in results]

    print(f"\nDuration: {duration:.2f}s")
    print(f"Successful requests: {len(successes)}")
    print(f"Failed requests: {len(failures)}")
    print(f"Throughput: {len(successes) / duration:.2f} req/s")
    print(f"Average latency: {statistics.mean(latencies):.2f} ms")
    print(f"P50 latency: {percentile(latencies, 50):.2f} ms")
    print(f"P95 latency: {percentile(latencies, 95):.2f} ms")
    print(f"P99 latency: {percentile(latencies, 99):.2f} ms")

    if failures:
        print("\nFirst 5 failures:")
        for failure in failures[:5]:
            print(failure)


if __name__ == "__main__":
    main()
