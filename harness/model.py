"""Gemini model wrapper - isolates SDK details from the rest of the harness."""
import json
from google import genai
from harness.config import GEMINI_API_KEY, GEMINI_MODEL


class ModelError(Exception):
    """Raised when the model layer encounters an error."""
    pass


class GeminiModel:
    """Clean wrapper around the Gemini foundation model.
    
    The rest of the harness should only interact with this class,
    never directly with the google-genai SDK.
    """

    def __init__(self, api_key: str = None, model_name: str = None):
        self._api_key = api_key or GEMINI_API_KEY
        self._model_name = model_name or GEMINI_MODEL
        if not self._api_key:
            raise ModelError("API key not configured")
        self._client = genai.Client(api_key=self._api_key)
        self.call_count = 0
        self.total_input_chars = 0
        self.total_output_chars = 0

    def generate(self, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> str:
        """Generate a response from the model.
        
        Args:
            system_prompt: System instructions for the model.
            user_prompt: The user/task prompt.
            temperature: Sampling temperature (lower = more deterministic).
            
        Returns:
            The model's text response.
            
        Raises:
            ModelError: If the API call fails.
        """
        self.call_count += 1
        self.total_input_chars += len(system_prompt) + len(user_prompt)
        
        models_to_try = [self._model_name]
        for fallback in ["gemini-3.7-flash", "gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-3.1-flash-lite-preview"]:
            if fallback not in models_to_try:
                models_to_try.append(fallback)

        last_error = None
        for model_candidate in models_to_try:
            try:
                response = self._client.models.generate_content(
                    model=model_candidate,
                    contents=user_prompt,
                    config={
                        "system_instruction": system_prompt,
                        "temperature": temperature,
                    },
                )
                if model_candidate != self._model_name:
                    print(f"  [Model fallback: using {model_candidate} due to quota limit]")
                    self._model_name = model_candidate
                text = response.text or ""
                self.total_output_chars += len(text)
                return text
            except Exception as e:
                last_error = e
                if any(err in str(e) for err in ["429", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE", "quota"]):
                    continue
                raise ModelError(f"Gemini API error: {type(e).__name__}: {e}") from e

        raise ModelError(f"Gemini API error (all models exhausted): {last_error}") from last_error

    def generate_json(self, system_prompt: str, user_prompt: str, temperature: float = 0.1) -> dict:
        """Generate a response and parse it as JSON.
        
        The prompt should instruct the model to respond with valid JSON.
        Attempts to extract JSON from the response even if surrounded by markdown.
        
        Returns:
            Parsed JSON as a dict.
            
        Raises:
            ModelError: If generation or JSON parsing fails.
        """
        text = self.generate(system_prompt, user_prompt, temperature)
        return self._parse_json(text)
    
    @staticmethod
    def _parse_json(text: str) -> dict:
        """Extract and parse JSON from model output."""
        cleaned = text.strip()
        
        # Try direct parse first
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass
        
        # Try extracting from markdown code block
        if "```" in cleaned:
            lines = cleaned.split("\n")
            json_lines = []
            in_block = False
            for line in lines:
                if line.strip().startswith("```") and not in_block:
                    in_block = True
                    continue
                elif line.strip().startswith("```") and in_block:
                    break
                elif in_block:
                    json_lines.append(line)
            if json_lines:
                try:
                    return json.loads("\n".join(json_lines))
                except json.JSONDecodeError:
                    pass
        
        # Try finding JSON object boundaries
        start = cleaned.find("{")
        end = cleaned.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(cleaned[start:end])
            except json.JSONDecodeError:
                pass
        
        raise ModelError(f"Failed to parse JSON from model output: {cleaned[:200]}")

    def get_metrics(self) -> dict:
        """Return model usage metrics."""
        return {
            "model_calls": self.call_count,
            "total_input_chars": self.total_input_chars,
            "total_output_chars": self.total_output_chars,
        }
