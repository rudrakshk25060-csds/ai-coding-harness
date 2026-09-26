"""Unit tests for model adapters (Gemini, DeepSeek, Qwen), model factory, and provider independence.

All tests mock API calls and do NOT require real API keys or internet access.
"""
import json
import io
import pytest
from unittest.mock import patch, MagicMock
from harness.model import (
    ModelAdapter,
    GeminiModel,
    DeepSeekModel,
    QwenModel,
    OpenAICompatibleModel,
    create_model_provider,
    ModelError,
)
from harness.orchestrator import Orchestrator
from harness.config import validate_config, get_config_summary


# ============================================================================
# 1. Gemini Adapter Tests (Mocked)
# ============================================================================

def test_gemini_adapter_mocked_generate():
    """Gemini adapter properly formats prompt and returns text response."""
    with patch("google.genai.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = '{"thought": "Inspect repo", "action": "list_files", "arguments": {"path": "."}}'
        mock_client.models.generate_content.return_value = mock_response
        mock_client_cls.return_value = mock_client

        model = GeminiModel(api_key="mock-gemini-key", model_name="gemini-3.8-flash")
        result = model.generate_json("System instructions", "User task")

        assert result["action"] == "list_files"
        assert result["arguments"]["path"] == "."
        assert model.call_count == 1
        assert model.provider_name == "gemini"


def test_gemini_missing_api_key_raises_when_called():
    """Gemini adapter raises ModelError when API key is missing and generate is called."""
    with patch("harness.model.GEMINI_API_KEY", ""):
        model = GeminiModel(api_key="", model_name="gemini-3.8-flash")
        with pytest.raises(ModelError, match="GEMINI API key not configured"):
            model.generate("system", "user")


# ============================================================================
# 2. DeepSeek Adapter Tests (Mocked)
# ============================================================================

def _make_mock_http_response(content: str, status_code: int = 200):
    """Helper to create a mock urllib response."""
    payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": content,
                }
            }
        ]
    }
    body = json.dumps(payload).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_resp.__enter__.return_value = mock_resp
    return mock_resp


def test_deepseek_adapter_mocked_generate():
    """DeepSeek adapter calls OpenAI-compatible endpoint with correct headers and payload."""
    expected_action = '{"thought": "Read calculator", "action": "read_file", "arguments": {"path": "calculator.py"}}'
    mock_resp = _make_mock_http_response(expected_action)

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        model = DeepSeekModel(
            api_key="mock-deepseek-key",
            model_name="deepseek-flash",
            base_url="https://api.deepseek.com/v1",
        )
        result = model.generate_json("You are an autonomous engineer.", "Fix bug")

        assert result["action"] == "read_file"
        assert result["arguments"]["path"] == "calculator.py"
        assert model.call_count == 1
        assert model.provider_name == "deepseek"

        # Verify HTTP request format
        req = mock_urlopen.call_args[0][0]
        assert req.full_url == "https://api.deepseek.com/v1/chat/completions"
        assert req.headers["Authorization"] == "Bearer mock-deepseek-key"
        assert req.headers["Content-type"] == "application/json"
        
        sent_body = json.loads(req.data.decode("utf-8"))
        assert sent_body["model"] == "deepseek-flash"
        assert sent_body["messages"][0]["role"] == "system"
        assert sent_body["messages"][1]["role"] == "user"


def test_deepseek_missing_api_key_raises_when_called():
    """DeepSeek adapter raises ModelError when API key is missing upon generate."""
    model = DeepSeekModel(api_key="", model_name="deepseek-flash")
    with pytest.raises(ModelError, match="DEEPSEEK API key not configured"):
        model.generate("system", "user")


# ============================================================================
# 3. Qwen Adapter Tests (Mocked)
# ============================================================================

