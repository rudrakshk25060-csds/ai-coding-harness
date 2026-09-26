"""Context manager - maintains structured state for the agent loop."""
from dataclasses import dataclass, field
from typing import Any
import time


@dataclass
class ToolResult:
    """Result from a tool execution."""
    tool: str
    arguments: dict
    success: bool
    output: str = ""
    error: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class FailureRecord:
    """Record of a failure for recovery tracking."""
    failure_type: str  # "test_failure", "command_error", "tool_error", "patch_error"
    command: str = ""
    exit_code: int = -1
    output: str = ""
    attempt: int = 0
    modified_files: list = field(default_factory=list)
    signature: str = ""  # Compact string for duplicate detection
    timestamp: float = field(default_factory=time.time)


class ContextManager:
    """Maintains structured state for the coding agent.
    
    Tracks the task, plan, observations, tool results, failures,
    and provides prioritized context for model prompts.
    """

    def __init__(self, task: str, repo_path: str):
        self.task = task
        self.repo_path = repo_path
        self.current_state = "UNDERSTAND"
        self.repository_summary = ""
        self.relevant_files: list[str] = []
        self.current_plan: list[str] = []
        self.completed_actions: list[str] = []
        self.tool_results: list[ToolResult] = []
        self.test_results: list[dict] = []
        self.failures: list[FailureRecord] = []
        self.modified_files: set[str] = set()
        self.iteration = 0
        self.recovery_attempts = 0
        self.observations: list[str] = []
        self.start_time = time.time()

    def add_observation(self, observation: str):
        """Record a textual observation."""
        self.observations.append(observation)

    def add_tool_result(self, result: ToolResult):
        """Record a tool execution result."""
        self.tool_results.append(result)
        action_desc = f"{result.tool}({result.arguments}) -> {'OK' if result.success else 'FAIL'}"
        self.completed_actions.append(action_desc)

    def record_failure(self, failure: FailureRecord):
        """Record a failure for recovery tracking."""
        failure.attempt = self.recovery_attempts + 1
        failure.modified_files = list(self.modified_files)
        self.failures.append(failure)

    def record_test_result(self, result: dict):
        """Record a test execution result."""
        self.test_results.append(result)

    def track_modified_file(self, filepath: str):
        """Track a file that was modified."""
        self.modified_files.add(filepath)

    def get_failure_signature_counts(self) -> dict[str, int]:
        """Count occurrences of each failure signature."""
        counts: dict[str, int] = {}
        for f in self.failures:
            if f.signature:
                counts[f.signature] = counts.get(f.signature, 0) + 1
        return counts

    def has_repeated_failure(self, signature: str, threshold: int = 2) -> bool:
        """Check if a failure signature has occurred >= threshold times."""
        counts = self.get_failure_signature_counts()
        return counts.get(signature, 0) >= threshold

    def set_state(self, new_state: str):
        """Transition to a new state."""
        valid_states = {
            "UNDERSTAND", "EXPLORE", "PLAN", "IMPLEMENT",
            "TEST", "VERIFY", "RECOVER", "DONE", "FAILED"
        }
        if new_state not in valid_states:
            raise ValueError(f"Invalid state: {new_state}. Valid: {valid_states}")
        self.current_state = new_state

    def build_prompt_context(self) -> str:
        """Build a prioritized context string for the model.
        
        Priority order:
        1. Current task
        2. Current state and plan  
        3. Relevant code / recent tool results
        4. Latest failure
        5. Recent tool results (older)
        6. Repository summary
        7. Older history
        """
        parts = []
        
        # 1. Task (always included)
        parts.append(f"## TASK\n{self.task}")
        
        # 2. Current state
        parts.append(f"## CURRENT STATE: {self.current_state}")
        parts.append(f"Iteration: {self.iteration}")
        parts.append(f"Recovery attempts: {self.recovery_attempts}")
        
        # Observations
        if self.observations:
            parts.append("## OBSERVATIONS")
            for obs in self.observations[-5:]:
                parts.append(f"- {obs}")
        
        # Plan
        if self.current_plan:
            parts.append("## CURRENT PLAN")
            for i, step in enumerate(self.current_plan, 1):
                parts.append(f"{i}. {step}")
        
        # 3. Relevant files
        if self.relevant_files:
            parts.append(f"## RELEVANT FILES\n" + "\n".join(self.relevant_files))
        
        # 4. Latest failure (high priority)
        if self.failures:
            latest = self.failures[-1]
            parts.append(f"## LATEST FAILURE")
            parts.append(f"Type: {latest.failure_type}")
            parts.append(f"Command: {latest.command}")
            parts.append(f"Exit code: {latest.exit_code}")
            # Truncate output if very long
            output = latest.output
            if len(output) > 2000:
                output = output[:1000] + "\n... [truncated] ...\n" + output[-1000:]
            parts.append(f"Output:\n{output}")
            parts.append(f"Attempt: {latest.attempt}")
            
            # Check for repeated failures
            if latest.signature:
                sig_counts = self.get_failure_signature_counts()
                count = sig_counts.get(latest.signature, 0)
                if count >= 2:
                    parts.append(
                        f"\n⚠️ WARNING: This failure has occurred {count} times. "
                        f"Your previous strategy FAILED. You MUST try a DIFFERENT approach."
                    )
        
        # 5. Recent tool results (last 5)
        if self.tool_results:
            parts.append("## RECENT TOOL RESULTS")
            for result in self.tool_results[-5:]:
                status = "✓" if result.success else "✗"
                output = result.output
                if len(output) > 1500:
                    output = output[:750] + "\n...[truncated]...\n" + output[-750:]
                parts.append(f"{status} {result.tool}({result.arguments})")
                if output:
                    parts.append(f"  Output: {output[:1500]}")
                if result.error:
                    parts.append(f"  Error: {result.error[:500]}")
        
        # Test results
        if self.test_results:
            parts.append("## TEST RESULTS")
            for tr in self.test_results[-3:]:
                parts.append(str(tr))
        
        # 6. Repository summary
        if self.repository_summary:
            summary = self.repository_summary
            if len(summary) > 2000:
                summary = summary[:2000] + "\n...[truncated]"
            parts.append(f"## REPOSITORY SUMMARY\n{summary}")
        
        # Modified files
        if self.modified_files:
            parts.append(f"## MODIFIED FILES\n" + "\n".join(sorted(self.modified_files)))
        
        # 7. Completed actions summary (compact)
        if self.completed_actions:
            recent = self.completed_actions[-10:]
            parts.append("## COMPLETED ACTIONS (recent)")
            for action in recent:
                parts.append(f"- {action}")
        
        return "\n\n".join(parts)

    def get_metrics(self) -> dict:
        """Return context metrics."""
        return {
            "iterations": self.iteration,
            "recovery_attempts": self.recovery_attempts,
            "files_inspected": len(self.relevant_files),
            "files_modified": len(self.modified_files),
            "tool_calls": len(self.tool_results),
            "test_runs": len(self.test_results),
            "failures": len(self.failures),
            "elapsed_time": round(time.time() - self.start_time, 1),
        }
