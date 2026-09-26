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

    models_to_try = [model]
    for fb in ["gemini-3.7-flash", "gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-3.1-flash-lite-preview"]:
        if fb not in models_to_try:
            models_to_try.append(fb)

    response = None
    for m in models_to_try:
        try:
            print(f"Testing Gemini model: {m}")
            response = client.models.generate_content(
                model=m,
                contents="Respond with exactly: GEMINI_CONNECTION_OK",
            )
            break
        except Exception as e:
            if "429" in str(e) or "503" in str(e) or "RESOURCE_EXHAUSTED" in str(e) or "UNAVAILABLE" in str(e):
                print(f"  ({m} temporary issue, trying next model...)")
                continue
            raise

    if response is None:
        raise RuntimeError("All candidate models exhausted")

    print("\nModel response:")
    print(response.text)
    return response.text


if __name__ == "__main__":
    test_gemini_connection()