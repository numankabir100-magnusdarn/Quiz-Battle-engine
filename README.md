# EEE Brain Battle — Phase 1: Game Engine & Backend

**EEECi FA'26 · Module 06**

A live quiz game-show engine that runs entirely **locally and offline** on one Windows PC sharing a Wi-Fi hotspot. The server holds all state; every client (moderator, admin, buzzers, display) connects via WebSocket and receives real-time updates.

---

## Project Structure

```
quiz battle/
├── server/                 # FastAPI application
│   ├── engine/             # Pure Python game logic (no web code)
│   │   ├── models.py       # Data models: Team, Match, Bracket, Question, etc.
│   │   ├── game_engine.py  # Core engine: rules, scoring, bracket progression
│   │   ├── questions.py    # QuestionProvider interface + sample EEE questions
│   │   └── __init__.py
│   ├── main.py             # FastAPI app, REST endpoints, WebSocket handler
│   ├── config.py           # Config loader (config.json + env vars)
│   ├── persistence.py      # Atomic state save/restore + audit log
│   ├── network.py          # Auto-detect hotspot/LAN IPs
│   ├── timer.py            # Server-side countdown timer
│   ├── ws_manager.py       # WebSocket connection registry + role permissions
│   └── __init__.py
├── web/
│   ├── static/
│   │   ├── theme.css       # Shared dark theme (design tokens + base styles)
│   │   └── debug.js        # Debug page client logic
│   └── debug.html          # Minimal /debug testing page
├── data/                   # Runtime data (auto-created)
│   ├── state.json          # Persisted game state
│   └── audit.log           # Action audit trail
├── tests/                  # pytest suite
│   ├── test_engine.py      # Engine rules: scoring, pass-over, sudden death
│   ├── test_bracket_sim.py # Full 13-match bracket + wild cards
│   ├── test_concurrency.py # First-buzz race (50 trials, 2 threads)
│   ├── test_persistence.py # Atomic save/restore after simulated crash
│   ├── test_permissions.py # Role auth + action permission matrix
│   ├── test_api.py         # REST endpoints + WebSocket integration
│   └── conftest.py         # Shared fixtures
├── config.json             # Server config (PINs, port, paths)
├── requirements.txt        # Python dependencies
├── start_server.bat        # One-click launcher
└── README.md               # This file
```

---

## How to Run

### Prerequisites
- **Python 3.11+** installed on the Windows PC
- All dependencies are standard PyPI packages (no internet needed at runtime)

### 1. Install Dependencies (one-time)
```bash
cd "C:\Users\Numan Kabir\Desktop\quiz battle"
pip install -r requirements.txt
```

### 2. Start the Server
Double-click **`start_server.bat`**, or run from terminal:
```bash
cd "C:\Users\Numan Kabir\Desktop\quiz battle"
"C:\Users\Numan Kabir\AppData\Local\Programs\Python\Python314\python.exe" -m uvicorn server.main:app --host 0.0.0.0 --port 8001
```
> **Dev Note:** For development with automatic code reload, append `--reload`:
> `python -m uvicorn server.main:app --host 0.0.0.0 --port 8001 --reload`

### 3. Open the Debug Page
On the server PC: **http://localhost:8001/debug**

From another device on the hotspot: **http://192.168.137.1:8001/debug**

If another device cannot connect, confirm that it is on the same Wi-Fi network,
that mobile data is off, and that the access point does not enable client/AP
isolation. Run `scripts\setup_firewall.bat` as Administrator to create the
idempotent allow rules; an optional port can be supplied, for example
`scripts\setup_firewall.bat 9001`.

### 4. Network Info
Hit `GET /api/network-info` to auto-detect the server IP and all connection URLs.

---

## How to Run Tests
```bash
cd "C:\Users\Numan Kabir\Desktop\quiz battle"
python -m pytest tests/ -v -p no:cacheprovider
```

---

## REST API

| Endpoint             | Method | Description                              |
|----------------------|--------|------------------------------------------|
| `/api/state`         | GET    | Full current game state                  |
| `/api/devices`       | GET    | Connected WebSocket devices + latency    |
| `/api/health`        | GET    | Server health, uptime, version           |
| `/api/network-info`  | GET    | Auto-detected IPs (hotspot priority)     |
| `/debug`             | GET    | Debug testing page (dark theme)          |
| `/hub`               | GET    | Offline operator Control Hub             |
| `/moderator`         | GET    | PIN-gated live moderator console         |
| `/admin`             | GET    | Admin and projector display controller   |
| `/display`           | GET    | Read-only audience projector             |
| `/buzzer/a`          | GET    | Team A buzzer phone                      |
| `/buzzer/b`          | GET    | Team B buzzer phone                      |

---

## WebSocket Protocol (`/ws`)

### Handshake
```json
{ "type": "hello", "role": "admin", "pin_or_code": "2222" }
```

### Roles & Default Credentials

