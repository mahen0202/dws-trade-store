
import multiprocessing
import os
import signal

from app.kafka.consumer import run_consumer


def main():
    count = int(os.getenv("KAFKA_CONSUMER_COUNT", "1"))

    if count < 1 or count > 6:
        raise ValueError(
            "KAFKA_CONSUMER_COUNT must be between 1 and 6"
        )

    processes = []

    try:
        for i in range(count):
            process = multiprocessing.Process(
                target=run_consumer,
                name=f"trade-consumer-{i + 1}",
            )
            process.start()
            processes.append(process)

            print(
                f"Started Kafka Consumer {i + 1}, "
                f"PID={process.pid}",
                flush=True,
            )

        for process in processes:
            process.join()

    except KeyboardInterrupt:
        print("Stopping Kafka consumers...", flush=True)

    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()

        for process in processes:
            process.join(timeout=10)

        print("All Kafka consumers stopped.", flush=True)


if __name__ == "__main__":
    main()
