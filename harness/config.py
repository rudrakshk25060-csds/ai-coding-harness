"""Configuration management for the AI coding harness."""
import os
from dotenv import load_dotenv

load_dotenv()

# Model Provider Selection (gemini, deepseek, qwen)
MODEL_PROVIDER = os.getenv("MODEL_PROVIDER", "gemini").lower()

# Evaluator generic API key
AI_API_KEY = os.getenv("AI_API_KEY", "")

# Gemini Configuration (uses GEMINI_API_KEY, falls back to AI_API_KEY)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "") or AI_API_KEY
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

# DeepSeek Configuration (uses DEEPSEEK_API_KEY, falls back to AI_API_KEY)
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "") or AI_API_KEY
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")

# Qwen Configuration (uses QWEN_API_KEY, falls back to AI_API_KEY)
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "") or AI_API_KEY
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen-turbo")
QWEN_BASE_URL = os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")

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


def validate_config(provider: str = None):
    """Validate that required configuration is present for the active provider."""
    active_provider = (provider or MODEL_PROVIDER).lower()
    if active_provider in ("gemini", "google"):
        if not (GEMINI_API_KEY or AI_API_KEY):
            raise RuntimeError(
                "GEMINI_API_KEY is not set (and AI_API_KEY fallback not provided). Add it to .env file."
            )
    elif active_provider == "deepseek":
        if not (DEEPSEEK_API_KEY or AI_API_KEY):
            raise RuntimeError(
                "DEEPSEEK_API_KEY is not set (and AI_API_KEY fallback not provided). Add it to .env file or environment."
            )
    elif active_provider in ("qwen", "dashscope"):
        if not (QWEN_API_KEY or AI_API_KEY):
            raise RuntimeError(
                "QWEN_API_KEY is not set (and AI_API_KEY fallback not provided). Add it to .env file or environment."
            )
    else:
        raise RuntimeError(
            f"Unknown MODEL_PROVIDER '{active_provider}'. Supported: gemini, deepseek, qwen"
        )
    return True


def get_config_summary(provider: str = None):
    """Return a safe config summary (no secrets)."""
    active_provider = (provider or MODEL_PROVIDER).lower()
    if active_provider in ("gemini", "google"):
        active_model = GEMINI_MODEL
        key_set = bool(GEMINI_API_KEY)
    elif active_provider == "deepseek":
        active_model = DEEPSEEK_MODEL
        key_set = bool(DEEPSEEK_API_KEY)
    elif active_provider in ("qwen", "dashscope"):
        active_model = QWEN_MODEL
        key_set = bool(QWEN_API_KEY)
    else:
        active_model = "unknown"
        key_set = False

    return {
        "provider": active_provider,
        "model": active_model,
        "max_iterations": MAX_ITERATIONS,
        "max_recovery_attempts": MAX_RECOVERY_ATTEMPTS,
        "max_same_error": MAX_SAME_ERROR,
        "api_key_set": key_set,
    }
