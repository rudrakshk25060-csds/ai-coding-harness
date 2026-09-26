from harnes.config import GEMINI_API_KEY, GEMINI_MODEL


def test_config():
    assert GEMINI_API_KEY
    assert GEMINI_MODEL

    print("Configuration loaded successfully")
    print(f"Model: {GEMINI_MODEL}")