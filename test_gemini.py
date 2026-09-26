import os
from dotenv import load_dotenv
from google import genai

load_dotenv()


def test_gemini_connection():
    api_key = os.getenv("GEMINI_API_KEY")
    model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    client = genai.Client(api_key=api_key)

    print(f"Testing Gemini model: {model}")

    response = client.models.generate_content(
        model=model,
        contents="Respond with exactly: GEMINI_CONNECTION_OK",
    )

    print("\nModel response:")
    print(response.text)
    return response.text


if __name__ == "__main__":
    test_gemini_connection()