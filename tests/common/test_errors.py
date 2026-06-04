"""Tests for common.errors exception hierarchy."""

from __future__ import annotations

import pytest

from common.errors import (
    AuthenticationError,
    AuthorizationError,
    CommonError,
    LLMCreditExhaustedError,
    LLMTimeoutError,
    LLMUnavailableError,
    RegistryError,
    SandboxError,
    StateError,
    StorageError,
    StorageNotFoundError,
)


class TestCommonError:
    """Tests for the base CommonError class."""

    def test_basic_instantiation(self):
        err = CommonError("something failed")
        assert err.message == "something failed"
        assert err.context == {}
        assert str(err) == "something failed"

    def test_with_context(self):
        err = CommonError("oops", tenant_id="t-1", task="eval")
        assert err.context == {"tenant_id": "t-1", "task": "eval"}

    def test_repr_without_context(self):
        err = CommonError("fail")
        assert repr(err) == "CommonError('fail')"

    def test_repr_with_context(self):
        err = CommonError("fail", key="val")
        assert repr(err) == "CommonError('fail', key='val')"

    def test_empty_message(self):
        err = CommonError()
        assert err.message == ""
        assert repr(err) == "CommonError('')"


class TestHierarchy:
    """Verify that the exception inheritance tree is correct."""

    def test_llm_unavailable_is_common_error(self):
        assert issubclass(LLMUnavailableError, CommonError)

    def test_llm_timeout_is_llm_unavailable(self):
        assert issubclass(LLMTimeoutError, LLMUnavailableError)

    def test_llm_credit_exhausted_is_llm_unavailable(self):
        assert issubclass(LLMCreditExhaustedError, LLMUnavailableError)

    def test_storage_error_is_common_error(self):
        assert issubclass(StorageError, CommonError)

    def test_storage_not_found_is_storage_error(self):
        assert issubclass(StorageNotFoundError, StorageError)

    def test_sandbox_error_is_common_error(self):
        assert issubclass(SandboxError, CommonError)

    def test_state_error_is_common_error(self):
        assert issubclass(StateError, CommonError)

    def test_authentication_error_is_common_error(self):
        assert issubclass(AuthenticationError, CommonError)

    def test_authorization_error_is_common_error(self):
        assert issubclass(AuthorizationError, CommonError)

    def test_registry_error_is_common_error(self):
        assert issubclass(RegistryError, CommonError)

    def test_catch_llm_unavailable_catches_timeout(self):
        """Agents catching LLMUnavailableError also catch timeouts."""
        with pytest.raises(LLMUnavailableError):
            raise LLMTimeoutError("timed out")

    def test_catch_llm_unavailable_catches_credit_exhausted(self):
        with pytest.raises(LLMUnavailableError):
            raise LLMCreditExhaustedError("budget gone")

    def test_catch_storage_error_catches_not_found(self):
        with pytest.raises(StorageError):
            raise StorageNotFoundError("key missing")


class TestLLMCreditExhaustedError:
    """Tests for the LLMCreditExhaustedError extended attributes."""

    def test_default_attributes(self):
        err = LLMCreditExhaustedError("budget gone")
        assert err.degradation_level == 1
        assert err.tier_availability == {
            "fast": "available",
            "mid": "available",
            "strong": "exhausted",
        }
        assert err.estimated_recovery is None
        assert err.can_queue is False
        assert err.queued_position is None

    def test_custom_attributes(self):
        err = LLMCreditExhaustedError(
            "all tiers exhausted",
            degradation_level=3,
            tier_availability={"fast": "exhausted", "mid": "exhausted", "strong": "exhausted"},
            estimated_recovery="2025-02-01T00:00:00Z",
            can_queue=True,
            queued_position=5,
            tenant_id="t-123",
        )
        assert err.degradation_level == 3
        assert err.tier_availability["fast"] == "exhausted"
        assert err.estimated_recovery == "2025-02-01T00:00:00Z"
        assert err.can_queue is True
        assert err.queued_position == 5
        assert err.context["tenant_id"] == "t-123"

    def test_repr_includes_context(self):
        err = LLMCreditExhaustedError("gone", tenant_id="t-1")
        r = repr(err)
        assert "LLMCreditExhaustedError" in r
        assert "tenant_id='t-1'" in r

    def test_is_exception(self):
        err = LLMCreditExhaustedError("test")
        assert isinstance(err, Exception)
