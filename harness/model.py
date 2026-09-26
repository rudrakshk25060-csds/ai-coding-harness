"""Model adapters and factory - isolates foundation model SDKs from the harness.

Supported providers:
- Gemini (Google GenAI SDK)
- DeepSeek (OpenAI-compatible REST API)
- Qwen (OpenAI-compatible REST API)
"""
import json
import os
import urllib.request
import urllib.error
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from harness.config import (
    MODEL_PROVIDER,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    DEEPSEEK_API_KEY,
    DEEPSEEK_MODEL,
    DEEPSEEK_BASE_URL,
    QWEN_API_KEY,
    QWEN_MODEL,
    QWEN_BASE_URL,
)


class ModelError(Exception):
    """Raised when any model layer encounters an error."""
    pass


class ModelAdapter(ABC):
    """Abstract base class for foundation model providers.
    
    Standardizes generation, structured JSON/action extraction, and metrics tracking.
    All model adapters must return normalized actions to the orchestrator.
    """

    def __init__(self, provider_name: str, model_name: str):
        self.provider_name = provider_name
        self.model_name = model_name
        self.call_count = 0
        self.total_input_chars = 0
        self.total_output_chars = 0

    @abstractmethod
    def generate(self, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> str:
        """Generate text response from the model.
        
        Args:
            system_prompt: System instructions for the model.
            user_prompt: The user/task prompt.
            temperature: Sampling temperature.
            
        Returns:
            The model's text response.
            
        Raises:
            ModelError: If the API call fails or credentials are missing.
        """
        raise NotImplementedError

    def generate_json(self, system_prompt: str, user_prompt: str, temperature: float = 0.1) -> dict:
        """Generate a response and parse it as JSON.
        
        Returns:
            Parsed JSON as a dict matching normalized action format.
            
        Raises:
            ModelError: If generation or JSON parsing fails.
        """
        text = self.generate(system_prompt, user_prompt, temperature)
        return self._parse_json(text)

    def get_metrics(self) -> dict:
        """Return model usage metrics."""
        return {
            "provider": self.provider_name,
            "model": self.model_name,
            "model_calls": self.call_count,
            "total_input_chars": self.total_input_chars,
            "total_output_chars": self.total_output_chars,
        }

    @staticmethod
    def _parse_json(text: str) -> dict:
        """Extract and parse JSON from model output.
        
        Handles:
        1. Clean JSON string
        2. Markdown code blocks (```json ... ```)
        3. Embedded JSON object boundaries ({ ... })
        """
        cleaned = text.strip()

        # 1. Try direct parse
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # 2. Try extracting from markdown code block
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

        # 3. Try finding JSON object boundaries
        start = cleaned.find("{")
        end = cleaned.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(cleaned[start:end])
            except json.JSONDecodeError:
                pass

        raise ModelError(f"Failed to parse JSON from model output: {cleaned[:200]}")


class GeminiModel(ModelAdapter):
    """Gemini foundation model adapter using google-genai SDK.
    
    Includes graceful quota and rate-limit fallbacks across compatible models.
    """

    def __init__(self, api_key: str = None, model_name: str = None):
        key = api_key or GEMINI_API_KEY
        model = model_name or GEMINI_MODEL
        super().__init__(provider_name="gemini", model_name=model)
        self._api_key = key
        self._client = None
        if self._api_key:
            from google import genai
            self._client = genai.Client(api_key=self._api_key)

    def _ensure_client(self):
        if not self._client:
            if not self._api_key:
                raise ModelError(
                    "GEMINI API key not configured. Set GEMINI_API_KEY in .env file."
                )
            from google import genai
            self._client = genai.Client(api_key=self._api_key)

    def generate(self, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> str:
        self._ensure_client()
        self.call_count += 1
        self.total_input_chars += len(system_prompt) + len(user_prompt)

        models_to_try = [self.model_name]
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
                if model_candidate != self.model_name:
                    print(f"  [Model fallback: using {model_candidate} due to quota limit]")
                    self.model_name = model_candidate
                text = response.text or ""
                self.total_output_chars += len(text)
                return text
            except Exception as e:
                last_error = e
                if any(err in str(e) for err in ["429", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE", "quota"]):
                    continue
                raise ModelError(f"Gemini API error: {type(e).__name__}: {e}") from e

        raise ModelError(f"Gemini API error (all models exhausted): {last_error}") from last_error


class OpenAICompatibleModel(ModelAdapter):
    """Base adapter for OpenAI-compatible REST APIs (used by DeepSeek, Qwen, vLLM, Ollama)."""

    def __init__(
        self,
        provider_name: str,
        api_key: Optional[str],
        model_name: str,
        base_url: str,
        timeout: int = 60,
    ):
        super().__init__(provider_name=provider_name, model_name=model_name)
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _ensure_api_key(self):
        if not self._api_key:
            env_var = f"{self.provider_name.upper()}_API_KEY"
            raise ModelError(
                f"{self.provider_name.upper()} API key not configured. "
                f"Set {env_var} in your environment or .env file."
            )

    def generate(self, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> str:
        self._ensure_api_key()
        self.call_count += 1
        self.total_input_chars += len(system_prompt) + len(user_prompt)

        url = f"{self._base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
            "User-Agent": "ai-coding-harness/0.1.0",
        }
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                choice = data.get("choices", [{}])[0]
                message = choice.get("message", {})
                
                # Check for tool_calls if returned in native format
                if "tool_calls" in message and message["tool_calls"]:
                    tool_call = message["tool_calls"][0]
                    fn = tool_call.get("function", {})
                    fn_name = fn.get("name", "")
                    fn_args = fn.get("arguments", "{}")
                    try:
                        args_dict = json.loads(fn_args) if isinstance(fn_args, str) else fn_args
                    except Exception:
                        args_dict = {}
                    normalized = {
                        "thought": message.get("content", ""),
                        "action": fn_name,
                        "arguments": args_dict,
                    }
                    content = json.dumps(normalized)
                else:
                    content = message.get("content", "")

                self.total_output_chars += len(content)
                return content
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            raise ModelError(
                f"{self.provider_name.capitalize()} API HTTP error {e.code}: {err_body[:300]}"
            ) from e
        except Exception as e:
            raise ModelError(f"{self.provider_name.capitalize()} API error: {e}") from e


class DeepSeekModel(OpenAICompatibleModel):
    """DeepSeek foundation model adapter using OpenAI-compatible REST API.
    
    Supports models such as 'deepseek-flash', 'deepseek-chat', 'deepseek-reasoner'.
    """

    DEFAULT_MODEL = "deepseek-flash"
    DEFAULT_BASE_URL = "https://api.deepseek.com/v1"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = 60,
    ):
        key = api_key if api_key is not None else DEEPSEEK_API_KEY
        model = model_name or DEEPSEEK_MODEL or self.DEFAULT_MODEL
        url = base_url or DEEPSEEK_BASE_URL or self.DEFAULT_BASE_URL
        super().__init__(
            provider_name="deepseek",
            api_key=key,
            model_name=model,
            base_url=url,
            timeout=timeout,
        )


class QwenModel(OpenAICompatibleModel):
    """Qwen foundation model adapter using OpenAI-compatible endpoint.
    
    Supports Alibaba DashScope and custom Qwen evaluator endpoints.
    """

    DEFAULT_MODEL = "qwen-turbo"
    DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = 60,
    ):
        key = api_key if api_key is not None else QWEN_API_KEY
        model = model_name or QWEN_MODEL or self.DEFAULT_MODEL
        url = base_url or QWEN_BASE_URL or self.DEFAULT_BASE_URL
        super().__init__(
            provider_name="qwen",
            api_key=key,
            model_name=model,
            base_url=url,
            timeout=timeout,
        )


def create_model_provider(
    provider_name: Optional[str] = None,
    api_key: Optional[str] = None,
    model_name: Optional[str] = None,
    **kwargs,
) -> ModelAdapter:
    """Factory function to instantiate the configured model provider.
    
    Args:
        provider_name: 'gemini', 'deepseek', or 'qwen'. If None, reads from MODEL_PROVIDER env.
        api_key: Optional API key override.
        model_name: Optional model name override.
        **kwargs: Additional provider-specific kwargs (e.g. base_url).
        
    Returns:
        An instance of ModelAdapter.
        
    Raises:
        ModelError: If provider is unrecognized.
    """
    provider = (provider_name or MODEL_PROVIDER or "gemini").strip().lower()

    if provider in ("gemini", "google"):
        return GeminiModel(api_key=api_key, model_name=model_name)
    elif provider in ("deepseek",):
        return DeepSeekModel(api_key=api_key, model_name=model_name, **kwargs)
    elif provider in ("qwen", "dashscope"):
        return QwenModel(api_key=api_key, model_name=model_name, **kwargs)
    else:
        raise ModelError(
            f"Unsupported model provider: '{provider}'. "
            f"Supported providers: gemini, deepseek, qwen"
        )
