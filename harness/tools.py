"""Tool system - safe tools for the coding agent to interact with repositories."""
import os
import sys
import subprocess
import re
from pathlib import Path
from harness.config import MAX_OUTPUT_CHARS, MAX_FILE_CHARS, FORBIDDEN_PATHS, FORBIDDEN_COMMANDS


class ToolError(Exception):
    """Raised when a tool encounters a safety or execution error."""
    pass


def _safe_path(path: str, repo_path: str) -> str:
    """Resolve and validate a path is within the repository.
    
    Raises ToolError if the path escapes the repository.
    """
    repo = Path(repo_path).resolve()
    target = (repo / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    
    if not str(target).startswith(str(repo)):
        raise ToolError(f"Path '{path}' is outside the repository '{repo}'")
    
    # Check forbidden paths
    rel = str(target.relative_to(repo))
    for forbidden in FORBIDDEN_PATHS:
        if rel == forbidden or rel.startswith(forbidden):
            raise ToolError(f"Access to '{rel}' is forbidden")
    
    return str(target)


def _truncate(text: str, max_chars: int = None) -> str:
    """Truncate output to prevent context overflow."""
    limit = max_chars or MAX_OUTPUT_CHARS
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + f"\n\n... [TRUNCATED {len(text) - limit} chars] ...\n\n" + text[-half:]


def list_files(path: str = ".", repo_path: str = ".") -> dict:
    """List files in a directory within the repository.
    
    Returns a structured result with file listing.
    """
    try:
        safe = _safe_path(path, repo_path)
        if not os.path.isdir(safe):
            return {"success": False, "error": f"Not a directory: {path}", "output": "", "metadata": {}}
        
        files = []
        for root, dirs, filenames in os.walk(safe):
            # Skip hidden dirs and common non-essential dirs
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in 
                       ("__pycache__", ".venv", "venv", "node_modules", ".git")]
            for f in sorted(filenames):
                if f.startswith(".") and f != ".gitignore":
                    continue
                full = os.path.join(root, f)
                rel = os.path.relpath(full, repo_path)
                files.append(rel)
        
        output = "\n".join(files)
        return {
            "success": True,
            "output": _truncate(output),
            "error": "",
            "metadata": {"file_count": len(files)},
        }
    except ToolError as e:
        return {"success": False, "error": str(e), "output": "", "metadata": {}}
    except Exception as e:
        return {"success": False, "error": f"list_files error: {e}", "output": "", "metadata": {}}


def search_code(query: str, path: str = ".", repo_path: str = ".") -> dict:
    """Search for a pattern in code files within the repository.
    
    Uses simple string matching (or regex if query looks like a pattern).
    """
    try:
        safe = _safe_path(path, repo_path)
        matches = []
        
        # Determine if query is regex
        is_regex = any(c in query for c in r"[](){}*+?|^$\\")
        
        for root, dirs, filenames in os.walk(safe):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in 
                       ("__pycache__", ".venv", "venv", "node_modules", ".git")]
            for fname in sorted(filenames):
                if fname.endswith((".pyc", ".pyo", ".so", ".o", ".bin", ".exe")):
                    continue
                full = os.path.join(root, fname)
                rel = os.path.relpath(full, repo_path)
                try:
                    with open(full, "r", errors="replace") as f:
                        for i, line in enumerate(f, 1):
                            found = False
                            if is_regex:
                                try:
                                    found = bool(re.search(query, line))
                                except re.error:
                                    found = query in line
                            else:
                                found = query in line
                            if found:
                                matches.append(f"{rel}:{i}: {line.rstrip()}")
                            if len(matches) >= 50:
                                break
                except (UnicodeDecodeError, PermissionError):
                    continue
                if len(matches) >= 50:
                    break
            if len(matches) >= 50:
                break
        
        output = "\n".join(matches) if matches else "No matches found."
        return {
            "success": True,
            "output": _truncate(output),
            "error": "",
            "metadata": {"match_count": len(matches)},
        }
    except ToolError as e:
        return {"success": False, "error": str(e), "output": "", "metadata": {}}
    except Exception as e:
        return {"success": False, "error": f"search_code error: {e}", "output": "", "metadata": {}}


def read_file(path: str, repo_path: str = ".") -> dict:
    """Read a file's contents from the repository."""
    try:
        safe = _safe_path(path, repo_path)
        if not os.path.isfile(safe):
            return {"success": False, "error": f"File not found: {path}", "output": "", "metadata": {}}
        
        with open(safe, "r", errors="replace") as f:
            content = f.read()
        
        line_count = content.count("\n") + 1
        return {
            "success": True,
            "output": _truncate(content, MAX_FILE_CHARS),
            "error": "",
            "metadata": {"line_count": line_count, "char_count": len(content)},
        }
    except ToolError as e:
        return {"success": False, "error": str(e), "output": "", "metadata": {}}
    except Exception as e:
        return {"success": False, "error": f"read_file error: {e}", "output": "", "metadata": {}}


