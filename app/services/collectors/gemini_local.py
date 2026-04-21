import asyncio
import glob
import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.config import is_local_collector_enabled

logger = logging.getLogger(__name__)


class GeminiLocalMixin:
    """Mixin for Gemini local session log parsing."""

    async def _collect_via_logs(
        self, client: httpx.AsyncClient | None = None
    ) -> list[dict[str, Any]]:
        """Parse Gemini usage from local session JSON files."""
        if not is_local_collector_enabled():
            return []

        potential_dirs = [
            os.path.expanduser("~/.gemini/tmp/ai-usage-tracker/chats"),
            os.path.expanduser("~/.gemini/tmp/gemini/chats"),
            os.path.expanduser("~/.gemini/tmp/sessions"),
            os.path.expanduser("~/.gemini/sessions"),
        ]

        session_files = []
        try:
            existing_dirs = [d for d in potential_dirs if os.path.isdir(d)]
            if existing_dirs:
                results = await asyncio.gather(
                    *[asyncio.to_thread(glob.glob, f"{d}/session-*.json") for d in existing_dirs]
                )
                for found in results:
                    session_files.extend(found)

            if not session_files:
                return []

            def process_sessions(fpaths: list[str]) -> dict[str, int]:
                totals = {
                    "input": 0,
                    "output": 0,
                    "cached": 0,
                    "thoughts": 0,
                    "tool": 0,
                    "total": 0,
                    "session_count": 0,
                }

                for fpath in fpaths:
                    try:
                        with open(fpath) as f:
                            data = json.load(f)

                        messages = data.get("messages", [])
                        if not messages:
                            continue

                        last_tokens = {}
                        for msg in reversed(messages):
                            last_tokens = msg.get("tokens", {})
                            if last_tokens:
                                break

                        if not last_tokens:
                            continue

                        totals["input"] += last_tokens.get("input", 0)
                        totals["output"] += last_tokens.get("output", 0)
                        totals["cached"] += last_tokens.get("cached", 0)
                        totals["thoughts"] += last_tokens.get("thoughts", 0)
                        totals["tool"] += last_tokens.get("tool", 0)
                        totals["total"] += last_tokens.get("total", 0)
                        totals["session_count"] += 1
                    except (json.JSONDecodeError, OSError) as e:
                        logger.debug(f"Failed to parse session file {fpath}: {e}")

                return totals

            totals = await asyncio.to_thread(process_sessions, session_files)

            if totals["total"] == 0:
                return []

            detail_parts = []
            if totals["input"]:
                detail_parts.append(f"in: {totals['input']:,}")
            if totals["output"]:
                detail_parts.append(f"out: {totals['output']:,}")
            if totals["cached"]:
                detail_parts.append(f"cached: {totals['cached']:,}")
            if totals["thoughts"]:
                detail_parts.append(f"thoughts: {totals['thoughts']:,}")

            detail_str = ", ".join(detail_parts) if detail_parts else f"{totals['total']:,} tokens"

            return [
                {
                    "service_name": "Gemini CLI (Session)",
                    "icon": "🔵",
                    "remaining": f"{totals['total']:,}",
                    "unit": "tokens",
                    "reset": "Rolling",
                    "health": "good",
                    "pace": "Stable",
                    "detail": f"{detail_str} | {totals['session_count']} sessions",
                    "used_value": float(totals["total"]),
                    "limit_value": 0.0,
                    "is_unlimited": True,
                    "unit_type": "tokens",
                    "data_source": self.DATA_SOURCE_LOCAL,
                    "usage_url": "https://one.google.com/settings",
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            ]
        except Exception as e:
            logger.debug(f"Gemini local session parsing failed: {e}")
            return []
