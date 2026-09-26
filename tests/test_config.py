"""Unit tests for configuration loading and safety."""
import os
import pytest
from unittest.mock import patch
from harness.config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    MAX_ITERATIONS,
    MAX_RECOVERY_ATTEMPTS,
    MAX_SAME_ERROR,
    validate_config,
    get_config_summary,
)


def test_config_values_present():
    """Verify default and loaded configuration constants exist."""
    assert GEMINI_MODEL is not None
    assert isinstance(GEMINI_MODEL, str)
    assert MAX_ITERATIONS == 12
    assert MAX_RECOVERY_ATTEMPTS == 4
    assert MAX_SAME_ERROR == 2


def test_validate_config_success():
    """validate_config returns True when API key is set."""
    with patch("harness.config.GEMINI_API_KEY", "mock-test-key-12345"):
        assert validate_config() is True


def test_validate_config_missing_key():
    """validate_config raises RuntimeError when API key is missing."""
    with patch("harness.config.GEMINI_API_KEY", ""):
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY is not set"):
            validate_config()


def test_config_summary_hides_secrets():
    """get_config_summary must never expose the raw API key."""
    fake_secret = "super_secret_api_key_xyz_999"
    with patch("harness.config.GEMINI_API_KEY", fake_secret):
        summary = get_config_summary()
        summary_str = str(summary)
        assert fake_secret not in summary_str
        assert summary["api_key_set"] is True
        assert summary["model"] == GEMINI_MODEL
        assert summary["max_iterations"] == 12