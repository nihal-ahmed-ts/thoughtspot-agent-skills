"""Domo internal-API client for the `domo-cloud` (live) mode.

Authenticates to a Domo instance with a Developer Access Token (`X-DOMO-Developer-
Token`) and reads the objects the public Developer API does NOT expose — full card
definitions and Beast Modes — alongside datasets and pages.

IMPORTANT: these are Domo's **internal, undocumented** endpoints (the ones the Domo
web app itself calls). They work today but are unsupported and may change; the parser
treats every response as best-effort and flags what it cannot read. Only stdlib is
used so the client stays dependency-free.

The token is held in memory only — never logged or written to disk.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Optional


class DomoError(RuntimeError):
    pass


class DomoClient:
    def __init__(self, instance: str, token: str, timeout: int = 30) -> None:
        # instance like "https://acme.domo.com" (scheme optional)
        inst = instance.strip().rstrip("/")
        if not inst.startswith("http"):
            inst = "https://" + inst
        self.base = inst
        self._token = token
        self.timeout = timeout

    # -- low-level ---------------------------------------------------------
    def _headers(self) -> dict:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-DOMO-Developer-Token": self._token,
        }

    def _request(self, path: str, method: str = "GET",
                 body: Optional[Any] = None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.base + path, data=data, headers=self._headers(), method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            detail = e.read().decode()[:200]
            raise DomoError(f"{method} {path} -> HTTP {e.code}: {detail}") from None
        except urllib.error.URLError as e:
            raise DomoError(f"{method} {path} -> {e}") from None

    def _get(self, path: str) -> Any:
        return self._request(path, "GET")

    def _post(self, path: str, body: Any) -> Any:
        return self._request(path, "POST", body)

    # -- datasets ----------------------------------------------------------
    def list_datasets(self, limit: int = 200) -> list[dict]:
        d = self._get(f"/api/data/v3/datasources?limit={limit}")
        return (d or {}).get("dataSources", []) if isinstance(d, dict) else (d or [])

    def get_dataset_schema(self, dataset_id: str) -> dict:
        """Return {id, name, rows, columns:[{name,type}]} for a dataset.

        Tries the schema endpoint, then falls back to the datasource detail.
        Column type keys vary (type / dataType), normalised by the parser.
        """
        for path in (
            f"/api/data/v3/datasources/{dataset_id}/schemas/latest",
            f"/api/data/v3/datasources/{dataset_id}",
        ):
            try:
                return self._get(path)
            except DomoError:
                continue
        raise DomoError(f"no schema for dataset {dataset_id}")

    # -- pages / cards -----------------------------------------------------
    def list_pages(self, limit: int = 100) -> list[dict]:
        d = self._get(f"/api/content/v1/pages?limit={limit}")
        return d if isinstance(d, list) else (d or {}).get("pages", [])

    def get_page_stack(self, page_id: str) -> dict:
        """Page with its cards + collections (tabs) + title."""
        return self._get(f"/api/content/v3/stacks/{page_id}/cards?parts=metadata")

    def get_page_card_refs(self, page_id: str) -> list[dict]:
        """Lightweight list of a page's card refs (urn/id/type)."""
        d = self._get(f"/api/content/v1/pages/{page_id}/cards")
        return d if isinstance(d, list) else (d or {}).get("cards", [])

    def get_card_definitions(self, urns: list[str],
                             parts: str = "metadata,datasources,slicers,dateGrain") -> list[dict]:
        if not urns:
            return []
        d = self._get(f"/api/content/v1/cards?urns={','.join(urns)}&parts={parts}")
        return (d or {}).get("cards", []) if isinstance(d, dict) else (d or [])

    # -- beast modes -------------------------------------------------------
    def search_beast_modes(self, dataset_id: Optional[str] = None,
                           limit: int = 200) -> list[dict]:
        body: dict = {"limit": limit, "offset": 0}
        if dataset_id:
            body["dataSourceId"] = dataset_id
        try:
            d = self._post("/api/query/v1/functions/search", body)
        except DomoError:
            return []
        return (d or {}).get("results", []) if isinstance(d, dict) else []


# ---------------------------------------------------------------------------
# Profile resolution — mirrors ts_cli/tableau/client.py
# ---------------------------------------------------------------------------

def load_domo_profiles() -> list[dict]:
    """Load Domo profiles from ~/.claude/domo-profiles.json.

    Delegates to profile_ops.load_platform_profiles.
    """
    from ts_cli.profile_ops import load_platform_profiles
    return load_platform_profiles("domo")


def _resolve_domo_profile(profile_name: Optional[str]) -> dict:
    """Return a single profile dict by name, or the only profile if name is None."""
    from ts_cli.profile_ops import PROFILE_PATHS
    profiles = load_domo_profiles()
    if not profiles:
        raise SystemExit(
            f"No Domo profiles found in {PROFILE_PATHS['domo']}.\n"
            "Run /ts-profile-domo to add a profile."
        )
    if profile_name:
        for p in profiles:
            if p.get("name") == profile_name:
                return p
        raise SystemExit(
            f"Domo profile {profile_name!r} not found. "
            f"Known: {[p.get('name') for p in profiles]}"
        )
    if len(profiles) > 1:
        raise SystemExit(
            "Multiple Domo profiles configured — pass --profile. "
            f"Known: {[p.get('name') for p in profiles]}"
        )
    return profiles[0]


def _resolve_token(profile: dict) -> str:
    """Read the developer token — env var first, OS credential store fallback.

    The token is never written to disk or logged; it is held in memory only.
    """
    from ts_cli.profile_ops import derive_keychain_service, slugify

    env_var = profile.get("token_env", "")
    if env_var:
        val = os.environ.get(env_var, "")
        if val:
            return val

    service = derive_keychain_service("domo", slugify(profile["name"]))
    try:
        import keyring  # deferred import — graceful if not installed
        stored = keyring.get_password(service, "developer-token")
        if stored:
            return stored
    except Exception:  # noqa: BLE001 — keyring is optional and may fail on any backend
        pass

    raise SystemExit(
        f"No credential found for Domo profile {profile['name']!r}.\n"
        "Run /ts-profile-domo to configure credentials."
    )


def client_from_profile(profile_name: Optional[str] = None,
                        timeout: int = 30) -> DomoClient:
    """Build a DomoClient from a configured profile (see /ts-profile-domo)."""
    profile = _resolve_domo_profile(profile_name)
    instance = profile.get("instance") or profile.get("instance_url") or ""
    if not instance:
        raise SystemExit(
            f"Domo profile {profile['name']!r} has no 'instance' field.\n"
            "Re-add it with: ts profiles add --platform domo --field instance=https://<tenant>.domo.com ..."
        )
    return DomoClient(instance, _resolve_token(profile), timeout=timeout)
