# AI Coding Harness

An autonomous, reliable, evidence-driven coding-agent harness with a **model-agnostic foundation-model interface** supporting Gemini, DeepSeek, and Qwen.

Designed for real-world software engineering tasks, the harness receives a problem statement, explores an existing codebase, plans minimal targeted changes, applies patches, runs tests, handles failures autonomously, and verifies the final result with concrete evidence before marking the task complete.

> **Correctness first. Evidence over claims. Efficiency matters.**

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
- [Model Providers](#model-providers)
- [Installation & Setup](#installation--setup)
- [How to Run](#how-to-run)
- [Running Tests](#running-tests)
- [Demo Walkthrough](#demo-walkthrough)
- [Known Limitations](#known-limitations)
- [Future Improvements](#future-improvements)
- [Project Structure](#project-structure)

---

## Why an Agent Harness?

Foundation models are powerful at code comprehension and generation, but raw model calls alone are not enough for reliable software engineering.

A coding agent needs to:

- Understand an unfamiliar repository before modifying it.
- Locate relevant files and symbols instead of guessing.
- Apply targeted changes rather than rewriting entire files.
- Execute tests and inspect real failures.
- Recover when an attempted fix does not work.
- Manage context so important information remains available.
- Verify the final result instead of trusting the model's claim of success.
- Avoid unsafe filesystem and secret-handling behavior.

Without these controls, coding agents can suffer from:

### Unbounded Hallucinations & Assumptions

Without active repository exploration, models may guess file paths, symbol names, APIs, or project conventions.

### False Success Claims

A model may declare a task fixed without actually running tests or inspecting the resulting diff.

### Looping on Failures

When a suggested fix fails, an unguided agent may repeatedly attempt the same ineffective strategy.

### Context Degradation

Dumping entire repositories or endless command output into the context window wastes tokens and hides the information that matters.

### Accidental Damage

Unconstrained tool execution can modify protected files, credentials, configuration, or unrelated parts of the repository.

### The AI Coding Harness

The harness addresses these problems through:

- A **bounded state machine** enforcing an Explore-Before-Modify and Test-Before-Done workflow.
- A **deterministic verifier** requiring concrete evidence before accepting completion.
- A **recovery manager** detecting repeated failures and encouraging strategy changes.
- A **safe tool suite** with repository-bound paths, secret suppression, targeted patching, and command timeouts.
- A **model-agnostic provider layer** allowing the orchestrator to work independently of a specific foundation-model vendor.
- **Context prioritization and truncation** to preserve useful information while controlling token usage.

---

## Architecture Overview

```text
                         ┌──────────────────────────┐
                         │       User / Task        │
                         └─────────────┬────────────┘
                                       │
                                       ▼
                         ┌──────────────────────────┐
                         │    Orchestrator Engine   │
                         └──────┬────────────▲──────┘
                                │            │
                   ┌────────────┴─┐       ┌─┴────────────┐
                   │ Context Mgr  │       │   Verifier   │
                   └────────────┬─┘       └──────▲───────┘
                                │                 │
                                ▼                 │ Evidence / Diff
                    ┌───────────────────────────────┐
                    │     Model Provider Adapter    │
                    │       ModelAdapter API        │
                    └──────────────┬────────────────┘
                                   │
                 ┌─────────────────┼─────────────────┐
                 │                 │                 │
                 ▼                 ▼                 ▼
          ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
          │   Gemini    │   │  DeepSeek   │   │    Qwen     │
          │ gemini-3.8  │   │ OpenAI-     │   │ OpenAI-     │
          │   -flash    │   │ compatible  │   │ compatible  │
          └──────┬──────┘   └──────┬──────┘   └──────┬──────┘
                 │                 │                 │
                 └─────────────────┼─────────────────┘
                                   │ Tool Calls
                                   ▼
                         ┌──────────────────────────┐
                         │      Tool Executor       │
                         ├──────────────────────────┤
                         │ • list_files             │
                         │ • search_code            │
                         │ • read_file              │
                         │ • apply_patch            │
                         │ • run_command            │
                         │ • run_tests               │
                         │ • git_diff                │
                         │ • git_status              │
                         │ • finish                  │
                         └────────────┬─────────────┘
                                      │
                              Failure / Error
                                      ▼
                         ┌──────────────────────────┐
                         │     Recovery Manager     │
                         │ Signature matching &      │
                         │ strategy alteration      │
                         └──────────────────────────┘
```

The core orchestrator is **provider-agnostic**. Model-specific SDK and API behavior is isolated behind the `ModelAdapter` interface.

This allows the same coding-agent logic to operate with different foundation models without changing the orchestration, context, tools, recovery, or verification layers.

---

## State Machine

The harness executes an explicit, bounded state machine:

```text
[UNDERSTAND]
      │
      ▼
[EXPLORE]
      │
      ▼
[PLAN]
      │
      ▼
[IMPLEMENT]
      │
      ▼
[TEST] ───────────────┐
      │               │
      ▼               │ FAIL
[VERIFY]              │
      │               ▼
      │           [RECOVER]
      │               │
      │               └──────────► [IMPLEMENT]
      │
      ▼
   [DONE]
```

### States

**UNDERSTAND**

Analyze the task description, identify the likely target area, and understand the repository structure.

**EXPLORE**

Inspect relevant files, search for symbols, understand relationships, and locate existing tests.

**PLAN**

Formulate specific, minimal changes required to resolve the issue without unnecessary modifications.

**IMPLEMENT**

Apply targeted modifications using `apply_patch` rather than blind full-file rewrites.

**TEST**

Execute the available test suite and inspect real pass/fail output.

**RECOVER**

When tests or commands fail, classify the failure and guide the model toward a different corrective strategy when repeated failures are detected.

**VERIFY**

Require evidence such as successful tests, diff inspection, intended changes, and absence of debugging leftovers.

**DONE**

Exit successfully with structured run metrics and an evidence summary.

### Bounds & Guardrails

```text
MAX_ITERATIONS = 12
MAX_RECOVERY_ATTEMPTS = 4
MAX_SAME_ERROR = 2
```

These limits prevent uncontrolled agent loops and force the system to reconsider its strategy when it repeatedly encounters the same failure.

---

## Tool System

All tools return a consistent dictionary structure:

```python
{
    "success": True,
    "output": "...",
    "error": "",
    "metadata": {}
}
```

### Implemented Tools

| Tool | Purpose |
|---|---|
| `list_files(path=".")` | Lists repository files while excluding common generated/protected directories |
| `search_code(query, path=".")` | Searches source files for symbols, strings, or patterns |
| `read_file(path)` | Reads a file with output bounds |
| `apply_patch(path, original, replacement)` | Performs targeted search-and-replace modifications |
| `run_command(command)` | Executes repository commands with safety checks and timeouts |
| `run_tests(test_path="")` | Runs pytest and parses test results |
| `git_diff()` | Inspects staged and unstaged changes |
| `git_status()` | Inspects repository state |
| `finish(summary)` | Requests final verification through the verifier |

The tool layer is deliberately narrow: the model gets enough capability to investigate, modify, test, and verify a repository without unrestricted access to the entire environment.

---

## Context Management

Context-window pollution is a major failure mode for LLM-based coding agents.

`harness/context.py` organizes information into priority tiers.

### Context Priority

1. **Task & State**
   - Current objective
   - Current state
   - Iteration number

2. **Current Plan & Recent Observations**
   - Current hypothesis
   - Planned next step
   - Recent discoveries

3. **Relevant Files**
   - Files inspected
   - Files identified as relevant to the task

4. **Latest Failure Details**
   - Error type
   - Exit code
   - Relevant traceback information

5. **Repeated Failure Warnings**
   - High-visibility warning when an error signature repeats

6. **Recent Tool History**
   - Recent tool calls
   - Concise, truncated outputs

7. **Modified Files**
   - Exact files changed during the session

Old tool outputs and redundant tracebacks are truncated or pruned to preserve context for reasoning.

---

## Recovery Strategy

When a tool fails or tests do not pass, `harness/recovery.py` takes over.

### Signature Hashing

Failures are converted into signatures using relevant failure information such as:

- Failure type
- Exit code
- Key traceback lines

### Repetition Detection

The recovery manager tracks repeated failure signatures.

When the same failure reaches `MAX_SAME_ERROR`, the agent is explicitly instructed to change strategy.

```text
⚠️ REPEATED FAILURE DETECTED

This same error has occurred before.
Your previous fix did NOT work.
You MUST try a COMPLETELY DIFFERENT approach.
```

### Structured Diagnosis

Recovery encourages the model to reason through:

```text
Expected behavior
Actual behavior
Root cause classification
Smallest corrective action
Verification strategy
```

This prevents the agent from blindly repeating an unsuccessful patch.

---

## Verification Strategy

The harness uses `harness/verifier.py` as a final accountability gate.

An agent cannot complete a task simply by responding:

```text
"I am done."
```

The verifier checks concrete execution evidence.

| Check | Required | Description |
|---|---:|---|
| `tests_executed` | Yes | Test runner was invoked |
| `tests_passed` | Yes | Executed tests passed without failures/errors |
| `files_modified` | No | Tracks intended modifications |
| `no_debug_leftovers` | No | Detects common debugging leftovers |
| `diff_inspected` | No | Confirms the final diff was reviewed |
| `only_intended_changes` | No | Checks that modifications remain within relevant files |
| `completion_summary` | No | Confirms a meaningful completion summary |

If required checks fail, completion is rejected and the failure is fed back into the agent context for further testing or recovery.

This creates a fundamental rule:

> **The model's claim is not the evidence. The repository state is the evidence.**

---

## Safety & Sandboxing

The harness includes several safeguards around repository operations.

### Repository Boundary Enforcement

`_safe_path` resolves paths canonically and prevents directory traversal outside the target repository.

Attempts such as:

```text
../../some-file
```

are rejected when they escape the repository boundary.

### Protected Files

Access or modification of sensitive files such as:

```text
.env
.git/config
credentials
```

is restricted.

### Secret Leak Prevention

Shell commands attempting to print sensitive API-key environment variables are blocked before execution.

API keys should never be committed to the repository or included in model/tool output.

### Process Timeouts

Commands and test runs have configurable timeouts to prevent hangs and uncontrolled execution.

### Output Truncation

Large command and file outputs are truncated to prevent catastrophic context/token consumption.

---

## Efficiency & Context Economy

The harness is designed to make model usage efficient as well as correct.

### Minimal Model Calls

Deterministic state transitions and tool execution reduce unnecessary model round trips.

### Surgical Patching

`apply_patch` allows the agent to modify only the required portion of a file rather than repeatedly sending entire files through the model context.

### Compact Actions

The model communicates tool actions through a compact structured action protocol.

### Bounded Execution

Iteration, recovery, command, and test limits prevent runaway execution.

The objective is not simply to make the model capable of solving a task, but to make the entire agent loop **reliable, measurable, and efficient**.

---

## Model Providers

The harness uses a provider abstraction so the core orchestration logic does not depend on a particular model vendor.

### Supported Providers

| Provider | Integration | Development Validation |
|---|---|---|
| Gemini | `google-genai` | Live-tested |
| DeepSeek | OpenAI-compatible API adapter | Mocked adapter/API tests |
| Qwen | OpenAI-compatible API adapter | Mocked adapter/API tests |

### Provider Selection

The provider can be selected through configuration or the command line.

Example:

```env
MODEL_PROVIDER=gemini
```

or:

```bash
python main.py --provider gemini "Task description"
```

The same orchestrator is intended to work with different supported providers.

### Development Validation

Gemini connectivity was live-tested locally using:

```bash
python test_gemini.py
```

DeepSeek and Qwen were validated through the provider abstraction and mocked API tests during development. Live DeepSeek/Qwen credentials were not used for local validation.

This distinction is intentional: the project does not claim live testing for providers that were not actually tested with live credentials.

---

## Installation & Setup

### Prerequisites

- macOS or Linux
- Python 3.10+
- Git
- API credentials for the model provider you want to use

The project was developed and tested with Python 3.14.

### Clone the Repository

```bash
git clone https://github.com/rudrakshk25060-csds/ai-coding-harness.git
cd ai-coding-harness
```

### Quickstart with Makefile

The project includes a standard `Makefile` for one-command evaluation:

```bash
# 1. Install all dependencies (creates .venv if needed)
make setup

# 2. Run the complete unit test suite (offline, no API key needed)
make test

# 3. Start the harness on the demo repository
make run

# 4. Clean build and cache artifacts
make clean
```

You can also pass custom tasks or arguments to `make run`:

```bash
make run ARGS='--provider deepseek "Fix the bug in examples/demo_repo and verify it with tests"'
```

---

### Manual Setup & Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

### Environment Variables & Evaluator Configuration

Create a `.env` file in the project root or export variables in your shell.

#### Generic Evaluator Key (`AI_API_KEY`)
The harness supports **`AI_API_KEY`** as a universal generic key. If the evaluator supplies `AI_API_KEY`, the harness automatically routes it to whichever model provider is selected (`gemini`, `deepseek`, or `qwen`):

```env
# Evaluator generic API key (acts as fallback for any provider)
AI_API_KEY=your_evaluator_api_key_here

# Selected model provider (gemini, deepseek, or qwen)
MODEL_PROVIDER=deepseek
```

#### Provider-Specific Configuration

| Variable | Description | Default |
|---|---|---|
| `MODEL_PROVIDER` | Active foundation model provider (`gemini`, `deepseek`, `qwen`) | `gemini` |
| `AI_API_KEY` | Generic evaluator API key (fallback for any provider) | *(none)* |
| `GEMINI_API_KEY` | Google Gemini API key | *(falls back to `AI_API_KEY`)* |
| `GEMINI_MODEL` | Gemini model name | `gemini-3.8-flash` |
| `DEEPSEEK_API_KEY` | DeepSeek API key | *(falls back to `AI_API_KEY`)* |
| `DEEPSEEK_MODEL` | DeepSeek model name | `deepseek-flash` |
| `DEEPSEEK_BASE_URL` | DeepSeek API base URL | `https://api.deepseek.com/v1` |
| `QWEN_API_KEY` | Qwen API key | *(falls back to `AI_API_KEY`)* |
| `QWEN_MODEL` | Qwen model name | `qwen-turbo` |
| `QWEN_BASE_URL` | Qwen API base URL | `https://dashscope.aliyuncs.com/compatible-mode/v1` |

#### Key Precedence
```text
Provider-Specific Key (e.g. DEEPSEEK_API_KEY)
       ↓ (if not set)
Generic Key (AI_API_KEY)
```

A safe template is provided in `.env.example`.

### Security Note

`.env` is strictly excluded through `.gitignore`.

**Never commit API keys, tokens, credentials, or other secrets to Git.**

---

## How to Run

### Using Make

```bash
# Run default demo task
make run

# Run custom task with arguments
make run ARGS='--repo examples/demo_repo "Fix the bug and verify with tests"'
```

### Direct Invocation

```bash
python main.py [--repo /path/to/repo] "Task description"
```

### Example

```bash
python main.py "Fix the bug in examples/demo_repo and verify it with tests"
```

### Specify a Provider

```bash
python main.py --provider gemini "Fix the bug in examples/demo_repo and verify it with tests"
```

The provider can also be selected through:

```env
MODEL_PROVIDER=gemini
```

---

## Running Tests

Run the complete unit test suite:

```bash
make test
# OR directly:
python -m pytest -q
```

The current test suite contains **63 tests** covering the core harness components.

### Test Coverage

```text
test_config.py
    Configuration parsing, execution bounds, and secret-related safeguards.

test_context.py
    State transitions, context prioritization, and failure tracking.

test_tools.py
    Path traversal protection, safe command execution, search,
    patch application, and tool error handling.

test_recovery.py
    Failure signature generation, recovery budgets,
    repeated-failure detection, and recovery prompting.

test_orchestrator.py
    State-machine behavior, verifier gates, rejected early completion,
    and orchestration transitions.

test_model_adapters.py
    Provider abstraction, provider factory,
    Gemini/DeepSeek/Qwen adapters, and mocked API behavior.
```

Expected result:

```text
72 passed
```

### Live Gemini Connection Test

To verify Gemini credentials and connectivity:

```bash
python test_gemini.py
```

---

## Demo Walkthrough

The repository includes a deliberately small demonstration project:

```text
examples/demo_repo/
├── calculator.py
└── test_calculator.py
```

### Initial Bug

`calculator.py` contains a deliberate bug:

```python
def multiply(a, b):
    # BUG: This should be a * b, not a + b
    return a + b
```

The corresponding test expects:

```python
multiply(3, 4) == 12
```

and initially fails because the buggy implementation produces:

```text
7
```

### Execution Flow

The harness receives:

```text
Fix the bug in examples/demo_repo and verify it with tests
```

#### 1. UNDERSTAND

The orchestrator initializes the task context and identifies the repository.

#### 2. EXPLORE

The model uses repository tools to discover:

```text
calculator.py
test_calculator.py
```

#### 3. PLAN

The model identifies the incorrect multiplication implementation and plans a minimal change.

#### 4. IMPLEMENT

The model uses `apply_patch` to replace:

```python
return a + b
```

with:

```python
return a * b
```

#### 5. TEST

The harness runs the test suite again.

The corrected implementation passes the demo tests.

#### 6. VERIFY

The harness inspects the Git diff to confirm that the intended change was made and that there are no unrelated modifications or debugging leftovers.

#### 7. DONE

The verifier accepts the task only after the required evidence checks succeed.

This demonstrates the central design principle of the project:

```text
Model proposes → Tools execute → Tests provide evidence → Verifier decides
```

---

## Known Limitations

### Complex Merge Conflicts

`apply_patch` currently performs targeted string replacement. Highly repetitive code may require unique anchors to avoid ambiguous replacements.

### Interactive Prompts

Shell commands that require interactive user input, such as password prompts or `read` operations, may time out.

### Single-Agent Scope

The current architecture is designed as an efficient deterministic **single-agent harness**, rather than a multi-agent debate or swarm framework.

### Provider Credentials

Different providers require their own credentials and API availability. Provider adapters can be tested independently through mocks, but live provider validation requires valid credentials and network access.

### Language Coverage

The current testing workflow is centered around Python/pytest repositories.

---

## Future Improvements

### AST-Aware Patching

Introduce syntax-aware refactoring using Python's `ast` module for safer language-level modifications.

### Multi-File Git Staging

Support progressive branch creation, checkpoints, and rollback for speculative multi-file changes.

### Test Matrix Generation

Automatically generate additional edge-case tests before accepting an issue fix.

### Multi-Language Support

Add test-runner adapters for:

```text
Cargo / Rust
Go
Jest / JavaScript
Maven / Java
```

### Improved Context Compression

Introduce more advanced summarization and long-horizon memory strategies for larger repositories.

### Provider-Level Evaluation

Run the same benchmark tasks across multiple supported foundation models and compare:

- Correctness
- Number of model calls
- Tool calls
- Test runs
- Recovery attempts
- Files inspected
- Files modified
- Total execution time

---

## Project Structure

```text
ai-coding-harness/
│
├── harness/
│   ├── __init__.py
│   ├── config.py
│   ├── model.py
│   ├── context.py
│   ├── tools.py
│   ├── recovery.py
│   ├── verifier.py
│   └── orchestrator.py
│
├── tests/
│   ├── __init__.py
│   ├── test_config.py
│   ├── test_context.py
│   ├── test_tools.py
│   ├── test_recovery.py
│   ├── test_orchestrator.py
│   └── test_model_adapters.py
│
├── examples/
│   └── demo_repo/
│       ├── calculator.py
│       └── test_calculator.py
│
├── main.py
├── Makefile
├── requirements.txt
├── test_gemini.py
├── pytest.ini
├── .env.example
├── .gitignore
└── README.md
```

---

## Design Summary

The harness is built around a simple principle:

```text
                 ┌──────────────────┐
                 │   Problem Task   │
                 └────────┬─────────┘
                          ▼
                 ┌──────────────────┐
                 │   Orchestrator   │
                 └────────┬─────────┘
                          ▼
                 ┌──────────────────┐
                 │ Context Manager  │
                 └────────┬─────────┘
                          ▼
                 ┌──────────────────┐
                 │  Model Adapter   │
                 └────────┬─────────┘
                          ▼
                 ┌──────────────────┐
                 │      Tools       │
                 └────────┬─────────┘
                          ▼
                 ┌──────────────────┐
                 │      Tests       │
                 └────────┬─────────┘
                          ▼
                 ┌──────────────────┐
                 │ Recovery / Retry │
                 └────────┬─────────┘
                          ▼
                 ┌──────────────────┐
                 │     Verifier     │
                 └────────┬─────────┘
                          ▼
                 ┌──────────────────┐
                 │ Verified Result  │
                 └──────────────────┘
```

The foundation model provides reasoning and code-generation capability.

The harness provides the engineering discipline around that model:

**exploration → planning → targeted modification → testing → recovery → verification.**

The result is an autonomous coding workflow that prioritizes **correctness, evidence, bounded execution, and model independence**.

---

## Hackathon Evaluation Focus

The architecture is intentionally designed around the core requirements of an autonomous coding-agent harness:

- Repository understanding
- Tool-based code navigation
- Context management
- Model orchestration
- Targeted code modification
- Automated testing
- Failure recovery
- Deterministic verification
- Safety boundaries
- Bounded execution
- Provider independence
- Measurable execution metrics

The same harness architecture can therefore be evaluated with different foundation models without changing the core agent loop.

---

## License

This project was created as part of the **LCC × DevClub AI Coding Harness Hackathon**.
