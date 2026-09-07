"""SofaScore/ESPN API istemcisi.

SofaScore öncelikli kullanılır. Render gibi ortamlarda SofaScore 403 döndürürse
ESPN'in herkese açık futbol API'si Bundesliga verileri için otomatik yedek olur.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from curl_cffi import requests as cffi

log = logging.getLogger("sofa.client")

API_BASE = "https://www.sofascore.com/api/v1"
ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"

IMPERSONATE_PROFILES = [
    "chrome120", "chrome123", "chrome124", "chrome131",
    "safari17_0", "safari17_2_ios", "edge101",
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
        self._profile = random.choice(IMPERSONATE_PROFILES)
        try:
            self._session.close()
        except Exception:
            pass
        self._session = self._new_session()
        self._warm()
        log.info("Yeni tarayıcı profili: %s", self._profile)

    def _espn_session(self) -> cffi.Session:
        return cffi.Session(
            headers={
                "Accept": "application/json",
                "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
                "User-Agent": "Mozilla/5.0",
            },
            timeout=20,
        )

    @staticmethod
    def _espn_competition_for_league(tournament_id: int) -> str:
        return "ger.1" if tournament_id == 35 else "ger.2"

    @staticmethod
    def _espn_event_to_sofa(event: Dict[str, Any], league_id: int) -> Dict[str, Any]:
        comps = event.get("competitions") or []
        comp = comps[0] if comps else {}
        competitors = comp.get("competitors") or []
        home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0] if competitors else {})
        away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1] if len(competitors) > 1 else {})
        status_raw = (event.get("status") or comp.get("status") or {})
        status_type = status_raw.get("type") or {}
        name = status_type.get("name", "")
        status = {
            "STATUS_SCHEDULED": "notstarted",
            "STATUS_IN_PROGRESS": "inprogress",
            "STATUS_FINAL": "finished",
            "STATUS_POSTPONED": "notstarted",
            "STATUS_CANCELED": "finished",
        }.get(name, "notstarted")
        start = event.get("date") or comp.get("date")
        try:
            ts = int(datetime.fromisoformat(start.replace("Z", "+00:00")).timestamp()) if start else None
        except Exception:
            ts = None

        def team(c: Dict[str, Any]) -> Dict[str, Any]:
            t = c.get("team") or {}
            return {
                "id": t.get("id"),
                "name": t.get("displayName") or t.get("name"),
                "shortName": t.get("abbreviation") or t.get("shortDisplayName"),
            }

        return {
            "id": int(event.get("id")) if str(event.get("id", "")).isdigit() else event.get("id"),
            "slug": event.get("shortName") or event.get("name"),
            "tournament": {"uniqueTournament": {"id": league_id, "name": "Bundesliga" if league_id == 35 else "2. Bundesliga"}},
            "roundInfo": {"round": ((event.get("week") or {}).get("number"))},
            "startTimestamp": ts,
            "status": {"type": status, "description": status_raw.get("shortDetail") or status_raw.get("description")},
            "homeTeam": team(home),
            "awayTeam": team(away),
            "homeScore": {"current": _score(home), "period1": None},
            "awayScore": {"current": _score(away), "period1": None},
            "winnerCode": 1 if home.get("winner") else 2 if away.get("winner") else None,
            "hasEventPlayerStatistics": False,
        }

    def _espn_events(self, tournament_id: int, dates: Optional[str] = None) -> Dict[str, Any]:
        league = self._espn_competition_for_league(tournament_id)
        session = self._espn_session()
        url = f"{ESPN_BASE}/{league}/scoreboard"
        params = {"dates": dates} if dates else {}
        resp = session.get(url, params=params)
        resp.raise_for_status()
        raw = resp.json()
        events = [self._espn_event_to_sofa(e, tournament_id) for e in raw.get("events", [])]
        return {"events": events, "hasNextPage": False}

    def _espn_fallback(self, path: str) -> Any:
        import re

        m = re.match(r"/unique-tournament/(35|44)/seasons$", path)
        if m:
            return {"seasons": [{"id": 2026, "name": "2026/27"}]}

        m = re.match(r"/unique-tournament/(35|44)/season/(\d+)/events/(last|next)/(\d+)$", path)
        if m:
            league_id = int(m.group(1))
            kind = m.group(3)
            today = datetime.now(timezone.utc).date()
            if kind == "last":
                dates = f"{(today - timedelta(days=35)).strftime('%Y%m%d')}-{today.strftime('%Y%m%d')}"
            else:
                dates = f"{today.strftime('%Y%m%d')}-{(today + timedelta(days=35)).strftime('%Y%m%d')}"
            return self._espn_events(league_id, dates)

        m = re.match(r"/unique-tournament/(35|44)/season/(\d+)/standings/total$", path)
        if m:
            league_id = int(m.group(1))
            league = self._espn_competition_for_league(league_id)
            session = self._espn_session()
            resp = session.get(f"https://site.api.espn.com/apis/v2/sports/soccer/{league}/standings")
            resp.raise_for_status()
            raw = resp.json()
            rows = []
            for child in raw.get("children", []):
                for entry in child.get("standings", {}).get("entries", []):
                    stats = {s.get("name"): s.get("value") for s in entry.get("stats", [])}
                    team = entry.get("team") or {}
                    rows.append({
                        "position": stats.get("rank"),
                        "team": team.get("displayName") or team.get("name"),
                        "teamId": team.get("id"),
                        "matches": stats.get("gamesPlayed"),
                        "wins": stats.get("wins"),
                        "draws": stats.get("ties"),
                        "losses": stats.get("losses"),
                        "scoresFor": stats.get("pointsFor"),
                        "scoresAgainst": stats.get("pointsAgainst"),
                        "points": stats.get("points"),
                    })
            return {"standings": [{"name": "Toplam", "rows": rows}]}

        m = re.match(r"/sport/football/scheduled-events/(\d{4}-\d{2}-\d{2})$", path)
        if m:
            date = m.group(1).replace("-", "")
            out = []
            for league_id in (35, 44):
                out.extend(self._espn_events(league_id, date).get("events", []))
            return {"events": out}

        if path == "/sport/football/events/live":
            date = datetime.now(timezone.utc).strftime("%Y%m%d")
            out = []
            for league_id in (35, 44):
                data = self._espn_events(league_id, date)
                out.extend([e for e in data.get("events", []) if e.get("status", {}).get("type") == "inprogress"])
            return {"events": out}

        return None

    def get(self, path: str, ttl: float = 20.0, use_cache: bool = True) -> Any:
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
                    last_err = RuntimeError(f"HTTP {status} @ {path}")
                    log.warning("HTTP %s -> SofaScore erişilemiyor, ESPN yedeğine geçiliyor", status)
                    break
                last_err = RuntimeError(f"HTTP {status} @ {path}")
            except Exception as exc:
                last_err = exc
                break

        try:
            fallback = self._espn_fallback(path)
            if fallback is not None:
                if use_cache:
                    self.cache.set(key, fallback, ttl)
                log.info("ESPN fallback kullanıldı: %s", path)
                return fallback
        except Exception as exc:
            log.warning("ESPN fallback başarısız: %s", exc)

        raise RuntimeError(f"İstek başarısız: {path} ({last_err})")


def _score(competitor: Dict[str, Any]) -> Optional[int]:
    value = competitor.get("score")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


client = SofaScoreClient()
