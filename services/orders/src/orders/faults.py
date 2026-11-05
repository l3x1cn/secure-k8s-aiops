"""Kontrolowane awarie orders: sekcja „Scenariusze awarii” w docs/architektura.md.

Router istnieje tylko przy FAULTS_ENABLED=true, więc bez tego /faults/* to zwykłe 404.
Naraz działa jedna awaria; nowa zastępuje bieżącą.
"""

import asyncio
import hmac
import logging
import mmap
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Query,
    status,
)
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Pamięć zajmujemy osobnymi mapowaniami anonimowymi: munmap oddaje je systemowi od razu,
# a bufor z malloc mógłby zostać w stercie procesu po zakończeniu awarii.
_MEMORY_CHUNK_BYTES = 16 * 1024 * 1024
# Tolerancja sumowania ułamków w awarii errors (np. 10 x 0.1 < 1.0 w float).
_ERROR_CREDIT_EPSILON = 1e-9
_STOP_JOIN_SECONDS = 5.0

Seconds = Annotated[int, Query(ge=1, le=3600)]


class FaultStarted(BaseModel):
    fault: str
    ends_at: datetime


class FaultStopped(BaseModel):
    stopped: str | None


class MemoryLimitUnknownError(RuntimeError):
    """Kontener nie ma limitu pamięci w cgroup v2, więc nie da się policzyć celu."""


@dataclass
class _Fault:
    name: str
    deadline: float
    stop: threading.Event
    error_ratio: float = 0.0
    delay_seconds: float = 0.0
    worker: threading.Thread | None = None


class FaultController:
    """Stan bieżącej awarii, współdzielony przez endpointy i wątki obciążające."""

    def __init__(
        self, cgroup_dir: Path, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._cgroup_dir = cgroup_dir
        self._clock = clock
        self._lock = threading.Lock()
        self._fault: _Fault | None = None
        self._error_credit = 0.0

    def start_cpu(self, seconds: int) -> datetime:
        return self._start("cpu", seconds, worker=self._burn_cpu)

    def start_memory(self, seconds: int, target_ratio: float) -> datetime:
        limit = self._read_cgroup("memory.max")
        if limit is None:
            raise MemoryLimitUnknownError("memory.max is not set")
        current = self._read_cgroup("memory.current") or 0
        nbytes = max(0, int(limit * target_ratio) - current)

        def hold(fault: _Fault) -> None:
            self._hold_memory(fault, nbytes)

        return self._start("memory", seconds, worker=hold)

    def start_errors(self, seconds: int, ratio: float) -> datetime:
        return self._start("errors", seconds, error_ratio=ratio)

    def start_latency(self, seconds: int, ms: int) -> datetime:
        return self._start("latency", seconds, delay_seconds=ms / 1000)

    def stop(self) -> str | None:
        with self._lock:
            fault = self._fault
            self._fault = None
        if fault is None:
            return None

        self._finish(fault)
        logger.warning("fault stopped: %s", fault.name)

        return fault.name

    async def apply(self) -> None:
        """Skutki awarii errors i latency dla jednego żądania /orders."""
        fault = self._current()
        if fault is None:
            return
        if fault.delay_seconds:
            await asyncio.sleep(fault.delay_seconds)
        if fault.error_ratio and self._take_error(fault):
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR, detail="injected fault"
            )

    def _start(
        self,
        name: str,
        seconds: int,
        *,
        worker: Callable[[_Fault], None] | None = None,
        error_ratio: float = 0.0,
        delay_seconds: float = 0.0,
    ) -> datetime:
        fault = _Fault(
            name=name,
            deadline=self._clock() + seconds,
            stop=threading.Event(),
            error_ratio=error_ratio,
            delay_seconds=delay_seconds,
        )
        if worker is not None:
            fault.worker = threading.Thread(
                target=worker, args=(fault,), name=f"fault-{name}", daemon=True
            )

        with self._lock:
            previous = self._fault
            self._fault = fault
            self._error_credit = 0.0
        if previous is not None:
            self._finish(previous)
        if fault.worker is not None:
            fault.worker.start()

        logger.warning("fault started: %s for %d s", name, seconds)

        return datetime.now(UTC) + timedelta(seconds=seconds)

    def _current(self) -> _Fault | None:
        with self._lock:
            fault = self._fault
            if fault is not None and self._clock() >= fault.deadline:
                self._fault = fault = None
        return fault

    def _take_error(self, fault: _Fault) -> bool:
        # Deterministyczny odsetek zamiast losowania: dokładnie `ratio` odpowiedzi to 500.
        with self._lock:
            self._error_credit += fault.error_ratio
            if self._error_credit < 1 - _ERROR_CREDIT_EPSILON:
                return False
            self._error_credit -= 1
            return True

    def _remaining(self, fault: _Fault) -> float:
        return max(0.0, fault.deadline - self._clock())

    def _burn_cpu(self, fault: _Fault) -> None:
        while not fault.stop.is_set() and self._remaining(fault) > 0:
            for _ in range(10_000):
                pass

    def _hold_memory(self, fault: _Fault, nbytes: int) -> None:
        blocks: list[mmap.mmap] = []
        try:
            remaining = nbytes
            while remaining > 0 and not fault.stop.is_set():
                size = min(_MEMORY_CHUNK_BYTES, remaining)
                block = mmap.mmap(-1, size)
                blocks.append(block)
                # Zapis w każdej stronie: dopiero wtedy pamięć wchodzi do working set.
                for offset in range(0, size, mmap.PAGESIZE):
                    block[offset] = 1
                remaining -= size
            fault.stop.wait(self._remaining(fault))
        finally:
            for block in blocks:
                block.close()

    def _finish(self, fault: _Fault) -> None:
        fault.stop.set()
        if fault.worker is not None and fault.worker.is_alive():
            fault.worker.join(_STOP_JOIN_SECONDS)

    def _read_cgroup(self, name: str) -> int | None:
        try:
            value = (self._cgroup_dir / name).read_text().strip()
        except FileNotFoundError:
            return None
        return None if value == "max" else int(value)


