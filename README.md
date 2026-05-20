# BetterLifeBot v2.1

Discord bot for habit tracking, wellbeing, productivity and personal development — with a full RPG progression system.

> Open-source · Event-Driven (Kafka) · Todoist · Garmin · Google Calendar

---

## Features

| Module | Description |
|---|---|
| **Habit Tracker** (§2.1) | Morning task display with one-click ✅/❌ buttons, streak system |
| **Wellbeing** (§2.2) | Private gratitude journal, willpower challenges (30 min, levels 1–15) |
| **Productivity** (§2.3) | Todoist integration, shared to-do, recurring habit tasks |
| **Sport** (§2.4) | Run scheduling via Google Calendar free slots + OpenWeather optimal windows |
| **RPG System** (§2.5) | XP/GP per Todoist task (tag + priority), levels 1–50, 6 specialised skills |
| **Garmin Sleep** (§2.6) | Auto-sync sleep data (OAuth 2.0), RPG modifiers, weekly reports |
| **Penalty System** (§2.7) | Nightly audit (23h55), weighted completion, recidivism escalation, recovery challenges |

---

## Quick Start

### 1. Clone & configure

```bash
cp .env.example .env
# Edit .env with your tokens
```

### 2. Generate encryption key

```bash
python -c "import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"
# Paste into ENCRYPTION_KEY in .env
```

### 3. Run with Docker Compose

```bash
docker compose up --build
```

### 4. Create your Discord Bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create application → Bot → copy token → paste into `DISCORD_TOKEN`
3. Enable **Message Content Intent** and **Server Members Intent**
4. Invite bot with `applications.commands` + `bot` scopes

---

## Discord Commands

### Habit & Profile
| Command | Description |
|---|---|
| `/register [timezone]` | Create your BetterLifeBot profile |
| `/habitudes` | Show today's habits |
| `/streak` | Show your current streaks |

### RPG
| Command | Description |
|---|---|
| `/profil [@user]` | RPG embed: level, XP, GP, skills, active bonuses |
| `/leaderboard [xp\|gp\|streak]` | Global rankings |
| `/shop` | Buy boosts with accumulated GP |
| `/historique [n]` | Last n completed tasks with XP/GP |
| `/bonus-actifs` | List active passive bonuses |

### Wellbeing
| Command | Description |
|---|---|
| `/gratitude <note>` | Log a private daily gratitude note |
| `/defi-volonte <description>` | Start a 30-min willpower challenge |
| `/gratitude-historique [n]` | View last n gratitude entries |

### Productivity (Todoist)
| Command | Description |
|---|---|
| `/sync-todoist` | Sync today's Todoist tasks |
| `/taches` | List today's tasks |
| `/historique [n]` | Completed tasks with XP/GP earned |

### Sport
| Command | Description |
|---|---|
| `/planifier-course <lat> <lon>` | Find optimal running windows |
| `/google-connect` | Link your Google Calendar |

### Garmin Sleep
| Command | Description |
|---|---|
| `/garmin-connect` | Link your Garmin watch (OAuth 2.0) |
| `/garmin-status` | Check connection & last sync |
| `/garmin-disconnect` | Revoke access & delete data |
| `/sommeil-aujourd-hui` | Last night's summary + RPG modifier |
| `/sommeil-semaine` | Weekly sleep report |
| `/sommeil-objectif [h]` | Set sleep duration goal (default: 8h) |
| `/batterie` | Current Body Battery level |

### Penalty System
| Command | Description |
|---|---|
| `/malus-aujourd-hui` | Today's penalty summary |
| `/malus-historique [n]` | Last n days with completion rate |
| `/grace` | Activate monthly grace day (no penalty) |
| `/vacances [jours]` | Vacation mode (suspend penalties, max 14d, 1×/quarter) |
| `/recidive` | Recidivism counter & multiplier |
| `/rattrapage` | Launch recovery challenge (recidivism ≥ 5) |

---

## RPG System

### XP & GP Formula

```
XP final = XP_Base(tag) × Multiplicateur(priorité)
GP final = GP_Base(tag) × Multiplicateur(priorité)
```

| Priority | Multiplier |
|---|---|
| P1 (Urgent) | ×3.0 |
| P2 (High) | ×2.0 |
| P3 (Normal) | ×1.5 |
| P4 (Basic) | ×1.0 |

### Level progression

`XP_required(n) = 100 × n^1.8` — levels 1 to 50

### Sleep RPG modifiers

| Sleep Score | XP Effect |
|---|---|
| 90–100 | ×1.3 XP + GP +15% |
| 75–89 | ×1.1 XP |
| 60–74 | Baseline |
| 40–59 | ×0.9 XP |
| < 40 | ×0.8 XP + penalties −50% |

---

## Architecture

```
Discord Bot (discord.py)
    ├── Cogs: habits, wellbeing, productivity, sport, rpg, garmin, penalties
    ├── APScheduler: Garmin sync 06h00 / Penalty audit 23h55
    └── Kafka consumer (background)

FastAPI Webhook Server
    ├── POST /todoist/webhook  (HMAC-verified)
    ├── GET  /google/callback  (OAuth exchange)
    └── GET  /garmin/callback  (OAuth exchange)

PostgreSQL (SQLAlchemy async)
Kafka (aiokafka, 8 topics)
```

### Kafka Topics

| Topic | Purpose |
|---|---|
| `betterlife.habits.events` | Habit completions |
| `betterlife.wellbeing.events` | Wellbeing / challenges |
| `betterlife.productivity.events` | Todoist task events |
| `betterlife.sport.events` | Run planning |
| `betterlife.rpg.events` | XP/GP/level/skill events |
| `betterlife.garmin.events` | Sleep / Body Battery |
| `betterlife.penalties.events` | Audit results & penalties |
| `betterlife.data.raw` | Aggregated data pipeline |

---

## Security

- Garmin OAuth tokens encrypted **AES-256-GCM** — never in logs
- Todoist webhooks verified with **HMAC-SHA256**
- Sleep & penalty data strictly private by default
- `#discipline` channel mentions are **opt-in** (disabled by default)

---

## Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run migrations
alembic upgrade head

# Run bot locally (requires .env)
python -m bot.main

# Run webhook server
python -m bot.webhooks.server
```
