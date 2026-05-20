"""Todoist REST API v2 client."""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

TODOIST_API = "https://api.todoist.com/rest/v2"
TODOIST_SYNC = "https://api.todoist.com/sync/v9"


class TodoistClient:
    def __init__(self, access_token: str) -> None:
        self._token = access_token
        self._headers = {"Authorization": f"Bearer {access_token}"}

    async def get_tasks_due_today(self) -> list[dict[str, Any]]:
        """Return all tasks due today (any project)."""
        today = date.today().isoformat()
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"{TODOIST_API}/tasks",
                headers=self._headers,
                params={"filter": f"due:{today}"},
            ) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def get_task(self, task_id: str) -> dict[str, Any]:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"{TODOIST_API}/tasks/{task_id}",
                headers=self._headers,
            ) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def close_task(self, task_id: str) -> None:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                f"{TODOIST_API}/tasks/{task_id}/close",
                headers=self._headers,
            ) as resp:
                resp.raise_for_status()

    async def get_projects(self) -> list[dict[str, Any]]:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"{TODOIST_API}/projects",
                headers=self._headers,
            ) as resp:
                resp.raise_for_status()
                return await resp.json()


def parse_priority(todoist_priority: int) -> str:
    """Todoist priority is 1(normal) – 4(urgent); we invert to P1–P4."""
    mapping = {4: "P1", 3: "P2", 2: "P3", 1: "P4"}
    return mapping.get(todoist_priority, "P4")


def parse_tag(labels: list[str]) -> str:
    """Map first recognised Todoist label to our internal TaskTag."""
    tag_map = {
        "work": "work", "pro": "work",
        "learning": "learning", "dev": "learning",
        "health": "health", "sport": "health",
        "creative": "creative",
        "admin": "admin", "finance": "admin",
        "social": "social",
        "habit": "habit",
    }
    for label in labels:
        key = label.lower()
        if key in tag_map:
            return tag_map[key]
    return "none"
