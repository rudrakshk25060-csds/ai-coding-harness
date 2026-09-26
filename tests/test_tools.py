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
