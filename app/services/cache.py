import time


CACHE_TTL_SECONDS = 300

cache: dict[tuple[int, str, str, float], tuple[str, float]] = {}


def make_cache_key(user_id: int, model: str, prompt: str, temperature: float):
    return (user_id, model, prompt, temperature)


def get_cached_answer(key):
    entry = cache.get(key)

    if entry is None:
        return None

    answer, expires_at = entry

    if time.monotonic() >= expires_at:
        del cache[key]
        return None

    return answer


def save_to_cache(key, answer: str):
    expires_at = time.monotonic() + CACHE_TTL_SECONDS
    cache[key] = (answer, expires_at)