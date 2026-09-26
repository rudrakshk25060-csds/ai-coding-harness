"""Configuration management for the AI coding harness."""
import os
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

# Execution bounds
MAX_ITERATIONS = 12
MAX_RECOVERY_ATTEMPTS = 4
MAX_SAME_ERROR = 2

# Output limits
MAX_OUTPUT_CHARS = 8000
MAX_FILE_CHARS = 12000

# Safety
FORBIDDEN_PATHS = [".env", ".git/config", ".git/credentials"]
FORBIDDEN_COMMANDS = ["rm -rf /", "rm -rf ~", ":(){ :|:& };:"]


def validate_config():
    """Validate that required configuration is present."""
    if not GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Add it to .env file."
        )
    return True


def get_config_summary():
    """Return a safe config summary (no secrets)."""
    return {
        "model": GEMINI_MODEL,
        "max_iterations": MAX_ITERATIONS,
        "max_recovery_attempts": MAX_RECOVERY_ATTEMPTS,
        "max_same_error": MAX_SAME_ERROR,
        "api_key_set": bool(GEMINI_API_KEY),
    }
