"""Tests for common.logging.pii PII wrapping and redaction."""

from __future__ import annotations

import pytest

from common.logging.pii import PII, REDACTION_PATTERNS, SAFE_FIELDS, redact_string


class TestPIIWrapper:
    """Tests for the PII class."""

    def test_str_returns_redacted(self):
        pii = PII("john@acme.com")
        assert str(pii) == "[PII]"

    def test_repr_returns_redacted(self):
        pii = PII("secret-data")
        assert repr(pii) == "[PII]"

    def test_raw_property_exposes_value(self):
        pii = PII("sensitive-value")
        assert pii.raw == "sensitive-value"

    def test_hash_deterministic(self):
        """Same value and key produce the same hash."""
        pii = PII("test@example.com")
        h1 = pii.hash("my-key")
        h2 = pii.hash("my-key")
        assert h1 == h2

    def test_hash_different_keys_produce_different_hashes(self):
        """Different HMAC keys produce different hashes."""
        pii = PII("test@example.com")
        h1 = pii.hash("key-a")
        h2 = pii.hash("key-b")
        assert h1 != h2

    def test_hash_format(self):
        """Hash output follows [redacted:XXXXXXXX] format."""
        pii = PII("hello")
        result = pii.hash("test-key")
        assert result.startswith("[redacted:")
        assert result.endswith("]")
        # 8 hex chars between colon and bracket
        hex_part = result[len("[redacted:"):-1]
        assert len(hex_part) == 8
        assert all(c in "0123456789abcdef" for c in hex_part)

    def test_hash_different_values_produce_different_hashes(self):
        """Different PII values produce different hashes with same key."""
        pii1 = PII("alice@example.com")
        pii2 = PII("bob@example.com")
        assert pii1.hash("same-key") != pii2.hash("same-key")

    def test_slots_defined(self):
        """PII uses __slots__ for memory efficiency."""
        pii = PII("val")
        assert hasattr(PII, "__slots__")
        with pytest.raises(AttributeError):
            pii.new_attr = "fail"  # type: ignore[attr-defined]


class TestRedactString:
    """Tests for regex-based redaction of free-text strings."""

    def test_redacts_email(self):
        text = "Contact john.doe@example.com for details"
        result = redact_string(text)
        assert "[EMAIL]" in result
        assert "john.doe@example.com" not in result

    def test_redacts_multiple_emails(self):
        text = "Emails: a@b.com and c@d.org"
        result = redact_string(text)
        assert result.count("[EMAIL]") == 2

    def test_redacts_ssn(self):
        text = "SSN is 123-45-6789"
        result = redact_string(text)
        assert "[SSN]" in result
        assert "123-45-6789" not in result

    def test_redacts_credit_card_with_spaces(self):
        text = "Card: 4111 1111 1111 1111"
        result = redact_string(text)
        assert "[CARD]" in result
        assert "4111 1111 1111 1111" not in result

    def test_redacts_credit_card_with_dashes(self):
        text = "Card: 4111-1111-1111-1111"
        result = redact_string(text)
        assert "[CARD]" in result
        assert "4111-1111-1111-1111" not in result

    def test_redacts_phone_us_format(self):
        text = "Call (555) 123-4567"
        result = redact_string(text)
        assert "[PHONE]" in result
        assert "(555) 123-4567" not in result

    def test_redacts_phone_with_country_code(self):
        text = "Call +1 555-123-4567"
        result = redact_string(text)
        assert "[PHONE]" in result
        assert "555-123-4567" not in result

    def test_no_redaction_for_safe_text(self):
        text = "Control CC6.1 evaluated successfully in 4200ms"
        result = redact_string(text)
        assert result == text

    def test_preserves_non_pii_content(self):
        text = "User john@acme.com logged in at 14:30"
        result = redact_string(text)
        assert "logged in at 14:30" in result


class TestSafeFields:
    """Tests for the SAFE_FIELDS frozenset."""

    def test_safe_fields_is_frozenset(self):
        assert isinstance(SAFE_FIELDS, frozenset)

    def test_contains_common_operational_fields(self):
        expected_fields = [
            "trace_id",
            "tenant_id",
            "session_id",
            "job_id",
            "task_id",
            "control_id",
            "framework",
            "duration_ms",
            "status",
            "status_code",
            "method",
            "path",
        ]
        for f in expected_fields:
            assert f in SAFE_FIELDS, f"Expected '{f}' in SAFE_FIELDS"

    def test_does_not_contain_pii_fields(self):
        pii_fields = ["email", "name", "address", "phone", "ssn", "password"]
        for f in pii_fields:
            assert f not in SAFE_FIELDS, f"'{f}' should NOT be in SAFE_FIELDS"

    def test_immutable(self):
        with pytest.raises(AttributeError):
            SAFE_FIELDS.add("evil_field")  # type: ignore[attr-defined]


class TestRedactionPatterns:
    """Tests for REDACTION_PATTERNS list structure."""

    def test_patterns_is_list_of_tuples(self):
        assert isinstance(REDACTION_PATTERNS, list)
        for item in REDACTION_PATTERNS:
            assert isinstance(item, tuple)
            assert len(item) == 2

    def test_patterns_have_compiled_regex(self):
        import re

        for pattern, replacement in REDACTION_PATTERNS:
            assert isinstance(pattern, re.Pattern)
            assert isinstance(replacement, str)

    def test_at_least_five_patterns(self):
        # email, SSN, card, IBAN, phone
        assert len(REDACTION_PATTERNS) >= 5
