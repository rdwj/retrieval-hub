"""retrieval-hub-auth: auth service for the retrieval-hub platform.

Issues short-lived JWTs via OAuth 2.1 ``client_credentials``, serves a JWKS
endpoint, and provides the validator library used by downstream consumers
(``retrieval-hub-mcp``, the UI BFF, the SDK).

See ``docs/auth.md`` in the repo root for the full design.
"""

from __future__ import annotations

__version__ = "0.0.1"
