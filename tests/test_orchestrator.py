"""Unit tests for the orchestrator, verifier, and agent state machine."""
import pytest
from unittest.mock import MagicMock
from harness.context import ContextManager, ToolResult
from harness.verifier import Verifier
from harness.orchestrator import Orchestrator
from harness.model import GeminiModel


def test_verifier_no_tests_executed():
    ctx = ContextManager("Fix bug", "/mock/repo")
    v = Verifier(ctx)
    res = v.verify("Fixed the bug")
    assert res.passed is False
    assert "tests_executed" in res.failures


def test_verifier_tests_failed():
    ctx = ContextManager("Fix bug", "/mock/repo")
    ctx.record_test_result({"passed": 0, "failed": 1, "all_passed": False})
    v = Verifier(ctx)
    res = v.verify("Fixed the bug")
    assert res.passed is False
    assert "tests_passed" in res.failures


def test_verifier_success_with_evidence():
    ctx = ContextManager("Fix bug", "/mock/repo")
    ctx.record_test_result({"passed": 2, "failed": 0, "all_passed": True})
    ctx.relevant_files = ["calc.py"]
    ctx.track_modified_file("calc.py")
    ctx.add_tool_result(ToolResult(tool="git_diff", arguments={}, success=True, output="+ return a * b"))

    v = Verifier(ctx)
    res = v.verify("Successfully fixed calculator multiplication and verified with pytest.")
    assert res.passed is True
    assert len(res.failures) == 0
    assert any("tests_passed" in e for e in res.evidence)


def test_verifier_detects_debug_leftover():
    ctx = ContextManager("Fix bug", "/mock/repo")
    ctx.record_test_result({"passed": 1, "failed": 0, "all_passed": True})
    ctx.track_modified_file("debug.py")
    ctx.add_tool_result(ToolResult(
        tool="read_file",
        arguments={"path": "debug.py"},
        success=True,
        output="def test():\n    breakpoint()\n",
    ))
    v = Verifier(ctx)
    res = v.verify("Done")
    check_debug = next(c for c in res.checks if c["name"] == "no_debug_leftovers")
    assert check_debug["passed"] is False


class MockSequenceModel:
    """Mock model returning a predefined sequence of JSON responses."""
    def __init__(self, responses):
        self.responses = list(responses)
        self.call_count = 0

    def generate_json(self, system_prompt, user_prompt, temperature=0.1):
        self.call_count += 1
        if self.responses:
            return self.responses.pop(0)
        return {"action": "finish", "arguments": {"summary": "Completed"}}


def test_orchestrator_premature_finish_rejected(tmp_path):
    """If the model attempts finish before tests, orchestrator rejects and continues."""
    mock_model = MockSequenceModel([
        # Model tries to immediately finish without running tests
        {"thought": "I think I am done", "action": "finish", "arguments": {"summary": "Done early"}},
        # Next turn: lists files
        {"thought": "Listing files", "action": "list_files", "arguments": {"path": "."}},
        # Model tries to finish again
        {"thought": "Done now", "action": "finish", "arguments": {"summary": "Really done"}},
    ])

    orchestrator = Orchestrator(task="Test task", repo_path=str(tmp_path), model=mock_model)
    # Run with small max iterations to test loop
    res = orchestrator.run()
    # It should not have been DONE on first action
    assert orchestrator.context.iteration >= 2


def test_orchestrator_state_transitions(tmp_path):
    """Test transitions through UNDERSTAND -> EXPLORE -> PLAN -> TEST -> VERIFY."""
    # Create a dummy test file in tmp_path
    test_file = tmp_path / "test_sample.py"
    test_file.write_text("def test_ok(): assert True\n")

    actions = [
        {"thought": "List repo", "action": "list_files", "arguments": {"path": "."}},
        {"thought": "Read test", "action": "read_file", "arguments": {"path": "test_sample.py"}},
        {"thought": "Run tests", "action": "run_tests", "arguments": {"test_path": "test_sample.py"}},
        {"thought": "Inspect diff", "action": "git_diff", "arguments": {}},
        {"thought": "Finish task", "action": "finish", "arguments": {"summary": "Tests pass and diff clean."}},
    ]

    mock_model = MockSequenceModel(actions)
    orchestrator = Orchestrator(task="Verify sample tests", repo_path=str(tmp_path), model=mock_model)
    result = orchestrator.run()

    assert result["status"] == "DONE"
    assert result["verification"]["passed"] is True
    assert orchestrator.metrics["test_runs"] >= 1
    assert orchestrator.metrics["model_calls"] >= 4


