
import argparse
import subprocess
import sys
import time

from sqlalchemy import text

from app.database import SessionLocal


def count_trades(prefix):
    with SessionLocal() as db:
        return db.execute(
            text("SELECT COUNT(*) FROM trades WHERE trade_id LIKE :prefix"),
            {"prefix": prefix + "%"},
        ).scalar_one()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=10000)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()

    if args.count < 1 or args.concurrency < 1 or args.timeout < 1:
        parser.error("All arguments must be positive")

    # The existing benchmark generates a unique run ID.
    # Capture its output so we can identify its database records.
    command = [
        sys.executable,
        "-m",
        "scripts.benchmark_rest",
        "--count",
        str(args.count),
        "--concurrency",
        str(args.concurrency),
        "--url",
        "http://127.0.0.1:8000/trades/kafka",
    ]

    start = time.perf_counter()
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    run_id = None
    http_successful = None
    http_failed = None

    for line in process.stdout:
        print(line, end="", flush=True)

        if line.startswith("Run ID:") and run_id is None:
            run_id = line.split(":", 1)[1].strip()

        if line.startswith("HTTP successful:"):
            http_successful = int(line.split(":", 1)[1].strip())

        if line.startswith("HTTP failed:"):
            http_failed = int(line.split(":", 1)[1].strip())

    process.wait()
    http_end = time.perf_counter()

    if not run_id or http_successful is None or http_failed is None:
        raise SystemExit("FAILED: Could not read HTTP benchmark results.")

    prefix = f"REST-BENCH-{run_id}-"
    print("\nWaiting for asynchronous PostgreSQL persistence...")

    persisted = 0
    last_report = time.perf_counter()
    deadline = start + args.timeout

    while True:
        persisted = count_trades(prefix)
        now = time.perf_counter()

        if persisted >= http_successful:
            break

        if now - last_report >= 5:
            print(
                f"[{now - start:.1f}s] "
                f"Persisted={persisted}/{http_successful}",
                flush=True,
            )
            last_report = now

        if now >= deadline:
            break

        time.sleep(min(0.25, max(0, deadline - now)))

    end = time.perf_counter()
    http_duration = http_end - start
    total_duration = end - start

    print("\n========== KAFKA API BENCHMARK ==========")
    print(f"Run ID:                {run_id}")
    print(f"Requested:             {args.count}")
    print(f"HTTP successful:       {http_successful}")
    print(f"HTTP failed:           {http_failed}")
    print(f"PostgreSQL persisted:  {persisted}")
    print(f"HTTP phase duration:   {http_duration:.2f}s")
    print(f"End-to-end duration:   {total_duration:.2f}s")
    print(
        f"HTTP acceptance rate:  "
        f"{http_successful / http_duration:.2f} req/sec"
    )
    print(
        f"End-to-end throughput: "
        f"{persisted / total_duration:.2f} trades/sec"
    )
    print("=========================================")

    if (
        http_failed
        or http_successful != args.count
        or persisted != args.count
    ):
        raise SystemExit("FAILED: Incomplete end-to-end ingestion.")

    print("SUCCESS: All Kafka API trades persisted.")


if __name__ == "__main__":
    main()
