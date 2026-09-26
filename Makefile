.PHONY: setup run test clean

PYTHON ?= python3
VENV ?= .venv
VENV_PYTHON = $(VENV)/bin/python

# Default demo task if no ARGS provided
TASK ?= "Fix the bug in examples/demo_repo and verify it with tests"
ARGS ?= $(TASK)

# Install all required Python dependencies for the project
setup:
	@if [ ! -d "$(VENV)" ]; then \
		echo "Creating virtual environment at $(VENV)..."; \
		$(PYTHON) -m venv $(VENV); \
	fi
	@echo "Installing project dependencies..."
	@if [ -f requirements.txt ]; then \
		$(VENV_PYTHON) -m pip install -q -r requirements.txt; \
	else \
		$(VENV_PYTHON) -m pip install -q google-genai python-dotenv pytest; \
	fi
	@echo "Setup complete."

# Start the existing harness using the existing main.py entry point
run:
	@if [ -f "$(VENV_PYTHON)" ]; then \
		$(VENV_PYTHON) main.py $(ARGS); \
	else \
		$(PYTHON) main.py $(ARGS); \
	fi

# Run the complete pytest test suite
test:
	@if [ -f "$(VENV_PYTHON)" ]; then \
		$(VENV_PYTHON) -m pytest -q; \
	else \
		pytest -q; \
	fi

# Remove only generated/cache artifacts such as __pycache__, .pytest_cache, etc.
clean:
	@echo "Cleaning temporary build and cache artifacts..."
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@find . -type f -name "*.pyo" -delete 2>/dev/null || true
	@find . -type f -name "*.pyd" -delete 2>/dev/null || true
	@find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	@echo "Clean complete."
