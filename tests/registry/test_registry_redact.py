import json
from pathlib import Path

import pytest

from content_automation.registry.redact import (
    REDACTED,
    redact_data,
    redact_text,
    secret_values,
)

FAKE_KEY = "fake-example-key-0123456789"


@pytest.fixture
def env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    path = tmp_path / ".env"
    path.write_text(
        "IMAGE_PROVIDER=openrouter\n"
        "HEYGEN_AVATAR_ID=avatar-123\n"
        'EXAMPLE_S3_SECRET_KEY="s3secret-abcdefgh"\n'
        "DRIVE_SHARE_WITH=manager@example.com\n",
        encoding="utf-8",
    )
    return path


def test_env_and_dotenv_secrets(env_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXAMPLE_API_KEY", FAKE_KEY)
    monkeypatch.setenv("SHORT_TOKEN", "abc")  # too short to replace everywhere
    secrets = secret_values()
    assert {FAKE_KEY, "s3secret-abcdefgh"} <= secrets
    assert "openrouter" not in secrets and "abc" not in secrets
    text = redact_text(f"pod failed: key {FAKE_KEY}, s3 s3secret-abcdefgh, provider openrouter")
    assert text == f"pod failed: key {REDACTED}, s3 {REDACTED}, provider openrouter"


@pytest.mark.parametrize("secret", [
    "sk-or-v1-0123456789abcdef0123456789abcdef",
    "sk_3f9a0c2b7e1d4a6b8c0d2e4f6a8b0c2d4e6f8a0b",
    "rpa_ABCDEFGHIJ0123456789KLMNOP",
    "hf_abcdefghijklmnopqrstuvwxyz012345",
    "ya29.a0AfH6SMBx-very_long-token.value",
    "1//0gLx2abcdefghijklmnopqrstuvwxyz",
    "GOCSPX-abcdefghijklmnopqrstu",
    "AIzaSyA1234567890abcdefghijklmnopqrstu",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.c2lnbmF0dXJlLXZhbHVl",
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "Zm9vYmFyQmF6UXV4MTIzNDU2Nzg5MEFCQ0RFRkdISUpLTE1OT1BRUlM",
])
def test_token_like_strings(secret: str, env_file: Path) -> None:
    assert secret not in redact_text(f"error: {secret} rejected", frozenset())


def test_bearer_and_assignments(env_file: Path) -> None:
    assert redact_text("Authorization: Bearer abc.def-ghi_jkl", frozenset()) == (
        f"Authorization: Bearer {REDACTED}"
    )
    assert redact_text("HEYGEN_API_KEY=abcdefgh12345 set", frozenset()) == (
        f"HEYGEN_API_KEY={REDACTED} set"
    )


def test_oauth_json(env_file: Path) -> None:
    client = {"installed": {"client_id": "123.apps.googleusercontent.com",
                            "client_secret": "GOCSPX-zzz", "refresh_token": "r",
                            "accessToken": "a"}}
    clean = redact_data(client, frozenset())
    assert clean["installed"]["client_secret"] == REDACTED
    assert clean["installed"]["refresh_token"] == REDACTED
    assert clean["installed"]["accessToken"] == REDACTED
    assert clean["installed"]["client_id"] == "123.apps.googleusercontent.com"
    text = redact_text(json.dumps({"token": "x", "refresh_token": "1/abc", "client_secret": "s"}),
                       frozenset())
    assert '"refresh_token": "[redacted]"' in text and '"client_secret": "[redacted]"' in text


def test_ordinary_values_stay_readable(env_file: Path) -> None:
    sha = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    details = {
        "idempotency_key": sha,
        "package": "outputs/content/2026-10-03_ai-chatbots-for-dentists/carousel/requests",
        "drive_file_id": "1AbCdEfGhIjKlMnOpQrStUvWxYz012345",
        "link": "https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOpQrStUvWxYz012345",
        "photo": "assets/reference/identity/person_01/IMG_20261003_123456.jpg",
        "content_id": "2026-W42-03", "cost": 0.039, "ok": True, "max_tokens": 1200,
        "path": Path("outputs/jobs/2026-10-13/1015_make-a-post"),
    }
    clean = redact_data(details, frozenset())
    assert clean == {**details, "path": "outputs/jobs/2026-10-13/1015_make-a-post"}
