import asyncio
import glob
import json
import logging
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.core.config import is_local_collector_enabled, settings
from app.core.utils import PaceCalculator, human_delta

logger = logging.getLogger(__name__)


class ChatGPTLocalMixin:
    """Mixin for ChatGPT local session and CLI RPC collection."""

    async def _collect_via_cli_rpc(
        self, client: httpx.AsyncClient | None = None
    ) -> list[dict[str, Any]]:
        """
        Fetch usage data from the codex CLI RPC server.
        """
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                "codex",
                "-s",
                "read-only",
                "-a",
                "untrusted",
                "app-server",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )

            async def call_rpc(method: str, params: dict | None = None) -> dict | None:
                if not process.stdin:
                    return None
                request = {
                    "jsonrpc": "2.0",
                    "id": str(uuid.uuid4()),
                    "method": method,
                    "params": params or {},
                }
                process.stdin.write((json.dumps(request) + "\n").encode())
                await process.stdin.drain()

                line = await process.stdout.readline()
                if not line:
                    return None
                try:
                    response = json.loads(line.decode())
                    return response.get("result")
                except json.JSONDecodeError:
                    return None

            init_res = await call_rpc(
                "initialize", {"clientInfo": {"name": "Runway", "version": "0.9.0"}}
            )
            if not init_res:
                return []

            account_data = await call_rpc("account/read")
            account = account_data.get("account") if account_data else None

            limits_data = await call_rpc("account/rateLimits/read")
            limits = limits_data.get("rateLimits") if limits_data else None

            if not limits:
                return []

            cards = []
            now = datetime.now(UTC)

            tier = "free"
            email = "Unknown"
            if account:
                plan_type = account.get("planType", "").lower()
                if "plus" in plan_type or "pro" in plan_type:
                    tier = "plus"
                elif "team" in plan_type:
                    tier = "team"
                email = account.get("email", "Unknown")

                cards.append(
                    {
                        "service_name": "ChatGPT",
                        "icon": "💬",
                        "remaining": tier.upper(),
                        "unit": "tier",
                        "reset": "Active",
                        "health": "good",
                        "pace": "Active",
                        "detail": f"Account: {email} [CLI RPC]",
                        "data_source": self.DATA_SOURCE_LOCAL,
                        "tier": tier,
                        "updated_at": now.isoformat(),
                    }
                )

            primary = limits.get("primary")
            if primary:
                pct = float(primary.get("usedPercent", 0.0))
                reset_ts = primary.get("resetsAt")
                reset_at = datetime.fromtimestamp(reset_ts, tz=UTC) if reset_ts else None

                cards.append(
                    {
                        "service_name": "ChatGPT",
                        "variant": "Codex",
                        "window_type": "weekly",
                        "icon": "💬",
                        "remaining": f"{(100 - pct):.1f}%",
                        "unit": "remaining",
                        "reset": human_delta(reset_at),
                        "health": "critical" if pct >= 90 else ("warning" if pct >= 80 else "good"),
                        "pace": PaceCalculator.estimate_longevity(pct, reset_at),
                        "detail": f"{pct:.1f}% used [CLI RPC]",
                        "used_value": pct,
                        "limit_value": 100.0,
                        "unit_type": "percent",
                        "reset_at": reset_at.isoformat() if reset_at else None,
                        "data_source": self.DATA_SOURCE_LOCAL,
                        "tier": tier,
                        "usage_url": "https://chatgpt.com/codex/settings/usage/",
                    }
                )

            credits = limits.get("credits")
            if credits:
                balance = credits.get("balance", 0.0)
                cards.append(
                    {
                        "service_name": "ChatGPT",
                        "variant": "Credits",
                        "window_type": "rolling",
                        "icon": "💰",
                        "remaining": f"${balance:.2f}",
                        "unit": "USD",
                        "reset": "Prepaid",
                        "health": "good",
                        "pace": "N/A",
                        "detail": f"Balance: ${balance:.2f} [CLI RPC]",
                        "data_source": self.DATA_SOURCE_LOCAL,
                        "tier": tier,
                        "updated_at": now.isoformat(),
                    }
                )

            return cards

        except Exception as e:
            logger.debug(f"Codex CLI RPC failed: {e}")
            return []
        finally:
            if process:
                try:
                    process.terminate()
                    await process.wait()
                except (ProcessLookupError, OSError):
                    pass

    async def _strategy_local_enrichment(
        self, client: httpx.AsyncClient | None = None
    ) -> list[dict[str, Any]]:
        """Local enrichment: aggregate per-call token usage from Codex session logs."""
        if not is_local_collector_enabled():
            return []
        return await self._collect_codex_session_enrichment()

    async def _collect_codex_session_enrichment(self) -> list[dict[str, Any]]:
        """
        Parse all Codex .jsonl session files and emit an enrichment dict for the
        current weekly window.
        """
        potential_dirs = [
            settings.CHATGPT_SESSIONS_DIR,
            os.path.expanduser("~/.codex/sessions"),
        ]

        session_files: list[str] = []
        seen: set[str] = set()
        for d in potential_dirs:
            if not d or not os.path.isdir(d):
                continue
            try:
                found = await asyncio.to_thread(glob.glob, f"{d}/**/*.jsonl", recursive=True)
                for f in found:
                    if f not in seen:
                        seen.add(f)
                        session_files.append(f)
            except Exception:
                continue

        if not session_files:
            logger.debug("No Codex session .jsonl files found")
            return []

        return await asyncio.to_thread(self._process_codex_sessions, session_files)

    def _process_codex_sessions(self, fpaths: list[str]) -> list[dict[str, Any]]:
        """
        Synchronous worker: parse all jsonl files and aggregate token usage.
        """
        events: list[dict[str, Any]] = []
        current_model = "unknown"

        for fpath in fpaths:
            try:
                with open(fpath, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        record_type = data.get("type")
                        payload = data.get("payload", {})

                        # Track current model from turn_context
                        if record_type == "turn_context" and isinstance(payload, dict):
                            model = payload.get("model")
                            if model:
                                current_model = model
                            continue

                        # Extract token_count events
                        if record_type == "event_msg" and isinstance(payload, dict):
                            if payload.get("type") != "token_count":
                                continue
                            info = payload.get("info")
                            if not info:
                                continue

                            last_usage = info.get("last_token_usage")
                            rate_limits = payload.get("rate_limits") or payload.get("rateLimits")
                            if not last_usage or not rate_limits:
                                continue

                            ts_str = data.get("timestamp")
                            try:
                                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                            except (ValueError, TypeError, AttributeError):
                                ts = datetime.now(UTC)

                            events.append(
                                {
                                    "ts": ts,
                                    "model": current_model,
                                    "input": int(last_usage.get("input_tokens", 0)),
                                    "output": int(last_usage.get("output_tokens", 0)),
                                    "reasoning": int(last_usage.get("reasoning_output_tokens", 0)),
                                    "cache_read": int(last_usage.get("cached_input_tokens", 0)),
                                    "total": int(last_usage.get("total_tokens", 0)),
                                    "rate_limits": rate_limits,
                                }
                            )
            except (OSError, json.JSONDecodeError) as e:
                logger.debug(f"Error reading Codex session file {fpath}: {e}")
                continue

        if not events:
            logger.debug("No token_count events found in Codex session logs")
            return []

        # Sort by timestamp ascending
        events.sort(key=lambda e: e["ts"])

        # Window info from the most recent event
        latest = events[-1]
        primary_limits = latest["rate_limits"].get("primary", {})
        used_percent = float(primary_limits.get("used_percent", 0.0))
        resets_at_ts = primary_limits.get("resets_at")
        window_minutes = int(primary_limits.get("window_minutes", 10080))
        plan_type = str(primary_limits.get("plan_type", "free")).lower()

        tier = "free"
        if "plus" in plan_type or "pro" in plan_type:
            tier = "plus"
        elif "team" in plan_type:
            tier = "team"

        reset_at = datetime.fromtimestamp(resets_at_ts, tz=UTC) if resets_at_ts else None
        cutoff = (
            reset_at - timedelta(minutes=window_minutes)
            if reset_at
            else datetime.now(UTC) - timedelta(minutes=window_minutes)
        )

        # Group events into conversations (boundary = input_tokens decreases)
        # Then compute net-new tokens per conversation to avoid double-counting
        # cumulative context.
        window_events = [e for e in events if e["ts"] >= cutoff]
        if not window_events:
            logger.debug("No Codex session events inside current window")
            return []

        conversations: list[list[dict[str, Any]]] = []
        current_conv: list[dict[str, Any]] = [window_events[0]]
        for e in window_events[1:]:
            if e["input"] < current_conv[-1]["input"]:
                conversations.append(current_conv)
                current_conv = []
            current_conv.append(e)
        conversations.append(current_conv)

        # Aggregate net-new tokens per conversation
        total_in = total_out = total_reason = total_cache = total_tok = 0
        total_billed = 0
        msgs = 0
        by_model: dict[str, dict[str, Any]] = {}

        for conv in conversations:
            if not conv:
                continue
            first = conv[0]
            last = conv[-1]
            conv_model = last["model"] or "unknown"

            # Net new input = growth in context window
            net_input = last["input"] - first["input"]
            # Sum outputs across all calls in conversation
            net_output = sum(e["output"] for e in conv)
            net_reason = sum(e["reasoning"] for e in conv)
            net_cache = sum(e["cache_read"] for e in conv)
            net_total = net_input + net_output
            billed = sum(e["total"] for e in conv)

            total_in += max(0, net_input)
            total_out += net_output
            total_reason += net_reason
            total_cache += net_cache
            total_tok += net_total
            total_billed += billed
            msgs += len(conv)

            entry = by_model.setdefault(
                conv_model, {"cost": 0.0, "msgs": 0, "tokens": {"input": 0, "output": 0}}
            )
            entry["msgs"] += len(conv)
            entry["tokens"]["input"] += max(0, net_input)
            entry["tokens"]["output"] += net_output

        token_usage = {
            "input": total_in,
            "output": total_out,
            "reasoning": total_reason,
            "cache_read": total_cache,
            "total": total_tok,
        }

        # Build compact detail string
        detail_parts: list[str] = []
        if total_tok:
            detail_parts.append(f"net:{self._fmt_tokens(total_tok)}")
        if total_billed:
            detail_parts.append(f"billed:{self._fmt_tokens(total_billed)}")
        if total_reason:
            detail_parts.append(f"reason:{self._fmt_tokens(total_reason)}")
        if total_cache:
            detail_parts.append(f"cache_r:{self._fmt_tokens(total_cache)}")
        token_detail = " ".join(detail_parts)

        model_parts = [
            f"{name}:{self._fmt_tokens(m['tokens']['input'] + m['tokens']['output'])}"
            for name, m in sorted(
                by_model.items(),
                key=lambda x: -(x[1]["tokens"]["input"] + x[1]["tokens"]["output"]),
            )
        ]
        model_detail = " ".join(model_parts)

        enrichment_detail = " | ".join(
            [p for p in [token_detail, model_detail, f"{msgs} msgs"] if p]
        )

        now = datetime.now(UTC)
        remaining_pct = 100.0 - used_percent

        fallback_card = {
            "service_name": "ChatGPT",
            "variant": "Codex",
            "window_type": "weekly",
            "icon": "💬",
            "remaining": f"{remaining_pct:.1f}%",
            "unit": "remaining",
            "reset": human_delta(reset_at),
            "health": "critical"
            if used_percent >= 90
            else ("warning" if used_percent >= 80 else "good"),
            "pace": PaceCalculator.estimate_longevity(used_percent, reset_at),
            "detail": f"{used_percent:.1f}% used [Local Logs]",
            "used_value": used_percent,
            "limit_value": 100.0,
            "unit_type": "percent",
            "reset_at": reset_at.isoformat() if reset_at else None,
            "data_source": self.DATA_SOURCE_LOCAL,
            "tier": tier,
            "usage_url": "https://chatgpt.com/codex/settings/usage/",
            "updated_at": now.isoformat(),
            "token_usage": token_usage,
            "by_model": by_model,
            "msgs": msgs,
            "pct_used": used_percent,
        }

        return [
            {
                "service_name": "ChatGPT",
                "variant": "Codex",
                "window_type": "weekly",
                "_enrichment_detail": enrichment_detail,
                "token_usage": token_usage,
                "msgs": msgs,
                "by_model": by_model,
                "_fallback_card": fallback_card,
            }
        ]

    @staticmethod
    def _fmt_tokens(n: int) -> str:
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 1000:
            return f"{n // 1000}k"
        return str(n)
