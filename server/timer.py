import asyncio
from typing import Callable, Optional, Awaitable, Any


class ServerTimer:
    """Server-side countdown timer for Rapid Fire and match events.
    The server owns the clock and triggers asynchronous callbacks on ticks and expiry.
    Supports start, pause, resume, and reset.
    """

    def __init__(self):
        self.seconds_remaining: int = 0
        self.is_running: bool = False
        self._task: Optional[asyncio.Task] = None
        self._on_tick: Optional[Callable[[int], Awaitable[None]]] = None
        self._on_expired: Optional[Callable[[], Awaitable[None]]] = None

    def start(
        self,
        seconds: int,
        on_tick: Optional[Callable[[int], Awaitable[None]]] = None,
        on_expired: Optional[Callable[[], Awaitable[None]]] = None,
    ) -> None:
        """Starts countdown from specified seconds."""
        self.pause()
        self.seconds_remaining = max(0, seconds)
        self.is_running = True
        self._on_tick = on_tick or self._on_tick
        self._on_expired = on_expired or self._on_expired
        self._task = asyncio.create_task(self._run_loop())

    def pause(self) -> None:
        """Pauses the countdown."""
        self.is_running = False
        if self._task and not self._task.done():
            self._task.cancel()
            self._task = None

    def resume(self) -> None:
        """Resumes countdown if paused and seconds remaining > 0."""
        if not self.is_running and self.seconds_remaining > 0:
            self.is_running = True
            self._task = asyncio.create_task(self._run_loop())

    def reset(self, seconds: int = 0) -> None:
        """Stops the countdown and sets remaining seconds."""
        self.pause()
        self.seconds_remaining = max(0, seconds)

    async def _run_loop(self) -> None:
        try:
            while self.is_running and self.seconds_remaining > 0:
                await asyncio.sleep(1.0)
                if not self.is_running:
                    break

                self.seconds_remaining -= 1

                if self._on_tick:
                    try:
                        await self._on_tick(self.seconds_remaining)
                    except Exception as e:
                        print(f"[Timer] Error in on_tick callback: {e}")

                if self.seconds_remaining <= 0:
                    self.is_running = False
                    if self._on_expired:
                        try:
                            await self._on_expired()
                        except Exception as e:
                            print(f"[Timer] Error in on_expired callback: {e}")
                    break
        except asyncio.CancelledError:
            pass
