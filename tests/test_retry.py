"""Tests der Wiederholstrategie."""

from __future__ import annotations

import asyncio
import random

import pytest

from proton_sync_ui.cli_adapter.errors import (
    NotAuthenticatedError,
    PermanentError,
    TransientError,
)
from proton_sync_ui.sync.retry import RetryPolicy, is_transient, retry_async

from .fake_proton_drive import collecting_sleep


class TestPolicyValidation:
    """Ungueltige Parameter fallen sofort auf."""

    def test_max_attempts_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="max_attempts"):
            RetryPolicy(max_attempts=0)

    def test_factor_must_be_at_least_one(self) -> None:
        with pytest.raises(ValueError, match="factor"):
            RetryPolicy(factor=0.5)

    def test_jitter_must_be_a_fraction(self) -> None:
        with pytest.raises(ValueError, match="jitter"):
            RetryPolicy(jitter=1.5)

    def test_negative_base_delay_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="base_delay"):
            RetryPolicy(base_delay=-1)


class TestBackoffCalculation:
    """Exponentiell wachsende Wartezeiten."""

    def test_no_delay_before_the_first_attempt(self) -> None:
        policy = RetryPolicy(base_delay=2.0, jitter=0.0)
        assert policy.delay_for(1) == 0.0

    def test_delays_grow_exponentially(self) -> None:
        policy = RetryPolicy(base_delay=2.0, factor=2.0, jitter=0.0, max_delay=1000)

        assert policy.delay_for(2) == 2.0
        assert policy.delay_for(3) == 4.0
        assert policy.delay_for(4) == 8.0
        assert policy.delay_for(5) == 16.0

    def test_delay_is_capped(self) -> None:
        policy = RetryPolicy(base_delay=2.0, factor=2.0, jitter=0.0, max_delay=10.0)

        assert policy.delay_for(10) == 10.0

    def test_jitter_stays_within_bounds(self) -> None:
        policy = RetryPolicy(base_delay=10.0, factor=1.0, jitter=0.25, max_delay=100)
        rng = random.Random(42)

        for _ in range(50):
            delay = policy.delay_for(2, rng=rng)
            assert 7.5 <= delay <= 12.5

    def test_jitter_never_produces_negative_delays(self) -> None:
        policy = RetryPolicy(base_delay=0.1, factor=1.0, jitter=1.0)
        rng = random.Random(1)

        for _ in range(50):
            assert policy.delay_for(2, rng=rng) >= 0.0


class TestTransientCheck:
    """Welche Fehler gelten als wiederholbar."""

    def test_transient_error_is_retryable(self) -> None:
        assert is_transient(TransientError("Netz weg")) is True

    def test_permanent_error_is_not_retryable(self) -> None:
        assert is_transient(PermanentError("Kontingent voll")) is False

    def test_auth_error_is_not_retryable(self) -> None:
        assert is_transient(NotAuthenticatedError("nicht angemeldet")) is False

    def test_os_error_is_retryable(self) -> None:
        assert is_transient(OSError("Verbindung abgebrochen")) is True

    def test_value_error_is_not_retryable(self) -> None:
        assert is_transient(ValueError("Programmfehler")) is False


class TestRetryExecution:
    """Ablauf der Wiederholversuche."""

    def test_success_on_first_attempt_does_not_sleep(self) -> None:
        delays: list[float] = []
        calls = 0

        async def operation() -> str:
            nonlocal calls
            calls += 1
            return "fertig"

        result = asyncio.run(retry_async(operation, sleep=collecting_sleep(delays)))

        assert result == "fertig"
        assert calls == 1
        assert delays == []

    def test_succeeds_after_transient_failures(self) -> None:
        delays: list[float] = []
        calls = 0

        async def operation() -> str:
            nonlocal calls
            calls += 1
            if calls < 3:
                raise TransientError("Netz kurz weg")
            return "endlich"

        result = asyncio.run(
            retry_async(
                operation,
                policy=RetryPolicy(max_attempts=3, base_delay=1.0, jitter=0.0),
                sleep=collecting_sleep(delays),
            )
        )

        assert result == "endlich"
        assert calls == 3
        assert delays == [1.0, 2.0]

    def test_permanent_error_is_not_retried(self) -> None:
        delays: list[float] = []
        calls = 0

        async def operation() -> str:
            nonlocal calls
            calls += 1
            raise PermanentError("Kontingent erschoepft")

        with pytest.raises(PermanentError):
            asyncio.run(
                retry_async(
                    operation,
                    policy=RetryPolicy(max_attempts=5),
                    sleep=collecting_sleep(delays),
                )
            )

        assert calls == 1
        assert delays == []

    def test_attempts_are_capped(self) -> None:
        calls = 0

        async def operation() -> str:
            nonlocal calls
            calls += 1
            raise TransientError("dauerhaft gestoert")

        with pytest.raises(TransientError):
            asyncio.run(
                retry_async(
                    operation,
                    policy=RetryPolicy(max_attempts=4, base_delay=0.0, jitter=0.0),
                    sleep=collecting_sleep([]),
                )
            )

        assert calls == 4

    def test_last_error_is_raised(self) -> None:
        calls = 0

        async def operation() -> str:
            nonlocal calls
            calls += 1
            raise TransientError(f"Fehler {calls}")

        with pytest.raises(TransientError, match="Fehler 3"):
            asyncio.run(
                retry_async(
                    operation,
                    policy=RetryPolicy(max_attempts=3, base_delay=0.0, jitter=0.0),
                    sleep=collecting_sleep([]),
                )
            )

    def test_on_retry_callback_receives_context(self) -> None:
        seen: list[tuple[int, float, str]] = []
        calls = 0

        async def operation() -> str:
            nonlocal calls
            calls += 1
            if calls < 3:
                raise TransientError("nochmal")
            return "ok"

        def note(attempt: int, delay: float, error: BaseException) -> None:
            seen.append((attempt, delay, str(error)))

        asyncio.run(
            retry_async(
                operation,
                policy=RetryPolicy(max_attempts=3, base_delay=1.0, jitter=0.0),
                on_retry=note,
                sleep=collecting_sleep([]),
            )
        )

        assert [entry[0] for entry in seen] == [2, 3]
        assert [entry[1] for entry in seen] == [1.0, 2.0]

    def test_single_attempt_policy_does_not_retry(self) -> None:
        calls = 0

        async def operation() -> str:
            nonlocal calls
            calls += 1
            raise TransientError("einmal reicht")

        with pytest.raises(TransientError):
            asyncio.run(retry_async(operation, policy=RetryPolicy(max_attempts=1)))

        assert calls == 1

    def test_cancellation_is_not_retried(self) -> None:
        calls = 0

        async def operation() -> str:
            nonlocal calls
            calls += 1
            raise asyncio.CancelledError

        with pytest.raises(asyncio.CancelledError):
            asyncio.run(
                retry_async(
                    operation,
                    policy=RetryPolicy(max_attempts=5),
                    sleep=collecting_sleep([]),
                )
            )

        assert calls == 1

    def test_custom_transient_check(self) -> None:
        calls = 0

        async def operation() -> str:
            nonlocal calls
            calls += 1
            if calls < 2:
                raise ValueError("normalerweise nicht wiederholbar")
            return "ok"

        result = asyncio.run(
            retry_async(
                operation,
                policy=RetryPolicy(max_attempts=3, base_delay=0.0, jitter=0.0),
                transient_check=lambda error: isinstance(error, ValueError),
                sleep=collecting_sleep([]),
            )
        )

        assert result == "ok"
        assert calls == 2
