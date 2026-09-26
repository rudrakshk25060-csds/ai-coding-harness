#!/usr/bin/env python3
"""AI Coding Harness - Autonomous coding agent entry point.

Usage:
    # Run on the built-in demo repo
    python main.py "Fix the bug in examples/demo_repo and run the tests"

    # Run on ANY real repository
    python main.py --repo /path/to/your/project "Fix the failing tests"
    python main.py --repo ~/projects/myapp "Refactor the login module and verify tests"
    python main.py --repo . "Find and fix the bug causing test_payment to fail"

    # Customize iteration budget
    python main.py --repo /path/to/repo --max-iterations 20 "Complex refactoring task"
"""
import sys
import os
import argparse

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness.config import validate_config, get_config_summary
from harness.model import create_model_provider, GeminiModel
from harness.orchestrator import Orchestrator


def main():
    """Main entry point for the AI coding harness."""
    parser = argparse.ArgumentParser(
        description="AI Coding Harness — Autonomous coding agent powered by Gemini",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Built-in demo (fix a deliberate calculator bug)
  python main.py "Fix the bug in examples/demo_repo and verify with tests"

  # Point at any real repository on disk
  python main.py --repo /path/to/project "Fix the failing test_login test"
  python main.py --repo ~/my-app "Refactor utils.py and make sure all tests pass"
  python main.py --repo . "Find and fix the bug in the payment module"

  # Increase iteration budget for complex tasks
  python main.py --repo /path/to/repo --max-iterations 20 "Large refactor task"
        """,
    )
    parser.add_argument(
        "task",
        help="Description of the coding task to perform (in quotes)",
    )
    parser.add_argument(
        "--repo",
        default=None,
        help="Path to the target repository (default: auto-detect from task, or current harness dir)",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="Override max agent iterations (default: 12)",
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="Model provider: gemini, deepseek, or qwen (default: from MODEL_PROVIDER env or gemini)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model name override (e.g. gemini-3.8-flash, deepseek-flash, qwen-turbo)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed tool output during execution",
    )

    args = parser.parse_args()
    task = args.task
    repo_path = args.repo
    provider = args.provider

    # Determine repo path
    if repo_path is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        if "demo_repo" in task or "demo" in task.lower():
            repo_path = os.path.join(script_dir, "examples", "demo_repo")
        else:
            # Default to project root (where main.py lives)
            repo_path = script_dir
    
    repo_path = os.path.abspath(os.path.expanduser(repo_path))

    if not os.path.isdir(repo_path):
        print(f"Error: Repository path does not exist: {repo_path}")
        sys.exit(1)

    # Validate configuration for the active provider
    try:
        validate_config(provider=provider)
    except RuntimeError as e:
        print(f"Configuration error: {e}")
        print("\nTo configure, set the appropriate variables in your .env file:")
        print("  MODEL_PROVIDER=gemini | deepseek | qwen")
        print("  GEMINI_API_KEY=... / DEEPSEEK_API_KEY=... / QWEN_API_KEY=...")
        sys.exit(1)

    config = get_config_summary(provider=provider)
    print(f"Configuration: provider={config['provider']}, model={config['model']}, api_key_set={config['api_key_set']}")

    # Initialize model via factory
    try:
        model = create_model_provider(provider_name=provider, model_name=args.model)
    except Exception as e:
        print(f"Failed to initialize model: {e}")
        sys.exit(1)

    # Run the orchestrator
    orchestrator = Orchestrator(task=task, repo_path=repo_path, model=model)

    # Override max iterations if specified
    if args.max_iterations:
        orchestrator.max_iterations = args.max_iterations

    result = orchestrator.run()

    # Exit code
    status = result.get("status", "UNKNOWN")
    if status == "DONE":
        verification = result.get("verification", {})
        if verification and verification.get("passed"):
            sys.exit(0)
        else:
            sys.exit(1)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
