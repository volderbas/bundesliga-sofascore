"""Bundesliga & 2. Bundesliga veri katmanı."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .client import client

# SofaScore unique-tournament id'leri
LEAGUES: Dict[str, Dict[str, Any]] = {
    "bundesliga": {"id": 35, "name": "Bundesliga", "country": "Almanya"},
    "bundesliga2": {"id": 44, "name": "2. Bundesliga", "country": "Almanya"},
}

_pool = ThreadPoolExecutor(max_workers=6)


def _safe(path: str, ttl: float) -> Any:
    try:
        return client.get(path, ttl=ttl)
    except Exception:
        return None


# ---------------------------------------------------------------- sezonlar
def get_seasons(league_key: str) -> List[Dict[str, Any]]:
    lg = LEAGUES[league_key]
    data = _safe(f"/unique-tournament/{lg['id']}/seasons", ttl=6 * 3600) or {}
    return data.get("seasons", [])


def current_season_id(league_key: str) -> Optional[int]:
    seasons = get_seasons(league_key)
    return seasons[0]["id"] if seasons else None


# ---------------------------------------------------------------- maç listeleri
def league_events(league_key: str, season_id: int, kind: str = "last", page: int = 0) -> Dict[str, Any]:
    """kind: 'last' (oynanmış) veya 'next' (gelecek)."""
    lg = LEAGUES[league_key]
    path = f"/unique-tournament/{lg['id']}/season/{season_id}/events/{kind}/{page}"
    data = _safe(path, ttl=120) or {}
    events = data.get("events", [])
    if kind == "last":
        events = list(reversed(events))
    return {"events": [slim_event(e) for e in events], "hasNextPage": data.get("hasNextPage", False)}


def league_round(league_key: str, season_id: int, round_number: int) -> List[Dict[str, Any]]:
    lg = LEAGUES[league_key]
    data = _safe(
        f"/unique-tournament/{lg['id']}/season/{season_id}/events/round/{round_number}", ttl=120
    ) or {}
    return [slim_event(e) for e in data.get("events", [])]


def live_events() -> List[Dict[str, Any]]:
    """Tüm canlı futbol maçlarından sadece Bundesliga 1-2 olanları süz."""
    data = _safe("/sport/football/events/live", ttl=12) or {}
    ids = {lg["id"] for lg in LEAGUES.values()}
    out = []
    for e in data.get("events", []):
        ut = (e.get("tournament") or {}).get("uniqueTournament") or {}
        if ut.get("id") in ids:
            out.append(slim_event(e))
    return out


def events_by_date(date_str: str) -> List[Dict[str, Any]]:
    """YYYY-MM-DD günündeki Bundesliga 1-2 maçları."""
    data = _safe(f"/sport/football/scheduled-events/{date_str}", ttl=120) or {}
    ids = {lg["id"] for lg in LEAGUES.values()}
    out = []
    for e in data.get("events", []):
        ut = (e.get("tournament") or {}).get("uniqueTournament") or {}
        if ut.get("id") in ids:
            out.append(slim_event(e))
    return out


def upcoming_days(days: int = 7) -> List[Dict[str, Any]]:
    today = datetime.now(timezone.utc).date()
    dates = [(today + timedelta(days=i)).isoformat() for i in range(days)]
    res: List[Dict[str, Any]] = []
    for chunk in _pool.map(events_by_date, dates):
        res.extend(chunk)
    res.sort(key=lambda e: e["startTimestamp"])
    return res


def standings(league_key: str, season_id: int) -> List[Dict[str, Any]]:
    lg = LEAGUES[league_key]
    data = _safe(
        f"/unique-tournament/{lg['id']}/season/{season_id}/standings/total", ttl=900
    ) or {}
    tables = []
    for st in data.get("standings", []):
        tables.append(
            {
                "name": st.get("name"),
                "rows": [
                    {
                        "position": r.get("position"),
                        "team": (r.get("team") or {}).get("name"),
                        "teamId": (r.get("team") or {}).get("id"),
                        "matches": r.get("matches"),
                        "wins": r.get("wins"),
                        "draws": r.get("draws"),
                        "losses": r.get("losses"),
                        "scoresFor": r.get("scoresFor"),
                        "scoresAgainst": r.get("scoresAgainst"),
                        "points": r.get("points"),
                    }
                    for r in st.get("rows", [])
                ],
            }
        )
    return tables


# ---------------------------------------------------------------- normalize
def slim_event(e: Dict[str, Any]) -> Dict[str, Any]:
    ut = (e.get("tournament") or {}).get("uniqueTournament") or {}
    status = e.get("status") or {}
    return {
        "id": e.get("id"),
        "slug": e.get("slug"),
        "leagueId": ut.get("id"),
        "league": ut.get("name") or (e.get("tournament") or {}).get("name"),
        "round": (e.get("roundInfo") or {}).get("round"),
        "startTimestamp": e.get("startTimestamp"),
        "status": status.get("type"),          # notstarted / inprogress / finished
        "statusText": status.get("description"),
        "home": {
            "id": (e.get("homeTeam") or {}).get("id"),
            "name": (e.get("homeTeam") or {}).get("name"),
            "short": (e.get("homeTeam") or {}).get("shortName"),
        },
        "away": {
            "id": (e.get("awayTeam") or {}).get("id"),
            "name": (e.get("awayTeam") or {}).get("name"),
            "short": (e.get("awayTeam") or {}).get("shortName"),
        },
        "homeScore": (e.get("homeScore") or {}).get("current"),
        "awayScore": (e.get("awayScore") or {}).get("current"),
        "homeHalf": (e.get("homeScore") or {}).get("period1"),
        "awayHalf": (e.get("awayScore") or {}).get("period1"),
        "winnerCode": e.get("winnerCode"),
        "hasLineups": e.get("hasEventPlayerStatistics"),
    }


def _player_row(p: Dict[str, Any]) -> Dict[str, Any]:
    player = p.get("player") or {}
    stats = p.get("statistics") or {}
    return {
        "id": player.get("id"),
        "name": player.get("name"),
        "shortName": player.get("shortName"),
        "position": p.get("position") or player.get("position"),
        "jerseyNumber": p.get("jerseyNumber") or player.get("jerseyNumber"),
        "country": (player.get("country") or {}).get("name"),
        "captain": p.get("captain", False),
        "substitute": p.get("substitute", False),
        "rating": stats.get("rating"),
        "minutesPlayed": stats.get("minutesPlayed"),
        "goals": stats.get("goals"),
        "goalAssist": stats.get("goalAssist"),
        "totalPass": stats.get("totalPass"),
        "accuratePass": stats.get("accuratePass"),
        "shotsOnTarget": stats.get("onTargetScoringAttempt"),
        "totalShots": (stats.get("onTargetScoringAttempt") or 0)
        + (stats.get("shotOffTarget") or 0)
        + (stats.get("blockedScoringAttempt") or 0),
        "duelWon": stats.get("duelWon"),
        "duelLost": stats.get("duelLost"),
        "fouls": stats.get("fouls"),
        "wasFouled": stats.get("wasFouled"),
        "saves": stats.get("saves"),
        "touches": stats.get("touches"),
    }


def _side_lineup(side: Dict[str, Any]) -> Dict[str, Any]:
    players = [_player_row(p) for p in side.get("players", [])]
    return {
        "formation": side.get("formation"),
        "missingPlayers": [
            {
                "name": (m.get("player") or {}).get("name"),
                "reason": m.get("reason"),
                "type": m.get("type"),
            }
            for m in side.get("missingPlayers", [])
        ],
        "startXI": [p for p in players if not p["substitute"]],
        "bench": [p for p in players if p["substitute"]],
    }


def _incidents(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for i in raw.get("incidents", []) or []:
        out.append(
            {
                "type": i.get("incidentType"),          # goal / card / substitution / period / injuryTime
                "class": i.get("incidentClass"),        # regular, penalty, ownGoal, yellow, red...
                "time": i.get("time"),
                "addedTime": i.get("addedTime"),
                "isHome": i.get("isHome"),
                "homeScore": i.get("homeScore"),
                "awayScore": i.get("awayScore"),
                "player": (i.get("player") or {}).get("name"),
                "assist": (i.get("assist1") or {}).get("name"),
                "playerIn": (i.get("playerIn") or {}).get("name"),
                "playerOut": (i.get("playerOut") or {}).get("name"),
                "reason": i.get("reason"),
                "text": i.get("text"),
                "description": i.get("description"),
            }
        )
    out.sort(key=lambda x: ((x["time"] or 0), (x["addedTime"] or 0)))
    return out


def match_detail(event_id: int) -> Dict[str, Any]:
    """Bir maçın tüm detayları: skor, ilk 11, yedekler, değişiklikler, olaylar, istatistik."""
    live_ttl = 15

    def task(name, path, ttl):
        return name, _safe(path, ttl)

    jobs = [
        ("event", f"/event/{event_id}", live_ttl),
        ("lineups", f"/event/{event_id}/lineups", live_ttl),
        ("incidents", f"/event/{event_id}/incidents", live_ttl),
        ("statistics", f"/event/{event_id}/statistics", live_ttl),
        ("managers", f"/event/{event_id}/managers", 3600),
        ("graph", f"/event/{event_id}/graph", live_ttl),
        ("h2h", f"/event/{event_id}/h2h", 3600),
    ]
    results = dict(_pool.map(lambda j: task(*j), jobs))

    ev_raw = (results.get("event") or {}).get("event") or {}
    detail: Dict[str, Any] = {"summary": slim_event(ev_raw) if ev_raw else {"id": event_id}}

    ev_full = ev_raw or {}
    detail["venue"] = ((ev_full.get("venue") or {}).get("stadium") or {}).get("name")
    detail["city"] = ((ev_full.get("venue") or {}).get("city") or {}).get("name")
    detail["referee"] = (ev_full.get("referee") or {}).get("name")
    detail["attendance"] = ev_full.get("attendance")
    detail["season"] = (ev_full.get("season") or {}).get("name")

    lu = results.get("lineups") or {}
    detail["lineupsConfirmed"] = lu.get("confirmed")
    detail["lineups"] = (
        {"home": _side_lineup(lu.get("home") or {}), "away": _side_lineup(lu.get("away") or {})}
        if lu
        else None
    )

    inc = _incidents(results.get("incidents") or {})
    detail["incidents"] = inc
    detail["goals"] = [i for i in inc if i["type"] == "goal"]
    detail["cards"] = [i for i in inc if i["type"] == "card"]
    detail["substitutions"] = [i for i in inc if i["type"] == "substitution"]

    stats_raw = results.get("statistics") or {}
    detail["statistics"] = [
        {
            "period": p.get("period"),
            "groups": [
                {
                    "name": g.get("groupName"),
                    "items": [
                        {
                            "name": s.get("name"),
                            "home": s.get("home"),
                            "away": s.get("away"),
                        }
                        for s in g.get("statisticsItems", [])
                    ],
                }
                for g in p.get("groups", [])
            ],
        }
        for p in stats_raw.get("statistics", [])
    ]

    mg = results.get("managers") or {}
    detail["managers"] = {
        "home": (mg.get("homeManager") or {}).get("name"),
        "away": (mg.get("awayManager") or {}).get("name"),
    }

    detail["momentum"] = (results.get("graph") or {}).get("graphPoints", [])

    h2h = (results.get("h2h") or {}).get("teamDuel") or {}
    detail["h2h"] = h2h or None

    return detail
