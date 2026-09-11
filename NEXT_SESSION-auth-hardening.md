# Next Session -- Auth Hardening

## Epic: Auth hardening + Google Docs integration

Harden the auth layer with scope enforcement, configurable Google OAuth,
and Google Docs data sources with hybrid access verification (content
indexed in pgvector, access verified live via Drive API at query time).

Issues: #69 (closed this session), #24

## What landed this session (2026-09-11, session 1)

### Phase 1: Scope enforcement + Google auth hardening

**Scope enforcement (#69):** `can_access()` now enforces scope
requirements for retrieval-hub JWT identities. Scope gate is backward
compatible -- skips for Google OAuth tokens and auth-disabled callers.
`admin.read` covers all read-side scopes; `admin.write` covers everything.
6 new tests, all 25 policy tests pass.

**Google domain allowlist:** Replaced hardcoded `@redhat.com` check with
configurable `RETRIEVAL_HUB_GOOGLE_ALLOWED_DOMAINS` env var. Empty = allow
all domains. 4 new tests, all 28 auth integration tests pass.

**Extra OAuth scopes:** Added `RETRIEVAL_HUB_GOOGLE_EXTRA_SCOPES` env var
for configuring additional Google OAuth scopes (e.g., Drive API scopes
for the Google Docs integration).

**Token passthrough:** Verified that FastMCP's `AccessToken.token` holds
the raw Google access token, enabling downstream Drive API calls.

**Closed:** #69 -- Auth: scope enforcement in access control

## Next: Google Docs ingestion adapter (Phase 2)

Build the ingestion pipeline for Google Docs sources: fetch from Drive
API using a service account, parse, chunk, embed, store in pgvector
with `doc_id` per chunk.

### Steps

1. **Google Docs fetch adapter**
   New `src/retrieval_hub/ingestion/fetch_google_docs.py`. Uses
   `google-auth` + `google-api-python-client` (service account creds).
   Accepts doc IDs or folder ID. Exports as plain text via Drive export
   API. Returns `FetchedDocument` with `metadata["google_doc_id"]`.

2. **Schema: add `doc_id` column**
   Add nullable `doc_id TEXT` to pgvector table schema in `write.py`.
   Populated only for Google Docs sources. Indexed for access checks.

3. **Pipeline integration**
   Add `google_docs` to `SourceFamily` enum. Pipeline dispatches through
   fetch -> parse -> chunk -> embed -> write. Recipe schema:
   ```yaml
   origin:
     kind: google_docs
     folder_id: "1abc..."
     service_account_key_path: "/secrets/sa-key.json"
   ```

4. **Integration test**
   Mock Drive API responses. Verify end-to-end: fetch -> chunk -> write
   with doc_id preserved.

**Dependencies:** `google-auth`, `google-api-python-client` (add to
requirements).

## Remaining epic phases

### Phase 2: Google Docs ingestion adapter

Fetch from Drive API using service account, parse, chunk, embed, store
with doc_id per chunk.

**Definition of done:** Pipeline can ingest a Google Docs folder into
pgvector. Each chunk carries its source doc's file ID. Integration tests
with mocked Drive API.

**Dependencies:** Phase 1 complete (auth config for Google).

### Phase 3: Query-time Drive access verification

At query time, when results come from a Google Docs source, verify the
user's Google identity still has read access to each underlying doc via
Drive API.

**Definition of done:** `check_drive_access(token, file_id)` verifies
user access. Results filtered before return. Cached per (user, file_id)
with short TTL. Clear error when Drive scope is missing.

**Dependencies:** Phase 2 (doc_id in chunks), Phase 1 (token passthrough).

### Phase 4: Keycloak reference realm (#24)

Ship a reference Keycloak realm definition with client_credentials
clients and role mapping.

**Definition of done:** JSON realm export, documented in auth.md.

**Dependencies:** None (can be done anytime).
