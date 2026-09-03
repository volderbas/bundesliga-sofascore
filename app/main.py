from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import sofascore as ss
from .client import client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="Bundesliga Live", version="1.0.0")


@app.exception_handler(RuntimeError)
async def runtime_error_handler(_req, exc: RuntimeError):
    return JSONResponse(status_code=502, content={"error": str(exc)})


@app.get("/api/leagues")
def leagues():
    return [
        {"key": k, **v, "seasons": ss.get_seasons(k)[:8]} for k, v in ss.LEAGUES.items()
    ]


@app.get("/api/live")
def live():
    return {"events": ss.live_events()}


@app.get("/api/upcoming")
def upcoming(days: int = Query(7, ge=1, le=14)):
    return {"events": ss.upcoming_days(days)}


@app.get("/api/date/{date_str}")
def by_date(date_str: str):
    return {"events": ss.events_by_date(date_str)}


def _season(league: str, season_id: int | None) -> int:
    if league not in ss.LEAGUES:
        raise HTTPException(404, "Bilinmeyen lig")
    sid = season_id or ss.current_season_id(league)
    if not sid:
        raise HTTPException(502, "Sezon bilgisi alınamadı")
    return sid


@app.get("/api/league/{league}/events")
def league_events(league: str, kind: str = "last", page: int = 0, season_id: int | None = None):
    sid = _season(league, season_id)
    if kind not in ("last", "next"):
        raise HTTPException(400, "kind: last | next")
    return {"seasonId": sid, **ss.league_events(league, sid, kind, page)}


@app.get("/api/league/{league}/round/{round_number}")
def league_round(league: str, round_number: int, season_id: int | None = None):
    sid = _season(league, season_id)
    return {"seasonId": sid, "events": ss.league_round(league, sid, round_number)}


@app.get("/api/league/{league}/standings")
def league_standings(league: str, season_id: int | None = None):
    sid = _season(league, season_id)
    return {"seasonId": sid, "tables": ss.standings(league, sid)}


@app.get("/api/match/{event_id}")
def match(event_id: int):
    return ss.match_detail(event_id)


@app.post("/api/cache/clear")
def clear_cache():
    client.cache.clear()
    client.rotate()
    return {"ok": True}


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


def run():
    import uvicorn

    port = int(os.getenv("PORT", "8777"))
    uvicorn.run(app, host="127.0.0.1", port=port)


if __name__ == "__main__":
    run()
