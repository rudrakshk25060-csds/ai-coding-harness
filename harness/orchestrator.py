"""Orchestrator - core agent loop implementing the state machine.

States: UNDERSTAND → EXPLORE → PLAN → IMPLEMENT → TEST → VERIFY → DONE
Recovery: TEST → RECOVER → IMPLEMENT → TEST
"""
import json
import time
from harness.config import MAX_ITERATIONS, MAX_RECOVERY_ATTEMPTS
from harness.model import GeminiModel, ModelError
from harness.context import ContextManager, ToolResult
from harness.tools import execute_tool, TOOL_REGISTRY
from harness.recovery import RecoveryManager
from harness.verifier import Verifier

# System prompt for the coding agent
SYSTEM_PROMPT = """You are an autonomous software engineer. You receive tasks and solve them by exploring code, understanding context, making targeted changes, and verifying your work.

## Core Principles
1. **Understand before modifying.** Read the relevant code first.
2. **Explore before guessing.** Use tools to discover the repository structure and content.
3. **Use tools.** Never invent facts about the repository. Always read files and search code.
4. **Make minimal changes.** Only modify what is necessary to complete the task.
5. **Preserve existing behavior.** Don't break things that already work.
6. **Run tests.** Always run relevant tests after making changes.
7. **Diagnose failures.** When tests fail, read the error output carefully. Don't blindly retry.
8. **Never claim success without evidence.** Run tests and inspect the diff.
9. **Inspect the final diff.** Before finishing, use git_diff to review all changes.
10. **Avoid unrelated changes.** Don't modify files that aren't relevant to the task.
11. **Stop when verified.** Once tests pass and the diff looks correct, finish.

## Available Tools
You must respond with a JSON object containing an "action" and "arguments" field.

Available actions:
- `list_files`: List files in a directory. Args: {"path": "relative/path"}
- `search_code`: Search for text in code files. Args: {"query": "search text", "path": "."}
- `read_file`: Read a file. Args: {"path": "relative/path"}
- `apply_patch`: Modify a file with targeted replacement. Args: {"path": "file", "original": "exact text to find", "replacement": "new text"}. For new files, set original to "".
- `run_command`: Run a shell command. Args: {"command": "shell command"}
- `run_tests`: Run pytest. Args: {"test_path": "tests/" or specific file}
- `git_diff`: Show all changes made. Args: {}
- `git_status`: Show modified file status. Args: {}
- `finish`: Signal task completion. Args: {"summary": "what was done"}

## Response Format
Always respond with EXACTLY one JSON object:
```json
{
  "thought": "Brief reasoning about what to do next",
  "action": "tool_name",
  "arguments": { ... }
}
```

Do NOT include any text outside the JSON object.
Do NOT use multiple actions in one response.
"""


