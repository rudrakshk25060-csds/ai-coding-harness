"""Unit tests for recovery management, diagnosis, and repeated failure handling."""
import pytest
from harness.context import ContextManager
from harness.recovery import RecoveryManager
from harness.config import MAX_RECOVERY_ATTEMPTS


def test_recovery_budget():
    ctx = ContextManager(task="Debug", repo_path="/mock/repo")
    rec = RecoveryManager(ctx)

    assert rec.check_recovery_budget() is True

    for _ in range(MAX_RECOVERY_ATTEMPTS):
        rec.increment_recovery()

    assert rec.check_recovery_budget() is False


def test_failure_record_and_signatures():
    ctx = ContextManager(task="Debug", repo_path="/mock/repo")
    rec = RecoveryManager(ctx)

    f1 = rec.create_failure_record(
        failure_type="test_failure",
        command="pytest",
        exit_code=1,
        output="FAILED test_calc.py::test_multiply - AssertionError: 7 != 12",
    )

    assert f1.signature != ""
    assert len(ctx.failures) == 1
    assert rec.is_repeated_failure(f1) is False

    # Create same failure again
    f2 = rec.create_failure_record(
        failure_type="test_failure",
        command="pytest",
        exit_code=1,
        output="FAILED test_calc.py::test_multiply - AssertionError: 7 != 12",
    )

    assert f2.signature == f1.signature
    assert rec.is_repeated_failure(f2) is True


def test_recovery_prompt_repeated_warning():
    ctx = ContextManager(task="Debug", repo_path="/mock/repo")
    rec = RecoveryManager(ctx)

    f1 = rec.create_failure_record(
        failure_type="test_failure",
        command="pytest",
        exit_code=1,
        output="AssertionError: 7 != 12",
    )
    prompt1 = rec.build_recovery_prompt(f1)
    assert "REPEATED FAILURE DETECTED" not in prompt1

    f2 = rec.create_failure_record(
        failure_type="test_failure",
        command="pytest",
        exit_code=1,
        output="AssertionError: 7 != 12",
    )
    prompt2 = rec.build_recovery_prompt(f2)
    assert "REPEATED FAILURE DETECTED" in prompt2
    assert "You MUST try a COMPLETELY DIFFERENT approach" in prompt2
    assert "diagnosis" in prompt2


def test_recovery_summary():
    ctx = ContextManager(task="Debug", repo_path="/mock/repo")
    rec = RecoveryManager(ctx)

    rec.create_failure_record("test_failure", "pytest", 1, "Error 1")
    rec.increment_recovery()

    summary = rec.get_recovery_summary()
    assert summary["total_attempts"] == 1
    assert summary["max_attempts"] == MAX_RECOVERY_ATTEMPTS
    assert summary["budget_remaining"] == MAX_RECOVERY_ATTEMPTS - 1
    assert summary["total_failures"] == 1