def apply_patch(path: str, original: str, replacement: str, repo_path: str = ".") -> dict:
    """Apply a targeted patch to a file.
    
    Finds 'original' text in the file and replaces it with 'replacement'.
    This is safer than rewriting entire files.
    
    Args:
        path: File path relative to repo.
        original: The exact text to find and replace.
        replacement: The replacement text.
        repo_path: Repository root path.
    """
    try:
        safe = _safe_path(path, repo_path)
        
        if os.path.isfile(safe):
            with open(safe, "r") as f:
                content = f.read()
        else:
            # Creating a new file
            content = ""
        
        if original == "" and content == "":
            # New file creation
            new_content = replacement
        elif original == "" and replacement != "":
            # Appending to empty match - write whole file
            new_content = replacement
        elif original not in content:
            return {
                "success": False,
                "error": f"Original text not found in {path}. Cannot apply patch.",
                "output": "",
                "metadata": {},
            }
        else:
            count = content.count(original)
            if count > 1:
                # Replace first occurrence only for safety
                idx = content.index(original)
                new_content = content[:idx] + replacement + content[idx + len(original):]
            else:
                new_content = content.replace(original, replacement)
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(safe) or ".", exist_ok=True)
        
        with open(safe, "w") as f:
            f.write(new_content)
        
        return {
            "success": True,
            "output": f"Patch applied to {path}",
            "error": "",
            "metadata": {"path": path},
        }
    except ToolError as e:
        return {"success": False, "error": str(e), "output": "", "metadata": {}}
    except Exception as e:
        return {"success": False, "error": f"apply_patch error: {e}", "output": "", "metadata": {}}


