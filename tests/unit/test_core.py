import pytest
from backend.providers.ollama import OllamaProvider
from backend.core.security import create_access_token, decode_access_token, hash_password, verify_password
from backend.rag.service import chunk_text, cosine
from backend.providers.vision import VisionPayload, parse_vision_payload
from backend.api.advanced_routes import SSE_DONE, _visual_evidence


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


def test_empty_vision_payload_is_not_marked_successful():
    with pytest.raises(RuntimeError, match="空观察结果"):
        parse_vision_payload('{"scene_summary":"", "observations":[]}')


def test_diagnosis_prompt_uses_fixed_markdown_sections():
    prompt = OllamaProvider(None).build_prompt('压力异常时怎么排查？', ['[通用手册 / 安全] 先停机并泄压。'])
    sections = ['## 结论', '## 资料依据', '## 排查步骤', '## 安全提示', '## 不确定性']
    positions = [prompt.index(section) for section in sections]
    assert positions == sorted(positions)
    assert '不要输出原始 HTML' in prompt

def test_sse_done_marker_uses_real_protocol_newlines():
    assert SSE_DONE == "data: [DONE]\n\n"
    assert "\\n" not in SSE_DONE


def test_visual_evidence_preserves_anomaly_signal():
    evidence = _visual_evidence({
        "scene_summary": "压缩机维护面板",
        "observations": ["温度显示 86°C"],
        "suspected_anomalies": ["异常：温度偏高；证据：温度显示 86°C；置信度：中"],
        "uncertainties": ["需要传感器历史曲线确认"],
        "safety_flags": ["检修前断电泄压"],
    })
    assert "[图片现场证据]" in evidence
    assert "疑似异常" in evidence
    assert "温度显示 86°C" in evidence