| Role       | Credential         | Permissions                          |
|------------|--------------------|------------------------------------|
| `display`  | *(no PIN)*         | Read-only state                      |
| `moderator`| PIN `1111`         | Match flow: questions, buzzer, scoring |
| `admin`    | PIN `2222`         | All moderator actions + setup, adjust, reset |
| `hub`      | PIN `3333`         | Read all (monitoring)                |
| `buzzer_a` | Code `BUZZ_A`      | `buzz()` only (mapped to Team A)     |
| `buzzer_b` | Code `BUZZ_B`      | `buzz()` only (mapped to Team B)     |

Open the Control Hub at `/hub` and enter the Hub PIN. The default is `3333`
from `config.json`; the browser receives a short-lived HttpOnly session cookie
before Hub status, QR, backup, and log APIs are available. The Hub can assign
connected buzzer devices, send a test pulse, lock/unlock buzzers, and download
the current `state.json` backup.

### Message Types

| Direction     | Type         | Purpose                              |
|---------------|--------------|--------------------------------------|
| Server → All  | `state`      | Full state broadcast after every change |
| Server → All  | `event`      | Named events (`buzz_first`, `timer_tick`, etc.) |
| Client → Srv  | `action`     | Execute engine action                |
| Server → Client | `action_ack` | Action success confirmation        |
| Server → Client | `error`    | Rejected action or validation error  |
| Client → Srv  | `ping`       | Heartbeat + latency measurement      |
| Server → Client | `pong`     | Heartbeat response with server time  |

---

## Game Actions

| Action                | Roles             | Payload                                  |
|-----------------------|-------------------|------------------------------------------|
| `setup_match`         | admin             | `{stage, match_number, team_a_id, team_b_id}` |
| `start_rapid_fire`    | moderator, admin  | `{team_id, duration_seconds}`            |
| `start_buzzer_battle` | moderator, admin  | `{}`                                     |
| `open_question`       | moderator, admin  | `{}`                                     |
| `mark_correct`        | moderator, admin  | `{team_id?}`                             |
| `mark_wrong`          | moderator, admin  | `{team_id?}`                             |
| `buzz`                | buzzer_a, buzzer_b| `{team?}` (auto-resolved from role)      |
| `confirm_first_buzz`  | moderator, admin  | `{}`                                     |
| `lock_buzzers`        | moderator, admin  | `{}`                                     |
| `unlock_buzzers`      | moderator, admin  | `{}`                                     |
| `reveal_answer`       | moderator, admin  | `{}`                                     |
| `next_question`       | moderator, admin  | `{}`                                     |
| `start_sudden_death`  | moderator, admin  | `{}`                                     |
| `end_match`           | moderator, admin  | `{}`                                     |
| `admin_adjust_score`  | admin             | `{team_id, delta, reason}`               |
| `reset_match`         | admin             | `{}`                                     |
| `override_quarterfinal_pairings` | admin  | `{pairings: [{match_number, team_a_id, team_b_id}, ...]}` |
| `start_timer`         | moderator, admin  | `{seconds}`                              |
| `pause_timer`         | moderator, admin  | `{}`                                     |
| `resume_timer`        | moderator, admin  | `{}`                                     |
| `reset_timer`         | moderator, admin  | `{seconds}`                              |

---

## Rules Enforced

### Question Tracking & Exhaustion Warning
- Questions are tracked event-wide and never repeated.
- If the question bank has 2 or fewer questions remaining, a warning (`question_bank_warning`) is sent to the moderator.
- If all questions are exhausted, an error is raised instead of wrapping around.

### Rapid Fire
- 120 seconds per team, +10 per correct, 0 for wrong (no negative marking)
- One designated speaker only; buzzers locked

### Buzzer Battle
- +15 correct, −5 wrong
- Wrong answer → passes to OTHER team only (no reread)
- If both teams fail → question closes
- First buzz locks buzzers for everyone else; moderator confirms (decision final)

### Sudden Death
- Triggered automatically on tied match end
- Buzzer questions; first correct answer wins immediately

### Bracket
- 12 teams → 6 qualifier matches → 6 winners + 2 highest-scoring losers (wild cards) → 8
- 4 quarterfinals → 2 semifinals → 1 final
- Wild-card tie resolved by sudden-death question

---

## Assumptions
- **Seeding for quarterfinals**: Default seeding is W1 vs WC2, W2 vs W5, W3 vs WC1, W4 vs W6 (standard bracket assumption pending organizer confirmation). Admins can override quarterfinal pairings at any time via the `override_quarterfinal_pairings` action.
- **Sudden death** in a tied match uses buzzer-style questions with the same scoring (+15)
- **Timer**: Timer starts explicitly after `start_rapid_fire` (auto-starts with the round); on server state restore, timer is always restored as paused.
- **Buzzer role mapping**: `buzzer_a` always maps to `team_a_id`, `buzzer_b` always maps to `team_b_id` of the current match
- **State persistence**: the full state including action log and used questions is saved; on restore the log is kept intact and the timer is always restored paused.

---

## Out of Scope (Phase 1)
Projector display, moderator panel, admin panel, buzzer page, Control Hub, QR codes, question import, animations.

---

*Built for EEECi FA'26, Module 06 — "EEE Brain Battle"*
