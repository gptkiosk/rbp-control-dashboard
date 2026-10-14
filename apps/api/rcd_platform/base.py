"""Small protocol shared by host collection implementations."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from processes import ProcessSampler

Runner = Callable[..., Awaitable[tuple[int, str]]]
Record = Callable[[dict[str, float | None], dict[str, object] | None], Awaitable[dict[str, object]]]


class Platform(Protocol):
    name: str
    metrics_status: str

    async def collect_metrics(self, record: Record, interval_s: int) -> None: ...
    async def stop(self) -> None: ...
    async def system_extras(self) -> dict[str, float | None]: ...
    async def snapshot_services(self, prefixes: tuple[str, ...]) -> list[dict[str, object]]: ...
    async def refresh_updates(self) -> dict[str, object]: ...
    def make_process_sampler(self) -> ProcessSampler: ...