def crash_process() -> None:
    # Bez sprzątania: ma wyglądać jak prawdziwa awaria, a kubelet zrestartuje kontener.
    os._exit(1)


def fault_router(
    controller: FaultController, token: str, crash: Callable[[], None]
) -> APIRouter:
    expected_token = token.encode()

    def require_fault_token(
        x_fault_token: Annotated[str | None, Header()] = None,
    ) -> None:
        if x_fault_token is None or not hmac.compare_digest(
            x_fault_token.encode(), expected_token
        ):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, detail="invalid or missing fault token"
            )

    router = APIRouter(prefix="/faults", dependencies=[Depends(require_fault_token)])

    # Endpointy synchroniczne: zatrzymanie poprzedniej awarii czeka na jej wątek,
    # więc nie może blokować pętli zdarzeń.
    @router.post("/cpu", status_code=status.HTTP_202_ACCEPTED)
    def cpu(seconds: Seconds = 120) -> FaultStarted:
        return FaultStarted(fault="cpu", ends_at=controller.start_cpu(seconds))

    @router.post("/memory", status_code=status.HTTP_202_ACCEPTED)
    def memory(
        seconds: Seconds = 180,
        # Powyżej 0.95 łatwo o OOMKill zamiast scenariusza HighMemory.
        target_ratio: Annotated[float, Query(gt=0, le=0.95)] = 0.9,
    ) -> FaultStarted:
        try:
            ends_at = controller.start_memory(seconds, target_ratio)
        except MemoryLimitUnknownError as exc:
            raise HTTPException(
                status.HTTP_409_CONFLICT, detail="container memory limit unknown"
            ) from exc
        return FaultStarted(fault="memory", ends_at=ends_at)

    @router.post("/errors", status_code=status.HTTP_202_ACCEPTED)
    def errors(
        seconds: Seconds = 180,
        ratio: Annotated[float, Query(gt=0, le=1)] = 0.5,
    ) -> FaultStarted:
        return FaultStarted(
            fault="errors", ends_at=controller.start_errors(seconds, ratio)
        )

    @router.post("/latency", status_code=status.HTTP_202_ACCEPTED)
    def latency(
        seconds: Seconds = 180,
        ms: Annotated[int, Query(ge=1, le=10_000)] = 500,
    ) -> FaultStarted:
        return FaultStarted(
            fault="latency", ends_at=controller.start_latency(seconds, ms)
        )

    @router.post("/crash", status_code=status.HTTP_202_ACCEPTED)
    def crash_endpoint(background_tasks: BackgroundTasks) -> FaultStarted:
        def crash_after_response() -> None:
            logger.error("fault crash: exiting process")
            crash()

        # Zadanie w tle rusza po wysłaniu odpowiedzi, więc klient dostaje 202.
        background_tasks.add_task(crash_after_response)
        return FaultStarted(fault="crash", ends_at=datetime.now(UTC))

    @router.post("/stop")
    def stop() -> FaultStopped:
        return FaultStopped(stopped=controller.stop())

    return router
