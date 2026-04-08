# retrieval-hub-auth

Auth service for retrieval-hub. Issues short-lived JWTs via OAuth 2.1
`client_credentials`, serves a JWKS for downstream validators, and provides
the validator library that consumers like `retrieval-hub-mcp` import.

See [`docs/auth.md`](../docs/auth.md) for the full design, the token shape,
the four IdP backends, the scope set, and the security posture.

## Status

Step 2 skeleton per `docs/SYSTEMS.md`:

- `local` IdP backend only (Postgres-backed client registration)
- JWT issuance with the documented `rh_*` claim shape
- JWKS endpoint with rotation support
- Validator library that enforces audience, issuer, expiry, and signature
- Hard-coded rule: `admin.write` is never issued to agent or service identities

The three other backends (`openshift_oauth`, `oidc_external`,
`external_jwt_validator`) are stubbed out; they are the job of a later step.
`external_jwt_validator` is the production default in Kagenti deploys per
[`docs/integrations/README.md`](../docs/integrations/README.md).

## Development

```bash
make install    # create .venv and install the package
make test       # run pytest
make test-cov   # run pytest with coverage
make lint       # ruff check + mypy
make run-dev    # start uvicorn on localhost:8000 with ephemeral test keys
```

Environment variables (all prefixed `RETRIEVAL_HUB_AUTH_`):

- `DB_URL` — SQLAlchemy URL for the service's Postgres schema
- `ISSUER` — the `iss` claim we mint
- `AUDIENCE` — the `aud` claim we mint
- `SIGNING_KEY_PATH` — path to the active PEM private key
- `ADDITIONAL_PUBLIC_KEY_PATHS` — comma-separated list of PEM public keys for rotation
- `DEFAULT_TOKEN_LIFETIME_SECONDS` — default 900
- `BACKEND` — default `local` (only backend implemented in this step)
- `LOG_LEVEL` — default `INFO`
- `RATE_LIMIT_PER_CLIENT_PER_MINUTE` — default 60