class Orchestrator:
    """Core agent loop implementing the state machine.
    
    Manages the lifecycle of a coding task from understanding
    through verification, with bounded execution and recovery.
    """

    def __init__(self, task: str, repo_path: str, model: GeminiModel = None):
        self.task = task
        self.repo_path = repo_path
        self.model = model or GeminiModel()
        self.context = ContextManager(task, repo_path)
        self.recovery = RecoveryManager(self.context)
        self.verifier = Verifier(self.context)
        self.metrics = {
            "model_calls": 0,
            "tool_calls": 0,
            "test_runs": 0,
            "recovery_attempts": 0,
            "files_inspected": 0,
            "files_modified": 0,
            "iterations": 0,
            "elapsed_time": 0,
        }
        self._start_time = time.time()

    def run(self) -> dict:
        """Execute the full agent loop.
        
        Returns:
            Dict with final status, verification result, and metrics.
        """
        print(f"\n{'='*60}")
        print(f"🤖 AI Coding Harness")
        print(f"{'='*60}")
        print(f"Task: {self.task}")
        print(f"Repo: {self.repo_path}")
        print(f"{'='*60}\n")

        try:
            result = self._agent_loop()
        except Exception as e:
            result = {
                "status": "ERROR",
                "error": str(e),
                "verification": None,
            }
            print(f"\n❌ Harness error: {e}")

        # Finalize metrics
        self.metrics["elapsed_time"] = round(time.time() - self._start_time, 1)
        self.metrics["model_calls"] = self.model.call_count
        self.metrics["files_modified"] = len(self.context.modified_files)
        self.metrics["files_inspected"] = len(self.context.relevant_files)
        self.metrics["iterations"] = self.context.iteration
        self.metrics["recovery_attempts"] = self.context.recovery_attempts

        result["metrics"] = self.metrics
        self._print_summary(result)
        return result

    def _agent_loop(self) -> dict:
        """Main bounded agent loop."""
        # Set initial state
        self.context.set_state("UNDERSTAND")

        for iteration in range(1, MAX_ITERATIONS + 1):
            self.context.iteration = iteration
            state = self.context.current_state

            print(f"\n--- Iteration {iteration}/{MAX_ITERATIONS} | State: {state} ---")

            if state == "DONE":
                return {"status": "DONE", "verification": None}

            if state == "FAILED":
                return {"status": "FAILED", "reason": "Recovery exhausted"}

            # Build the prompt based on current state
            user_prompt = self._build_state_prompt(state)

            # Call the model
            try:
                action = self._get_model_action(user_prompt)
            except ModelError as e:
                print(f"  ⚠️  Model error: {e}")
                continue

            if not action:
                print("  ⚠️  No valid action from model")
                continue

            thought = action.get("thought", "")
            action_name = action.get("action", "")
            arguments = action.get("arguments", {})

            print(f"  💭 {thought[:100]}")
            print(f"  🔧 {action_name}({json.dumps(arguments, default=str)[:100]})")

            # Handle finish action
            if action_name == "finish":
                finish_result = self._handle_finish(arguments.get("summary", ""))
                if finish_result is not None:
                    return finish_result
                continue

            # Execute the tool
            result = self._execute_action(action)
            self.metrics["tool_calls"] += 1

            # Track relevant state changes
            if action_name == "read_file" and result["success"]:
                path = arguments.get("path", "")
                if path and path not in self.context.relevant_files:
                    self.context.relevant_files.append(path)
                    self.metrics["files_inspected"] += 1

            if action_name == "apply_patch" and result["success"]:
                path = arguments.get("path", "")
                if path:
                    self.context.track_modified_file(path)

            if action_name in ("run_tests",):
                self.metrics["test_runs"] += 1
                test_meta = result.get("metadata", {})
                self.context.record_test_result(test_meta)
                
                if not result["success"] or not test_meta.get("all_passed", False):
                    # Test failure - enter recovery
                    self._handle_test_failure(result)

            # Record tool result
            tool_result = ToolResult(
                tool=action_name,
                arguments=arguments,
                success=result["success"],
                output=result.get("output", "")[:2000],
                error=result.get("error", ""),
            )
            self.context.add_tool_result(tool_result)

            # Print result status
            status_icon = "✅" if result["success"] else "❌"
            output_preview = result.get("output", "")[:150].replace("\n", " ")
            print(f"  {status_icon} {output_preview}")

            if result.get("error"):
                print(f"  ⚠️  {result['error'][:150]}")

            # Auto-advance state machine
            self._advance_state(action_name, result)

        # Exhausted iterations
        print(f"\n⚠️  Max iterations ({MAX_ITERATIONS}) reached")
        return {"status": "MAX_ITERATIONS", "verification": None}

    def _build_state_prompt(self, state: str) -> str:
        """Build a state-appropriate prompt for the model."""
        context_str = self.context.build_prompt_context()

        state_guidance = {
            "UNDERSTAND": (
                "You are in the UNDERSTAND phase. Read the task carefully. "
                "Start by listing files to understand the repository structure. "
                "Then read relevant files to understand the codebase."
            ),
            "EXPLORE": (
                "You are in the EXPLORE phase. Search for relevant code, "
                "read key files, and build understanding of the codebase. "
                "Look for the specific area related to the task."
            ),
            "PLAN": (
                "You are in the PLAN phase. Based on your understanding, "
                "decide what changes to make. Be specific and minimal."
            ),
            "IMPLEMENT": (
                "You are in the IMPLEMENT phase. Make the necessary code changes "
                "using apply_patch. Make targeted, minimal changes."
            ),
            "TEST": (
                "You are in the TEST phase. Run the relevant tests to verify "
                "your changes work correctly."
            ),
            "VERIFY": (
                "You are in the VERIFY phase. Run git_diff to inspect all changes. "
                "Make sure only intended files were modified and the changes look correct. "
                "Then use finish to complete the task."
            ),
            "RECOVER": (
                "You are in RECOVERY mode. A previous attempt failed. "
                "Read the failure details carefully and try a DIFFERENT approach. "
                "Do NOT repeat the same change that already failed."
            ),
        }

        guidance = state_guidance.get(state, "Continue working on the task.")

        return f"{guidance}\n\n{context_str}"

    def _get_model_action(self, user_prompt: str) -> dict | None:
        """Get a validated action from the model."""
        self.metrics["model_calls"] += 1

        try:
            result = self.model.generate_json(SYSTEM_PROMPT, user_prompt)
        except ModelError as e:
            # Try once more with explicit JSON instruction
            try:
                retry_prompt = (
                    user_prompt + "\n\nIMPORTANT: Respond with ONLY a valid JSON object. "
                    "No markdown, no explanation, just JSON."
                )
                result = self.model.generate_json(SYSTEM_PROMPT, retry_prompt)
            except ModelError as e2:
                self.context.add_observation(f"Failed to parse model JSON: {e2}")
                return None

        if not isinstance(result, dict):
            self.context.add_observation("Response must be a JSON object with 'action' and 'arguments'.")
            return None

        # Validate the action
        action_name = result.get("action", "")
        aliases = {
            "run_test": "run_tests",
            "test": "run_tests",
            "pytest": "run_tests",
            "patch": "apply_patch",
            "diff": "git_diff",
            "status": "git_status",
            "read": "read_file",
            "list": "list_files",
            "search": "search_code",
        }
        if action_name in aliases:
            action_name = aliases[action_name]
            result["action"] = action_name

        if action_name not in TOOL_REGISTRY:
            self.context.add_observation(
                f"Unknown action '{action_name}'. Valid actions: {list(TOOL_REGISTRY.keys())}"
            )
            return None

        if "arguments" not in result or not isinstance(result["arguments"], dict):
            result["arguments"] = {}

        return result

    def _execute_action(self, action: dict) -> dict:
        """Execute a validated action."""
        return execute_tool(action, self.repo_path)

    def _handle_finish(self, summary: str) -> dict:
        """Handle the finish action with verification."""
        print(f"\n📋 Model wants to finish: {summary[:200]}")

        # Run verification
        verification = self.verifier.verify(summary)

        if verification.passed:
            print(f"\n{verification.summary}")
            self.context.set_state("DONE")
            return {
                "status": "DONE",
                "verification": {
                    "passed": verification.passed,
                    "checks": verification.checks,
                    "failures": verification.failures,
                    "evidence": verification.evidence,
                    "summary": verification.summary,
                },
            }
        else:
            print(f"\n{verification.summary}")
            print("  → Verification failed, continuing work...")

            # Add verification failure to context
            self.context.add_observation(
                f"Verification failed: {verification.failures}. "
                f"Must address: {', '.join(verification.failures)}"
            )

            # If tests weren't run, go to TEST state
            if "tests_executed" in verification.failures:
                self.context.set_state("TEST")
            elif "tests_passed" in verification.failures:
                self.context.set_state("RECOVER")
            else:
                self.context.set_state("VERIFY")

            return None  # Continue the loop

    def _handle_test_failure(self, result: dict):
        """Handle a test failure by entering recovery mode."""
        if not self.recovery.check_recovery_budget():
            print("  ⚠️  Recovery budget exhausted")
            self.context.set_state("FAILED")
            return

        record = self.recovery.create_failure_record(
            failure_type="test_failure",
            command="pytest",
            exit_code=result.get("metadata", {}).get("exit_code", -1),
            output=result.get("output", ""),
        )

        self.recovery.increment_recovery()
        self.metrics["recovery_attempts"] += 1

        if self.recovery.is_repeated_failure(record):
            print("  🔄 Repeated failure detected - forcing strategy change")
            self.context.add_observation(
                "REPEATED FAILURE: The same error has occurred multiple times. "
                "You MUST try a completely different approach."
            )

        self.context.set_state("RECOVER")

    def _advance_state(self, action_name: str, result: dict):
        """Auto-advance the state machine based on actions taken."""
        state = self.context.current_state

        if state == "UNDERSTAND":
            # After reading files, move to EXPLORE
            if action_name in ("list_files", "read_file"):
                if len(self.context.relevant_files) >= 1:
                    self.context.set_state("EXPLORE")

        elif state == "EXPLORE":
            # After sufficient exploration, move to PLAN
            if len(self.context.tool_results) >= 3:
                self.context.set_state("PLAN")

        elif state == "PLAN":
            # Model can plan then move to IMPLEMENT
            if action_name in ("read_file", "search_code", "list_files"):
                pass  # Still planning/exploring
            else:
                self.context.set_state("IMPLEMENT")

        elif state == "IMPLEMENT":
            # After applying patches, move to TEST
            if action_name == "apply_patch" and result["success"]:
                self.context.set_state("TEST")

        elif state == "TEST":
            # Tests determine next state
            if action_name == "run_tests":
                meta = result.get("metadata", {})
                if meta.get("all_passed", False):
                    self.context.set_state("VERIFY")
                # Failure handled in _handle_test_failure

        elif state == "RECOVER":
            # After recovery action, go to IMPLEMENT or TEST
            if action_name == "apply_patch" and result["success"]:
                self.context.set_state("TEST")
            elif action_name in ("read_file", "search_code"):
                pass  # Still diagnosing

        elif state == "VERIFY":
            # Stay in VERIFY until finish
            pass

    def _print_summary(self, result: dict):
        """Print a concise run summary."""
        print(f"\n{'='*60}")
        print(f"📊 Run Summary")
        print(f"{'='*60}")
        print(f"Status: {result.get('status', 'UNKNOWN')}")

        metrics = result.get("metrics", {})
        print(f"Iterations: {metrics.get('iterations', 0)}")
        print(f"Model calls: {metrics.get('model_calls', 0)}")
        print(f"Tool calls: {metrics.get('tool_calls', 0)}")
        print(f"Test runs: {metrics.get('test_runs', 0)}")
        print(f"Recovery attempts: {metrics.get('recovery_attempts', 0)}")
        print(f"Files inspected: {metrics.get('files_inspected', 0)}")
        print(f"Files modified: {metrics.get('files_modified', 0)}")
        print(f"Elapsed time: {metrics.get('elapsed_time', 0)}s")

        verification = result.get("verification")
        if verification:
            print(f"\n{verification.get('summary', '')}")

        print(f"{'='*60}\n")
