
from unittest.mock import MagicMock, patch

import pytest

from app.kafka import launcher


def test_launcher_default_one_consumer(monkeypatch):
    monkeypatch.delenv("KAFKA_CONSUMER_COUNT", raising=False)

    process = MagicMock()
    process.pid = 1234
    process.is_alive.return_value = False

    with patch.object(launcher.multiprocessing, "Process", return_value=process) as factory:
        launcher.main()

    factory.assert_called_once()
    assert factory.call_args.kwargs["target"] == launcher.run_consumer
    assert factory.call_args.kwargs["name"] == "trade-consumer-1"
    process.start.assert_called_once()
    process.join.assert_called()
    process.terminate.assert_not_called()


def test_launcher_three_consumers(monkeypatch):
    monkeypatch.setenv("KAFKA_CONSUMER_COUNT", "3")

    processes = [MagicMock() for _ in range(3)]
    for i, process in enumerate(processes):
        process.pid = 2000 + i
        process.is_alive.return_value = False

    with patch.object(
        launcher.multiprocessing,
        "Process",
        side_effect=processes,
    ) as factory:
        launcher.main()

    assert factory.call_count == 3

    for i, process in enumerate(processes, start=1):
        assert factory.call_args_list[i - 1].kwargs["name"] == f"trade-consumer-{i}"
        process.start.assert_called_once()
        process.join.assert_called()
        process.terminate.assert_not_called()


@pytest.mark.parametrize("count", ["0", "-1", "7", "abc"])
def test_launcher_invalid_consumer_count(monkeypatch, count):
    monkeypatch.setenv("KAFKA_CONSUMER_COUNT", count)

    with patch.object(launcher.multiprocessing, "Process") as factory:
        with pytest.raises(ValueError):
            launcher.main()

    factory.assert_not_called()


def test_launcher_keyboard_interrupt_terminates_children(monkeypatch):
    monkeypatch.setenv("KAFKA_CONSUMER_COUNT", "2")

    first = MagicMock()
    second = MagicMock()

    first.join.side_effect = [KeyboardInterrupt(), None]
    first.is_alive.return_value = True
    second.is_alive.return_value = True

    with patch.object(
        launcher.multiprocessing,
        "Process",
        side_effect=[first, second],
    ):
        launcher.main()

    first.terminate.assert_called_once()
    second.terminate.assert_called_once()
    first.join.assert_called()
    second.join.assert_called()
