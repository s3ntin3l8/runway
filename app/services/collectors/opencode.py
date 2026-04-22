"""
OpenCode quota collector with web API (Chrome cookies) as primary source.

Collection Strategy:
1. OpenCode Web API (PRIMARY)
   - Uses Chrome cookies to authenticate with opencode.ai
   - Calls https://opencode.ai/_server endpoint
   - Returns aggregated usage from ALL devices (web IDE, TUI, etc.)
   - Shows rolling 5-hour and weekly windows

2. Sidecar Aggregation (FALLBACK)
   - Aggregates local DB data from multiple hosts via external metrics
   - Used when web API fails (no Chrome login, cookie decryption fails)
   - Each host runs sidecar script to push local data

Local DB Collection:
- Controlled by LOCAL_COLLECTOR_ENABLED env var
- Only used as additional data source, not primary
"""

import asyncio
import logging
import os
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.core.browser_cookies import get_opencode_session_cookie
from app.core.config import is_local_collector_enabled, settings
from app.core.utils import PaceCalculator, error_card, http_request_with_retry
from app.services.collectors.base import BaseCollector
from app.services.external_metrics import external_metric_service

logger = logging.getLogger(__name__)


class OpenCodeCollector(BaseCollector):
    PROVIDER_ID = "opencode"
    DEFAULT_WINDOW_TYPE = "weekly"

    STRATEGIES: dict[str, tuple[str, str] | tuple[str, str, dict]] = {
        "web": ("Web API (Browser Cookie)", "_get_opencode_web"),
        "sidecar": ("Sidecar Aggregation (Multi-Host)", "_strategy_sidecar_aggregation"),
        "local": ("Local Database", "_strategy_local_db_fallback", {"enrich": True}),
    }

    def __init__(self, account_id: str | None = None, account_label: str | None = None):
        super().__init__(account_id=account_id, account_label=account_label)

    async def is_configured(self) -> bool:
        """Check if OpenCode session cookie or local DB is present."""
        # Check for session cookie
        session_cookie = await asyncio.to_thread(get_opencode_session_cookie)
        if session_cookie:
            return True

        # Check for local DB if enabled
        if is_local_collector_enabled():
            potential_paths = [
                settings.OPENCODE_DB_PATH,
                os.path.expanduser("~/.local/share/opencode/opencode.db"),
                os.path.expanduser("~/.opencode/opencode.db"),
            ]
            if any(os.path.exists(p) for p in potential_paths):
                return True

        return False

    def _fallback_strategies(self) -> list[Any]:
        """Return the fallback strategies for OpenCode (Sidecar, Local DB)."""
        return [
            self._strategy_sidecar_aggregation,
            self._strategy_local_db_fallback,
        ]

    async def _primary_strategy(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        """OpenCode Web API strategy."""
        return await self._get_opencode_web(client)

    async def _error_handler(self) -> list[dict[str, Any]]:
        """Return empty list on failure (OpenCode is non-critical)."""
        return []

    async def _strategy_sidecar_aggregation(
        self, client: httpx.AsyncClient
    ) -> list[dict[str, Any]]:
        """Second tier: Sidecar aggregation of multi-host data."""
        return await external_metric_service.get_opencode_aggregated()

    async def _strategy_local_db_fallback(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        """Third tier: Local database collection (if enabled)."""
        if is_local_collector_enabled():
            return await self._get_opencode_tui()
        return []

    async def _get_opencode_web(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        """
        Fetch OpenCode usage from web API using Chrome cookies.

        This queries the opencode.ai servers and returns aggregated usage
        from ALL devices where the user is logged in (web IDE, TUI, etc.).

        Process:
        1. Extract session cookie from Chrome
        2. Call workspaces endpoint to get workspace ID
        3. Call subscription endpoint to get usage data
        4. Parse JavaScript response with regex

        Returns:
            List[Dict[str, Any]]: Cards for 5h and weekly windows, or empty list on failure
        """
        # Check for session cookie (local Chrome or sidecar cache)
        session_cookie = await asyncio.to_thread(get_opencode_session_cookie)

        if not session_cookie:
            return []

        try:
            headers = {
                "Cookie": f"auth={session_cookie}",
                "Content-Type": "application/json",
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
                "Referer": "https://opencode.ai/",
                "Origin": "https://opencode.ai",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
            }

            # 1. Get workspace ID
            workspace_id = await self._get_workspace_id(client, headers)
            if not workspace_id:
                return []

            # 2. Get subscription data
            usage_data = await self._get_subscription_data(client, headers, workspace_id)
            if not usage_data:
                return []

            # 3. Parse and return cards
            return self._parse_usage_data(usage_data, workspace_id)

        except Exception:
            return []

    async def _get_workspace_id(
        self, client: httpx.AsyncClient, headers: dict[str, str]
    ) -> str | None:
        """Get the first workspace ID from opencode.ai."""
        try:
            # Check for env override first
            env_workspace = os.getenv("OPENCODE_WORKSPACE_ID")
            if env_workspace:
                # Handle full URL format
                if "workspace/" in env_workspace:
                    return env_workspace.split("workspace/")[-1].split("/")[0]
                return env_workspace

            import uuid

            ws_headers = headers.copy()
            func_id = "def39973159c7f0483d8793a822b8dbb10d067e12c65455fcb4608459ba0234f"
            ws_headers.update(
                {
                    "X-Server-Id": func_id,
                    "X-Server-Instance": f"server-fn:{uuid.uuid4()}",
                    "Accept": "text/javascript, application/json;q=0.9, */*;q=0.8",
                }
            )

            # Try primary GET approach
            url = f"https://opencode.ai/_server?id={func_id}"
            resp = await http_request_with_retry(
                client, "GET", url, headers=ws_headers, timeout=10.0, follow_redirects=True
            )

            # Fallback to POST with empty body if GET fails
            if resp.status_code != 200:
                resp = await http_request_with_retry(
                    client,
                    "POST",
                    "https://opencode.ai/_server",
                    headers=ws_headers,
                    json=[],
                    timeout=10.0,
                    follow_redirects=True,
                )

            if resp.status_code != 200:
                return None

            # Parse JavaScript response
            text = resp.text

            # Try to capture email here too
            email_match = re.search(r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", text)
            if email_match:
                self.account_label = email_match.group(1)

            # Look for workspace ID pattern: id:"wrk_..."
            match = re.search(r'id:"(wrk_[a-zA-Z0-9]+)"', text)
            if match:
                return match.group(1)

            return None
        except Exception:
            return None

    async def _get_subscription_data(
        self, client: httpx.AsyncClient, headers: dict[str, str], workspace_id: str
    ) -> str | None:
        """Get subscription/usage data from the workspace page (GET)."""
        try:
            url = f"https://opencode.ai/workspace/{workspace_id}/go"
            # Switch to HTML accept header for the page fetch
            usage_headers = headers.copy()
            usage_headers["Accept"] = (
                "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
            )

            resp = await http_request_with_retry(
                client, "GET", url, headers=usage_headers, timeout=15.0, follow_redirects=True
            )

            if resp.status_code != 200:
                return None

            return resp.text
        except Exception:
            return None

    def _parse_usage_data(self, text: str, workspace_id: str) -> list[dict[str, Any]]:
        """
        Parse JavaScript/React stream response to extract usage data.
        """
        # logger.info(f"OpenCode parsing usage data (text length: {len(text)})")

        cards = []
        now = datetime.now(UTC)
        now_iso = now.isoformat()
        usage_url = f"https://opencode.ai/workspace/{workspace_id}/go"

        # Discover email for account_label
        email = ""
        email_match = re.search(r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", text)
        if email_match:
            email = email_match.group(1)
            self.account_label = email

        identity_suffix = f" | {email}" if email else ""

        # Definition of windows to search for
        windows = [
            ("rollingUsage", "OpenCode (5h)", 12.0, "Rolling 5h"),
            ("weeklyUsage", "OpenCode (7d)", 30.0, "Rolling 7d"),
            ("monthlyUsage", "OpenCode (30d)", 60.0, "Monthly"),
        ]

        for key, service_name, limit, reset_label in windows:
            # Even more flexible regex
            # key:($R[xx]=)?{...}
            pattern = rf"{key}:(?:\$R\[\d+\]=)?\{{([^}}]+)\}}"
            match = re.search(pattern, text)

            if not match:
                logger.info(f"OpenCode: Could not find object for {key}")
                continue

            obj_content = match.group(1)
            # logger.info(f"OpenCode: Found {key} object content: {obj_content}")

            # Extract fields from the object content
            pct_match = re.search(r"usagePercent:([\d.]+)", obj_content)
            reset_match = re.search(r"resetInSec:(\d+)", obj_content)

            if not pct_match or not reset_match:
                logger.info(f"OpenCode: Missing fields in {key} object")
                continue

            pct = float(pct_match.group(1))
            reset_sec = int(reset_match.group(1))
            # logger.info(f"OpenCode: Parsed {key}: {pct}% used, reset in {reset_sec}s")

            used = (pct / 100) * limit
            remaining = max(0, limit - used)
            reset_at = now + timedelta(seconds=reset_sec)

            cards.append(
                {
                    "service_name": service_name,
                    "icon": "⚡",
                    "remaining": f"${remaining:.2f}",
                    "unit": f"${limit:.0f} limit",
                    "reset": reset_label,
                    "health": "good" if pct < 70 else "warning" if pct < 90 else "critical",
                    "pace": PaceCalculator.estimate_longevity(pct, reset_at),
                    "detail": f"${used:.2f} used ({pct:.1f}%) · Web API{identity_suffix}",
                    "used_value": used,
                    "limit_value": limit,
                    "is_unlimited": False,
                    "unit_type": "currency",
                    "currency": "USD",
                    "account_label": email,
                    "reset_at": reset_at.isoformat(),
                    "data_source": self.DATA_SOURCE_WEB,
                    "input_source": "server",
                    "usage_url": usage_url,
                    "updated_at": now_iso,
                }
            )

        # logger.info(f"OpenCode: _parse_usage_data returning {len(cards)} cards")
        return cards

    async def _get_opencode_tui(self) -> list[dict[str, Any]]:
        """
        Query local DB and emit one enrichment dict per window.

        Returns enrichment-shaped dicts (not real cards) carrying
        `_enrichment_detail`, `totals`, and `_fallback_card`. The custom
        `_enrich_results` merges them into the web-API primary cards; when
        there is no primary, `_fallback_card` is promoted so local-only
        hosts still render a card.
        """
        potential_paths = [
            settings.OPENCODE_DB_PATH,
            os.path.expanduser("~/.local/share/opencode/opencode.db"),
            os.path.expanduser("~/.opencode/opencode.db"),
        ]

        db = None
        for p in potential_paths:
            if os.path.exists(p):
                db = p
                logger.debug(f"Found OpenCode database at: {p}")
                break

        if not db:
            logger.debug("No OpenCode database found in any of the potential paths.")
            return []

        try:
            import aiosqlite

            now = datetime.now(UTC)

            if not self.account_label or self.account_label.lower() == "default":
                try:
                    proc = await asyncio.create_subprocess_exec(
                        "git",
                        "config",
                        "--global",
                        "user.email",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    stdout, _ = await proc.communicate()
                    if proc.returncode == 0:
                        git_email = stdout.decode().strip()
                        if git_email:
                            self.account_label = git_email
                except Exception:
                    pass

            identity_suffix = f" | {self.account_label}" if self.account_label else ""

            windows = [
                (
                    "5h",
                    int((now - timedelta(hours=5)).timestamp() * 1000),
                    "OpenCode (5h)",
                    12.0,
                    "5h",
                ),
                (
                    "week",
                    int((now - timedelta(days=7)).timestamp() * 1000),
                    "OpenCode (7d)",
                    30.0,
                    "7d",
                ),
                (
                    "month",
                    int((now - timedelta(days=30)).timestamp() * 1000),
                    "OpenCode (30d)",
                    60.0,
                    "30d",
                ),
            ]

            results = []
            async with aiosqlite.connect(db) as conn:
                for _window_key, cutoff_ms, service_name, limit, label in windows:
                    cursor = await conn.execute(
                        """
                        SELECT
                            json_extract(data, '$.cost')             AS cost,
                            json_extract(data, '$.tokens.input')     AS t_in,
                            json_extract(data, '$.tokens.output')    AS t_out,
                            json_extract(data, '$.tokens.reasoning') AS t_reason,
                            json_extract(data, '$.tokens.cache.read')  AS cache_r,
                            json_extract(data, '$.tokens.cache.write') AS cache_w,
                            json_extract(data, '$.modelID')          AS model_id,
                            json_extract(data, '$.parentID')         AS parent_id
                        FROM message
                        WHERE time_created > ?
                          AND json_valid(data)
                          AND json_extract(data, '$.role') = 'assistant'
                        """,
                        (cutoff_ms,),
                    )
                    rows = await cursor.fetchall()

                    total_cost = 0.0
                    total_in = total_out = total_reason = cache_r = cache_w = 0
                    by_model: dict[str, dict] = {}
                    convos: set[str] = set()

                    for cost, t_in, t_out, t_reason, cr, cw, model_id, parent_id in rows:
                        total_cost += float(cost or 0)
                        total_in += int(t_in or 0)
                        total_out += int(t_out or 0)
                        total_reason += int(t_reason or 0)
                        cache_r += int(cr or 0)
                        cache_w += int(cw or 0)
                        if parent_id:
                            convos.add(parent_id)
                        if model_id:
                            short = self._short_model_id_oc(model_id)
                            entry = by_model.setdefault(short, {"cost": 0.0, "msgs": 0})
                            entry["cost"] += float(cost or 0)
                            entry["msgs"] += 1

                    msgs = len(rows)
                    remaining = max(0.0, limit - total_cost)
                    pct = (total_cost / limit * 100) if limit > 0 else 0.0

                    totals = {
                        "cost": total_cost,
                        "msgs": msgs,
                        "convos": len(convos),
                        "tokens": {
                            "input": total_in,
                            "output": total_out,
                            "reasoning": total_reason,
                            "cache_read": cache_r,
                            "cache_write": cache_w,
                        },
                        "by_model": by_model,
                    }

                    enrichment_detail = self._build_oc_enrichment_detail(totals)

                    fallback_card = {
                        "service_name": service_name,
                        "icon": "⚡",
                        "remaining": f"${remaining:.2f}",
                        "unit": f"${limit:.0f} limit",
                        "reset": f"Rolling {label}",
                        "health": "good" if pct < 70 else "warning" if pct < 90 else "critical",
                        "pace": "Stable" if pct < 50 else "High" if pct < 80 else "Fatigue",
                        "detail": f"${total_cost:.2f} used · {msgs} msgs · Local DB{identity_suffix}",
                        "used_value": total_cost,
                        "limit_value": limit,
                        "is_unlimited": False,
                        "unit_type": "currency",
                        "currency": "USD",
                        "account_label": self.account_label,
                        "reset_at": None,
                        "data_source": self.DATA_SOURCE_LOCAL,
                        "input_source": "server",
                        "updated_at": datetime.now(UTC).isoformat(),
                    }

                    results.append(
                        {
                            "service_name": service_name,
                            "_enrichment_detail": enrichment_detail,
                            "totals": totals,
                            "_fallback_card": fallback_card,
                        }
                    )

            return results

        except Exception as e:
            return [
                error_card(
                    "OpenCode TUI",
                    "⚡",
                    f"DB Error: {str(e)[:15]}",
                    error_type="api_error",
                )
            ]

    def _short_model_id_oc(self, model_id: str) -> str:
        """Shorten a model ID for display, e.g. claude-sonnet-4-6 → sonnet."""
        m = model_id.lower()
        # Strip claude- prefix then any trailing -version suffix
        m = re.sub(r"^claude-", "", m)
        m = re.sub(r"-\d+[-.]?\d*$", "", m)
        # Trim -free / -latest suffixes
        m = re.sub(r"-(free|latest|preview)$", "", m)
        return m or model_id

    def _build_oc_enrichment_detail(self, totals: dict) -> str:
        """Build the enrichment detail string from per-window totals."""
        parts: list[str] = []

        cost = totals.get("cost", 0.0)
        parts.append(f"${cost:.2f}")

        tok = totals.get("tokens", {})
        token_segs: list[str] = []
        if tok.get("input"):
            token_segs.append(f"in:{tok['input']:,}")
        if tok.get("output"):
            token_segs.append(f"out:{tok['output']:,}")
        if tok.get("cache_read"):
            token_segs.append(f"cache_r:{tok['cache_read']:,}")
        if tok.get("cache_write"):
            token_segs.append(f"cache_w:{tok['cache_write']:,}")
        if token_segs:
            parts.append(" ".join(token_segs))

        by_model = totals.get("by_model", {})
        if by_model:
            top = sorted(by_model.items(), key=lambda x: x[1]["cost"], reverse=True)[:3]
            model_segs = [f"{name}:${info['cost']:.2f}" for name, info in top]
            parts.append(" ".join(model_segs))

        convos = totals.get("convos", 0)
        if convos:
            parts.append(f"{convos} convos")

        return " | ".join(parts)

    def _enrich_results(
        self,
        primary: list[dict[str, Any]] | None,
        enrichment: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not enrichment or self._is_error_result(enrichment):
            return primary or []

        # Local-only host: promote fallback cards so the account still renders.
        if not primary or self._is_error_result(primary):
            promoted = [e["_fallback_card"] for e in enrichment if e.get("_fallback_card")]
            return promoted or (primary or [])

        by_name = {e.get("service_name"): e for e in enrichment if e.get("_enrichment_detail")}
        for card in primary:
            match = by_name.get(card.get("service_name"))
            if not match:
                continue
            suffix = match["_enrichment_detail"]
            if suffix:
                card["detail"] = f"{card.get('detail', '').rstrip()} | {suffix}".strip(" |")
        return primary
