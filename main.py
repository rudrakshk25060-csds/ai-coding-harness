#!/usr/bin/env python3
"""AI Coding Harness - Main entry point.

Usage:
    python main.py "Fix the bug in examples/demo_repo and run the tests"
    python main.py --repo /path/to/repo "Task description"
"""
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness.config import validate_config, get_config_summary
from harness.model import GeminiModel
from harness.orchestrator import Orchestrator


def main():
    """Main entry point for the AI coding harness."""
    # Parse arguments
    args = sys.argv[1:]
    
    if not args or args[0] in ("--help", "-h"):
        print("Usage: python main.py [--repo REPO_PATH] \"task description\"")
        print("\nExamples:")
        print('  python main.py "Fix the failing test in examples/demo_repo"')
        print('  python main.py --repo /path/to/repo "Fix the bug and run tests"')
        sys.exit(0)
    
    # Parse --repo flag
    repo_path = None
    task = None
    
    i = 0
    while i < len(args):
        if args[i] == "--repo" and i + 1 < len(args):
            repo_path = args[i + 1]
            i += 2
        else:
            task = args[i]
            i += 1
    
    if not task:
        print("Error: No task provided.")
        print("Usage: python main.py \"task description\"")
        sys.exit(1)
    
    # Default repo path: if task mentions demo_repo, use it
    if repo_path is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        if "demo_repo" in task or "demo" in task.lower():
            repo_path = os.path.join(script_dir, "examples", "demo_repo")
        else:
            repo_path = script_dir
    
    repo_path = os.path.abspath(repo_path)
    
    if not os.path.isdir(repo_path):
        print(f"Error: Repository path does not exist: {repo_path}")
        sys.exit(1)
    
    # Validate configuration
    try:
        validate_config()
    except RuntimeError as e:
        print(f"Configuration error: {e}")
        sys.exit(1)
    
    config = get_config_summary()
    print(f"Configuration: model={config['model']}, api_key_set={config['api_key_set']}")
    
    # Initialize model
    try:
        model = GeminiModel()
    except Exception as e:
        print(f"Failed to initialize model: {e}")
        sys.exit(1)
    
    # Run the orchestrator
    orchestrator = Orchestrator(task=task, repo_path=repo_path, model=model)
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
