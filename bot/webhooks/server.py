"""FastAPI webhook server — receives Todoist webhooks and Google OAuth callbacks."""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request, Response
from sqlalchemy import select

from bot.config import get_settings
from bot.database.connection import get_session, init_db
from bot.database.models import DailyLog, GarminToken, TaskPriority, TaskTag, User
from bot.database.queries import get_user_by_discord_id, get_user_by_todoist_id
from bot.kafka import publish, topics
from bot.services import calendar as cal_service
from bot.services.encryption import encrypt
from bot.services.todoist import parse_priority, parse_tag

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="BetterLifeBot Webhook Server", lifespan=lifespan)


# ── Todoist Webhook ───────────────────────────────────────────────────────────

@app.post("/todoist/webhook")
async def todoist_webhook(
    request: Request,
    x_todoist_hmac_sha256: str = Header(default=""),
) -> Response:
    body = await request.body()
    settings = get_settings()

    # Verify HMAC signature (Todoist sends base64-encoded SHA256)
    digest = hmac.new(
        settings.todoist_webhook_secret.encode(),
        body,
        hashlib.sha256,
    ).digest()
    expected = base64.b64encode(digest).decode()
    if not hmac.compare_digest(expected, x_todoist_hmac_sha256):
        raise HTTPException(status_code=401, detail="Invalid signature")

    import json
    payload = json.loads(body)
    event_name = payload.get("event_name", "")

    if event_name == "item:completed":
        await _handle_item_completed(payload)
    elif event_name == "item:added":
        await _handle_item_added(payload)

    return Response(status_code=200)


async def _handle_item_completed(payload: dict) -> None:
    item = payload.get("event_data", {})
    initiator = payload.get("initiator", {})
    todoist_user_id = str(initiator.get("id", ""))

    async with get_session() as session:
        user = await get_user_by_todoist_id(session, todoist_user_id)
        if not user:
            return

        task_id = str(item.get("id", ""))
        today = date.today()

        existing = await session.execute(
            select(DailyLog).where(
                DailyLog.user_id == user.id,
                DailyLog.todoist_task_id == task_id,
            )
        )
        log = existing.scalar_one_or_none()

        if not log:
            labels = item.get("labels", [])
            tag_str = parse_tag(labels)
            prio_str = parse_priority(item.get("priority", 1))
            log = DailyLog(
                user_id=user.id,
                log_date=today,
                todoist_task_id=task_id,
                task_name=item.get("content", ""),
                tag=TaskTag(tag_str),
                priority=TaskPriority(prio_str),
                is_recurring=bool(item.get("due", {}).get("is_recurring", False)),
            )
            session.add(log)
            await session.flush()

        if not log.completed:
            log.completed = True
            log.completed_at = datetime.now(timezone.utc)
            session.add(log)

            from bot.services.rpg import apply_task_completion
            from bot.services.streak import record_completion
            xp, gp, levelled_up, skilled_up = await apply_task_completion(session, user, log)
            await record_completion(session, user, today)

            logger.info(
                "Task completed via webhook: user=%s task=%s xp=%d gp=%d",
                user.discord_id, log.task_name, xp, gp,
            )


async def _handle_item_added(payload: dict) -> None:
    item = payload.get("event_data", {})
    initiator = payload.get("initiator", {})
    todoist_user_id = str(initiator.get("id", ""))

    due = item.get("due")
    if not due or not due.get("date"):
        return
    due_date_str = due["date"]
    try:
        due_date = date.fromisoformat(due_date_str[:10])
    except ValueError:
        return

    async with get_session() as session:
        user = await get_user_by_todoist_id(session, todoist_user_id)
        if not user:
            return

        labels = item.get("labels", [])
        tag_str = parse_tag(labels)
        prio_str = parse_priority(item.get("priority", 1))

        log = DailyLog(
            user_id=user.id,
            log_date=due_date,
            todoist_task_id=str(item.get("id", "")),
            task_name=item.get("content", ""),
            tag=TaskTag(tag_str),
            priority=TaskPriority(prio_str),
            is_recurring=bool(due.get("is_recurring", False)),
        )
        session.add(log)


# ── Google OAuth Callback ─────────────────────────────────────────────────────

@app.get("/google/callback")
async def google_callback(code: str, state: str) -> dict:
    try:
        tokens = await cal_service.exchange_code(code)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    # state encodes discord_id
    try:
        discord_id = int(state.split(":")[0])
    except (ValueError, IndexError):
        raise HTTPException(status_code=400, detail="Invalid state")

    async with get_session() as session:
        user = await get_user_by_discord_id(session, discord_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        user.google_access_token = encrypt(tokens["access_token"])
        if "refresh_token" in tokens:
            user.google_refresh_token = encrypt(tokens["refresh_token"])
        session.add(user)

    return {"status": "ok", "message": "Google Calendar connecté avec succès !"}



# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio
    from bot.database.connection import init_db
    from bot.kafka.producer import get_producer

    settings = get_settings()
    uvicorn.run(
        "bot.webhooks.server:app",
        host=settings.webhook_host,
        port=settings.webhook_port,
        reload=False,
    )
