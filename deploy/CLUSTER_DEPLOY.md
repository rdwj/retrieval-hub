# Deploying RetrievalHub to a Fresh Cluster

End-to-end instructions for deploying the full RetrievalHub platform to an
OpenShift cluster. Covers infrastructure, secrets, services, and verification.

## Prerequisites

- `oc` CLI authenticated to the target cluster (`oc login`)
- Python 3.11+ with a venv: `pip install -e ".[dev]"` from the repo root
- `pg_isready` (from postgresql client tools) for migration health checks

For Google OAuth (optional):
- A Google Cloud project with OAuth 2.0 credentials (Web application type)
- The redirect URI configured in Google Cloud Console (see step 2)

## 1. Configure

Copy the env template and fill in cluster-specific values:

```bash
cp deploy/env.example deploy/.env
# Edit deploy/.env with your values
```

Required values:
- `CONTEXT` -- your OpenShift context name (`oc config get-contexts`)
- `POSTGRES_PASSWORD` -- change from the default for production

Optional values:
- `RETRIEVAL_HUB_GOOGLE_CLIENT_ID` and `_SECRET` -- enables Google OAuth
- `RETRIEVAL_HUB_AUTH_SIGNING_KEY_PATH` -- path to a PEM private key for
  persistent JWT signing (without this, the auth service generates an
  ephemeral key that doesn't survive pod restarts)
- `LLM_ENDPOINT_URL` -- vLLM endpoint for query rewriting and eval

## 2. Google OAuth setup (optional)

If you want interactive Google login for MCP clients:

1. Go to Google Cloud Console > APIs & Services > Credentials
2. Create an OAuth 2.0 Client ID (Web application)
3. Add authorized redirect URI -- you'll need the route URL, which is
   determined by your cluster. The format is:
   `https://retrieval-hub-mcp-retrieval-hub.apps.<cluster-domain>/auth/callback`
4. Copy the Client ID and Client Secret into your `deploy/.env`

The deploy script auto-detects the MCP route URL after deployment and
patches the `RETRIEVAL_HUB_GOOGLE_BASE_URL` env var on the MCP server.
You may need to update the Google Cloud Console redirect URI after the
first deploy once you know the actual route URL.

## 3. Deploy

Full platform deploy (infrastructure + all services):

```bash
make deploy-cluster CONTEXT=<your-context> ENV_FILE=deploy/.env
```

Or infrastructure only (databases, embedding models, migrations):

```bash
make deploy-cluster-infra CONTEXT=<your-context> ENV_FILE=deploy/.env
```

The deploy script is idempotent. Secrets are created only if they don't
already exist. Re-running won't overwrite existing secrets or lose data.

## What gets deployed

| Component | Type | Port | Route |
|-----------|------|------|-------|
| PostgreSQL + pgvector | StatefulSet | 5432 | internal |
| Embedding models (TEI, vLLM) | Deployments | 8080/8000 | internal |
| Auth service | Deployment | 8000 | internal |
| MCP server | Deployment | 8080 | external (TLS) |
| BFF | Deployment | 8080 | internal |
| EvalHub | Job (on-demand) | -- | -- |
| UI | Deployment | 8080 | external (TLS) |
| Model health probe | CronJob (5min) | -- | -- |

## Secrets

The deploy script creates these secrets from your env file if they don't
already exist:

| Secret | Keys | Created from |
|--------|------|-------------|
| `retrieval-hub-pg` | POSTGRES_USER, POSTGRES_PASSWORD, DB URLs | POSTGRES_USER, POSTGRES_PASSWORD |
| `retrieval-hub-auth` | DB_URL | Derived from PG credentials |
| `retrieval-hub-auth-signing-key` | signing.pem | RETRIEVAL_HUB_AUTH_SIGNING_KEY_PATH |
| `retrieval-hub-google-oauth` | Client ID, Client Secret | RETRIEVAL_HUB_GOOGLE_CLIENT_ID, _SECRET |

To update a secret after initial deployment:

```bash
oc delete secret <name> --context=<ctx> -n retrieval-hub
# Re-run the deploy, or create manually:
oc create secret generic <name> --from-literal=KEY=VALUE \
    --context=<ctx> -n retrieval-hub
# Restart the affected deployment:
oc rollout restart deployment/<name> --context=<ctx> -n retrieval-hub
```

## 4. Verify

After deployment completes, the script runs verification automatically.
To check manually:

```bash
# Health check
curl https://<mcp-route>/health

# OAuth discovery (if Google OAuth is enabled)
curl https://<mcp-route>/.well-known/oauth-authorization-server

# Auth enforcement (should return 401)
curl -s -o /dev/null -w "%{http_code}" https://<mcp-route>/mcp \
    -H 'Content-Type: application/json' \
    -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'
```

## 5. Connect with Claude Code

```bash
claude mcp add --transport http retrieval-hub https://<mcp-route>/mcp
```

Then open Claude Code, type `/mcp`, select `retrieval-hub`, and
authenticate with your Google account.

## Troubleshooting

**Secret was overwritten with empty values:**
The per-component `openshift.yaml` files should not contain Secret
resources. If a deploy script applies a manifest that includes a Secret
with empty `stringData`, it will overwrite your real secret. Delete the
empty secret, recreate it with real values, and restart the deployment.

**OAuth endpoints return 404:**
The MCP server's Route must not have a `path:` restriction. The OAuth
endpoints (`/authorize`, `/token`, `/auth/callback`) are served at the
root, not under `/mcp`. Check with:
`oc get route retrieval-hub-mcp -o jsonpath='{.spec.path}'`

**Google login rejected with "not in domain redhat.com":**
The MCP server restricts Google OAuth to `@redhat.com` emails. This is
enforced in `retrieval-hub-mcp/src/retrieval_hub_mcp/auth.py`. Change
`_ALLOWED_EMAIL_DOMAIN` to allow other domains.

**Pod OOMKilled after loading embedding model:**
Embedding models use much more memory than their on-disk size. See the
lesson learned in CLAUDE.md about container memory limits. Increase the
memory limit in the Deployment manifest.

## Manual step-by-step (for debugging)

If the automated deploy fails partway through, you can run individual
steps. The deploy-platform.sh script calls these in order:

```bash
CTX="--context=<your-context>"
NS="-n retrieval-hub"

# 1. Secrets (see "Secrets" section above)

# 2. Infrastructure
oc apply -f deploy/openshift/retrieval-hub/secret.yaml $CTX $NS
oc apply -f deploy/openshift/retrieval-hub/pvc.yaml $CTX $NS
oc apply -f deploy/openshift/retrieval-hub/init-configmap.yaml $CTX $NS
oc apply -f deploy/openshift/retrieval-hub/statefulset.yaml $CTX $NS
oc apply -f deploy/openshift/retrieval-hub/service.yaml $CTX $NS
oc apply -f deploy/openshift/retrieval-hub/embedding/ $CTX $NS

# 3. Migrations (port-forward to PG first)
oc port-forward statefulset/retrieval-hub-pg 15432:5432 $CTX $NS &
RETRIEVAL_HUB_DB_URL="postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:15432/retrievalhub" \
    alembic upgrade head

# 4. Seed model registry
python scripts/seed_model_endpoints.py --db-url "postgresql+psycopg://..."

# 5. Services (each has its own deploy.sh)
./retrieval-hub-auth/deploy.sh --context=<ctx>
./retrieval-hub-mcp/deploy.sh --context=<ctx>
./retrieval-hub-bff/deploy.sh --context=<ctx>
./retrieval-hub-evalhub/deploy.sh --context=<ctx>
./scripts/deploy-ui-live.sh --context=<ctx>
```
