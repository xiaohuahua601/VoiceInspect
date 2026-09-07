from backend.core.security import create_access_token, decode_access_token, hash_password, verify_password
from backend.rag.service import chunk_text, cosine


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
