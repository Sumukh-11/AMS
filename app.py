from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path
from typing import Any, Iterator

import pandas as pd
import streamlit as st
from event_feed import find_nearby_events


ROOT = Path(__file__).resolve().parent
if getattr(sys, "frozen", False):
    DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Stride" / "data"
else:
    DATA_DIR = ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "stride.db"
PAGES = ["Athlete", "Coach", "Logs", "Goals", "Events", "Team", "Video lab", "AI companion", "Profile", "Admin"]
ROLES = ["Athlete", "Coach", "Mentor", "Physiotherapist", "Fitness trainer", "Health manager", "Other"]

DATA_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)

st.set_page_config(page_title="Stride | athlete workspace", page_icon=":material/directions_run:", layout="wide")
st.html(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&family=DM+Sans:wght@400;500;600;700&display=swap');
    :root { --ink:#16221f; --forest:#174f43; --lime:#c9e37b; --paper:#f6f7f1; --muted:#74817b; --line:#e3e8df; --coral:#df755c; }
    html, body, [class*="stApp"] { font-family:'DM Sans',sans-serif; }
    [data-testid="stAppViewContainer"] { background:var(--paper); }
    [data-testid="stSidebar"] { background:#eef1e9; border-right:1px solid var(--line); }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h1 { font-family:'Barlow Condensed',sans-serif; font-size:2.3rem; letter-spacing:0; color:var(--forest); }
    h1,h2,h3 { font-family:'Barlow Condensed',sans-serif !important; letter-spacing:0 !important; color:var(--ink); }
    h1 { font-size:2.7rem !important; }
    [data-testid="stMetric"] { background:#fff; border:1px solid var(--line); border-radius:8px; padding:16px 18px; }
    [data-testid="stMetricLabel"] { color:var(--muted); }
    [data-testid="stMetricValue"] { color:var(--ink); }
    div[data-testid="stButton"] button[kind="primary"] { background:var(--forest); border-color:var(--forest); }
    div[data-testid="stButton"] button { border-radius:6px; }
    [data-testid="stChatMessage"] { border-radius:8px; }
    .eyebrow { text-transform:uppercase; letter-spacing:0; font-size:.72rem; font-weight:700; color:var(--forest); }
    .hero { min-height:180px; padding:28px 32px; border-radius:10px; color:#fff; background:linear-gradient(100deg,rgba(17,49,42,.92),rgba(17,49,42,.55)),url('https://images.unsplash.com/photo-1461896836934-ffe607ba8211?auto=format&fit=crop&w=1800&q=85') center 42%/cover; display:flex; flex-direction:column; justify-content:center; }
    .hero h2 { margin:6px 0 2px; color:#fff !important; font-family:'Barlow Condensed',sans-serif; font-size:2.6rem; }
    .hero p { margin:0; color:#eaf0e6; max-width:540px; }
    .hero .eyebrow { color:var(--lime); }
    .hero .motto { margin-top:14px; color:var(--lime); font-size:.78rem; font-weight:700; }
    .hero .signature { color:#eaf0e6; font-size:.72rem; }
    .motto { margin-top:18px; color:var(--forest); font-size:.8rem; font-weight:700; }
    .signature { color:var(--muted); font-size:.74rem; }
    .quiet { color:var(--muted); font-size:.9rem; }
    </style>
    """
)


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db() -> None:
    with connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                name TEXT NOT NULL,
                role TEXT NOT NULL,
                sport TEXT NOT NULL DEFAULT '',
                team TEXT NOT NULL DEFAULT '',
                city TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS links (
                athlete_id INTEGER NOT NULL REFERENCES accounts(id),
                member_id INTEGER NOT NULL REFERENCES accounts(id),
                created_at TEXT NOT NULL,
                PRIMARY KEY (athlete_id, member_id)
            );
            CREATE TABLE IF NOT EXISTS invites (
                code TEXT PRIMARY KEY,
                athlete_id INTEGER NOT NULL REFERENCES accounts(id),
                role TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY,
                athlete_id INTEGER NOT NULL REFERENCES accounts(id),
                author_id INTEGER NOT NULL REFERENCES accounts(id),
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                detail TEXT NOT NULL DEFAULT '',
                event_date TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY,
                athlete_id INTEGER NOT NULL REFERENCES accounts(id),
                session_date TEXT NOT NULL,
                activity TEXT NOT NULL,
                duration_min REAL NOT NULL DEFAULT 0,
                distance_km REAL,
                avg_hr REAL,
                recovery_score REAL,
                source TEXT NOT NULL DEFAULT 'Manual',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS goals (
                id INTEGER PRIMARY KEY,
                athlete_id INTEGER NOT NULL REFERENCES accounts(id),
                title TEXT NOT NULL,
                target REAL NOT NULL,
                current REAL NOT NULL DEFAULT 0,
                start_value REAL NOT NULL DEFAULT 0,
                direction TEXT NOT NULL DEFAULT 'increase',
                unit TEXT NOT NULL,
                due_date TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS goal_events (
                id INTEGER PRIMARY KEY,
                athlete_id INTEGER NOT NULL REFERENCES accounts(id),
                goal_id INTEGER NOT NULL REFERENCES goals(id),
                amount REAL NOT NULL,
                points INTEGER NOT NULL DEFAULT 20,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS game_events (
                id INTEGER PRIMARY KEY,
                athlete_id INTEGER NOT NULL REFERENCES accounts(id),
                event_type TEXT NOT NULL,
                reference_id TEXT NOT NULL,
                points INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE (athlete_id, event_type, reference_id)
            );
            CREATE TABLE IF NOT EXISTS devices (
                id INTEGER PRIMARY KEY,
                athlete_id INTEGER NOT NULL REFERENCES accounts(id),
                provider TEXT NOT NULL,
                device_name TEXT NOT NULL,
                last_import TEXT,
                row_count INTEGER NOT NULL DEFAULT 0,
                UNIQUE (athlete_id, device_name)
            );
            CREATE TABLE IF NOT EXISTS media (
                id INTEGER PRIMARY KEY,
                athlete_id INTEGER NOT NULL REFERENCES accounts(id),
                uploader_id INTEGER NOT NULL REFERENCES accounts(id),
                filename TEXT NOT NULL,
                path TEXT NOT NULL,
                media_type TEXT NOT NULL,
                shared INTEGER NOT NULL DEFAULT 0,
                review TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY,
                athlete_id INTEGER NOT NULL REFERENCES accounts(id),
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        goal_columns = {row["name"] for row in db.execute("PRAGMA table_info(goals)")}
        if "start_value" not in goal_columns:
            db.execute("ALTER TABLE goals ADD COLUMN start_value REAL NOT NULL DEFAULT 0")
            db.execute("UPDATE goals SET start_value=current WHERE current<>0")
        if "direction" not in goal_columns:
            db.execute("ALTER TABLE goals ADD COLUMN direction TEXT NOT NULL DEFAULT 'increase'")
            db.execute(
                "UPDATE goals SET direction='decrease' WHERE title='Run a sub-60 400 m' AND athlete_id=(SELECT id FROM accounts WHERE email='maya.demo@stride.local')"
            )


def now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="minutes")


def password_digest(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return f"{salt.hex()}${digest.hex()}"


def password_matches(password: str, encoded: str) -> bool:
    salt_hex, digest_hex = encoded.split("$", maxsplit=1)
    candidate = password_digest(password, bytes.fromhex(salt_hex)).split("$", maxsplit=1)[1]
    return hmac.compare_digest(candidate, digest_hex)


def account_by_email(email: str) -> sqlite3.Row | None:
    with connect() as db:
        return db.execute("SELECT * FROM accounts WHERE email = ?", (email.strip(),)).fetchone()


def account_by_id(account_id: int) -> sqlite3.Row | None:
    with connect() as db:
        return db.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()


def admin_setting(name: str) -> str:
    value = os.getenv(name, "")
    if value:
        return value
    try:
        return str(st.secrets.get(name, ""))
    except Exception:
        return ""


def ensure_admin_account() -> str:
    email = admin_setting("STRIDE_ADMIN_EMAIL").strip().lower()
    password = admin_setting("STRIDE_ADMIN_PASSWORD")
    if not email and not password:
        with connect() as db:
            existing_admin = db.execute("SELECT 1 FROM accounts WHERE role='Admin' LIMIT 1").fetchone()
        if existing_admin:
            return ""
        return "Admin sign-in is disabled. Configure STRIDE_ADMIN_EMAIL and STRIDE_ADMIN_PASSWORD before starting Stride."
    if not email or not password:
        return "Admin setup requires both STRIDE_ADMIN_EMAIL and STRIDE_ADMIN_PASSWORD."
    if "@" not in email or len(password) < 12:
        return "Admin setup needs a valid email and a password with at least 12 characters."
    existing = account_by_email(email)
    if existing:
        return "" if existing["role"] == "Admin" else "The configured admin email belongs to a non-admin account. Use a separate admin email."
    try:
        with connect() as db:
            db.execute(
                "INSERT INTO accounts(email,password_hash,name,role,sport,team,city,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (email, password_digest(password), "Stride administrator", "Admin", "", "", "", now_text()),
            )
        return ""
    except sqlite3.IntegrityError:
        return "The configured admin email is already in use."


def create_account(email: str, password: str, name: str, role: str, sport: str, team: str, city: str, invite_code: str) -> tuple[sqlite3.Row | None, str | None]:
    email = email.strip().lower()
    if not email or "@" not in email:
        return None, "Enter a valid email address."
    if len(password) < 8:
        return None, "Use a password with at least 8 characters."
    if role != "Athlete" and not invite_code.strip():
        return None, "Ask the athlete for an invite code before creating a support account."
    if account_by_email(email):
        return None, "An account already exists for that email."
    stamp = now_text()
    try:
        with connect() as db:
            cursor = db.execute(
                "INSERT INTO accounts(email,password_hash,name,role,sport,team,city,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (email, password_digest(password), name.strip(), role, sport.strip(), team.strip(), city.strip(), stamp),
            )
            new_id = int(cursor.lastrowid)
            if role != "Athlete" and invite_code.strip():
                invite = db.execute("SELECT athlete_id,role FROM invites WHERE code = ?", (invite_code.strip().upper(),)).fetchone()
                if not invite:
                    db.execute("DELETE FROM accounts WHERE id = ?", (new_id,))
                    return None, "That team invite code is not valid. Ask the athlete to create a new one."
                if invite["role"] != role:
                    db.execute("DELETE FROM accounts WHERE id = ?", (new_id,))
                    return None, f"That invite is for a {invite['role']} account. Ask the athlete for the right role's code."
                db.execute("INSERT OR IGNORE INTO links(athlete_id,member_id,created_at) VALUES(?,?,?)", (invite["athlete_id"], new_id, stamp))
                db.execute("DELETE FROM invites WHERE code = ?", (invite_code.strip().upper(),))
            row = db.execute("SELECT * FROM accounts WHERE id = ?", (new_id,)).fetchone()
            return row, None
    except sqlite3.IntegrityError:
        return None, "An account already exists for that email."


def ensure_demo() -> sqlite3.Row:
    existing = account_by_email("maya.demo@stride.local")
    if existing:
        ensure_demo_support(existing["id"])
        return existing
    athlete, _ = create_account("maya.demo@stride.local", "stride-demo", "Maya Chen", "Athlete", "Track & field", "Northstar Track", "Toronto", "")
    assert athlete is not None
    ensure_demo_support(athlete["id"])
    stamp = now_text()
    coach = account_by_email("jordan.demo@stride.local")
    with connect() as db:
        for days_ago, duration, activity, hr, recovery in [
            (6, 48, "Track intervals", 151, 82), (5, 36, "Strength", 128, 79),
            (3, 54, "Tempo run", 146, 76), (2, 28, "Mobility + drills", 112, 86),
            (0, 62, "Speed endurance", 158, 84),
        ]:
            db.execute(
                "INSERT INTO sessions(athlete_id,session_date,activity,duration_min,avg_hr,recovery_score,source,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (athlete["id"], (date.today() - timedelta(days=days_ago)).isoformat(), activity, duration, hr, recovery, "Demo data", stamp),
            )
        db.execute("INSERT INTO goals(athlete_id,title,target,current,start_value,direction,unit,due_date,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (athlete["id"], "Run a sub-60 400 m", 60, 63.4, 63.4, "decrease", "seconds", (date.today() + timedelta(days=42)).isoformat(), stamp))
        goal_id = db.execute("SELECT id FROM goals WHERE athlete_id=? ORDER BY id DESC LIMIT 1", (athlete["id"],)).fetchone()["id"]
        db.execute("INSERT INTO goal_events(athlete_id,goal_id,amount,points,created_at) VALUES(?,?,?,?,?)", (athlete["id"], goal_id, 0, 120, stamp))
        db.execute("INSERT INTO entries(athlete_id,author_id,kind,title,detail,event_date,created_at) VALUES(?,?,?,?,?,?,?)", (athlete["id"], coach["id"] if coach else athlete["id"], "Plan", "Speed mechanics check-in", "Keep the first 80 m relaxed. We will review the next block together.", date.today().isoformat(), stamp))
    return athlete


def ensure_demo_support(athlete_id: int) -> None:
    stamp = now_text()
    with connect() as db:
        coach = db.execute("SELECT id FROM accounts WHERE email=?", ("jordan.demo@stride.local",)).fetchone()
        if not coach:
            cursor = db.execute(
                "INSERT INTO accounts(email,password_hash,name,role,sport,team,city,created_at) VALUES(?,?,?,?,?,?,?,?)",
                ("jordan.demo@stride.local", password_digest("stride-demo"), "Jordan Lee", "Coach", "Track & field", "Northstar Track", "", stamp),
            )
            coach_id = int(cursor.lastrowid)
        else:
            coach_id = int(coach["id"])
        db.execute("INSERT OR IGNORE INTO links(athlete_id,member_id,created_at) VALUES(?,?,?)", (athlete_id, coach_id, stamp))
        goal = db.execute("SELECT id FROM goals WHERE athlete_id=? ORDER BY id LIMIT 1", (athlete_id,)).fetchone()
        events = db.execute("SELECT COUNT(*) FROM goal_events WHERE athlete_id=?", (athlete_id,)).fetchone()[0]
        if goal and not events:
            db.execute("INSERT INTO goal_events(athlete_id,goal_id,amount,points,created_at) VALUES(?,?,?,?,?)", (athlete_id, goal["id"], 0, 120, stamp))
        db.execute(
            "UPDATE goal_events SET points=0 WHERE athlete_id=? AND goal_id IN (SELECT id FROM goals WHERE title='Run a sub-60 400 m') AND amount=0",
            (athlete_id,),
        )
        db.execute(
            "UPDATE goals SET direction='decrease' WHERE athlete_id=? AND title='Run a sub-60 400 m'",
            (athlete_id,),
        )
        db.execute(
            "INSERT OR IGNORE INTO game_events(athlete_id,event_type,reference_id,points,created_at) SELECT athlete_id,'session',CAST(id AS TEXT),25,created_at FROM sessions WHERE athlete_id=? AND source='Demo data'",
            (athlete_id,),
        )


def current_account() -> sqlite3.Row | None:
    account_id = st.session_state.get("account_id")
    return account_by_id(int(account_id)) if account_id else None


def athlete_for(account: sqlite3.Row) -> sqlite3.Row:
    if account["role"] == "Athlete":
        return account
    with connect() as db:
        linked = db.execute(
            "SELECT a.* FROM accounts a JOIN links l ON l.athlete_id=a.id WHERE l.member_id=? ORDER BY a.name",
            (account["id"],),
        ).fetchall()
    if not linked:
        return account
    athlete_options = {int(row["id"]): str(row["name"]) for row in linked}
    selected_id = st.sidebar.selectbox("Athlete profile", list(athlete_options), format_func=athlete_options.get, key="athlete_profile")
    return account_by_id(selected_id) or account


def linked_members(athlete_id: int) -> list[sqlite3.Row]:
    with connect() as db:
        return db.execute(
            "SELECT a.id,a.name,a.role,a.email FROM accounts a JOIN links l ON l.member_id=a.id WHERE l.athlete_id=? ORDER BY a.role,a.name",
            (athlete_id,),
        ).fetchall()


def add_entry(athlete_id: int, author_id: int, kind: str, title: str, detail: str, event_date: str) -> None:
    with connect() as db:
        db.execute(
            "INSERT INTO entries(athlete_id,author_id,kind,title,detail,event_date,created_at) VALUES(?,?,?,?,?,?,?)",
            (athlete_id, author_id, kind, title.strip(), detail.strip(), event_date, now_text()),
        )


@st.cache_data(ttl="30m", max_entries=80, show_spinner=False)
def weather_for_city(city: str) -> dict[str, Any]:
    if not city.strip():
        return {"error": "Add a city in your profile to see live training conditions."}
    try:
        query = urllib.parse.urlencode({"name": city, "count": 1, "language": "en", "format": "json"})
        with urllib.request.urlopen(f"https://geocoding-api.open-meteo.com/v1/search?{query}", timeout=5) as response:
            place_data = json.loads(response.read().decode())
        places = place_data.get("results", [])
        if not places:
            return {"error": f"No matching location found for {city}."}
        place = places[0]
        params = urllib.parse.urlencode({"latitude": place["latitude"], "longitude": place["longitude"], "current": "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,weather_code", "timezone": "auto"})
        with urllib.request.urlopen(f"https://api.open-meteo.com/v1/forecast?{params}", timeout=5) as response:
            weather = json.loads(response.read().decode())
        return {"place": f"{place['name']}, {place.get('country', '')}", **weather.get("current", {})}
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as error:
        return {"error": f"Live weather is unavailable right now ({type(error).__name__})."}


@st.cache_data(ttl="6h", max_entries=60, show_spinner=False)
def cached_event_search(sport: str, city: str, radius_km: int) -> dict[str, Any]:
    return find_nearby_events(sport, city, radius_km)


def configured_secret(name: str) -> str:
    session_keys = st.session_state.get("ai_api_keys", {})
    if session_keys.get(name):
        return str(session_keys[name])
    value = os.getenv(name, "")
    if value:
        return value
    try:
        return str(st.secrets.get(name, ""))
    except Exception:
        return ""


def openai_key() -> str:
    return configured_secret("OPENAI_API_KEY")


def companion_context(athlete: sqlite3.Row) -> str:
    game = gamification_summary(athlete["id"])
    with connect() as db:
        sessions = db.execute(
            "SELECT session_date,activity,duration_min,avg_hr,recovery_score FROM sessions WHERE athlete_id=? ORDER BY session_date DESC LIMIT 5",
            (athlete["id"],),
        ).fetchall()
        goals = db.execute(
            "SELECT title,target,current,unit,direction FROM goals WHERE athlete_id=? ORDER BY due_date LIMIT 4",
            (athlete["id"],),
        ).fetchall()
        notes = db.execute(
            "SELECT kind,title,event_date,detail FROM entries WHERE athlete_id=? ORDER BY id DESC LIMIT 3",
            (athlete["id"],),
        ).fetchall()
    context = [
        f"Athlete: {athlete['name']}; sport: {athlete['sport'] or 'not set'}; team: {athlete['team'] or 'not set'}.",
        "Recent athlete-entered sessions: " + ("; ".join(f"{row['session_date']} {row['activity']} for {row['duration_min']:g} min" + (f", recovery {row['recovery_score']:g}/100" if row["recovery_score"] is not None else "") for row in sessions) or "none logged"),
        "Current goals: " + ("; ".join(f"{row['title']} ({row['current']:g} toward {row['target']:g} {row['unit']}, direction {row['direction']})" for row in goals) or "none set"),
        "Recent shared team notes: " + ("; ".join(f"{row['event_date']} {row['kind']}: {row['title']} - {row['detail']}" for row in notes) or "none"),
        f"Game progress: level {game['level']}, {game['points']} XP, current training-day streak {game['streak']}, weekly quest {game['week_days']}/3 days.",
    ]
    return "\n".join(context)


def stream_companion(messages: list[dict[str, str]], athlete: sqlite3.Row, provider: str | None) -> Iterator[str]:
    if provider is None:
        yield local_coach_response(messages[-1]["content"], athlete, messages[:-1])
        return
    system = (
        "You are Stride, a warm, thoughtful friend and companion. You can talk about everyday life, relationships, school, work, motivation, "
        "or sports; do not force every conversation into training advice. Listen first, remember what the athlete said earlier in this chat, "
        "and respond naturally rather than using canned openings. Use athlete context only when it genuinely helps, and ask one useful follow-up "
        "when it feels conversational rather than interrogative. "
        "Celebrate consistency and effort without pressuring the athlete to train every day; rest is part of progress. Acknowledge frustration before problem-solving. "
        "Never invent session, device, medical, or competition data. Separate observations from hypotheses. Do not diagnose or prescribe treatment. "
        "For pain, injury, or concerning symptoms, recommend a qualified clinician. Do not claim elite-athlete comparison or validated fact-checking. "
        "The athlete context is private and may include health-adjacent information; do not repeat more detail than needed.\n\n"
        f"Athlete context:\n{companion_context(athlete)}"
    )
    headers = {"Content-Type": "application/json"}
    if provider == "OpenAI":
        key = openai_key()
        if not key:
            yield "The OpenAI key is no longer available. Add it in your environment and reconnect."
            return
        headers["Authorization"] = f"Bearer {key}"
        payload = {
            "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            "messages": [{"role": "system", "content": system}, *messages[-16:]],
            "stream": True,
        }
        endpoint = "https://api.openai.com/v1/chat/completions"
    else:
        key = configured_secret("ANTHROPIC_API_KEY")
        if not key:
            yield "The Claude key is no longer available. Add it in your environment and reconnect."
            return
        headers["x-api-key"] = key
        headers["anthropic-version"] = "2023-06-01"
        payload = {
            "model": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
            "max_tokens": 1200,
            "system": system,
            "messages": messages[-16:],
            "stream": True,
        }
        endpoint = "https://api.anthropic.com/v1/messages"
    request = urllib.request.Request(endpoint, data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if provider == "OpenAI":
                    choices = event.get("choices", [])
                    chunk = choices[0].get("delta", {}).get("content") if choices else None
                    if isinstance(chunk, str) and chunk:
                        yield chunk
                elif event.get("type") == "content_block_delta":
                    chunk = event.get("delta", {}).get("text", "")
                    if chunk:
                        yield chunk
    except urllib.error.HTTPError as error:
        yield f"The {provider} request failed (HTTP {error.code}). Check the API key, model name, or account access."
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        yield f"I couldn't reach {provider} right now ({type(error).__name__}). Check your connection and try again."


def local_coach_response(
    prompt: str,
    athlete: sqlite3.Row,
    conversation: list[dict[str, str]] | None = None,
) -> str:
    text = prompt.lower()
    conversation = conversation or []
    with connect() as db:
        recent = db.execute("SELECT activity,duration_min,recovery_score,session_date FROM sessions WHERE athlete_id=? ORDER BY session_date DESC LIMIT 1", (athlete["id"],)).fetchone()
        goal = db.execute("SELECT title,target,current,unit,direction FROM goals WHERE athlete_id=? ORDER BY due_date LIMIT 1", (athlete["id"],)).fetchone()
    context = f"Your latest logged session: {recent['activity']} for {recent['duration_min']:g} minutes on {recent['session_date']}." if recent else "You haven't logged a session yet, so I'm not going to guess about your training."
    if any(word in text for word in ["pain", "injury", "hurt", "sore"]):
        opening = secrets.choice(["I can't assess an injury from chat.", "Let's put safety first: I can't diagnose what's causing pain."])
        return f"{opening} Pause anything that makes it worse and check in with your physiotherapist or clinician; seek urgent care for severe or sudden symptoms. {context}"
    if text.strip().strip(".!? ") in {"hi", "hello", "hey", "hey friend", "good morning", "good evening"}:
        return secrets.choice([
            "Hey, good to see you. What's on your mind today? We can talk sport, life, or absolutely anything else.",
            "Hey! I'm here. How's your day actually going?",
            "Hi, friend. Want to talk something through, celebrate a win, or just hang out for a minute?",
        ])
    if any(word in text for word in ["overwhelmed", "lonely", "school", "work", "family", "friendship", "breakup", "stressed", "stressful", "bad day", "sad", "anxious", "can't focus"]):
        opening = secrets.choice([
            "That sounds like a lot to carry.",
            "I'm glad you told me. That sounds tough.",
            "Oof, I can see why that would be weighing on you.",
        ])
        return f"{opening} We don't have to turn it into a plan unless you want to. What part has been sitting with you the most?"
    previous_user = next((item["content"] for item in reversed(conversation) if item["role"] == "user"), "")
    if previous_user and any(phrase in text for phrase in ["tell me more", "what about that", "why do you think", "and then", "what should i do", "that makes sense"]):
        return f"I'm following. You mentioned: **{previous_user[:180]}**. What feels most important about that part to you?"
    if any(word in text for word in ["friend", "talk", "bored", "joke", "music", "movie", "book", "game", "what do you think"]):
        return "I'm here for that. We can talk about whatever's on your mind; you don't have to make it about sport. What's been keeping you company lately?"
    if any(phrase in text for phrase in ["not working", "nothing is working", "stuck", "frustrat", "discourag", "can't improve", "cannot improve"]):
        goal_context = "" if not goal else f" Your current target is {goal['title']}, and the latest result is {goal['current']:g} {goal['unit']}."
        opening = secrets.choice(["That sounds really frustrating.", "I hear you; putting in work without seeing a change can wear you down."])
        return f"{opening} A plateau doesn't cancel the work you've already done. {context}{goal_context} Before adding more training, compare a few recent sessions and bring the pattern to your coach; changing one variable at a time makes it easier to learn what helps. What part feels most stuck right now?"
    if any(word in text for word in ["goal", "progress", "time", "target"]):
        target_context = f" Your current goal is **{goal['title']}**; latest result {goal['current']:g} {goal['unit']}, target {goal['target']:g} {goal['unit']} ({'lower' if goal['direction'] == 'decrease' else 'higher'} is better)." if goal else " You can add a measurable target in Goals."
        opening = secrets.choice(["Let's make the next step measurable.", "We can turn that into a small checkpoint."])
        return f"{opening} {context}{target_context} Repeat the benchmark under similar conditions and review the trend with your coach. What does a good next check-in look like for you?"
    if any(word in text for word in ["recovery", "sleep", "tired", "rest"]):
        score = f" The latest recorded recovery score was {recent['recovery_score']:g}/100." if recent and recent["recovery_score"] is not None else " No recovery score is logged yet."
        opening = secrets.choice(["Let's check in before adding more load.", "Recovery is part of the training, not a detour."])
        return f"{opening} Compare how you feel with your own baseline. {context}{score} If fatigue sticks around, talk it through with your coach or health professional. What feels most different today?"
    if any(word in text for word in ["competition", "race", "nervous", "pressure", "meet"]):
        return f"Competition nerves are common; we can make the day feel more controllable. {context} Pick one process cue you can execute regardless of the result, and rehearse your warm-up routine. What part of competition is on your mind?"
    if any(word in text for word in ["plan", "workout", "session", "training"]):
        return f"Let's build from what you actually logged: {context} Keep the next session consistent with the plan your coach has set, and make one variable the focus. What is the main thing you're training for this week?"
    if any(word in text for word in ["technique", "form", "video", "movement"]):
        return f"I can help you think it through, but a text chat can't see your movement. {context} Use Video lab to share a clip with your coach or request a cautious image review. Which moment or cue do you want feedback on?"
    if previous_user:
        return f"I remember you mentioned **{previous_user[:180]}**. Do you want to stay with that, or is something else on your mind?"
    return "I'm here with you. We can talk about training, life, or whatever's on your mind. What's been happening today?"


def add_session(athlete_id: int, activity: str, session_date: str, duration: float, distance: float | None, avg_hr: float | None, recovery: float | None, source: str) -> None:
    with connect() as db:
        cursor = db.execute(
            "INSERT INTO sessions(athlete_id,session_date,activity,duration_min,distance_km,avg_hr,recovery_score,source,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (athlete_id, session_date, activity, duration, distance, avg_hr, recovery, source, now_text()),
        )
        db.execute(
            "INSERT INTO game_events(athlete_id,event_type,reference_id,points,created_at) VALUES(?,?,?,?,?)",
            (athlete_id, "session", str(cursor.lastrowid), 25, now_text()),
        )


def goal_progress(goal: sqlite3.Row) -> float:
    start = float(goal["start_value"])
    target = float(goal["target"])
    current = float(goal["current"])
    if goal["direction"] == "decrease":
        span = start - target
        if span <= 0:
            return 1.0 if current <= target else 0.0
        return min(1.0, max(0.0, (start - current) / span))
    span = target - start
    if span <= 0:
        return 1.0 if current >= target else 0.0
    return min(1.0, max(0.0, (current - start) / span))


def gamification_summary(athlete_id: int) -> dict[str, Any]:
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    with connect() as db:
        week_days = db.execute(
            "SELECT COUNT(DISTINCT session_date) FROM sessions WHERE athlete_id=? AND session_date BETWEEN ? AND ?",
            (athlete_id, week_start.isoformat(), today.isoformat()),
        ).fetchone()[0]
        if week_days >= 3:
            db.execute(
                "INSERT OR IGNORE INTO game_events(athlete_id,event_type,reference_id,points,created_at) VALUES(?,?,?,?,?)",
                (athlete_id, "weekly_quest", week_start.isoformat(), 50, now_text()),
            )
        recent_dates = [
            date.fromisoformat(row["session_date"])
            for row in db.execute(
                "SELECT DISTINCT session_date FROM sessions WHERE athlete_id=? ORDER BY session_date DESC LIMIT 365",
                (athlete_id,),
            ).fetchall()
        ]
        session_count = db.execute("SELECT COUNT(*) FROM sessions WHERE athlete_id=?", (athlete_id,)).fetchone()[0]
        goal_rows = db.execute("SELECT target,current,start_value,direction FROM goals WHERE athlete_id=?", (athlete_id,)).fetchall()
        team_count = db.execute("SELECT COUNT(*) FROM links WHERE athlete_id=?", (athlete_id,)).fetchone()[0]
        shared_clips = db.execute("SELECT COUNT(*) FROM media WHERE athlete_id=? AND shared=1", (athlete_id,)).fetchone()[0]
        points = db.execute(
            "SELECT (SELECT COALESCE(SUM(points),0) FROM game_events WHERE athlete_id=?) + (SELECT COALESCE(SUM(points),0) FROM goal_events WHERE athlete_id=?)",
            (athlete_id, athlete_id),
        ).fetchone()[0]
    streak = 0
    previous_day: date | None = None
    if recent_dates and (today - recent_dates[0]).days <= 1:
        for session_day in recent_dates:
            if previous_day is None:
                streak = 1
            elif (previous_day - session_day).days <= 2:
                streak += 1
            else:
                break
            previous_day = session_day
    completed_goal = any(goal_progress(goal) >= 1 for goal in goal_rows)
    level = int(points) // 250 + 1
    level_points = int(points) % 250
    return {
        "points": int(points),
        "level": level,
        "level_points": level_points,
        "level_progress": level_points / 250,
        "streak": streak,
        "week_days": int(week_days),
        "badges": [
            ("First session", session_count > 0, ":material/directions_run:"),
            ("Three-day rhythm", week_days >= 3, ":material/calendar_month:"),
            ("Goal reached", completed_goal, ":material/flag:"),
            ("Team connected", team_count > 0, ":material/groups:"),
            ("Clip shared", shared_clips > 0, ":material/movie:"),
        ],
    }


def render_auth(admin_status: str) -> None:
    left, right = st.columns([1.1, 0.9], gap="large", vertical_alignment="center")
    with left:
        st.markdown('<div class="eyebrow">Stride / athlete workspace</div>', unsafe_allow_html=True)
        st.title("Your work. Your people. Your next level.")
        st.write("A shared training home for athletes and the people who support them.")
        st.markdown("**Training load** · **Team notes** · **Movement review** · **One steady companion**")
        st.markdown('<p class="motto">NOTHING HAPPENS OVERNIGHT NOTHING TAKES THE WHOLE LIFE</p><p class="signature">- SUMUKH</p>', unsafe_allow_html=True)
        st.caption("Local prototype. Create an account to store your workspace on this computer.")
    with right:
        sign_in, register, admin_sign_in = st.tabs(["Sign in", "Create account", "Admin sign-in"])
        with sign_in:
            with st.form("sign_in"):
                email = st.text_input("Email", key="login_email")
                password = st.text_input("Password", type="password", key="login_password")
                submitted = st.form_submit_button("Sign in", type="primary", width="stretch")
            if submitted:
                account = account_by_email(email)
                if account and password_matches(password, account["password_hash"]):
                    st.session_state.account_id = account["id"]
                    st.rerun()
                st.error("Email or password does not match.")
            if st.button("Explore the demo workspace", icon=":material/visibility:", width="stretch"):
                st.session_state.account_id = ensure_demo()["id"]
                st.rerun()

        with register:
            with st.form("register"):
                name = st.text_input("Full name")
                new_email = st.text_input("Email address", key="register_email")
                new_password = st.text_input("Password (8+ characters)", type="password", key="register_password")
                role = st.selectbox("I am joining as", ROLES)
                sport = st.text_input("Sport", placeholder="e.g. Track & field")
                team = st.text_input("Team or club", placeholder="Optional")
                city = st.text_input("Training city", placeholder="Used for live weather context")
                invite = st.text_input("Athlete invite code", help="Support members need a code from the athlete to connect. Athletes can leave this blank.") if role != "Athlete" else ""
                submitted = st.form_submit_button("Create my workspace", type="primary", width="stretch")
            if submitted:
                if not name.strip():
                    st.error("Add your name to continue.")
                else:
                    account, error = create_account(new_email, new_password, name, role, sport, team, city, invite)
                    if error:
                        st.error(error)
                    else:
                        st.session_state.account_id = account["id"]
                        st.rerun()

        with admin_sign_in:
            st.caption("Restricted administrator access")
            if admin_status:
                st.info(admin_status, icon=":material/lock:")
            with st.form("admin_sign_in"):
                admin_email = st.text_input("Admin email", key="admin_login_email")
                admin_password = st.text_input("Admin password", type="password", key="admin_login_password")
                submitted = st.form_submit_button("Sign in as admin", type="primary", width="stretch", disabled=bool(admin_status))
            if submitted:
                admin = account_by_email(admin_email)
                if admin and admin["role"] == "Admin" and password_matches(admin_password, admin["password_hash"]):
                    st.session_state.account_id = admin["id"]
                    st.rerun()
                st.error("Admin email or password does not match.")


def render_profile(account: sqlite3.Row) -> None:
    st.subheader("Your profile")
    st.caption("These details belong to your login. Changes save to this local workspace.")
    with st.form("profile_form"):
        name = st.text_input("Full name", value=account["name"])
        email = st.text_input("Email address", value=account["email"])
        st.text_input("Account type", value=account["role"], disabled=True)
        sport = st.text_input("Sport", value=account["sport"])
        team = st.text_input("Team or club", value=account["team"])
        city = st.text_input("Training city", value=account["city"])
        submitted = st.form_submit_button("Save profile", type="primary", icon=":material/save:")
    if submitted:
        normalized_email = email.strip().lower()
        if not name.strip() or "@" not in normalized_email:
            st.error("Enter your name and a valid email address.")
        else:
            profile_saved = False
            with connect() as db:
                duplicate = db.execute("SELECT id FROM accounts WHERE email=? AND id<>?", (normalized_email, account["id"])).fetchone()
                if duplicate:
                    st.error("That email address is already in use.")
                else:
                    db.execute(
                        "UPDATE accounts SET name=?,email=?,sport=?,team=?,city=? WHERE id=?",
                        (name.strip(), normalized_email, sport.strip(), team.strip(), city.strip(), account["id"]),
                    )
                    profile_saved = True
            if profile_saved:
                st.toast("Profile saved.", icon=":material/check_circle:")
                st.rerun()


def render_admin() -> None:
    st.subheader("Administrator overview")
    st.caption("Account and system overview only. Athlete sessions, health-adjacent metrics, media, and private chat are not shown here.")
    with connect() as db:
        counts = db.execute("SELECT role,COUNT(*) AS total FROM accounts GROUP BY role").fetchall()
        users = db.execute(
            "SELECT name AS Name,email AS Email,role AS Role,sport AS Sport,team AS Team,created_at AS 'Created' FROM accounts WHERE role<>'Admin' ORDER BY created_at DESC"
        ).fetchall()
        pending_invites = db.execute("SELECT COUNT(*) FROM invites").fetchone()[0]
        linked_members = db.execute("SELECT COUNT(*) FROM links").fetchone()[0]
    totals = {row["role"]: int(row["total"]) for row in counts}
    athlete_col, member_col, invite_col, link_col = st.columns(4)
    athlete_col.metric("Athletes", totals.get("Athlete", 0), border=True)
    member_col.metric("Support accounts", sum(total for role, total in totals.items() if role not in {"Athlete", "Admin"}), border=True)
    invite_col.metric("Pending invites", int(pending_invites), border=True)
    link_col.metric("Team links", int(linked_members), border=True)
    st.subheader("Accounts")
    if users:
        st.dataframe(pd.DataFrame([dict(row) for row in users]), hide_index=True)
    else:
        st.caption("No non-admin accounts yet.")


def render_dashboard(athlete: sqlite3.Row, game: dict[str, Any]) -> None:
    first_name = athlete["name"].split()[0]
    first_name = escape(first_name)
    st.html(f'<section class="hero"><div class="eyebrow">{date.today().strftime("%A, %B %-d") if os.name != "nt" else date.today().strftime("%A, %B %d").replace(" 0", " ")}</div><h2>Keep showing up, {first_name}.</h2><p>One clear view of your training, your people, and what comes next.</p><p class="motto">NOTHING HAPPENS OVERNIGHT NOTHING TAKES THE WHOLE LIFE</p><small class="signature">- SUMUKH</small></section>')
    st.write("")
    with connect() as db:
        sessions = pd.read_sql_query("SELECT session_date AS Date, activity AS Session, duration_min AS Minutes, distance_km AS Distance, avg_hr AS 'Avg HR', recovery_score AS Recovery, source AS Source FROM sessions WHERE athlete_id=? ORDER BY session_date DESC", db, params=(athlete["id"],))
        recent = db.execute("SELECT COUNT(*) AS n, COALESCE(SUM(duration_min),0) AS mins, AVG(recovery_score) AS recovery FROM sessions WHERE athlete_id=? AND session_date>=?", (athlete["id"], (date.today() - timedelta(days=6)).isoformat())).fetchone()
        goal = db.execute("SELECT title,target,current,start_value,direction,unit,due_date FROM goals WHERE athlete_id=? ORDER BY due_date LIMIT 1", (athlete["id"],)).fetchone()
        points = db.execute("SELECT COALESCE(SUM(points),0) FROM goal_events WHERE athlete_id=?", (athlete["id"],)).fetchone()[0]
    metric_a, metric_b, metric_c, metric_d = st.columns(4)
    metric_a.metric("Sessions · 7 days", int(recent["n"]), border=True)
    metric_b.metric("Training time", f"{recent['mins'] / 60:.1f} h", border=True)
    metric_c.metric("Recovery trend", f"{recent['recovery']:.0f}/100" if recent["recovery"] is not None else "Not logged", border=True)
    metric_d.metric("Current streak", f"{game['streak']} days", "a rest day keeps it going", border=True)
    with st.container(border=True):
        level_column, quest_column = st.columns([1, 1], gap="large")
        with level_column:
            st.subheader(f"Level {game['level']} · the climb")
            st.progress(game["level_progress"], text=f"{game['level_points']} / 250 XP to level {game['level'] + 1} · {game['points']} total XP")
        with quest_column:
            st.subheader("Weekly quest")
            quest_progress = min(1.0, game["week_days"] / 3)
            quest_text = "Quest complete · +50 XP earned" if game["week_days"] >= 3 else f"Train on 3 different days · {game['week_days']} / 3"
            st.progress(quest_progress, text=quest_text)
        st.markdown("**Milestones**")
        with st.container(horizontal=True, gap="small"):
            for label, unlocked, icon in game["badges"]:
                st.badge(label, icon=icon, color="green" if unlocked else "gray")
        st.caption("Sessions earn 25 XP · meaningful goal progress earns 20 XP · one rest day between sessions keeps your rhythm alive.")
    chart_col, context_col = st.columns([1.5, 0.8], gap="large")
    with chart_col:
        with st.container(border=True):
            st.subheader("Training rhythm")
            if not sessions.empty:
                sessions["Date"] = pd.to_datetime(sessions["Date"])
                chart = sessions.groupby("Date", as_index=False)["Minutes"].sum().sort_values("Date")
                st.bar_chart(chart, x="Date", y="Minutes", x_label="Training day", y_label="Minutes")
            else:
                st.caption("Your session trend will appear here after your first log.")
    with context_col:
        with st.container(border=True):
            st.subheader("Conditions around you")
            weather = weather_for_city(athlete["city"])
            if weather.get("error"):
                st.caption(weather["error"])
            else:
                st.metric("Current temperature", f"{weather.get('temperature_2m', '—')}°C", weather.get("place", ""))
                st.write(f"Wind **{weather.get('wind_speed_10m', '—')} km/h** · humidity **{weather.get('relative_humidity_2m', '—')}%**")
                st.caption("Live conditions · Open-Meteo · not a training prescription")
            if goal:
                st.markdown("**Next milestone**")
                st.write(goal["title"])
                st.progress(goal_progress(goal), text=f"{goal['current']:g} → {goal['target']:g} {goal['unit']} · due {goal['due_date']}")
    if not sessions.empty:
        with st.container(border=True):
            st.subheader("Recent sessions")
            st.dataframe(sessions.head(5), hide_index=True, column_config={"Minutes": st.column_config.NumberColumn(format="%.0f min"), "Distance": st.column_config.NumberColumn(format="%.2f km"), "Avg HR": st.column_config.NumberColumn(format="%.0f bpm"), "Recovery": st.column_config.NumberColumn(format="%.0f/100")})


def render_logs(account: sqlite3.Row, athlete: sqlite3.Row) -> None:
    st.subheader("Training log")
    st.caption("Manual logs and imported device exports stay attached to this athlete profile.")
    if account["role"] != "Athlete":
        st.info("Session data is read-only for support accounts in this prototype.", icon=":material/lock:")
        with connect() as db:
            frame = pd.read_sql_query("SELECT session_date AS Date, activity AS Session, duration_min AS Minutes, distance_km AS 'Distance (km)', avg_hr AS 'Avg HR', recovery_score AS Recovery, source AS Source FROM sessions WHERE athlete_id=? ORDER BY session_date DESC", db, params=(athlete["id"],))
        st.dataframe(frame, hide_index=True)
        return
    with st.form("session_form"):
        cols = st.columns([1.1, 1, 0.8, 0.8])
        activity = cols[0].text_input("Session", placeholder="Easy run, intervals…")
        session_day = cols[1].date_input("Date", value=date.today())
        duration = cols[2].number_input("Minutes", min_value=0.0, max_value=1440.0, value=45.0, step=5.0)
        avg_hr = cols[3].number_input("Average heart rate", min_value=0.0, max_value=250.0, value=0.0, step=1.0, help="Leave at 0 when not measured.")
        second = st.columns(3)
        distance = second[0].number_input("Distance (km)", min_value=0.0, max_value=500.0, value=0.0, step=0.1)
        recovery = second[1].number_input("Recovery score (0–100)", min_value=0.0, max_value=100.0, value=0.0, step=1.0)
        submitted = second[2].form_submit_button("Save session", type="primary", width="stretch")
    if submitted:
        if not activity.strip() or duration <= 0:
            st.error("Add a session name and a duration above zero.")
        else:
            add_session(athlete["id"], activity, session_day.isoformat(), duration, distance or None, avg_hr or None, recovery or None, f"{account['name']} · manual")
            st.toast("Session saved to the athlete profile.", icon=":material/check_circle:")
            st.rerun()
    with st.expander("Import a device export (CSV)", icon=":material/upload_file:"):
        st.caption("Export a CSV from Garmin, Apple Health, WHOOP, Polar, Oura, or another source. This is a file import, not a direct account connection.")
        upload = st.file_uploader("Choose a CSV", type=["csv"], key="device_csv")
        provider = st.selectbox("Device or source", ["Garmin", "Apple Health", "WHOOP", "Polar", "Oura", "Other CSV export"])
        st.caption("Required column: date. Optional: activity, duration_min, distance_km, avg_hr, recovery_score.")
        if upload and st.button("Import sessions", icon=":material/sync:"):
            try:
                frame = pd.read_csv(upload)
                frame.columns = [str(column).strip().lower() for column in frame.columns]
                if "date" not in frame.columns:
                    raise ValueError("CSV needs a date column.")
                imported = 0
                for _, row in frame.iterrows():
                    raw_duration = row.get("duration_min", 0)
                    duration_value = 0.0 if pd.isna(raw_duration) else float(raw_duration)
                    if duration_value <= 0:
                        continue
                    parsed_date = pd.to_datetime(row["date"], errors="raise").date().isoformat()
                    def optional_number(column: str) -> float | None:
                        value = row.get(column)
                        return None if value is None or pd.isna(value) else float(value)
                    raw_activity = row.get("activity", "Training session")
                    session_name = "Training session" if pd.isna(raw_activity) else str(raw_activity)
                    add_session(athlete["id"], session_name, parsed_date, duration_value, optional_number("distance_km"), optional_number("avg_hr"), optional_number("recovery_score"), provider)
                    imported += 1
                with connect() as db:
                    db.execute("INSERT INTO devices(athlete_id,provider,device_name,last_import,row_count) VALUES(?,?,?,?,?) ON CONFLICT(athlete_id,device_name) DO UPDATE SET last_import=excluded.last_import,row_count=devices.row_count+excluded.row_count,provider=excluded.provider", (athlete["id"], provider, provider, now_text(), imported))
                st.success(f"Imported {imported} session(s) from {provider}.")
                st.rerun()
            except (ValueError, TypeError, KeyError) as error:
                st.error(f"Could not import this file: {error}")
    with connect() as db:
        frame = pd.read_sql_query("SELECT session_date AS Date, activity AS Session, duration_min AS Minutes, distance_km AS 'Distance (km)', avg_hr AS 'Avg HR', recovery_score AS Recovery, source AS Source FROM sessions WHERE athlete_id=? ORDER BY session_date DESC", db, params=(athlete["id"],))
        devices = db.execute("SELECT provider,device_name,last_import,row_count FROM devices WHERE athlete_id=? ORDER BY device_name", (athlete["id"],)).fetchall()
    st.subheader("Sessions")
    if frame.empty:
        st.caption("No sessions yet. Add one above or import a wearable export.")
    else:
        st.dataframe(frame, hide_index=True)
    if devices:
        st.subheader("Imported sources")
        for device in devices:
            st.markdown(f"**{device['device_name']}** · {device['row_count']} session rows · last import {device['last_import']}")


def render_goals(account: sqlite3.Row, athlete: sqlite3.Row) -> None:
    st.subheader("Goals and milestones")
    if account["role"] == "Athlete":
        with st.form("goal_form"):
            title = st.text_input("Goal", placeholder="e.g. Complete 3 quality sessions each week")
            columns = st.columns(3)
            target = columns[0].number_input("Target", min_value=0.1, value=3.0, step=0.5)
            current = columns[1].number_input("Starting result", min_value=0.0, value=0.0, step=0.5)
            unit = columns[2].text_input("Unit", value="sessions")
            direction_label = st.selectbox("Progress direction", ["Increase to target", "Reduce to target"])
            due = st.date_input("Target date", value=date.today() + timedelta(days=28))
            submitted = st.form_submit_button("Add goal", type="primary")
        if submitted:
            if not title.strip():
                st.error("Give the goal a name first.")
            else:
                with connect() as db:
                    direction = "decrease" if direction_label == "Reduce to target" else "increase"
                    db.execute("INSERT INTO goals(athlete_id,title,target,current,start_value,direction,unit,due_date,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (athlete["id"], title.strip(), target, current, current, direction, unit.strip() or "steps", due.isoformat(), now_text()))
                st.toast("Goal added.", icon=":material/flag:")
                st.rerun()
    with connect() as db:
        goals = db.execute("SELECT * FROM goals WHERE athlete_id=? ORDER BY due_date", (athlete["id"],)).fetchall()
    if not goals:
        st.caption("Add a goal to make progress visible.")
    for goal in goals:
        with st.container(border=True):
            st.markdown(f"**{goal['title']}**")
            st.progress(goal_progress(goal), text=f"{goal['current']:g} → {goal['target']:g} {goal['unit']} · due {goal['due_date']}")
            with st.form(f"progress_{goal['id']}"):
                update = st.number_input("New result", min_value=0.0, value=float(goal["current"]), step=0.5, key=f"progress_amount_{goal['id']}")
                submitted = st.form_submit_button("Log result", icon=":material/add:")
            if submitted:
                improved = update < goal["current"] if goal["direction"] == "decrease" else update > goal["current"]
                if improved:
                    with connect() as db:
                        db.execute("UPDATE goals SET current=? WHERE id=?", (update, goal["id"]))
                        db.execute("INSERT INTO goal_events(athlete_id,goal_id,amount,points,created_at) VALUES(?,?,?,?,?)", (athlete["id"], goal["id"], abs(goal["current"] - update), 20, now_text()))
                    st.toast("Improvement logged · +20 XP", icon=":material/military_tech:")
                    st.rerun()
                else:
                    st.warning("Log a result that moves closer to your target to earn progress points.")
    if account["role"] != "Athlete":
        st.caption("Progress belongs to the athlete profile. Shared staff can view it but cannot change athlete goals in this prototype.")


def render_events(athlete: sqlite3.Row) -> None:
    st.subheader("Upcoming official events")
    st.caption("Live listings from the official athletics calendar for your country, filtered by sport and distance from your location.")
    with st.form("event_search_form"):
        columns = st.columns([1, 1, 0.65])
        sport = columns[0].text_input("Sport", value=athlete["sport"], placeholder="e.g. Track & field")
        city = columns[1].text_input("Search near", value=athlete["city"], placeholder="City or town")
        radius_km = columns[2].selectbox("Radius", [25, 50, 100, 250, 500], index=3, format_func=lambda distance: f"{distance} km")
        submitted = st.form_submit_button("Find nearby events", type="primary", icon=":material/search:")
    if submitted:
        if not sport.strip() or not city.strip():
            st.error("Enter a sport and a nearby city to search.")
        else:
            with st.spinner("Checking official event listings near you…"):
                st.session_state.event_results = cached_event_search(sport.strip(), city.strip(), int(radius_km))
                st.session_state.event_search_label = f"{sport.strip()} near {city.strip()} within {radius_km} km"
    result = st.session_state.get("event_results")
    if not result:
        st.info("Enter your sport and city, then search the official event calendar.", icon=":material/event:")
        return
    st.caption(st.session_state.get("event_search_label", "Official event search"))
    if result.get("error"):
        st.warning(result["error"], icon=":material/info:")
        return
    source = result.get("source", "official event calendar")
    st.caption(f"Showing {len(result['events'])} upcoming event(s) near {result['location']}. Source: {source}.")
    if result.get("source_url"):
        st.link_button("Open official calendar", result["source_url"], icon=":material/open_in_new:")
    if not result["events"]:
        st.info("No matching events were found in this radius. Try widening the distance or checking the official calendar.")
        return
    for event in result["events"]:
        with st.container(border=True):
            st.markdown(f"**{event['title']}**")
            st.write(event["date_location"])
            st.caption(f"{event['distance_km']} km away · {event['source']}")
            with st.container(horizontal=True, gap="small"):
                if event["registration_url"]:
                    st.link_button("Register", event["registration_url"], type="primary", icon=":material/how_to_reg:")
                elif event["event_url"]:
                    event_label = "Open official listing" if event["source"] == "World Athletics official calendar" else "Open event / registration"
                    st.link_button(event_label, event["event_url"], type="primary", icon=":material/open_in_new:")
                    st.caption("No separate registration link is published in this official listing.")
                if event["event_url"] and event["registration_url"]:
                    st.link_button("Event details", event["event_url"], icon=":material/info:")


def render_team(account: sqlite3.Row, athlete: sqlite3.Row) -> None:
    st.subheader("Your support team")
    st.caption("Athletes choose who joins. Connected members can add dated notes and plans that stay visible here.")
    if account["role"] == "Athlete":
        with st.form("invite_form"):
            role = st.selectbox("Invite someone as", ROLES[1:])
            submitted = st.form_submit_button("Create invite code", icon=":material/person_add:")
        if submitted:
            code = secrets.token_urlsafe(6).replace("-", "").replace("_", "").upper()[:8]
            with connect() as db:
                db.execute("INSERT INTO invites(code,athlete_id,role,created_at) VALUES(?,?,?,?)", (code, athlete["id"], role, now_text()))
            st.session_state.latest_invite = code
        if st.session_state.get("latest_invite"):
            st.code(st.session_state.latest_invite, language=None)
            st.caption("Share this code privately. It links a new support-member account to your workspace.")
    members = linked_members(athlete["id"])
    if members:
        st.dataframe(pd.DataFrame([{"Name": member["name"], "Role": member["role"], "Email": member["email"]} for member in members]), hide_index=True)
    else:
        st.caption("No support members are linked yet.")
    st.subheader("Shared notebook")
    with st.form("shared_entry"):
        kind = st.selectbox("Entry type", ["Note", "Plan", "Session date", "Competition date"])
        title = st.text_input("Title", placeholder="What should the team know?")
        detail = st.text_area("Details", placeholder="Add context, next steps, or feedback.")
        event_day = st.date_input("Relevant date", value=date.today())
        submitted = st.form_submit_button("Post to athlete workspace", type="primary")
    if submitted:
        if not title.strip():
            st.error("Add a title before posting.")
        else:
            add_entry(athlete["id"], account["id"], kind, title, detail, event_day.isoformat())
            st.toast("Added to the shared notebook.", icon=":material/check_circle:")
            st.rerun()
    with connect() as db:
        entries = db.execute("SELECT e.*,a.name AS author_name,a.role AS author_role FROM entries e JOIN accounts a ON a.id=e.author_id WHERE e.athlete_id=? ORDER BY e.event_date DESC,e.id DESC LIMIT 50", (athlete["id"],)).fetchall()
    if entries:
        for entry in entries:
            with st.container(border=True):
                st.markdown(f"**{entry['title']}**  ·  {entry['kind']}  ·  {entry['event_date']}")
                st.caption(f"{entry['author_name']} · {entry['author_role']}")
                if entry["detail"]:
                    st.write(entry["detail"])
    else:
        st.caption("Notes, plans, and important dates will appear here.")


def store_upload(athlete_id: int, uploader_id: int, uploaded: Any, shared: bool, review: str = "") -> None:
    safe_name = Path(uploaded.name).name.replace(" ", "_")
    file_name = f"{athlete_id}_{secrets.token_hex(5)}_{safe_name}"
    target = UPLOAD_DIR / file_name
    target.write_bytes(uploaded.getvalue())
    extension = target.suffix.lower()
    media_type = "video" if extension in {".mp4", ".mov", ".webm", ".m4v"} else "image"
    with connect() as db:
        db.execute("INSERT INTO media(athlete_id,uploader_id,filename,path,media_type,shared,review,created_at) VALUES(?,?,?,?,?,?,?,?)", (athlete_id, uploader_id, uploaded.name, str(target), media_type, int(shared), review, now_text()))


def analyze_image(image_bytes: bytes, mime_type: str, sport: str, prompt: str) -> str:
    key = openai_key()
    if not key:
        return "Image is saved, but an AI vision review has not run. Add OPENAI_API_KEY to your environment or Streamlit secrets to enable evidence-based image feedback. Your coach can still review the image in Video lab."
    system = f"You are a cautious sports movement assistant for {sport or 'an unspecified sport'}. Describe only visible evidence in this single image. Offer at most 3 practical cues. A still image cannot verify movement over time, compare performance to professional athletes, diagnose injury, or establish medical facts. Say what cannot be assessed."
    data_url = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode()}"
    body = json.dumps({"model": "gpt-4o-mini", "input": [{"role": "system", "content": [{"type": "input_text", "text": system}]}, {"role": "user", "content": [{"type": "input_text", "text": prompt or "What is visible, and what is one safe technique cue to discuss with my coach?"}, {"type": "input_image", "image_url": data_url}]}]}).encode()
    request = urllib.request.Request("https://api.openai.com/v1/responses", data=body, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            result = json.loads(response.read().decode())
        if result.get("output_text"):
            return result["output_text"].strip()
        return " ".join(item.get("text", "") for block in result.get("output", []) for item in block.get("content", []) if item.get("type") == "output_text").strip() or "The vision service returned no review."
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        return f"The vision service could not complete this review ({type(error).__name__}). The image can still be shared with your support team."


def render_video_lab(account: sqlite3.Row, athlete: sqlite3.Row) -> None:
    st.subheader("Video lab")
    st.caption("Capture or upload evidence, then choose whether to share it with your connected support team.")
    upload_col, camera_col = st.columns(2, gap="large")
    with upload_col:
        media = st.file_uploader("Upload a video or image", type=["mp4", "mov", "webm", "m4v", "jpg", "jpeg", "png", "webp"], key="movement_upload")
        if media:
            if media.type.startswith("video/"):
                st.video(media)
            elif media.type.startswith("image/"):
                st.image(media, width="stretch")
    with camera_col:
        capture = st.camera_input("Capture a technique image", key="movement_camera")
    share = st.checkbox("Share this upload with my support team", value=True, key="share_media")
    question = st.text_input("What would you like feedback on?", placeholder="e.g. body position at take-off")
    selected_image = capture if capture else media if media and media.type.startswith("image/") else None
    analyze = st.button("Save upload and request image review", type="primary", icon=":material/visibility:", disabled=not (media or capture))
    if analyze and (media or capture):
        review = ""
        if selected_image:
            with st.spinner("Reviewing visible evidence…"):
                review = analyze_image(selected_image.getvalue(), selected_image.type or "image/jpeg", athlete["sport"], question)
        elif media and media.type.startswith("video/"):
            review = "Video stored for team review. Automated motion analysis is not enabled in this prototype; no movement claims have been generated."
        if media:
            store_upload(athlete["id"], account["id"], media, share, review)
        elif capture:
            store_upload(athlete["id"], account["id"], capture, share, review)
        st.session_state.latest_review = review
        if share:
            add_entry(athlete["id"], account["id"], "Video review", "New movement upload shared", "A new upload is ready for your support team to review.", date.today().isoformat())
        st.rerun()
    if st.session_state.get("latest_review"):
        with st.container(border=True):
            st.markdown("**Review notes**")
            st.write(st.session_state.latest_review)
            st.caption("A single image is not a validated performance test or a substitute for a coach or clinician.")
    with connect() as db:
        if account["role"] == "Athlete":
            media_rows = db.execute("SELECT m.*,a.name AS author FROM media m JOIN accounts a ON a.id=m.uploader_id WHERE m.athlete_id=? ORDER BY m.id DESC", (athlete["id"],)).fetchall()
        else:
            media_rows = db.execute("SELECT m.*,a.name AS author FROM media m JOIN accounts a ON a.id=m.uploader_id WHERE m.athlete_id=? AND m.shared=1 ORDER BY m.id DESC", (athlete["id"],)).fetchall()
    st.subheader("Review queue")
    if not media_rows:
        st.caption("No uploads yet.")
    for item in media_rows:
        with st.container(border=True):
            st.markdown(f"**{item['filename']}** · {item['media_type']} · {item['created_at']} · {'shared with team' if item['shared'] else 'athlete only'}")
            path = Path(item["path"])
            if path.exists():
                if item["media_type"] == "video":
                    st.video(str(path))
                else:
                    st.image(str(path), width="stretch")
            if item["review"]:
                st.write(item["review"])
            if account["role"] != "Athlete":
                with st.form(f"coach_review_{item['id']}"):
                    note = st.text_area("Add coach or support-team feedback", key=f"coach_note_{item['id']}")
                    submitted = st.form_submit_button("Post feedback")
                if submitted:
                    if note.strip():
                        add_entry(athlete["id"], account["id"], "Video review", f"Feedback on {item['filename']}", note, date.today().isoformat())
                        st.toast("Feedback added to the athlete notebook.")
                        st.rerun()
                    st.error("Add feedback before posting.")


def render_ai(account: sqlite3.Row, athlete: sqlite3.Row) -> None:
    st.subheader("Stride companion")
    if account["role"] != "Athlete":
        st.info("The athlete's companion conversation is private and is not available to support accounts.", icon=":material/lock:")
        return
    with st.expander("AI connection settings", icon=":material/key:"):
        with st.form("ai_connection_form"):
            connection_provider = st.selectbox("Provider", ["OpenAI", "Claude"], key="ai_connection_provider")
            key_name = "OPENAI_API_KEY" if connection_provider == "OpenAI" else "ANTHROPIC_API_KEY"
            connection_key = st.text_input("API key", type="password", placeholder="Paste your provider key", key="ai_connection_key")
            save_key = st.form_submit_button("Connect for this session", icon=":material/bolt:")
        if save_key:
            if not connection_key.strip():
                st.error("Paste an API key to connect.")
            else:
                session_keys = dict(st.session_state.get("ai_api_keys", {}))
                session_keys[key_name] = connection_key.strip()
                st.session_state.ai_api_keys = session_keys
                st.toast(f"{connection_provider} connected for this session.", icon=":material/check_circle:")
                st.rerun()
        st.caption("Session-only: the key stays in this app process's memory. It is not written to the workspace database or a file. Provider use may incur charges.")
    available = []
    if openai_key():
        available.append("OpenAI")
    if configured_secret("ANTHROPIC_API_KEY"):
        available.append("Claude")
    if available:
        provider = st.selectbox("Response engine", available, key="ai_provider")
        st.badge(f"{provider} · streaming", icon=":material/bolt:", color="green")
        st.caption(f"Your message and recent training context are sent to {provider}; chat history is also saved in this local workspace. Avoid sharing information you do not want processed by that provider.")
    else:
        provider = None
        st.badge("Offline guide · no AI key configured", icon=":material/info:", color="orange")
        st.caption("Connect an API key in AI connection settings for live streamed responses. The offline guide makes no external AI request.")
    st.caption("Training support, not medical care. The conversation is private to the athlete in this prototype.")
    with connect() as db:
        history = db.execute("SELECT role,content FROM messages WHERE athlete_id=? ORDER BY id DESC LIMIT 40", (athlete["id"],)).fetchall()
    messages = list(reversed(history))
    if not messages:
        st.markdown("**Start with a prompt**")
        suggestion = st.pills("Try one", ["Can we just talk?", "Help me reset after a hard day", "What should I focus on this week?", "I'm nervous about competition"], label_visibility="collapsed")
        if suggestion:
            st.session_state.pending_prompt = suggestion
            st.rerun()
    for message in messages:
        with st.chat_message(message["role"], avatar=":material/directions_run:" if message["role"] == "assistant" else None):
            st.write(message["content"])
    prompt = st.session_state.pop("pending_prompt", None) or st.chat_input("Talk to me about sport, life, or anything on your mind")
    if prompt:
        with connect() as db:
            db.execute("INSERT INTO messages(athlete_id,role,content,created_at) VALUES(?,?,?,?)", (athlete["id"], "user", prompt, now_text()))
        transcript = [{"role": item["role"], "content": item["content"]} for item in messages] + [{"role": "user", "content": prompt}]
        with st.chat_message("user"):
            st.write(prompt)
        with st.chat_message("assistant", avatar=":material/directions_run:"):
            answer = st.write_stream(stream_companion(transcript, athlete, provider))
        with connect() as db:
            db.execute("INSERT INTO messages(athlete_id,role,content,created_at) VALUES(?,?,?,?)", (athlete["id"], "assistant", answer, now_text()))
        st.rerun()


def render_coach(account: sqlite3.Row, athlete: sqlite3.Row) -> None:
    st.subheader("Coach workspace")
    if account["role"] == "Athlete":
        st.caption("A read-through of the support workspace connected to your profile.")
    else:
        st.caption(f"Shared athlete view · {athlete['name']} · {athlete['sport'] or 'sport not set'}")
    with connect() as db:
        open_reviews = db.execute("SELECT COUNT(*) FROM media WHERE athlete_id=? AND shared=1", (athlete["id"],)).fetchone()[0]
        next_items = db.execute("SELECT kind,title,event_date,detail FROM entries WHERE athlete_id=? AND event_date>=? ORDER BY event_date LIMIT 5", (athlete["id"], date.today().isoformat())).fetchall()
        latest_sessions = db.execute("SELECT session_date,activity,duration_min,source FROM sessions WHERE athlete_id=? ORDER BY session_date DESC LIMIT 6", (athlete["id"],)).fetchall()
    a, b = st.columns(2)
    a.metric("Shared movement reviews", open_reviews)
    b.metric("Upcoming dates", len(next_items))
    st.markdown("**Upcoming and shared notes**")
    if next_items:
        for item in next_items:
            st.markdown(f"- **{item['event_date']}** · {item['title']} ({item['kind']})")
    else:
        st.caption("No upcoming dates have been added.")
    st.markdown("**Recent athlete sessions**")
    if latest_sessions:
        st.dataframe(pd.DataFrame([dict(row) for row in latest_sessions]), hide_index=True)
    else:
        st.caption("No training sessions are logged yet.")
    st.info("This workspace uses the athlete's explicit invite link. Health records and AI chat are not exposed here.", icon=":material/lock:")


init_db()
admin_status = ensure_admin_account()
account = current_account()
if not account:
    render_auth(admin_status)
    st.stop()

available_pages = ["Admin"] if account["role"] == "Admin" else [page for page in PAGES if page != "Admin"]
if st.session_state.get("workspace") not in available_pages:
    st.session_state.workspace = available_pages[0]

with st.sidebar:
    st.markdown("# stride")
    st.caption("ATHLETE PERFORMANCE, TOGETHER")
    st.selectbox("Workspace", available_pages, key="workspace", label_visibility="visible")
    st.space("small")
    st.markdown(f"**{account['name']}**")
    st.caption(f"{account['role']} · {account['sport'] or 'sport not set'}")
    if account["team"]:
        st.caption(account["team"])
    if st.button("Sign out", icon=":material/logout:", width="stretch"):
        st.session_state.clear()
        st.rerun()
    st.caption("Workspace stored locally on this computer")

if account["role"] == "Admin":
    athlete = account
    game = None
else:
    athlete = athlete_for(account)
    game = gamification_summary(athlete["id"])
    with st.sidebar:
        st.markdown(f"**Level {game['level']}** · {game['points']} XP")
        st.progress(game["level_progress"], text=f"{game['level_points']} / 250 to next level")
if account["role"] not in {"Athlete", "Admin"} and athlete["id"] == account["id"]:
    st.warning("This support account is not linked to an athlete yet. Join with an athlete invite code when you register, or create one from the athlete's Team page.")

workspace = st.session_state.get("workspace", "Athlete")
if workspace == "Athlete":
    render_dashboard(athlete, game)
elif workspace == "Coach":
    render_coach(account, athlete)
elif workspace == "Logs":
    render_logs(account, athlete)
elif workspace == "Goals":
    render_goals(account, athlete)
elif workspace == "Events":
    render_events(athlete)
elif workspace == "Team":
    render_team(account, athlete)
elif workspace == "Video lab":
    render_video_lab(account, athlete)
elif workspace == "AI companion":
    render_ai(account, athlete)
elif workspace == "Profile":
    render_profile(account)
elif workspace == "Admin" and account["role"] == "Admin":
    render_admin()