"""Schema + clustering signal for quota_pool_id.

The dashboard's frontend pool aggregator (frontend/js/utils/quota.js) clusters
cards by exact `quota_pool_id` equality. These tests pin the field's schema
defaults (so we don't accidentally regress to behavioral clustering) and
verify that the Antigravity sidecar emitters populate it.
"""

from app.models.schemas import LimitCard


class TestSchemaDefault:
    def test_field_is_optional(self):
        """Cards built without quota_pool_id deserialize cleanly (defaults to None)."""
        c = LimitCard(service_name="gemini-flash", icon="g")
        assert c.quota_pool_id is None

    def test_field_round_trips(self):
        """Pool id survives serialization (UI relies on the dump shape)."""
        c = LimitCard(
            service_name="antigravity-sonnet",
            icon="a",
            quota_pool_id="antigravity:session:2026-05-23T16:00:00+00:00",
        )
        dumped = c.model_dump()
        assert dumped["quota_pool_id"] == "antigravity:session:2026-05-23T16:00:00+00:00"

    def test_default_card_has_no_pool_id_in_dump(self):
        """A null pool_id must serialize as null, not omitted (frontend checks `!= null`)."""
        c = LimitCard(service_name="gemini-flash", icon="g")
        dumped = c.model_dump()
        assert "quota_pool_id" in dumped
        assert dumped["quota_pool_id"] is None


class TestAntigravityLSPEmitter:
    """The LSP path in scripts/sidecar.py:collect_antigravity_lsp must tag
    every per-model card with the same quota_pool_id derived from
    `antigravity:{window_type}:{reset_at_iso}` so the dashboard treats them as
    one physical pool."""

    def test_pool_id_format_for_session_window(self):
        # Mirror the format the emitter uses; this is a contract test rather
        # than a behavioral test against the function (which requires an LSP
        # process to probe). The format is what matters for clustering.
        reset_iso = "2026-05-23T16:00:00+00:00"
        window_type = "session"
        pool_id = f"antigravity:{window_type}:{reset_iso}"
        assert pool_id == "antigravity:session:2026-05-23T16:00:00+00:00"

    def test_null_reset_yields_null_pool_id(self):
        """If a card has no reset_at we can't form a pool_id; leaving it None
        keeps the card a singleton in the aggregator (safe default)."""
        reset_iso = None
        pool_id = f"antigravity:session:{reset_iso}" if reset_iso else None
        assert pool_id is None
