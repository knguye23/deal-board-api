"""deal-board-api: tiny term store behind the Deal Board settings UI.

The hourly OfferUp/Craigslist sweep reads its search terms from here;
the Deal Board settings drawer writes them here. One row, three segments.
"""
import json
import os

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ["DATABASE_URL"]
WRITE_KEY = os.environ.get("TERMS_WRITE_KEY", "")
ORIGINS = [o.strip() for o in os.environ.get(
    "CORS_ORIGINS", "https://deal-board.pages.dev").split(",") if o.strip()]

app = FastAPI(title="deal-board-api")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGINS,
    allow_methods=["GET"],
    allow_headers=["*"],
)

DDL = """CREATE TABLE IF NOT EXISTS sweep_terms (
  id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  segments JSONB NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"""


def db():
    return psycopg2.connect(DATABASE_URL, connect_timeout=20)


@app.on_event("startup")
def startup():
    c = db()
    c.autocommit = True
    try:
        c.cursor().execute(DDL)
    finally:
        c.close()


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/terms")
def get_terms():
    c = db()
    try:
        cur = c.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT segments, updated_at FROM sweep_terms WHERE id = 1")
        row = cur.fetchone()
    finally:
        c.close()
    if not row:
        return {"segments": {"0": [], "1": [], "2": []}, "updated_at": None}
    return {"segments": row["segments"],
            "updated_at": row["updated_at"].isoformat()}


def validate_segments(segs):
    if not isinstance(segs, dict):
        raise HTTPException(400, "segments must be an object")
    out = {}
    for k in ("0", "1", "2"):
        terms = segs.get(k)
        if not isinstance(terms, list) or not terms:
            raise HTTPException(400, f"segment {k} must be a non-empty list")
        if len(terms) > 40:
            raise HTTPException(400, f"segment {k} exceeds 40 terms")
        clean = []
        for t in terms:
            if not isinstance(t, str) or not (1 <= len(t.strip()) <= 80):
                raise HTTPException(400, f"invalid term in segment {k}")
            clean.append(t.strip())
        out[k] = clean
    return out


@app.put("/api/terms")
def put_terms(body: dict, x_api_key: str = Header(None)):
    if not WRITE_KEY or x_api_key != WRITE_KEY:
        raise HTTPException(401, "unauthorized")
    segs = validate_segments(body.get("segments"))
    c = db()
    c.autocommit = True
    try:
        cur = c.cursor()
        cur.execute(
            """INSERT INTO sweep_terms (id, segments, updated_at)
               VALUES (1, %s, now())
               ON CONFLICT (id) DO UPDATE
               SET segments = EXCLUDED.segments, updated_at = now()
               RETURNING updated_at""",
            [json.dumps(segs)],
        )
        updated = cur.fetchone()[0]
    finally:
        c.close()
    return {"ok": True, "updated_at": updated.isoformat()}
