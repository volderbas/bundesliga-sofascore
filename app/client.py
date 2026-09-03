"""SofaScore API istemcisi.

curl_cffi ile gerçek bir Chrome tarayıcısının TLS/JA3 parmak izini taklit eder.
Ban yememek için: rastgele profil, insansı gecikme, oran sınırlama (rate limit),
otomatik yeniden deneme (exponential backoff) ve bellek içi cache kullanır.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from typing import Any, Dict, Optional

from curl_cffi import requests as cffi

log = logging.getLogger("sofa.client")

API_BASE = "https://www.sofascore.com/api/v1"

# curl_cffi'nin desteklediği güncel tarayıcı profilleri
IMPERSONATE_PROFILES = [
    "chrome120",
    "chrome123",
    "chrome124",
    "chrome131",
    "safari17_0",
    "safari17_2_ios",
    "edge101",
]

BASE_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.sofascore.com/",
    "Origin": "https://www.sofascore.com",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "X-Requested-With": "XMLHttpRequest",
}


class RateLimiter:
    """Basit token/aralık tabanlı oran sınırlayıcı (thread-safe)."""

    def __init__(self, min_interval: float = 0.8, jitter: float = 0.6):
        self.min_interval = min_interval
        self.jitter = jitter
        self._last = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            target = self._last + self.min_interval + random.uniform(0, self.jitter)
            if now < target:
                time.sleep(target - now)
            self._last = time.monotonic()


class TTLCache:
    def __init__(self):
        self._data: Dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            item = self._data.get(key)
            if not item:
                return None
            exp, value = item
            if exp < time.time():
                self._data.pop(key, None)
                return None
            return value

    def set(self, key: str, value: Any, ttl: float) -> None:
        with self._lock:
            self._data[key] = (time.time() + ttl, value)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


class SofaScoreClient:
    def __init__(self, min_interval: float = 0.9, max_retries: int = 4):
        self.limiter = RateLimiter(min_interval=min_interval)
        self.cache = TTLCache()
        self.max_retries = max_retries
        self._profile = random.choice(IMPERSONATE_PROFILES)
        self._session = self._new_session()
        self._lock = threading.Lock()
        self._requests = 0
        self._warm()

    def _warm(self) -> None:
        """Ana sayfayı ziyaret ederek Cloudflare çerezlerini al (ban riskini düşürür)."""
        try:
            self._session.get("https://www.sofascore.com/", timeout=20)
        except Exception as exc:
            log.debug("Warm-up başarısız: %s", exc)

    def _new_session(self) -> cffi.Session:
        return cffi.Session(
            impersonate=self._profile,
            headers=dict(BASE_HEADERS),
            timeout=25,
        )

    def rotate(self) -> None:
        """Parmak izini değiştir (ban riskini azaltmak için periyodik)."""
        self._profile = random.choice(IMPERSONATE_PROFILES)
        try:
            self._session.close()
        except Exception:
            pass
        self._session = self._new_session()
        self._warm()
        log.info("Yeni tarayıcı profili: %s", self._profile)

    def get(self, path: str, ttl: float = 20.0, use_cache: bool = True) -> Any:
        """API'den JSON çeker. path örn: '/event/12345/lineups'."""
        key = path
        if use_cache:
            cached = self.cache.get(key)
            if cached is not None:
                return cached

        url = f"{API_BASE}{path}"
        last_err: Optional[Exception] = None

        for attempt in range(self.max_retries):
            self.limiter.wait()
            with self._lock:
                self._requests += 1
                if self._requests % 120 == 0:
                    self.rotate()
                session = self._session
            try:
                resp = session.get(url)
                status = resp.status_code
                if status == 200:
                    data = resp.json()
                    if use_cache:
                        self.cache.set(key, data, ttl)
                    return data
                if status == 404:
                    if use_cache:
                        self.cache.set(key, None, ttl)
                    return None
                if status in (403, 429, 503):
                    # Ban / throttle sinyali: profil değiştir ve bekle
                    wait = (2**attempt) + random.uniform(1, 3)
                    log.warning("HTTP %s -> %.1fs bekleniyor, profil yenileniyor", status, wait)
                    self.rotate()
                    time.sleep(wait)
                    continue
                last_err = RuntimeError(f"HTTP {status} @ {path}")
            except Exception as exc:  # ağ hatası
                last_err = exc
                time.sleep((2**attempt) * 0.5 + random.uniform(0, 1))

        raise RuntimeError(f"İstek başarısız: {path} ({last_err})")


client = SofaScoreClient()