def test_verifier_arbitrary_large_count_passes():
    """Verifier dynamically passes arbitrary large test counts (e.g. 750 tests)."""
    ctx = ContextManager("Fix bug", "/mock/repo")
    ctx.record_test_result({"passed": 750, "failed": 0, "errors": 0, "all_passed": True})
    v = Verifier(ctx)
    res = v.verify("Fixed the bug with full suite pass")
    check_tests = next(c for c in res.checks if c["name"] == "tests_passed")
    assert check_tests["passed"] is True
    assert "Passed: 750, Failed: 0" in check_tests["evidence"]


def test_verifier_single_failure_in_large_suite_fails():
    """Verifier fails when even 1 test fails in a 750-test suite."""
    ctx = ContextManager("Fix bug", "/mock/repo")
    ctx.record_test_result({"passed": 749, "failed": 1, "errors": 0, "all_passed": False})
    v = Verifier(ctx)
    res = v.verify("Fixed the bug")
    assert res.passed is False
    assert "tests_passed" in res.failures
    check_tests = next(c for c in res.checks if c["name"] == "tests_passed")
    assert check_tests["passed"] is False
    assert "Passed: 749, Failed: 1" in check_tests["evidence"]


def test_verifier_empty_or_zero_test_count_fails():
    """Verifier fails if zero tests passed."""
    ctx = ContextManager("Fix bug", "/mock/repo")
    ctx.record_test_result({"passed": 0, "failed": 0, "errors": 0, "all_passed": False})
    v = Verifier(ctx)
    res = v.verify("Done")
    assert res.passed is False
    assert "tests_passed" in res.failures


def test_stale_verification_rejected_scenario_a(tmp_path):
    """Scenario A: If code is broken after a passing test run, finish MUST re-run tests and reject verification."""
    # 1. Create a passing test file in tmp_path
    test_file = tmp_path / "test_logic.py"
    test_file.write_text("def test_ok():\n    assert 1 == 1\n")

    # Sequence:
    # 1. Run tests (passes)
    # 2. Break the file (assert 1 == 999)
    # 3. Call finish
    # 4. Finish must execute tests freshly, fail, and reject finish!
    actions = [
        {"thought": "Run initial tests", "action": "run_tests", "arguments": {"test_path": "test_logic.py"}},
        {"thought": "Break the code", "action": "apply_patch", "arguments": {
            "path": "test_logic.py",
            "original": "assert 1 == 1",
            "replacement": "assert 1 == 999",
        }},
        {"thought": "Premature finish claim", "action": "finish", "arguments": {"summary": "Done everything!"}},
        # Next action after finish is rejected:
        {"thought": "Now in recovery", "action": "list_files", "arguments": {"path": "."}},
    ]

    mock_model = MockSequenceModel(actions)
    orchestrator = Orchestrator(task="Fix logic", repo_path=str(tmp_path), model=mock_model)
    orchestrator.max_iterations = 4
    result = orchestrator.run()

    # The finish call MUST NOT have marked it DONE / VERIFIED because fresh verification caught the broken file!
    assert result["status"] != "DONE"
    assert orchestrator.context.current_state in ("RECOVER", "FAILED", "TEST")
    assert orchestrator.metrics["test_runs"] >= 2  # Initial run + fresh run on finish
    # Check that recovery recorded the fresh test failure
    assert orchestrator.metrics["recovery_attempts"] >= 1


