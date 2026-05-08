"""Persistent watermark of last-pushed event timestamp per (provider, account)."""

import json
from datetime import datetime
from pathlib import Path


class EventWatermark:
    """Track last-successfully-pushed event timestamp per (provider_id, account_id).

    Stored in a JSON file at `path`. Thread-safe for single-process use (GIL + atomic
    write pattern via write-to-tmp then rename is not needed here; the sidecar is
    single-threaded per cycle).
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._data: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        try:
            text = self.path.read_text()
            self._data = json.loads(text).get("last_pushed_ts", {})
        except (FileNotFoundError, json.JSONDecodeError):
            self._data = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"last_pushed_ts": self._data}))

    def last_pushed(self, provider_id: str, account_id: str) -> datetime | None:
        """Return the last pushed ts for (provider_id, account_id), or None."""
        key = f"{provider_id}|{account_id}"
        v = self._data.get(key)
        if not v:
            return None
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None

    def advance(self, provider_id: str, account_id: str, ts: datetime) -> None:
        """Move the watermark forward to ts (no-op if ts is not later than current)."""
        key = f"{provider_id}|{account_id}"
        cur = self.last_pushed(provider_id, account_id)
        if cur is None or ts > cur:
            self._data[key] = ts.isoformat()
            self._save()
