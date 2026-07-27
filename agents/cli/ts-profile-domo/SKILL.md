---
name: ts-profile-domo
description: Set up and manage Domo connection profiles for the Domo → ThoughtSpot converter. Use when configuring a new Domo instance for dashboard migration, updating credentials, or testing whether an existing profile works. Supports OAuth2 client-credentials (client_id + client_secret) and access-token auth. Credentials are stored securely in the OS keychain.
---

# Domo Profile Setup

Manage Domo connection profiles used by `ts-convert-from-domo` (`--mode domo-cloud`). Credentials
are stored in the OS keychain (macOS Keychain / Windows Credential Manager / Linux Secret
Service) via the `ts` CLI — never written to a file or echoed in this conversation.

Ask one question at a time for **dependent** decisions (auth flows are sequential). Batch
**independent** questions — e.g. profile name + instance URL can be collected together.

---

## Prerequisites

- `ts` CLI installed: `pip install -e tools/ts-cli`
- A Domo instance and a **Domo API client** (Domo → Admin → Authentication → Client Management →
  *New Client*), which yields a **client_id** and **client_secret**.
- Scopes: request at least **`data`** (dataset schema) and the scopes needed to read **card and
  page definitions** (`dashboard` / content scopes). See `../ts-convert-from-domo/references/open-items.md`
  item #2 — confirm scope coverage against your tenant, since card *definition* access can require
  more than the public Datasets scope.

---

## On Invocation

Ask: **Add, List, Test, or Remove a Domo profile?**

## Add

### Step 1 — Collect profile details (batch)
- **Profile name** (e.g. `acme-domo`)
- **Instance URL** (e.g. `https://acme.domo.com`)
- **Auth method**: `client-credentials` (client_id + client_secret) — recommended — or
  `access-token`.

### Step 2 — Collect credentials (in the user's terminal, never here)
Direct the user to store the secret via the CLI so it lands in the keychain, not the transcript:
```bash
ts profile domo add --name <profile> --instance <url> --auth client-credentials
# CLI prompts for client_id / client_secret (hidden) and stores them in the keychain
```
For token auth: `--auth access-token` (CLI prompts for the token).

### Step 3 — Token exchange note
`client-credentials` exchanges client_id/secret for a short-lived bearer token at
`POST https://api.domo.com/oauth/token?grant_type=client_credentials&scope=<scopes>` — the `ts`
CLI performs and caches this automatically; the user never handles the bearer token.

## Test
```bash
ts profile domo test --name <profile>
```
Verifies the credentials exchange for a token and a sample dataset-schema call succeeds. Reports
which scopes resolved (flag if card/page scopes are missing).

## List
```bash
ts profile domo list
```
Shows profile names + instance URLs only — never secrets.

## Remove
```bash
ts profile domo remove --name <profile>
```
Deletes the keychain entry.

---

## Guardrails
- Never enter client_secret / tokens in this conversation — always via the CLI prompt into the
  keychain.
- `list` / logs never print secrets.

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 0.1.0 | (scaffold) | Profile skill structure — CLI `ts profile domo` impl pending |
