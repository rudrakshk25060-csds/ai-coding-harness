"""Verifier - ensures task completion with evidence before reporting success."""
from dataclasses import dataclass, field


@dataclass
class VerificationCheck:
    """A single verification check."""
    name: str
    passed: bool
    evidence: str = ""
    required: bool = True


@dataclass
class VerificationResult:
    """Complete verification result."""
    passed: bool = False
    checks: list = field(default_factory=list)
    failures: list = field(default_factory=list)
    evidence: list = field(default_factory=list)
    summary: str = ""


class Verifier:
    """Verifies that a task was actually completed correctly.
    
    Does not allow the harness to report DONE merely because
    the model says it is finished. Requires actual evidence.
    """

    def __init__(self, context):
        self.context = context

    def verify(self, finish_summary: str = "") -> VerificationResult:
        """Run all verification checks.
        
        Args:
            finish_summary: The model's summary of what it did.
            
        Returns:
            VerificationResult with pass/fail and evidence.
        """
        checks = []
        
        # Check 1: Tests were run
        tests_run = len(self.context.test_results) > 0
        last_test = self.context.test_results[-1] if self.context.test_results else {}
        checks.append(VerificationCheck(
            name="tests_executed",
            passed=tests_run,
            evidence=f"Test runs: {len(self.context.test_results)}",
            required=True,
        ))
        
        # Check 2: Tests passed (if tests were run)
        if tests_run:
            all_passed = last_test.get("all_passed", False)
            passed_count = last_test.get("passed", 0)
            failed_count = last_test.get("failed", 0)
            errors_count = last_test.get("errors", 0)
            evidence = f"Passed: {passed_count}, Failed: {failed_count}"
            if errors_count > 0:
                evidence += f", Errors: {errors_count}"
            checks.append(VerificationCheck(
                name="tests_passed",
                passed=all_passed,
                evidence=evidence,
                required=True,
            ))
        else:
            checks.append(VerificationCheck(
                name="tests_passed",
                passed=False,
                evidence="No tests were executed",
                required=True,
            ))
        
        # Check 3: Files were actually modified (if task required changes)
        has_modifications = len(self.context.modified_files) > 0
        checks.append(VerificationCheck(
            name="files_modified",
            passed=has_modifications,
            evidence=f"Modified: {sorted(self.context.modified_files) if has_modifications else 'none'}",
            required=False,  # Some tasks might be read-only
        ))
        
        # Check 4: No debugging leftovers
        debug_clean = self._check_no_debug_leftovers()
        checks.append(VerificationCheck(
            name="no_debug_leftovers",
            passed=debug_clean["clean"],
            evidence=debug_clean["evidence"],
            required=False,
        ))
        
        # Check 5: Git diff was inspected
        diff_inspected = any(
            r.tool == "git_diff" and r.success
            for r in self.context.tool_results
        )
        checks.append(VerificationCheck(
            name="diff_inspected",
            passed=diff_inspected,
            evidence="git_diff was called" if diff_inspected else "git_diff was NOT called",
            required=False,
        ))
        
        # Check 6: Only intended files changed
        only_intended = self._check_only_intended_files()
        checks.append(VerificationCheck(
            name="only_intended_changes",
            passed=only_intended["ok"],
            evidence=only_intended["evidence"],
            required=False,
        ))
        
        # Check 7: Finish summary provided
        checks.append(VerificationCheck(
            name="completion_summary",
            passed=bool(finish_summary and len(finish_summary) > 10),
            evidence=finish_summary[:200] if finish_summary else "No summary",
            required=False,
        ))
        
        # Compute overall result
        required_checks = [c for c in checks if c.required]
        required_passed = all(c.passed for c in required_checks)
        
        failures = [c.name for c in checks if not c.passed]
        evidence = [f"{c.name}: {c.evidence}" for c in checks]
        
        result = VerificationResult(
            passed=required_passed,
            checks=[{"name": c.name, "passed": c.passed, "evidence": c.evidence, "required": c.required} for c in checks],
            failures=failures,
            evidence=evidence,
            summary=self._build_summary(checks, required_passed),
        )
        
        return result

    def _check_no_debug_leftovers(self) -> dict:
        """Check modified files for debugging leftovers."""
        debug_patterns = ["breakpoint()", "import pdb", "pdb.set_trace()", "print('DEBUG", 'print("DEBUG']
        found = []
        
        for filepath in self.context.modified_files:
            # Read the file from tool results if available
            for result in reversed(self.context.tool_results):
                if result.tool == "read_file" and result.arguments.get("path") == filepath:
                    for pattern in debug_patterns:
                        if pattern in result.output:
                            found.append(f"{filepath}: {pattern}")
                    break
        
        return {
            "clean": len(found) == 0,
            "evidence": "No debug leftovers" if not found else f"Found: {found}",
        }

    def _check_only_intended_files(self) -> dict:
        """Check that only files related to the task were modified."""
        modified = self.context.modified_files
        relevant = set(self.context.relevant_files)
        
        if not modified:
            return {"ok": True, "evidence": "No files modified"}
        
        if not relevant:
            # Can't verify without knowing relevant files
            return {"ok": True, "evidence": f"Modified {len(modified)} file(s), relevance not tracked"}
        
        unrelated = modified - relevant
        if unrelated:
            return {
                "ok": False,
                "evidence": f"Potentially unrelated changes: {sorted(unrelated)}",
            }
        
        return {"ok": True, "evidence": f"All {len(modified)} modified files are relevant"}

    def _build_summary(self, checks: list, passed: bool) -> str:
        """Build a human-readable verification summary."""
        status = "✅ VERIFICATION PASSED" if passed else "❌ VERIFICATION FAILED"
        lines = [status]
        for c in checks:
            icon = "✓" if c.passed else "✗"
            req = " [REQUIRED]" if c.required else ""
            lines.append(f"  {icon} {c.name}{req}: {c.evidence}")
        return "\n".join(lines)
