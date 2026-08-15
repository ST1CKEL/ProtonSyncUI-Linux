"""Wiederholversuche mit exponentiell wachsender Wartezeit.

Nur als voruebergehend eingestufte Fehler werden wiederholt. Dauerhafte
Fehler -- fehlende Berechtigung, volles Kontingent, gesperrtes Kommando --
fuehren sofort zum Abbruch des betroffenen Uploads, ohne den Gesamtlauf zu
beenden.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final

from ..cli_adapter.errors import ProtonCliError
from ..logging_setup import get_logger

log = get_logger("sync.retry")

SleepFunc = Callable[[float], Awaitable[None]]
RetryCallback = Callable[[int, float, BaseException], None]

DEFAULT_MAX_ATTEMPTS: Final = 3


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Parameter der Wiederholstrategie."""

    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    base_delay: float = 2.0
    factor: float = 2.0
    max_delay: float = 60.0
    #: Anteil zufaelliger Streuung, damit viele Dateien nicht im Gleichtakt
    #: erneut anfragen.
    jitter: float = 0.25

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts muss mindestens 1 sein.")
        if self.base_delay < 0:
            raise ValueError("base_delay darf nicht negativ sein.")
        if self.factor < 1:
            raise ValueError("factor muss mindestens 1 sein.")
        if not 0 <= self.jitter <= 1:
            raise ValueError("jitter muss zwischen 0 und 1 liegen.")

    def delay_for(self, attempt: int, *, rng: random.Random | None = None) -> float:
        """Wartezeit vor dem Versuch ``attempt`` (1-basiert).

        Vor dem ersten Versuch wird nicht gewartet.
        """
        if attempt <= 1:
            return 0.0
        raw = self.base_delay * (self.factor ** (attempt - 2))
        capped = min(raw, self.max_delay)
        if self.jitter == 0:
            return capped
        source = rng if rng is not None else random
        spread = capped * self.jitter
        return max(0.0, capped + source.uniform(-spread, spread))


def is_transient(error: BaseException) -> bool:
    """Standardregel: nur als voruebergehend markierte CLI-Fehler wiederholen."""
    if isinstance(error, ProtonCliError):
        return error.transient
    # Netzwerknahe Betriebssystemfehler koennen ebenfalls voruebergehend sein.
    return isinstance(error, OSError | asyncio.IncompleteReadError)


async def retry_async[T](
    operation: Callable[[], Awaitable[T]],
    *,
    policy: RetryPolicy | None = None,
    transient_check: Callable[[BaseException], bool] = is_transient,
    on_retry: RetryCallback | None = None,
    sleep: SleepFunc = asyncio.sleep,
    rng: random.Random | None = None,
) -> T:
    """Fuehrt ``operation`` aus und wiederholt sie bei voruebergehenden Fehlern.

    Gibt das Ergebnis des ersten erfolgreichen Versuchs zurueck. Schlagen alle
    Versuche fehl, wird der letzte Fehler weitergereicht.

    ``sleep`` ist austauschbar, damit Tests ohne echte Wartezeit laufen.
    """
    active = policy if policy is not None else RetryPolicy()
    last_error: BaseException | None = None

    for attempt in range(1, active.max_attempts + 1):
        if attempt > 1:
            delay = active.delay_for(attempt, rng=rng)
            if on_retry is not None and last_error is not None:
                on_retry(attempt, delay, last_error)
            if delay > 0:
                await sleep(delay)

        try:
            return await operation()
        except asyncio.CancelledError:
            raise
        except BaseException as error:
            last_error = error
            if not transient_check(error):
                raise
            if attempt >= active.max_attempts:
                raise
            log.debug(
                "Versuch %d/%d fehlgeschlagen: %s",
                attempt,
                active.max_attempts,
                error,
                extra={"attempt": attempt},
            )

    # Unerreichbar: Die Schleife endet immer mit return oder raise.
    raise last_error if last_error is not None else RuntimeError("Retry ohne Ergebnis.")


__all__ = [
    "DEFAULT_MAX_ATTEMPTS",
    "RetryPolicy",
    "is_transient",
    "retry_async",
]
