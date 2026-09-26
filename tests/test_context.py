"""Unit tests for the context manager."""
import pytest
from harness.context import ContextManager, ToolResult, FailureRecord


def test_context_initial_state():
    ctx = ContextManager(task="Fix math bug", repo_path="/mock/repo")
    assert ctx.task == "Fix math bug"
    assert ctx.repo_path == "/mock/repo"
    assert ctx.current_state == "UNDERSTAND"
    assert ctx.relevant_files == []
    assert ctx.modified_files == set()
    assert ctx.tool_results == []
    assert ctx.failures == []


def test_context_state_transition():
    ctx = ContextManager(task="Fix math bug", repo_path="/mock/repo")
    ctx.set_state("EXPLORE")
    assert ctx.current_state == "EXPLORE"
    ctx.set_state("PLAN")
    assert ctx.current_state == "PLAN"
    ctx.set_state("IMPLEMENT")
    assert ctx.current_state == "IMPLEMENT"
    ctx.set_state("TEST")
    assert ctx.current_state == "TEST"
    ctx.set_state("VERIFY")
    assert ctx.current_state == "VERIFY"
    ctx.set_state("DONE")
    assert ctx.current_state == "DONE"

    with pytest.raises(ValueError, match="Invalid state"):
        ctx.set_state("NON_EXISTENT_STATE")


def test_add_tool_result_and_actions():
    ctx = ContextManager(task="Task 1", repo_path="/mock/repo")
    res = ToolResult(
        tool="read_file",
        arguments={"path": "calc.py"},
        success=True,
        output="def add(): pass",
    )
    ctx.add_tool_result(res)
    assert len(ctx.tool_results) == 1
    assert len(ctx.completed_actions) == 1
    assert "read_file" in ctx.completed_actions[0]
    assert "OK" in ctx.completed_actions[0]


def test_failure_tracking_and_signatures():
    ctx = ContextManager(task="Task 1", repo_path="/mock/repo")
    f1 = FailureRecord(
        failure_type="test_failure",
        command="pytest",
        exit_code=1,
        output="AssertionError: 5 != 12",
        signature="sig_test_1",
    )
    ctx.record_failure(f1)
    assert f1.attempt == 1
    assert ctx.has_repeated_failure("sig_test_1", threshold=2) is False

    f2 = FailureRecord(
        failure_type="test_failure",
        command="pytest",
        exit_code=1,
        output="AssertionError: 5 != 12",
        signature="sig_test_1",
    )
    ctx.record_failure(f2)
    assert ctx.has_repeated_failure("sig_test_1", threshold=2) is True


def test_track_modified_file():
    ctx = ContextManager(task="Task 1", repo_path="/mock/repo")
    ctx.track_modified_file("calculator.py")
    assert "calculator.py" in ctx.modified_files
    # Set uniqueness
    ctx.track_modified_file("calculator.py")
    assert len(ctx.modified_files) == 1


def test_build_prompt_context_priority():
    ctx = ContextManager(task="Fix multiplication", repo_path="/mock/repo")
    ctx.set_state("IMPLEMENT")
    ctx.current_plan = ["Inspect calculator.py", "Fix operator", "Run tests"]
    ctx.relevant_files = ["calculator.py"]
    ctx.track_modified_file("calculator.py")

    f = FailureRecord(
        failure_type="test_failure",
        command="pytest",
        exit_code=1,
        output="AssertionError: 7 != 12",
        signature="sig_mult",
    )
    ctx.record_failure(f)
    ctx.record_failure(f)  # repeat to trigger warning

    prompt_ctx = ctx.build_prompt_context()

    assert "## TASK\nFix multiplication" in prompt_ctx
    assert "## CURRENT STATE: IMPLEMENT" in prompt_ctx
    assert "## CURRENT PLAN" in prompt_ctx
    assert "## RELEVANT FILES\ncalculator.py" in prompt_ctx
    assert "## LATEST FAILURE" in prompt_ctx
    assert "⚠️ WARNING: This failure has occurred 2 times." in prompt_ctx
    assert "## MODIFIED FILES\ncalculator.py" in prompt_ctx


def test_get_metrics():
    ctx = ContextManager(task="Task 1", repo_path="/mock/repo")
    ctx.iteration = 3
    ctx.recovery_attempts = 1
    ctx.relevant_files = ["a.py", "b.py"]
    ctx.track_modified_file("a.py")
    ctx.record_test_result({"passed": 1, "failed": 0})

    metrics = ctx.get_metrics()
    assert metrics["iterations"] == 3
    assert metrics["recovery_attempts"] == 1
    assert metrics["files_inspected"] == 2
    assert metrics["files_modified"] == 1
    assert metrics["test_runs"] == 1
    assert "elapsed_time" in metrics
