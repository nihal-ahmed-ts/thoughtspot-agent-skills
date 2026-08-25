"""Tests for Domo profile + developer-token resolution (ts-profile-domo).

Covers the contract the skill documents: the token resolves from the env var first,
falls back to the OS credential store, and is never persisted to the profile file.
"""
from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from ts_cli import profile_ops
from ts_cli.cli import app
from ts_cli.domo import client as domo_client

runner = CliRunner()


@pytest.fixture
def domo_profiles(tmp_path, monkeypatch):
    path = tmp_path / "domo-profiles.json"
    monkeypatch.setattr(
        profile_ops, "PROFILE_PATHS", {**profile_ops.PROFILE_PATHS, "domo": path}
    )
    return path


def _write(path, profiles):
    path.write_text(json.dumps(profiles))


class TestProfileResolution:
    def test_no_profiles_points_at_skill(self, domo_profiles):
        with pytest.raises(SystemExit) as e:
            domo_client.client_from_profile()
        assert "ts-profile-domo" in str(e.value)

    def test_single_profile_resolves_without_name(self, domo_profiles, monkeypatch):
        _write(domo_profiles, [{"name": "Acme", "instance": "https://acme.domo.com",
                                "auth": "developer-token",
                                "token_env": "DOMO_TOK_ACME"}])
        monkeypatch.setenv("DOMO_TOK_ACME", "tok-123")
        c = domo_client.client_from_profile()
        assert c.base == "https://acme.domo.com"
        assert c._headers()["X-DOMO-Developer-Token"] == "tok-123"

    def test_multiple_profiles_require_explicit_name(self, domo_profiles):
        _write(domo_profiles, [
            {"name": "A", "instance": "https://a.domo.com", "token_env": "T_A"},
            {"name": "B", "instance": "https://b.domo.com", "token_env": "T_B"},
        ])
        with pytest.raises(SystemExit) as e:
            domo_client.client_from_profile()
        assert "--profile" in str(e.value)

    def test_named_profile_selected(self, domo_profiles, monkeypatch):
        _write(domo_profiles, [
            {"name": "A", "instance": "https://a.domo.com", "token_env": "T_A"},
            {"name": "B", "instance": "https://b.domo.com", "token_env": "T_B"},
        ])
        monkeypatch.setenv("T_B", "tok-b")
        assert domo_client.client_from_profile("B").base == "https://b.domo.com"

    def test_unknown_profile_name_errors(self, domo_profiles):
        _write(domo_profiles, [{"name": "A", "instance": "https://a.domo.com"}])
        with pytest.raises(SystemExit) as e:
            domo_client.client_from_profile("nope")
        assert "not found" in str(e.value)

    def test_missing_instance_field_errors(self, domo_profiles, monkeypatch):
        _write(domo_profiles, [{"name": "A", "token_env": "T_A"}])
        monkeypatch.setenv("T_A", "tok")
        with pytest.raises(SystemExit) as e:
            domo_client.client_from_profile()
        assert "instance" in str(e.value)

    def test_scheme_added_when_missing(self, domo_profiles, monkeypatch):
        _write(domo_profiles, [{"name": "A", "instance": "acme.domo.com",
                                "token_env": "T_A"}])
        monkeypatch.setenv("T_A", "tok")
        assert domo_client.client_from_profile().base == "https://acme.domo.com"


class TestTokenResolution:
    def test_keychain_fallback_used_when_env_unset(self, domo_profiles, monkeypatch):
        _write(domo_profiles, [{"name": "Acme", "instance": "https://acme.domo.com",
                                "token_env": "DOMO_TOK_UNSET"}])
        monkeypatch.delenv("DOMO_TOK_UNSET", raising=False)

        calls = {}

        class FakeKeyring:
            @staticmethod
            def get_password(service, account):
                calls["service"] = service
                calls["account"] = account
                return "tok-from-keychain"

        monkeypatch.setitem(__import__("sys").modules, "keyring", FakeKeyring)
        c = domo_client.client_from_profile()
        assert c._headers()["X-DOMO-Developer-Token"] == "tok-from-keychain"
        assert calls == {"service": "domo-acme", "account": "developer-token"}

    def test_no_credential_anywhere_points_at_skill(self, domo_profiles, monkeypatch):
        _write(domo_profiles, [{"name": "Acme", "instance": "https://acme.domo.com",
                                "token_env": "DOMO_TOK_NONE"}])
        monkeypatch.delenv("DOMO_TOK_NONE", raising=False)

        class FakeKeyring:
            @staticmethod
            def get_password(service, account):
                return None

        monkeypatch.setitem(__import__("sys").modules, "keyring", FakeKeyring)
        with pytest.raises(SystemExit) as e:
            domo_client.client_from_profile()
        assert "ts-profile-domo" in str(e.value)


class TestSigninCommand:
    def test_signin_reports_reachability_without_printing_token(
        self, domo_profiles, monkeypatch
    ):
        _write(domo_profiles, [{"name": "Acme", "instance": "https://acme.domo.com",
                                "token_env": "DOMO_TOK_S"}])
        monkeypatch.setenv("DOMO_TOK_S", "super-secret-token")
        monkeypatch.setattr(domo_client.DomoClient, "list_datasets",
                            lambda self, limit=200: [{"id": "1"}, {"id": "2"}])
        monkeypatch.setattr(domo_client.DomoClient, "list_pages",
                            lambda self, limit=100: [{"id": "p1"}])

        result = runner.invoke(app, ["domo", "signin", "--profile", "Acme"])
        assert result.exit_code == 0, result.output
        out = json.loads(result.output)
        assert out["ok"] is True
        assert out["reachable"] == {"datasets": 2, "pages": 1}
        assert "super-secret-token" not in result.output

    def test_signin_exits_nonzero_when_nothing_reachable(
        self, domo_profiles, monkeypatch
    ):
        _write(domo_profiles, [{"name": "Acme", "instance": "https://acme.domo.com",
                                "token_env": "DOMO_TOK_F"}])
        monkeypatch.setenv("DOMO_TOK_F", "tok")

        def boom(self, **kwargs):
            raise domo_client.DomoError("HTTP 401: unauthorized")

        monkeypatch.setattr(domo_client.DomoClient, "list_datasets", boom)
        monkeypatch.setattr(domo_client.DomoClient, "list_pages", boom)

        result = runner.invoke(app, ["domo", "signin", "--profile", "Acme"])
        assert result.exit_code == 1
        assert "FAILED" in result.output
