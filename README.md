# AI Coding Harness

An autonomous, reliable, and evidence-driven coding-agent harness powered by Google Gemini.

Designed for real-world software engineering tasks, the harness receives a problem statement, explores a target codebase, plans minimal targeted changes, applies patches, runs test suites, handles test and execution failures autonomously, and verifies the resolution with rigorous evidence checks before marking the task complete.

---

## Table of Contents
- [Why an Agent Harness?](#why-an-agent-harness)
- [Architecture Overview](#architecture-overview)
- [State Machine](#state-machine)
- [Tool System](#tool-system)
- [Context Management](#context-management)
- [Recovery Strategy](#recovery-strategy)
- [Verification Strategy](#verification-strategy)
- [Safety & Sandboxing](#safety--sandboxing)
- [Efficiency & Context Economy](#efficiency--context-economy)
- [Installation & Setup](#installation--setup)
- [How to Run](#how-to-run)
- [Running Tests](#running-tests)
- [Demo Walkthrough](#demo-walkthrough)
- [Known Limitations](#known-limitations)
- [Future Improvements](#future-improvements)

---

## Why an Agent Harness?

Foundation models like Gemini possess extraordinary code comprehension and generation abilities. However, raw model calls alone cannot reliably solve engineering issues because:
1. **Unbounded Hallucinations & Assumptions:** Without active repository exploration, models guess file paths, symbol names, and API conventions.
2. **False Success Claims:** Models frequently declare a task "fixed" without running tests or inspecting actual git diffs.
3. **Looping on Failures:** When a suggested fix fails, unguided models often repeat the identical flawed patch repeatedly.
4. **Context Degradation:** Dumping entire repositories or endless test outputs into the prompt window drowns out the relevant code and wastes tokens.
5. **Accidental Damage:** Unconstrained tool execution can overwrite critical configs (like `.env` or `.git`) or make uncontrolled filesystem modifications.

The **AI Coding Harness** solves these problems by providing:
- A strict **State Machine** enforcing an Explore-Before-Modify and Test-Before-Done workflow.
- A **Deterministic Verifier** requiring concrete evidence (passing tests, clean diffs, no leftover debug breakpoints) before accepting completion.
- A **Recovery Manager** detecting repeated failure signatures and mandating alternative strategies.
- A **Safe Tool Suite** with path sandboxing, secret suppression, and targeted line-level patching.

---

## Architecture Overview

```
                          ┌──────────────────────────┐
                          │       User / Task        │
                          └─────────────┬────────────┘
                                        │
                                        ▼
                          ┌──────────────────────────┐
                          │   Orchestrator Engine    │
                          └──────┬────────────▲──────┘
                                 │            │
                     ┌───────────┴─┐        ┌─┴────────────┐
                     │ Context Mgr │        │   Verifier   │
                     └───────────┬─┘        └─▲────────────┘
                                 │            │ Evidence / Diff
                                 ▼            │
                      ┌───────────────────────┴──┐
                      │ Gemini Foundation Model  │
                      │   (gemini-3.8-flash)     │
                      └──────────┬───────────────┘
                                 │ Tool Calls (JSON)
                                 ▼
                      ┌──────────────────────────┐
                      │      Tool Executor       │
                      ├──────────────────────────┤
                      │ • list_files             │
                      │ • search_code            │
                      │ • read_file              │
                      │ • apply_patch            │
                      │ • run_command            │
                      │ • run_tests (pytest)     │
                      │ • git_diff / git_status  │
                      └──────────┬───────────────┘
                                 │ Failure / Error
                                 ▼
                      ┌──────────────────────────┐
                      │     Recovery Manager     │
                      │  (Signature matching &   │
                      │  Strategy alteration)    │
                      └──────────────────────────┘
```

The system is strictly modularized under `harness/`:
- `harness/config.py`: Environment configuration, execution bounds, safety rules.
- `harness/model.py`: Provider-agnostic foundation model wrapper isolating `google-genai` SDK details and structured JSON extraction.
- `harness/context.py`: Multi-tier context manager maintaining plan state, observations, tool outcomes, and token-efficient prompt synthesis.
- `harness/tools.py`: Path-sandboxed tools for file reading, targeted patching, code search, testing, and git inspection.
- `harness/recovery.py`: Failure classification, MD5 signature hashing, duplicate error detection, and strategic redirection.
- `harness/verifier.py`: Gatekeeper ensuring tasks cannot pass without passing test runs and diff verification.
- `harness/orchestrator.py`: State machine execution loop with bounded iterations.

---

## State Machine

The harness executes an explicit, bounded state machine:

```
[UNDERSTAND] ────► [EXPLORE] ────► [PLAN] ────► [IMPLEMENT] ────► [TEST] ────► [VERIFY] ────► [DONE]
                                                      ▲             │
                                                      │    FAIL     │
                                                      └─ [RECOVER] ◄┘
```

### States
1. **UNDERSTAND:** Analyze the task description, identify target modules, and examine repo structure.
2. **EXPLORE:** Inspect relevant files, search for symbols, understand caller relationships and existing tests.
3. **PLAN:** Formulate specific, minimal changes required to resolve the issue without collateral breakages.
4. **IMPLEMENT:** Apply targeted modifications using `apply_patch` (never full blind rewrites).
5. **TEST:** Execute the pytest suite to observe pass/fail status and examine test output.
6. **RECOVER:** If tests or commands fail, analyze root causes and enforce an alternate fix strategy if repeated.
7. **VERIFY:** Require a clean diff review, verify all tests pass, ensure no debugging leftovers exist, and log evidence.
8. **DONE:** Exit successfully with structured run metrics and evidence summary.

### Bounds & Guardrails
- `MAX_ITERATIONS = 12`: Halts infinite loops if an agent cannot converge.
- `MAX_RECOVERY_ATTEMPTS = 4`: Limits retries when a bug resists automated repair.
- `MAX_SAME_ERROR = 2`: Flags duplicate error signatures and explicitly warns the model to pivot.

---

## Tool System

All tools in `harness/tools.py` return a consistent dictionary structure:
```json
{
  "success": true,
  "output": "...",
  "error": "",
  "metadata": {}
}
```

### Implemented Tools
- `list_files(path=".")`: Lists project files excluding `.git`, `__pycache__`, `.venv`, and `node_modules`.
- `search_code(query, path=".")`: Fast text and regex search with match limits across project files.
- `read_file(path)`: Reads file contents with character bounds to prevent context flooding.
- `apply_patch(path, original, replacement)`: Surgical search-and-replace modification. Guarantees that only targeted text is modified, tracking touched files in the context.
- `run_command(command, timeout=30)`: Safely executes shell commands in the repository directory with environment protection.
- `run_tests(test_path="", timeout=60)`: Executes pytest via the environment's Python interpreter, automatically parsing passed, failed, and error counts.
- `git_diff()`: Returns unstaged and staged changes.
- `git_status()`: Returns compact working tree status.
- `finish(summary)`: Triggers the Verifier check to conclude the task.

---

## Context Management

Context window pollution is a primary failure mode for LLM agents. `harness/context.py` structures context into strict priority tiers:

1. **Task & State (Highest Priority):** Current objective, iteration index, and active phase.
2. **Current Plan & Recent Observations:** Hypotheses and next steps.
3. **Relevant Files:** Files inspected and known to be related to the task.
4. **Latest Failure Details:** Exact error type, command, exit code, and truncated traceback.
5. **Repeated Failure Warnings:** High-visibility banner when a failure signature recurs.
6. **Recent Tool History:** Last 5 tool invocations with concise truncated outputs.
7. **Modified Files Tracker:** Exact set of files altered during the session.

Old tool outputs and redundant tracebacks are pruned or truncated, preserving token budget for reasoning.

---

## Recovery Strategy

When a tool fails or tests do not pass, `harness/recovery.py` takes over:

1. **Signature Hashing:** Computes an MD5 signature from the failure type, exit code, and key traceback lines.
2. **Repetition Detection:** Tracks the frequency of each error signature.
3. **Strategy Inversion:** If an error occurs $\ge 2$ times (`MAX_SAME_ERROR`), the recovery manager injects a directive:
   > `⚠️ REPEATED FAILURE DETECTED: This same error has occurred before. Your previous fix did NOT work. You MUST try a COMPLETELY DIFFERENT approach.`
4. **Structured Diagnosis:** Guides the model to output:
   - Expected behavior
   - Actual behavior
   - Root cause classification (code, test, environment, or tool)
   - Smallest possible corrective action

---

## Verification Strategy

The harness enforces strict accountability via `harness/verifier.py`. An agent cannot conclude simply by outputting "I am done". When `finish` is invoked, the Verifier executes these checks:

| Check | Required? | Description |
|---|:---:|---|
| `tests_executed` | **Yes** | Test runner was invoked at least once. |
| `tests_passed` | **Yes** | All executed tests passed with zero failures or errors. |
| `files_modified` | No | Tracks that intended modifications took place. |
| `no_debug_leftovers` | No | Scans diffs for `breakpoint()`, `pdb.set_trace()`, or debug print logs. |
| `diff_inspected` | No | Confirms the model reviewed `git_diff` prior to finishing. |
| `only_intended_changes` | No | Validates modified files are within the identified relevant files. |
| `completion_summary` | No | Validates a detailed summary was provided. |

If required checks fail, completion is rejected, the failure reasons are logged into the agent context, and the agent is transitioned back to `TEST` or `RECOVER`.

---

## Safety & Sandboxing

1. **Repository Boundary Enforcement:** `_safe_path` checks canonical paths using `Path.resolve()`. Any path attempting directory traversal (`../../`) outside the repository triggers a `ToolError`.
2. **Protected Files:** Access or modification to `.env`, `.git/config`, and credentials is strictly prohibited.
3. **Secret Leak Prevention:** Shell commands attempting to echo or print environment variables containing `API_KEY` are blocked prior to execution.
4. **Process Timeouts:** All shell and test commands are bounded by configurable timeouts (30s default for commands, 60s for tests) to prevent hang-ups on blocking input or infinite loops.
5. **Output Truncation:** Command and file outputs are capped (`MAX_OUTPUT_CHARS = 8000`, `MAX_FILE_CHARS = 12000`) to protect against catastrophic token exhaustion.

---

## Efficiency & Context Economy

- **Minimal Model Calls:** Deterministic state machine checks and automatic tool execution avoid wasted LLM ping-pong round-trips.
- **Surgical Patching:** `apply_patch` eliminates the need to stream entire file contents back and forth across API calls.
- **Compact JSON Actions:** Single-action JSON protocol minimizes output token generation latency.

---

## Installation & Setup

### Prerequisites
- macOS or Linux
- Python 3.10+ (tested on Python 3.14)
- Git

### Setup
```bash
# Clone the repository
git clone <repo-url> ai-coding-harness
cd ai-coding-harness

# Activate existing virtual environment (or create one)
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt # (google-genai, python-dotenv, pytest)
```

### Configuration (`.env`)
Create a `.env` file in the root directory:
```env
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-3.8-flash
```

> **Security Note:** `.env` is ignored by Git in `.gitignore`. Never commit or log your API key.

---

## How to Run

### Command Syntax
```bash
# General invocation
python main.py [--repo /path/to/repo] "Task description"

# Run on the included demo repository
python main.py "Fix the bug in examples/demo_repo and verify it with tests"
```

---

## Running Tests

### Unit Test Suite
The harness includes a comprehensive suite of 36 unit tests covering all components with mocked models:
```bash
python -m pytest -q
```

Coverage includes:
- `test_config.py`: Configuration parsing, boundary constants, and secret suppression.
- `test_context.py`: State transitions, priority context compilation, signature counting.
- `test_tools.py`: Path traversal protection, safe execution, search, patch application, and error boundaries.
- `test_recovery.py`: Failure signature generation, budget checks, and repeated failure prompting.
- `test_orchestrator.py`: Verifier gates, rejected early finish, and state machine transitions.

### Live Gemini Connection Test
Verify API credentials and foundation model connectivity:
```bash
python test_gemini.py
```

---

## Demo Walkthrough

The harness includes a demo repository at `examples/demo_repo`:
- `calculator.py`: Contains a deliberate bug in `multiply(a, b)`:
  ```python
  def multiply(a, b):
      # BUG: This should be a * b, not a + b
      return a + b
  ```
- `test_calculator.py`: Unit test verifying `multiply(3, 4) == 12`, which initially fails with `assert 7 == 12`.

### Execution Flow
1. Harness initializes context with task: `"Fix the bug in examples/demo_repo and verify it with tests"`.
2. State `UNDERSTAND` ➔ Model executes `list_files` to discover `calculator.py` and `test_calculator.py`.
3. State `EXPLORE` ➔ Model runs `run_tests` and observes the failing assertion (`assert 7 == 12`).
4. State `PLAN` / `IMPLEMENT` ➔ Model reads `calculator.py` and calls `apply_patch` replacing `return a + b` with `return a * b`.
5. State `TEST` ➔ Model runs `run_tests` which now passes (4/4 tests passed).
6. State `VERIFY` ➔ Model runs `git_diff` to ensure only the intended 1-line change occurred.
7. Model calls `finish`. The Verifier validates passing tests, inspects diff evidence, and transitions to `DONE`.

---

## Known Limitations

- **Complex Merge Conflicts:** `apply_patch` performs single-occurrence string replacement. Highly repetitive boilerplate code requires unique anchor lines to avoid ambiguous replacements.
- **Interactive Prompts:** Shell commands that prompt for user input (e.g. `read -p`, password prompts) will trigger command timeouts.
- **Single-Agent Scope:** Designed specifically as an efficient, deterministic single-agent harness rather than a multi-agent debate framework.

---

## Future Improvements

- **AST-Aware Patching:** Syntax-aware refactoring tools using Python's `ast` module for language-level surgical modifications.
- **Multi-File Git Staging:** Support for progressive branch creation and rollback checkpoints for speculative edits.
- **Test Matrix Generation:** Automatically synthesizing new edge-case tests before accepting an issue fix.
- **Multi-Language Support:** Adding test runner adapters for Cargo, Go, Jest, and Maven.