def test_qwen_adapter_mocked_generate():
    """Qwen adapter calls DashScope/custom endpoint with normalized action extraction."""
    expected_action = '{"thought": "Run test suite", "action": "run_tests", "arguments": {"test_path": "tests/"}}'
    mock_resp = _make_mock_http_response(expected_action)

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        model = QwenModel(
            api_key="mock-qwen-key",
            model_name="qwen-turbo",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        result = model.generate_json("System prompt", "User prompt")

        assert result["action"] == "run_tests"
        assert result["arguments"]["test_path"] == "tests/"
        assert model.call_count == 1
        assert model.provider_name == "qwen"

        req = mock_urlopen.call_args[0][0]
        assert "dashscope.aliyuncs.com" in req.full_url
        assert req.headers["Authorization"] == "Bearer mock-qwen-key"


def test_qwen_missing_api_key_raises_when_called():
    """Qwen adapter raises ModelError when API key is missing upon generate."""
    model = QwenModel(api_key="", model_name="qwen-turbo")
    with pytest.raises(ModelError, match="QWEN API key not configured"):
        model.generate("system", "user")


# ============================================================================
# 4. Model Factory & Provider Selection Tests
# ============================================================================

def test_create_model_provider_gemini():
    """Factory instantiates GeminiModel for 'gemini'."""
    with patch("harness.model.GEMINI_API_KEY", "mock-key"):
        model = create_model_provider("gemini")
        assert isinstance(model, GeminiModel)
        assert model.provider_name == "gemini"


def test_create_model_provider_deepseek():
    """Factory instantiates DeepSeekModel for 'deepseek'."""
    model = create_model_provider("deepseek", api_key="test-ds-key", model_name="deepseek-flash")
    assert isinstance(model, DeepSeekModel)
    assert model.provider_name == "deepseek"
    assert model.model_name == "deepseek-flash"


def test_create_model_provider_qwen():
    """Factory instantiates QwenModel for 'qwen'."""
    model = create_model_provider("qwen", api_key="test-qwen-key", model_name="qwen-turbo")
    assert isinstance(model, QwenModel)
    assert model.provider_name == "qwen"
    assert model.model_name == "qwen-turbo"


def test_create_model_provider_from_env():
    """Factory respects MODEL_PROVIDER environment setting."""
    with patch("harness.model.MODEL_PROVIDER", "deepseek"):
        model = create_model_provider(api_key="ds-key")
        assert isinstance(model, DeepSeekModel)


def test_create_model_provider_unsupported_raises():
    """Factory rejects unknown providers cleanly."""
    with pytest.raises(ModelError, match="Unsupported model provider: 'unknown_provider'"):
        create_model_provider("unknown_provider")


# ============================================================================
# 5. Normalized Action & JSON Robustness Tests
# ============================================================================

def test_normalized_action_from_markdown_block():
    """Model output wrapped in markdown code fence parses correctly into normalized action."""
    raw = """Here is the next action:
```json
{
    "thought": "Apply surgical patch to calculator",
    "action": "apply_patch",
    "arguments": {
        "path": "calculator.py",
        "original": "return a + b",
        "replacement": "return a * b"
    }
}
```
Let me know if this works."""
    parsed = ModelAdapter._parse_json(raw)
    assert parsed["action"] == "apply_patch"
    assert parsed["arguments"]["replacement"] == "return a * b"


def test_normalized_action_from_boundary_extraction():
    """Model output with leading text and trailing commentary parses correctly."""
    raw = 'Sure, I will execute this now: {"thought": "Inspect diff", "action": "git_diff", "arguments": {}} hope it helps!'
    parsed = ModelAdapter._parse_json(raw)
    assert parsed["action"] == "git_diff"
    assert parsed["arguments"] == {}


def test_openai_compatible_native_tool_call_normalization():
    """OpenAI-compatible models returning tool_calls structure get normalized."""
    tool_call_payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Executing test suite",
                    "tool_calls": [
                        {
                            "id": "call_123",
                            "type": "function",
                            "function": {
                                "name": "run_tests",
                                "arguments": json.dumps({"test_path": "test_calculator.py"}),
                            },
                        }
                    ],
                }
            }
        ]
    }
    body = json.dumps(tool_call_payload).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        model = DeepSeekModel(api_key="test-key")
        result = model.generate_json("sys", "user")
        assert result["action"] == "run_tests"
        assert result["arguments"]["test_path"] == "test_calculator.py"


