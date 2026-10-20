"""How fast a copy is going and how long is left. No Qt in here.

Speed is measured over a moving window rather than the whole run, so the number on screen is what
the cards are doing now, not an average dragged down by a slow patch twenty minutes ago. The window
also quietly absorbs the bursts that come from files already at the destination: those are counted
as done the instant they are checked, which for a moment looks like copying at 40 GB/s.
"""
from __future__ import annotations

import time
from collections import deque
from typing import Callable

WINDOW = 20.0            # seconds of history the speed is averaged over
_MIN_SPAN = 1.5          # and the least history needed before a speed is worth showing


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def human_time(seconds: float) -> str:
    """A rough time left, said the way someone deciding whether to wait up would say it."""
    seconds = max(0.0, seconds)
    if seconds < 45:
        return "under a minute left"
    minutes = round(seconds / 60)
    if minutes < 60:
        return f"{minutes} min left"
    hours, minutes = divmod(minutes, 60)
    if hours >= 24:
        return "more than a day left"
    return f"{hours} h {minutes:02d} min left"


class Progress:
    """Feed it the running byte total; it gives back the line under the progress bar."""

    def __init__(self, total: int, window: float = WINDOW, clock: Callable[[], float] = time.monotonic) -> None:
        self.total = max(0, int(total))
        self.window, self.clock = window, clock
        self.done = 0
        self._samples: deque[tuple[float, int]] = deque()
        self.update(0)

    def update(self, done: int) -> None:
        now = self.clock()
        self.done = max(0, int(done))
        self._samples.append((now, self.done))
        while len(self._samples) > 2 and now - self._samples[0][0] > self.window:
            self._samples.popleft()

    def speed(self) -> float:
        """Bytes per second over the window, or 0.0 when there is not enough to say yet."""
        if len(self._samples) < 2:
            return 0.0
        (first_at, first), (last_at, last) = self._samples[0], self._samples[-1]
        span = last_at - first_at
        if span < _MIN_SPAN:
            return 0.0
        return max(0.0, (last - first) / span)

    def left(self) -> float | None:
        """Seconds remaining, or None when it cannot be worked out yet."""
        speed = self.speed()
        if not speed or not self.total or self.done >= self.total:
            return None
        return (self.total - self.done) / speed

    def text(self) -> str:
        """'58.2 GB of 214.0 GB  ·  118.4 MB/s  ·  22 min left'"""
        parts = [f"{human(self.done)} of {human(self.total)}"] if self.total else [human(self.done)]
        speed = self.speed()
        if speed:
            parts.append(f"{human(speed)}/s")
        remaining = self.left()
        if remaining is not None:
            parts.append(human_time(remaining))
        return "  ·  ".join(parts)
