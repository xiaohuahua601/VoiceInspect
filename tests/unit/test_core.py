from backend.providers.ollama import OllamaProvider
from backend.core.security import create_access_token, decode_access_token, hash_password, verify_password
from backend.rag.service import chunk_text, cosine
from backend.providers.vision import VisionPayload


def test_password_hash_round_trip():
    encoded = hash_password("secret-value")
    assert encoded != "secret-value"
    assert verify_password("secret-value", encoded)
    assert not verify_password("wrong", encoded)


def test_token_round_trip():
    token = create_access_token("user-1", "operator", "operator", "test-secret", 5)
    payload = decode_access_token(token, "test-secret")
    assert payload and payload["sub"] == "user-1"
    assert decode_access_token(token, "wrong-secret") is None


def test_chunking_and_cosine():
    chunks = chunk_text("第一段。" * 200, target=100, overlap=10)
    assert len(chunks) > 1
    assert cosine([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert cosine([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_vision_payload_normalizes_structured_items():
    payload = VisionPayload(
        uncertainties=[{"type": "不确定", "description": "无法确认是否存在泄漏"}],
    )
    assert payload.uncertainties == ["不确定：无法确认是否存在泄漏"]


def test_diagnosis_prompt_uses_fixed_markdown_sections():
    prompt = OllamaProvider(None).build_prompt('压力异常时怎么排查？', ['[通用手册 / 安全] 先停机并泄压。'])
    sections = ['## 结论', '## 资料依据', '## 排查步骤', '## 安全提示', '## 不确定性']
    positions = [prompt.index(section) for section in sections]
    assert positions == sorted(positions)
    assert '不要输出原始 HTML' in prompt
