"""PII redaction in the global exception handler (audit R10).

Account IDs in this codebase are email addresses (see
account_identity.resolve_account_id). Any uncaught exception whose
traceback formats a value involving an account_id thus emits an email
to whatever sink the log handlers go to. The audit's R10 calls for the
formatted exception text to be redacted before logging.
"""

from __future__ import annotations

from app.core.log_redaction import scrub_pii


def test_scrubs_a_plain_email_address():
    assert scrub_pii("user@example.com hit a 500") == "[REDACTED_EMAIL] hit a 500"


def test_scrubs_multiple_emails_in_one_string():
    text = "alice@example.com and bob+work@sub.example.co.uk"
    out = scrub_pii(text)
    assert "alice@example.com" not in out
    assert "bob+work@sub.example.co.uk" not in out
    assert out.count("[REDACTED_EMAIL]") == 2


def test_passes_unrelated_strings_through_unchanged():
    text = "no PII here, just a stack frame"
    assert scrub_pii(text) == text


def test_handles_non_string_input_gracefully():
    # The exception handler may pass through non-string values (None,
    # ints, etc) when stringifying loggers. Helper must not crash.
    assert scrub_pii(None) is None
    assert scrub_pii(42) == 42
