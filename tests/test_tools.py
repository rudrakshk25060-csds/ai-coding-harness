"""Unit tests for tool system and safety mechanisms."""
import os
import tempfile
import pytest
from harness.tools import (
    _safe_path,
    ToolError,
    list_files,
    search_code,
    read_file,
    apply_patch,
    run_command,
    run_tests,
    execute_tool,
)


@pytest.fixture
def temp_repo():
    """Create a temporary repository directory with sample files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a sample file
        os.makedirs(os.path.join(tmpdir, "pkg"), exist_ok=True)
        with open(os.path.join(tmpdir, "pkg", "mod.py"), "w") as f:
            f.write("def calculate(x):\n    return x + 1\n")
        with open(os.path.join(tmpdir, "pkg", "sub.py"), "w") as f:
            f.write("import math\n# Note: helper function\n")
        yield tmpdir


def test_safe_path_valid(temp_repo):
    p = _safe_path("pkg/mod.py", temp_repo)
    assert os.path.exists(p)


def test_safe_path_outside_traversal(temp_repo):
    with pytest.raises(ToolError, match="outside the repository"):
        _safe_path("../../etc/passwd", temp_repo)


def test_safe_path_forbidden_file(temp_repo):
    # Attempting to access .env or .git/config must raise ToolError
    with pytest.raises(ToolError, match="forbidden"):
        _safe_path(".env", temp_repo)


def test_list_files(temp_repo):
    res = list_files(".", temp_repo)
    assert res["success"] is True
    assert "pkg/mod.py" in res["output"]
    assert "pkg/sub.py" in res["output"]


def test_read_file_success(temp_repo):
    res = read_file("pkg/mod.py", temp_repo)
    assert res["success"] is True
    assert "def calculate(x):" in res["output"]
    assert res["metadata"]["line_count"] >= 2


def test_read_file_not_found(temp_repo):
    res = read_file("pkg/nonexistent.py", temp_repo)
    assert res["success"] is False
    assert "not found" in res["error"].lower()


def test_search_code_literal(temp_repo):
    res = search_code("helper function", ".", temp_repo)
    assert res["success"] is True
    assert "pkg/sub.py" in res["output"]
    assert "helper function" in res["output"]


def test_search_code_not_found(temp_repo):
    res = search_code("nonexistent_random_symbol_99", ".", temp_repo)
    assert res["success"] is True
    assert "No matches found" in res["output"]


def test_apply_patch_success(temp_repo):
    patch_res = apply_patch(
        path="pkg/mod.py",
        original="return x + 1",
        replacement="return x * 2",
        repo_path=temp_repo,
    )
    assert patch_res["success"] is True

    # Read back and verify change
    read_res = read_file("pkg/mod.py", temp_repo)
    assert "return x * 2" in read_res["output"]
    assert "return x + 1" not in read_res["output"]


def test_apply_patch_original_not_found(temp_repo):
    patch_res = apply_patch(
        path="pkg/mod.py",
        original="non_existent_code_line()",
        replacement="replacement()",
        repo_path=temp_repo,
    )
    assert patch_res["success"] is False
    assert "not found" in patch_res["error"].lower()


def test_run_command_safe(temp_repo):
    res = run_command("python -c \"print('HELLO_SAFE')\"", temp_repo)
    assert res["success"] is True
    assert "HELLO_SAFE" in res["output"]


def test_run_command_forbidden_pattern(temp_repo):
    res = run_command("rm -rf /", temp_repo)
    assert res["success"] is False
    assert "Forbidden" in res["error"]


def test_run_command_secret_protection(temp_repo):
    res = run_command("echo $GEMINI_API_KEY", temp_repo)
    assert res["success"] is False
    assert "Cannot expose API keys" in res["error"]


def test_execute_tool_dispatcher(temp_repo):
    action = {
        "action": "read_file",
        "arguments": {"path": "pkg/mod.py"},
    }
    res = execute_tool(action, temp_repo)
    assert res["success"] is True
    assert "calculate" in res["output"]


def test_execute_tool_unknown(temp_repo):
    action = {
        "action": "hack_system",
        "arguments": {},
    }
    res = execute_tool(action, temp_repo)
    assert res["success"] is False
    assert "Unknown tool" in res["error"]


def test_run_tests_arbitrary_large_count_passes(monkeypatch):
    """Test output parsing dynamically handles large test suites (e.g. 524 tests)."""
    fake_pytest_output = (
        "test_suite.py::test_001 PASSED\n"
        "test_suite.py::test_524 PASSED\n"
        "========================= 524 passed in 14.23s =========================\n"
    )
    monkeypatch.setattr("harness.tools.run_command", lambda cmd, repo, timeout: {
        "success": True,
        "output": fake_pytest_output,
        "error": "",
        "metadata": {"exit_code": 0}
    })
    res = run_tests(repo_path=".")
    assert res["metadata"]["passed"] == 524
    assert res["metadata"]["failed"] == 0
    assert res["metadata"]["errors"] == 0
    assert res["metadata"]["all_passed"] is True


def test_run_tests_large_suite_with_failure(monkeypatch):
    """A single failure among hundreds of tests marks all_passed as False."""
    fake_pytest_output = (
        "test_suite.py::test_001 PASSED\n"
        "test_suite.py::test_499 FAILED\n"
        "=================== 1 failed, 523 passed in 14.23s ====================\n"
    )
    monkeypatch.setattr("harness.tools.run_command", lambda cmd, repo, timeout: {
        "success": False,
        "output": fake_pytest_output,
        "error": "Exit code: 1",
        "metadata": {"exit_code": 1}
    })
    res = run_tests(repo_path=".")
    assert res["metadata"]["passed"] == 523
    assert res["metadata"]["failed"] == 1
    assert res["metadata"]["all_passed"] is False


def test_run_tests_empty_output(monkeypatch):
    """Empty test runner output does not pass verification."""
    monkeypatch.setattr("harness.tools.run_command", lambda cmd, repo, timeout: {
        "success": False,
        "output": "",
        "error": "Command failed",
        "metadata": {"exit_code": 1}
    })
    res = run_tests(repo_path=".")
    assert res["metadata"]["passed"] == 0
    assert res["metadata"]["failed"] == 0
    assert res["metadata"]["all_passed"] is False


def test_run_tests_invalid_garbage_output(monkeypatch):
    """Unparseable/garbage test runner output does not pass verification."""
    monkeypatch.setattr("harness.tools.run_command", lambda cmd, repo, timeout: {
        "success": False,
        "output": "Fatal python error: Segmentation fault\ncore dumped",
        "error": "Exit code: 139",
        "metadata": {"exit_code": 139}
    })
    res = run_tests(repo_path=".")
    assert res["metadata"]["passed"] == 0
    assert res["metadata"]["all_passed"] is False


def test_safe_path_prefix_confusion(tmp_path):
    """Path containment must not confuse sibling directory prefixes."""
    project = tmp_path / "project"
    project.mkdir()
    project_other = tmp_path / "project-other"
    project_other.mkdir()

    # ALLOWED: inside project
    f1 = project / "file.py"
    f1.write_text("x = 1")
    assert _safe_path("file.py", str(project)) == str(f1.resolve())

    (project / "src").mkdir()
    f2 = project / "src" / "test.py"
    f2.write_text("assert True")
    assert _safe_path("src/test.py", str(project)) == str(f2.resolve())

    # BLOCKED: prefix confusion (/tmp/project-other/file.py must be blocked)
    f_other = project_other / "file.py"
    f_other.write_text("secret = True")
    with pytest.raises(ToolError, match="outside the repository"):
        _safe_path(str(f_other), str(project))

    # BLOCKED: relative traversal into sibling prefix
    with pytest.raises(ToolError, match="outside the repository"):
        _safe_path("../project-other/file.py", str(project))

    # BLOCKED: parent dir file (/tmp/file.py)
    f_parent = tmp_path / "file.py"
    f_parent.write_text("parent = True")
    with pytest.raises(ToolError, match="outside the repository"):
        _safe_path(str(f_parent), str(project))


def test_generalized_secret_protection_all_keys(monkeypatch):
    """Verify secret protection covers all required provider keys."""
    keys = [
        "AI_API_KEY",
        "GEMINI_API_KEY",
        "DEEPSEEK_API_KEY",
        "QWEN_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
    ]
    for key in keys:
        res = run_command(f"echo ${key}")
        assert res["success"] is False, f"Expected {key} exposure via echo to be blocked"
        assert "Cannot expose API keys" in res["error"]

        res = run_command(f"printenv {key}")
        assert res["success"] is False, f"Expected {key} exposure via printenv to be blocked"
        assert "Cannot expose API keys" in res["error"]

    # Verify that documentation searches containing the variable name are NOT blocked
    doc_search = run_command("grep -rn 'GEMINI_API_KEY' README.md")
    # This command should execute normally (not blocked by the secret shield)
    assert "Cannot expose API keys" not in doc_search.get("error", "")

    # Verify secret value redaction from command output
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-secret-deepseek-token-999")
    res_clean = run_command('python -c "print(\'sk-secret-deepseek-token-999\')"')
    assert "sk-secret-deepseek-token-999" not in res_clean["output"]
    assert "[REDACTED]" in res_clean["output"]


def test_detect_test_command(tmp_path):
    """Lightweight test command detection identifies common ecosystem markers."""
    from harness.tools import detect_test_command

    # Empty dir defaults to empty string (which falls back to pytest)
    assert detect_test_command(str(tmp_path)) == ""

    # Node.js
    (tmp_path / "package.json").write_text("{}")
    assert detect_test_command(str(tmp_path)) == "npm test"
    (tmp_path / "package.json").unlink()

    # Go
    (tmp_path / "go.mod").write_text("module example.com/app")
    assert detect_test_command(str(tmp_path)) == "go test ./..."
    (tmp_path / "go.mod").unlink()

    # Rust
    (tmp_path / "Cargo.toml").write_text("[package]\nname = 'app'")
    assert detect_test_command(str(tmp_path)) == "cargo test"


def test_run_tests_custom_command_exits_zero_unrecognized_output(monkeypatch):
    """Custom command exiting 0 with unrecognized output passes without fabricating passed counts."""
    monkeypatch.setattr("harness.tools.run_command", lambda cmd, repo, timeout: {
        "success": True,
        "output": "Project test suite completed successfully with no errors.",
        "error": "",
        "metadata": {"exit_code": 0},
    })
    res = run_tests(test_cmd="npm test", repo_path=".")
    assert res["metadata"]["all_passed"] is True
    # Crucial: test count must NOT be fabricated (remains 0 if unparseable)
    assert res["metadata"]["passed"] == 0
    assert res["metadata"]["failed"] == 0
    assert res["metadata"]["command"] == "npm test"


def test_run_tests_custom_command_exits_nonzero_fails(monkeypatch):
    """Custom command exiting non-zero fails verification."""
    monkeypatch.setattr("harness.tools.run_command", lambda cmd, repo, timeout: {
        "success": False,
        "output": "npm ERR! Test failed. See output above.",
        "error": "Exit code: 1",
        "metadata": {"exit_code": 1},
    })
    res = run_tests(test_cmd="npm test", repo_path=".")
    assert res["metadata"]["all_passed"] is False
