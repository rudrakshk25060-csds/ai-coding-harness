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