# ============================================================================
# 6. Provider-Independent Orchestrator Tests
# ============================================================================

def test_orchestrator_runs_with_deepseek_adapter(tmp_path):
    """Orchestrator works identically when driven by DeepSeekModel adapter."""
    test_file = tmp_path / "test_example.py"
    test_file.write_text("def test_ok(): assert True\n")

    actions = [
        '{"thought": "List files", "action": "list_files", "arguments": {"path": "."}}',
        '{"thought": "Run tests", "action": "run_tests", "arguments": {"test_path": "test_example.py"}}',
        '{"thought": "Show diff", "action": "git_diff", "arguments": {}}',
        '{"thought": "All verified", "action": "finish", "arguments": {"summary": "Verified with tests and diff."}}',
    ]

    responses = [_make_mock_http_response(act) for act in actions]

    with patch("urllib.request.urlopen", side_effect=responses):
        deepseek_model = DeepSeekModel(api_key="mock-key", model_name="deepseek-flash")
        orchestrator = Orchestrator(task="Verify tests", repo_path=str(tmp_path), model=deepseek_model)
        result = orchestrator.run()

        assert result["status"] == "DONE"
        assert result["verification"]["passed"] is True
        assert orchestrator.metrics["model_calls"] >= 4
        assert deepseek_model.call_count >= 4
        assert deepseek_model.provider_name == "deepseek"


def test_orchestrator_runs_with_qwen_adapter(tmp_path):
    """Orchestrator works identically when driven by QwenModel adapter."""
    test_file = tmp_path / "test_sample.py"
    test_file.write_text("def test_ok(): assert True\n")

    actions = [
        '{"thought": "Listing directory", "action": "list_files", "arguments": {"path": "."}}',
        '{"thought": "Execute pytest", "action": "run_tests", "arguments": {"test_path": "test_sample.py"}}',
        '{"thought": "Inspect git diff", "action": "git_diff", "arguments": {}}',
        '{"thought": "Done", "action": "finish", "arguments": {"summary": "Completed successfully."}}',
    ]

    responses = [_make_mock_http_response(act) for act in actions]

    with patch("urllib.request.urlopen", side_effect=responses):
        qwen_model = QwenModel(api_key="mock-key", model_name="qwen-turbo")
        orchestrator = Orchestrator(task="Verify tests", repo_path=str(tmp_path), model=qwen_model)
        result = orchestrator.run()

        assert result["status"] == "DONE"
        assert result["verification"]["passed"] is True
        assert orchestrator.metrics["model_calls"] >= 4
        assert qwen_model.call_count >= 4
        assert qwen_model.provider_name == "qwen"


# ============================================================================
# 7. Config Validation per Provider
# ============================================================================

def test_validate_config_per_provider():
    """validate_config checks the appropriate API key based on the provider."""
    # DeepSeek requires DEEPSEEK_API_KEY
    with patch("harness.config.DEEPSEEK_API_KEY", ""):
        with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY is not set"):
            validate_config(provider="deepseek")

    with patch("harness.config.DEEPSEEK_API_KEY", "ds-key-123"):
        assert validate_config(provider="deepseek") is True

    # Qwen requires QWEN_API_KEY
    with patch("harness.config.QWEN_API_KEY", ""):
        with pytest.raises(RuntimeError, match="QWEN_API_KEY is not set"):
            validate_config(provider="qwen")

    with patch("harness.config.QWEN_API_KEY", "qwen-key-123"):
        assert validate_config(provider="qwen") is True
