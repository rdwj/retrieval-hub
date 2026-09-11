# Next Session -- Auth Hardening

## Epic: Auth hardening + Google Docs integration

Harden the auth layer with scope enforcement, configurable Google OAuth,
and Google Docs data sources with hybrid access verification (content
indexed in pgvector, access verified live via Drive API at query time).

Issues: #69 (closed), #24

## What landed

### Session 1 (2026-09-11): Phase 1 -- Scope enforcement + Google auth
See session-summaries/2026-09-11-auth-hardening-gdocs-ingestion.md.

### Session 2 (2026-09-11): Phase 2 -- Google Docs ingestion adapter
Commit 0391631. Fetch adapter, doc_id column, pipeline integration,
CLI script, 8 tests. Full detail in session summary.

## Next: Query-time Drive access verification (Phase 3)

At query time, when results come from a Google Docs source, verify the
user's Google identity still has read access to each underlying doc via
the Drive API. This is the payoff: content is indexed once by a service
account, but access is enforced per-user at query time.

### Steps

1. **`check_drive_access(token, file_id) -> bool`**
   New function (likely in `src/retrieval_hub/policy/` or a new
   `src/retrieval_hub/integrations/google_drive.py`). Calls
   `files().get(fileId=file_id, fields="id")` with the user's OAuth
   token. Returns True if 200, False if 404/403. Wraps API errors.

2. **Cache access checks**
   Per `(user_email, file_id)` with short TTL (e.g. 5 minutes).
   `functools.lru_cache` or a simple dict with timestamp expiry.
   Drive API quota is 12,000 queries/100s -- uncached checks on every
   result chunk would exhaust it quickly.

3. **Filter results in the document adapter**
   In `src/retrieval_hub/adapters/document.py`, after retrieval, if the
   source family is `google_docs`, filter out chunks whose `doc_id`
   the user cannot access. The user's Google access token is available
   via `AccessToken.token` (verified in Phase 1).

4. **Handle missing Drive scope gracefully**
   If the user authenticated with Google but didn't grant Drive read
   scope, return a clear error rather than silent empty results.
   Check for `https://www.googleapis.com/auth/drive.readonly` in the
   token's scopes.

5. **Tests**
   - Mock Drive API for access checks (allowed, denied, error)
   - Test result filtering (mixed accessible/inaccessible chunks)
   - Test cache behavior (repeated checks don't hit API)
   - Test missing-scope error path

### Dependencies
- Phase 2 complete (doc_id in chunks) -- done
- Phase 1 complete (token passthrough) -- done

### Blockers / pre-work
- The `doc_id` column exists in the DDL but not in existing cluster
  tables. Before deploying, run `ALTER TABLE idx_<name>_<suffix>
  ADD COLUMN IF NOT EXISTS doc_id TEXT` on each existing table, or
  use the next re-ingestion as the opportunity.

## Remaining epic phases

### Phase 3: Query-time Drive access verification
(See "Next" above.)

**Definition of done:** `check_drive_access(token, file_id)` verifies
user access. Results filtered before return. Cached per (user, file_id)
with short TTL. Clear error when Drive scope is missing.

### Phase 4: Keycloak reference realm (#24)

Ship a reference Keycloak realm definition with client_credentials
clients and role mapping.

**Definition of done:** JSON realm export, documented in auth.md.

**Dependencies:** None (can be done anytime).
