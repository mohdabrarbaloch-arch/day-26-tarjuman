"""Tests for the API surface.

The provider is stubbed so these run offline and fast. What is being tested is
the HTTP contract: status codes, auth enforcement, ownership scoping, and
validation -- not the translation quality, which has its own tests.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.provider import TranslationResult


class StubProvider:
    """A provider that returns a fixed translation, for offline tests."""

    name = "stub"
    max_chars = 500

    def __init__(self, mapping: dict[str, str] | None = None) -> None:
        self.mapping = mapping or {}
        self.calls = 0

    async def translate(self, text: str, source: str, target: str) -> TranslationResult:
        self.calls += 1
        if text in self.mapping:
            return TranslationResult(self.mapping[text], self.name)
        # Default: a plausible Urdu string for ur targets, else echo-ish.
        if target == "ur":
            return TranslationResult("یہ ایک ترجمہ ہے", self.name)
        return TranslationResult("This is a translation", self.name)

    async def aclose(self) -> None:
        return None


@pytest.fixture
def stub_provider(monkeypatch: pytest.MonkeyPatch) -> StubProvider:
    stub = StubProvider()
    monkeypatch.setattr("app.core.translator.get_provider", lambda: stub)
    return stub


class TestHealth:
    def test_health_ok(self, client: TestClient) -> None:
        r = client.get("/api/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["version"] == "1.0.0"

    def test_index_serves_html(self, client: TestClient) -> None:
        r = client.get("/")
        assert r.status_code == 200
        assert "Tarjuman" in r.text

    def test_security_headers_present(self, client: TestClient) -> None:
        r = client.get("/")
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["x-frame-options"] == "DENY"
        assert "content-security-policy" in r.headers


class TestLanguages:
    def test_lists_languages(self, client: TestClient) -> None:
        r = client.get("/api/languages")
        assert r.status_code == 200
        codes = {lang["code"] for lang in r.json()}
        assert {"en", "ur", "hi", "ar"} <= codes

    def test_urdu_is_rtl(self, client: TestClient) -> None:
        r = client.get("/api/languages")
        urdu = next(lang for lang in r.json() if lang["code"] == "ur")
        assert urdu["rtl"] is True
        assert urdu["script"] == "arabic"


class TestAuth:
    def test_register_returns_token(self, client: TestClient) -> None:
        r = client.post(
            "/api/auth/register",
            json={"email": "new@example.com", "password": "GoodPassword1"},
        )
        assert r.status_code == 201
        assert r.json()["access_token"]
        assert r.json()["user"]["email"] == "new@example.com"

    def test_duplicate_email_conflicts(self, client: TestClient) -> None:
        payload = {"email": "dup@example.com", "password": "GoodPassword1"}
        assert client.post("/api/auth/register", json=payload).status_code == 201
        r = client.post("/api/auth/register", json=payload)
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "email_taken"

    def test_short_password_rejected(self, client: TestClient) -> None:
        r = client.post("/api/auth/register", json={"email": "x@example.com", "password": "short"})
        assert r.status_code == 422

    def test_all_digit_password_rejected(self, client: TestClient) -> None:
        r = client.post(
            "/api/auth/register", json={"email": "y@example.com", "password": "1234567890"}
        )
        assert r.status_code == 422

    def test_login_succeeds(self, client: TestClient) -> None:
        client.post(
            "/api/auth/register",
            json={"email": "login@example.com", "password": "GoodPassword1"},
        )
        r = client.post(
            "/api/auth/login",
            json={"email": "login@example.com", "password": "GoodPassword1"},
        )
        assert r.status_code == 200
        assert r.json()["access_token"]

    def test_wrong_password_rejected(self, client: TestClient) -> None:
        client.post(
            "/api/auth/register",
            json={"email": "wp@example.com", "password": "GoodPassword1"},
        )
        r = client.post(
            "/api/auth/login", json={"email": "wp@example.com", "password": "WrongPassword1"}
        )
        assert r.status_code == 401

    def test_unknown_email_same_error_as_wrong_password(self, client: TestClient) -> None:
        """No account enumeration: both paths return the same code."""
        r = client.post(
            "/api/auth/login", json={"email": "ghost@example.com", "password": "Whatever1"}
        )
        assert r.status_code == 401
        assert r.json()["detail"]["code"] == "bad_credentials"

    def test_me_requires_token(self, client: TestClient) -> None:
        assert client.get("/api/auth/me").status_code == 401

    def test_me_with_token(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        r = client.get("/api/auth/me", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["email"] == "tester@example.com"

    def test_bad_token_rejected(self, client: TestClient) -> None:
        r = client.get("/api/auth/me", headers={"Authorization": "Bearer nonsense"})
        assert r.status_code == 401


class TestTranslate:
    def test_translate_works_anonymously(
        self, client: TestClient, stub_provider: StubProvider
    ) -> None:
        r = client.post(
            "/api/translate",
            json={"text": "Hello there", "source_lang": "en", "target_lang": "ur"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["translated_text"]
        assert body["verification"]["verdict"] in ("verified", "likely", "uncertain", "failed")
        assert len(body["verification"]["findings"]) == 5

    def test_empty_text_rejected(self, client: TestClient) -> None:
        r = client.post(
            "/api/translate", json={"text": "   ", "source_lang": "en", "target_lang": "ur"}
        )
        assert r.status_code == 422

    def test_unknown_target_rejected(self, client: TestClient) -> None:
        r = client.post(
            "/api/translate", json={"text": "hello", "source_lang": "en", "target_lang": "zz"}
        )
        assert r.status_code == 422

    def test_same_language_rejected(self, client: TestClient) -> None:
        r = client.post(
            "/api/translate", json={"text": "hello", "source_lang": "en", "target_lang": "en"}
        )
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "same_language"

    def test_too_long_rejected(self, client: TestClient) -> None:
        r = client.post(
            "/api/translate",
            json={"text": "x" * 6000, "source_lang": "en", "target_lang": "ur"},
        )
        assert r.status_code == 422

    def test_save_requires_auth(self, client: TestClient, stub_provider: StubProvider) -> None:
        r = client.post(
            "/api/translate",
            json={"text": "Hello", "source_lang": "en", "target_lang": "ur", "save": True},
        )
        assert r.status_code == 200
        assert r.json()["saved_id"] is None

    def test_save_with_auth(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        stub_provider: StubProvider,
    ) -> None:
        r = client.post(
            "/api/translate",
            json={"text": "Hello", "source_lang": "en", "target_lang": "ur", "save": True},
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.json()["saved_id"] is not None


class TestHistory:
    def _save_one(self, client: TestClient, headers: dict[str, str]) -> str:
        r = client.post(
            "/api/translate",
            json={"text": "Hello", "source_lang": "en", "target_lang": "ur", "save": True},
            headers=headers,
        )
        return r.json()["saved_id"]

    def test_history_requires_auth(self, client: TestClient) -> None:
        assert client.get("/api/history").status_code == 401

    def test_history_lists_saved(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        stub_provider: StubProvider,
    ) -> None:
        self._save_one(client, auth_headers)
        r = client.get("/api/history", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["total"] == 1

    def test_favourite_toggle(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        stub_provider: StubProvider,
    ) -> None:
        tid = self._save_one(client, auth_headers)
        r = client.patch(
            f"/api/history/{tid}/favourite",
            json={"is_favourite": True},
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.json()["is_favourite"] is True

    def test_delete_removes(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        stub_provider: StubProvider,
    ) -> None:
        tid = self._save_one(client, auth_headers)
        assert client.delete(f"/api/history/{tid}", headers=auth_headers).status_code == 204
        assert client.get(f"/api/history/{tid}", headers=auth_headers).status_code == 404

    def test_other_users_record_is_404(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        stub_provider: StubProvider,
    ) -> None:
        """Ownership: someone else's record must look like it does not exist."""
        tid = self._save_one(client, auth_headers)

        other = client.post(
            "/api/auth/register",
            json={"email": "other@example.com", "password": "GoodPassword1"},
        ).json()
        other_headers = {"Authorization": f"Bearer {other['access_token']}"}

        r = client.get(f"/api/history/{tid}", headers=other_headers)
        assert r.status_code == 404

    def test_other_user_cannot_delete(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        stub_provider: StubProvider,
    ) -> None:
        tid = self._save_one(client, auth_headers)
        other = client.post(
            "/api/auth/register",
            json={"email": "other2@example.com", "password": "GoodPassword1"},
        ).json()
        other_headers = {"Authorization": f"Bearer {other['access_token']}"}
        assert client.delete(f"/api/history/{tid}", headers=other_headers).status_code == 404