def run_command(command: str, repo_path: str = ".", timeout: int = 30) -> dict:
    """Run a shell command within the repository.
    
    Safety: Commands run with cwd set to repo_path.
    Output is truncated to prevent context overflow.
    """
    try:
        # Basic safety checks
        for forbidden in FORBIDDEN_COMMANDS:
            if forbidden in command:
                return {
                    "success": False,
                    "error": f"Forbidden command pattern: {forbidden}",
                    "output": "",
                    "metadata": {},
                }
        
        # Prevent accessing secrets
        if "GEMINI_API_KEY" in command and ("echo" in command or "print" in command or "cat" in command):
            return {
                "success": False,
                "error": "Cannot expose API keys via commands",
                "output": "",
                "metadata": {},
            }
        
        cmd_env = {
            **os.environ,
            "PATH": f"{os.path.dirname(sys.executable)}:{os.environ.get('PATH', '')}",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        result = subprocess.run(
            command,
            shell=True,
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=cmd_env,
        )
        
        output = result.stdout
        if result.stderr:
            output += "\nSTDERR:\n" + result.stderr
        
        return {
            "success": result.returncode == 0,
            "output": _truncate(output),
            "error": "" if result.returncode == 0 else f"Exit code: {result.returncode}",
            "metadata": {"exit_code": result.returncode},
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": f"Command timed out after {timeout}s",
            "output": "",
            "metadata": {"timeout": True},
        }
    except Exception as e:
        return {"success": False, "error": f"run_command error: {e}", "output": "", "metadata": {}}


def run_tests(test_path: str = "", test_cmd: str = "", repo_path: str = ".", timeout: int = 60) -> dict:
    """Run tests within the repository.
    
    Supports pytest, python -m unittest, or custom commands.
    
    Args:
        test_path: Specific test file or directory. Empty = run all tests.
        test_cmd: Explicit custom test command to run.
        repo_path: Repository root.
        timeout: Max seconds for test execution.
    """
    if test_cmd:
        cmd = f"{test_cmd} 2>&1"
    elif test_path:
        cmd = f'"{sys.executable}" -m pytest {test_path} -v --tb=short 2>&1'
    else:
        cmd = f'"{sys.executable}" -m pytest -v --tb=short 2>&1'

    result = run_command(cmd, repo_path, timeout)
    
    # If pytest was not found or failed to collect tests, check if unittest works
    output = result["output"]
    if ("No module named pytest" in output or "command not found" in output) and not test_cmd:
        fallback_cmd = f'"{sys.executable}" -m unittest discover -v 2>&1'
        result = run_command(fallback_cmd, repo_path, timeout)
        output = result["output"]

    # Parse test summary (supports pytest and unittest formats)
    passed_match = re.search(r"(\d+)\s+passed", output)
    failed_match = re.search(r"(\d+)\s+failed", output)
    error_match = re.search(r"(\d+)\s+error", output)
    
    unittest_ran = re.search(r"Ran\s+(\d+)\s+tests?", output)
    unittest_ok = bool(re.search(r"\bOK\b", output) and unittest_ran)
    unittest_fail = re.search(r"FAILED\s+\((?:failures=(\d+))?(?:,\s*)?(?:errors=(\d+))?\)", output)
    
    if unittest_ok:
        passed = int(unittest_ran.group(1))
        failed = 0
        errors = 0
    elif unittest_fail:
        failed = int(unittest_fail.group(1) or 0)
        errors = int(unittest_fail.group(2) or 0)
        total = int(unittest_ran.group(1)) if unittest_ran else failed + errors
        passed = max(0, total - failed - errors)
    else:
        passed = int(passed_match.group(1)) if passed_match else len(re.findall(r"\bPASSED\b", output))
        failed = int(failed_match.group(1)) if failed_match else len(re.findall(r"\bFAILED\b", output))
        errors = int(error_match.group(1)) if error_match else len(re.findall(r"\bERROR\b", output))
    
    all_passed = (result["success"] or result["metadata"].get("exit_code") == 0) and failed == 0 and errors == 0 and passed > 0
    
    result["metadata"].update({
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "all_passed": all_passed,
    })
    
    return result


def git_diff(repo_path: str = ".") -> dict:
    """Show the current git diff of the repository."""
    return run_command("git diff", repo_path)


def git_status(repo_path: str = ".") -> dict:
    """Show the current git status of the repository."""
    return run_command("git status --short", repo_path)


# Tool registry - maps tool names to their functions and signatures
TOOL_REGISTRY = {
    "list_files": {
        "function": list_files,
        "description": "List files in a directory within the repository.",
        "parameters": {"path": "Directory path relative to repo (default: '.')"},
    },
    "search_code": {
        "function": search_code,
        "description": "Search for a pattern in code files.",
        "parameters": {"query": "Search string or pattern", "path": "Directory to search in (default: '.')"},
    },
    "read_file": {
        "function": read_file,
        "description": "Read a file's contents.",
        "parameters": {"path": "File path relative to repo"},
    },
    "apply_patch": {
        "function": apply_patch,
        "description": "Apply a targeted text replacement to a file. Use 'original' as the exact text to find and 'replacement' as the new text. For new files, set original to empty string.",
        "parameters": {"path": "File path", "original": "Exact text to find", "replacement": "Replacement text"},
    },
    "run_command": {
        "function": run_command,
        "description": "Run a shell command in the repository.",
        "parameters": {"command": "Shell command to execute"},
    },
    "run_tests": {
        "function": run_tests,
        "description": "Run tests (pytest, unittest, or custom). Supports pytest by default, falls back to unittest if pytest is unavailable. Use test_cmd for custom commands like 'npm test' or 'make test'.",
        "parameters": {"test_path": "Test file or dir (empty for all)", "test_cmd": "Custom test command (e.g. 'npm test', 'make test')"},
    },
    "git_diff": {
        "function": git_diff,
        "description": "Show the git diff of changes.",
        "parameters": {},
    },
    "git_status": {
        "function": git_status,
        "description": "Show git status.",
        "parameters": {},
    },
    "finish": {
        "function": None,  # Handled by orchestrator
        "description": "Signal that the task is complete. Provide a summary of what was done.",
        "parameters": {"summary": "Summary of completed work"},
    },
}


def execute_tool(action: dict, repo_path: str) -> dict:
    """Execute a tool action.
    
    Args:
        action: Dict with 'action' and 'arguments' keys.
        repo_path: Repository root path.
        
    Returns:
        Tool result dict.
    """
    tool_name = action.get("action", "")
    arguments = action.get("arguments", {})
    
    if tool_name not in TOOL_REGISTRY:
        return {
            "success": False,
            "error": f"Unknown tool: {tool_name}. Available: {list(TOOL_REGISTRY.keys())}",
            "output": "",
            "metadata": {},
        }
    
    if tool_name == "finish":
        return {
            "success": True,
            "output": arguments.get("summary", "Task finished."),
            "error": "",
            "metadata": {"finished": True},
        }
    
    tool_func = TOOL_REGISTRY[tool_name]["function"]
    
    # Inject repo_path into arguments
    arguments["repo_path"] = repo_path
    
    try:
        return tool_func(**arguments)
    except TypeError as e:
        return {
            "success": False,
            "error": f"Invalid arguments for {tool_name}: {e}",
            "output": "",
            "metadata": {},
        }
