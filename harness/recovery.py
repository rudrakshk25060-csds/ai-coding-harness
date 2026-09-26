"""Recovery system - handles failure diagnosis and recovery strategies."""
import hashlib
from harness.context import FailureRecord, ContextManager
from harness.config import MAX_RECOVERY_ATTEMPTS, MAX_SAME_ERROR


class RecoveryExhausted(Exception):
    """Raised when all recovery attempts are exhausted."""
    pass


class RecoveryManager:
    """Manages failure recovery for the coding agent.
    
    Tracks failures, detects repeated errors, and generates
    structured recovery prompts for the model.
    """

    def __init__(self, context: ContextManager):
        self.context = context

    def create_failure_record(
        self,
        failure_type: str,
        command: str = "",
        exit_code: int = -1,
        output: str = "",
    ) -> FailureRecord:
        """Create a structured failure record.
        
        Generates a signature for duplicate detection.
        """
        # Create a compact signature from failure type + key output lines
        sig_input = f"{failure_type}:{exit_code}"
        # Extract key error lines
        error_lines = []
        for line in output.split("\n"):
            line = line.strip()
            if any(kw in line.lower() for kw in ["error", "fail", "assert", "exception", "traceback"]):
                error_lines.append(line[:100])
        if error_lines:
            sig_input += ":" + "|".join(error_lines[:3])
        
        signature = hashlib.md5(sig_input.encode()).hexdigest()[:12]
        
        record = FailureRecord(
            failure_type=failure_type,
            command=command,
            exit_code=exit_code,
            output=output[:3000],  # Limit stored output
            signature=signature,
        )
        
        self.context.record_failure(record)
        return record

    def check_recovery_budget(self) -> bool:
        """Check if recovery attempts are still available."""
        return self.context.recovery_attempts < MAX_RECOVERY_ATTEMPTS

    def is_repeated_failure(self, record: FailureRecord) -> bool:
        """Check if this failure has occurred before with the same signature."""
        return self.context.has_repeated_failure(record.signature, MAX_SAME_ERROR)

    def build_recovery_prompt(self, record: FailureRecord) -> str:
        """Build a structured prompt asking the model to diagnose and fix.
        
        If the failure is repeated, explicitly requires a different strategy.
        """
        parts = [
            "## FAILURE RECOVERY REQUIRED",
            "",
            f"**Failure Type:** {record.failure_type}",
            f"**Command:** {record.command}",
            f"**Exit Code:** {record.exit_code}",
            f"**Attempt:** {record.attempt}",
            "",
            "**Output:**",
            record.output[:2000],
            "",
        ]
        
        if record.modified_files:
            parts.append(f"**Modified files:** {', '.join(record.modified_files)}")
            parts.append("")
        
        is_repeated = self.is_repeated_failure(record)
        
        if is_repeated:
            parts.extend([
                "⚠️ **REPEATED FAILURE DETECTED**",
                "This same error has occurred before. Your previous fix did NOT work.",
                "You MUST try a COMPLETELY DIFFERENT approach.",
                "Do NOT repeat the same change that already failed.",
                "",
                "Consider:",
                "- Is the root cause different from what you assumed?",
                "- Are you modifying the wrong file?",
                "- Is there a different API or approach to use?",
                "- Should you read more code to understand the context better?",
                "",
            ])
        
        parts.extend([
            "Please diagnose this failure. Respond with JSON:",
            "",
            "```json",
            "{",
            '  "diagnosis": {',
            '    "expected_behavior": "what should have happened",',
            '    "actual_behavior": "what actually happened",',
            '    "root_cause": "likely cause of the failure",',
            '    "issue_type": "code|test|environment|tool",',
            '    "requires_different_strategy": true/false',
            "  },",
            '  "action": {',
            '    "action": "tool_name",',
            '    "arguments": { ... }',
            "  }",
            "}",
            "```",
        ])
        
        return "\n".join(parts)

    def increment_recovery(self):
        """Increment recovery attempt counter."""
        self.context.recovery_attempts += 1

    def get_recovery_summary(self) -> dict:
        """Summarize recovery state."""
        sig_counts = self.context.get_failure_signature_counts()
        return {
            "total_attempts": self.context.recovery_attempts,
            "max_attempts": MAX_RECOVERY_ATTEMPTS,
            "budget_remaining": MAX_RECOVERY_ATTEMPTS - self.context.recovery_attempts,
            "total_failures": len(self.context.failures),
            "repeated_failures": sum(1 for c in sig_counts.values() if c >= MAX_SAME_ERROR),
            "unique_failure_types": len(sig_counts),
        }