def test_fresh_verification_passes_scenario_b(tmp_path):
    """Scenario B: When code is modified correctly and finish is called, fresh verification verifies it."""
    # Create a broken test file
    test_file = tmp_path / "test_logic.py"
    test_file.write_text("def test_ok():\n    assert 1 == 999\n")

    actions = [
        {"thought": "Fix the code", "action": "apply_patch", "arguments": {
            "path": "test_logic.py",
            "original": "assert 1 == 999",
            "replacement": "assert 1 == 1",
        }},
        {"thought": "Inspect diff", "action": "git_diff", "arguments": {}},
        # Notice: finish is called WITHOUT calling run_tests first. Fresh verification MUST run tests.
        {"thought": "Finish", "action": "finish", "arguments": {"summary": "Fixed test to pass."}},
    ]

    mock_model = MockSequenceModel(actions)
    orchestrator = Orchestrator(task="Fix logic", repo_path=str(tmp_path), model=mock_model)
    result = orchestrator.run()

    # Fresh verification ran on finish, detected that tests pass, and verified!
    assert result["status"] == "DONE"
    assert result["verification"]["passed"] is True
    assert orchestrator.metrics["test_runs"] >= 1


def test_final_verification_uses_explicit_test_command(tmp_path, monkeypatch):
    """Final verification must execute the explicit test command (e.g. npm test) instead of hardcoding pytest."""
    recorded_commands = []

    def mock_run_command(cmd, repo_path=".", timeout=30):
        recorded_commands.append(cmd)
        return {
            "success": True,
            "output": "PASS all 12 tests",
            "error": "",
            "metadata": {"exit_code": 0},
        }

    monkeypatch.setattr("harness.tools.run_command", mock_run_command)

    actions = [
        {"thought": "Finish", "action": "finish", "arguments": {"summary": "Node project tests pass"}},
    ]
    mock_model = MockSequenceModel(actions)
    orchestrator = Orchestrator(
        task="Test javascript app with npm test",
        repo_path=str(tmp_path),
        model=mock_model,
        test_cmd="npm test",
    )
    result = orchestrator.run()

    assert result["status"] == "DONE"
    assert result["verification"]["command"] == "npm test"
    # Verify npm test was actually executed by run_command
    assert any("npm test" in c for c in recorded_commands)
    # Ensure pytest was NOT executed
    assert not any("pytest" in c for c in recorded_commands)


def test_recovery_connected_to_final_verification_failure(tmp_path, monkeypatch):
    """When fresh final verification fails, it routes through RecoveryManager with full evidence."""
    call_count = [0]

    def mock_run_command(cmd, repo_path=".", timeout=30):
        call_count[0] += 1
        if call_count[0] == 1:
            # First verification fails
            return {
                "success": False,
                "output": "FAILED: expected 42 got 0\nAssertionError: 42 != 0",
                "error": "Exit code: 1",
                "metadata": {"exit_code": 1},
            }
        else:
            # Second verification after recovery passes
            return {
                "success": True,
                "output": "1 passed in 0.05s",
                "error": "",
                "metadata": {"exit_code": 0},
            }

    monkeypatch.setattr("harness.tools.run_command", mock_run_command)

    actions = [
        # Model tries to finish, but fresh verification will fail
        {"thought": "First finish attempt", "action": "finish", "arguments": {"summary": "Claiming done"}},
        # Model receives recovery prompt and applies fix
        {"thought": "Applying fix after recovery", "action": "apply_patch", "arguments": {"path": "a.py", "original": "0", "replacement": "42"}},
        # Model tries to finish again, fresh verification passes!
        {"thought": "Second finish attempt", "action": "finish", "arguments": {"summary": "Actually done now"}},
    ]

    mock_model = MockSequenceModel(actions)
    orchestrator = Orchestrator(task="Fix math", repo_path=str(tmp_path), model=mock_model)
    result = orchestrator.run()

    # The flow recovered from the initial finish failure and verified on second attempt!
    assert result["status"] == "DONE"
    assert result["verification"]["passed"] is True
    assert orchestrator.metrics["recovery_attempts"] >= 1
    # Check that failure details were stored in recovery records
    assert len(orchestrator.recovery.context.failures) >= 1
    last_failure = orchestrator.recovery.context.failures[-1]
    assert last_failure.exit_code == 1
    assert "AssertionError" in last_failure.output
