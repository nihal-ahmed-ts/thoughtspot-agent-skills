"""Domo internal-API client for capturing a bundle.

Authenticates to a Domo instance with a Developer Access Token (`X-DOMO-Developer-
Token`) and reads the objects the public Developer API does NOT expose — card
metadata and Beast Modes — alongside datasets and pages.

IMPORTANT: these are Domo's **internal, undocumented** endpoints (the ones the Domo
web app itself calls). They work today but are unsupported and may change; every
response is treated as best-effort and what cannot be read is flagged.

Credential handling — the rules this module has to hold, and why
---------------------------------------------------------------
The token is a bearer credential in a *custom* header, which changes what the stdlib
does for you. All four of these were live defects found in review:

- **HTTPS is mandatory.** `if not inst.startswith("http")` accepted `http://` (it
  starts with "http"), so the token went out in cleartext. The scheme is now
  allowlisted, not sniffed.
- **Redirects are not followed.** urllib's default redirect handler rebuilds every
  header except `content-length`/`content-type` onto the new request, and whatever
  stripping it does for `Authorization` does not apply to `X-DOMO-Developer-Token`.
  A 302 to another origin therefore handed the token to that origin. Verified
  against two local servers; now refused.
- **The host is validated.** `https://acme.domo.com@example.com` connects to
  example.com while every UI string shows acme.domo.com; a bare `169.254.169.254`
  reaches cloud metadata; `https://evil.com/?x=` turns each path into a query
  parameter. Userinfo, query and fragment are rejected, and the path is built with
  `urljoin`-safe concatenation off a normalised origin.
- **Server text never reaches the terminal.** The response body was interpolated
  into the exception, which `ts domo signin` prints — so a host the operator was
  tricked into naming could echo the token back into their transcript. Only the
  status code and reason are surfaced now.

The token is resolved lazily (see `_resolve_token`) and is never held in a frame that
can raise before it is used, so it cannot be rendered into a traceback.
"""
from __future__ import annotations

import ipaddress
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Optional

# A Domo tenant is always reached over TLS. Anything else is refused rather than
# downgraded, because the credential travels in a header on every request.
_ALLOWED_SCHEMES = ("https",)


class DomoError(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect.

    The custom auth header would be replayed onto the redirect target, which the
    server chooses. There is no legitimate cross-origin redirect on these endpoints,
    so a redirect is an error rather than something to follow carefully.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        raise DomoError(
            f"refusing to follow an HTTP {code} redirect to {newurl!r}: the Domo "
            "developer token would be replayed onto that host. Check the instance URL.")


def normalise_instance(instance: str) -> str:
    """Validate a Domo instance URL and return its bare origin.

    Raises DomoError with the reason, rather than silently accepting something that
    sends the token somewhere unintended.
    """
    raw = (instance or "").strip()
    if not raw:
        raise DomoError("Domo instance is empty")
    if "://" not in raw:
        raw = "https://" + raw

    parts = urllib.parse.urlsplit(raw)
    if parts.scheme not in _ALLOWED_SCHEMES:
        raise DomoError(
            f"Domo instance must use https:// (got {parts.scheme!r}). The developer "
            "token is sent as a request header, so plain HTTP would expose it.")
    if "@" in parts.netloc:
        raise DomoError(
            "Domo instance must not contain credentials or a userinfo '@' section — "
            f"{raw!r} would connect to {parts.hostname!r}, not to the host shown "
            "before the '@'.")
    if parts.query or parts.fragment:
        raise DomoError(
            "Domo instance must be a bare host, with no query string or fragment "
            f"(got {raw!r}) — otherwise every API path becomes a query parameter.")
    if (parts.path or "").strip("/"):
        raise DomoError(
            f"Domo instance must be a bare host, with no path (got {raw!r}).")
    if not parts.hostname:
        raise DomoError(f"Domo instance has no host: {raw!r}")
    _reject_internal_host(parts.hostname)
    return f"{parts.scheme}://{parts.netloc}"


def _reject_internal_host(host: str) -> None:
    """Refuse loopback / link-local / private literals.

    A Domo tenant is SaaS and never on one of these, but `169.254.169.254` is the
    cloud metadata service and the rest are the usual SSRF pivots. Requiring HTTPS
    already blocks the plain-HTTP metadata endpoint; this closes the class rather
    than that one instance. There is deliberately no override flag.
    """
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return                     # a DNS name — nothing to classify here
    if (ip.is_loopback or ip.is_link_local or ip.is_private or ip.is_reserved
            or ip.is_multicast or ip.is_unspecified):
        raise DomoError(
            f"Domo instance must be a public tenant host (got {host!r}, which is a "
            "loopback/link-local/private address). A Domo tenant looks like "
            "https://<tenant>.domo.com.")


class DomoClient:
    def __init__(self, instance: str, token: Optional[str] = None,
                 timeout: int = 30, *,
                 token_provider: Optional[Callable[[], str]] = None) -> None:
        """`instance` is validated up front; the token is resolved lazily.

        Pass `token_provider` to defer resolution entirely (the profile path does),
        so the raw secret is never a local in a frame that could raise.
        """
        self.base = normalise_instance(instance)
        self._token = token
        self._token_provider = token_provider
        self.timeout = timeout
        self._opener = urllib.request.build_opener(_NoRedirect)

    # -- low-level ---------------------------------------------------------
    def _headers(self) -> dict:
        token = self._token if self._token is not None else (
            self._token_provider() if self._token_provider else "")
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-DOMO-Developer-Token": token,
        }

    def _url(self, path: str) -> str:
        """Join `path` onto the validated origin without letting it change host."""
        if not path.startswith("/"):
            path = "/" + path
        return self.base + path

    def _request(self, path: str, method: str = "GET",
                 body: Optional[Any] = None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self._url(path), data=data, headers=self._headers(), method=method)
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            # Status + reason only. The response BODY is attacker-controlled and
            # `ts domo signin` prints DomoError text to the operator's terminal.
            reason = str(getattr(e, "reason", "") or "")[:80]
            raise DomoError(f"{method} {path} -> HTTP {e.code} {reason}".rstrip()) from None
        except DomoError:
            raise
        except urllib.error.URLError as e:
            raise DomoError(f"{method} {path} -> {type(e).__name__}") from None
        except json.JSONDecodeError:
            raise DomoError(f"{method} {path} -> response was not JSON") from None

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


def _credential_present(profile: dict) -> bool:
    """Is a token obtainable for this profile? Returns a bool, never the value.

    Lets `client_from_profile` fail fast on a missing credential without binding the
    secret to a name, so the lazy-resolution guarantee still holds.
    """
    env_var = profile.get("token_env", "")
    if env_var and os.environ.get(env_var):
        return True
    from ts_cli.profile_ops import derive_keychain_service, slugify
    service = derive_keychain_service("domo", slugify(profile["name"]))
    try:
        import keyring
        return keyring.get_password(service, "developer-token") is not None
    except Exception:  # noqa: BLE001 — keyring is optional and may fail on any backend
        return False


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
    # Fail fast on a missing credential, but WITHOUT binding it: _credential_present
    # returns a bool. Resolution itself stays deferred, because passing the secret
    # positionally would make it a local in a frame that raises if `instance` is bad,
    # and typer<1 permits versions whose traceback panels render locals.
    if not _credential_present(profile):
        raise SystemExit(
            f"No credential found for Domo profile {profile['name']!r}.\n"
            "Run /ts-profile-domo to configure credentials.")
    return DomoClient(instance, token_provider=lambda: _resolve_token(profile),
                      timeout=timeout)
