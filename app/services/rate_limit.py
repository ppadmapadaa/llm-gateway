import math
import time


class FixedWindowRateLimiter:
    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window_seconds = window_seconds
        self.windows: dict[int, tuple[float, int]] = {}

    def check(self, key_id: int) -> tuple[bool, int, int]:
        now = time.monotonic()

        window_start, request_count = self.windows.get(
            key_id,
            (now, 0),
        )

        window_age = now - window_start

        if window_age >= self.window_seconds:
            window_start = now
            request_count = 0

        if request_count >= self.limit:
            retry_after = math.ceil(self.window_seconds - window_age)
            return False, 0, retry_after

        request_count += 1
        self.windows[key_id] = (window_start, request_count)

        remaining = self.limit - request_count
        return True, remaining, 0


rate_limiter = FixedWindowRateLimiter(
    limit=10,
    window_seconds=60,
)