class TestConversation:
    def test_create_requires_auth(self, client: TestClient) -> None:
        r = client.post("/api/conversations", json={"lang_a": "en", "lang_b": "ur"})
        assert r.status_code == 401

    def test_create_conversation(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        r = client.post(
            "/api/conversations",
            json={"title": "Test", "lang_a": "en", "lang_b": "ur"},
            headers=auth_headers,
        )
        assert r.status_code == 201
        assert r.json()["lang_a"] == "en"

    def test_same_languages_rejected(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        r = client.post(
            "/api/conversations",
            json={"lang_a": "en", "lang_b": "en"},
            headers=auth_headers,
        )
        assert r.status_code == 422

    def test_add_turn_translates(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        stub_provider: StubProvider,
    ) -> None:
        conv = client.post(
            "/api/conversations",
            json={"lang_a": "en", "lang_b": "ur"},
            headers=auth_headers,
        ).json()
        r = client.post(
            f"/api/conversations/{conv['id']}/turns",
            json={"speaker": "a", "text": "Hello there"},
            headers=auth_headers,
        )
        assert r.status_code == 201
        body = r.json()
        assert body["translated_text"]
        assert body["source_lang"] == "en"
        assert body["target_lang"] == "ur"

    def test_turn_flips_direction_for_speaker_b(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        stub_provider: StubProvider,
    ) -> None:
        conv = client.post(
            "/api/conversations",
            json={"lang_a": "en", "lang_b": "ur"},
            headers=auth_headers,
        ).json()
        r = client.post(
            f"/api/conversations/{conv['id']}/turns",
            json={"speaker": "b", "text": "السلام علیکم"},
            headers=auth_headers,
        )
        assert r.status_code == 201
        assert r.json()["source_lang"] == "ur"
        assert r.json()["target_lang"] == "en"

    def test_other_user_cannot_read_conversation(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        conv = client.post(
            "/api/conversations",
            json={"lang_a": "en", "lang_b": "ur"},
            headers=auth_headers,
        ).json()
        other = client.post(
            "/api/auth/register",
            json={"email": "conv-other@example.com", "password": "GoodPassword1"},
        ).json()
        other_headers = {"Authorization": f"Bearer {other['access_token']}"}
        assert (
            client.get(f"/api/conversations/{conv['id']}", headers=other_headers).status_code == 404
        )


class TestErrorShape:
    def test_404_has_code_and_message(self, client: TestClient) -> None:
        r = client.get("/api/nonexistent")
        assert r.status_code == 404
        assert "code" in r.json()["detail"]
        assert "message" in r.json()["detail"]

    def test_validation_error_lists_fields(self, client: TestClient) -> None:
        r = client.post("/api/translate", json={"text": "hi"})
        assert r.status_code == 422
        detail = r.json()["detail"]
        assert detail["code"] == "validation_error"
        assert isinstance(detail["fields"], list)
