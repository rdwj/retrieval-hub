# Configuring Llama Stack with OAuth authentication

By default, a `LlamaStackDistribution` in OpenShift AI 3 accepts
unauthenticated traffic from within the cluster. For production
environments, Red Hat recommends enabling OAuth 2.1 authentication so
that agent calls and tool invocations are subject to identity and
authorization checks.

## Prerequisites

Before enabling OAuth authentication on Llama Stack you need:

1. A reachable OAuth 2.1 authorization server. Keycloak is the most
   common choice in Red Hat environments and is used in the examples
   that follow, but any OpenID Connect provider with a JWKS endpoint
   works.
2. A Keycloak **realm** that your agent workloads will authenticate
   against. The example assumes a realm named `llamastack-demo`.
3. A Keycloak **client** for Llama Stack with direct access grants
   enabled. The example uses client id `llamastack`.
4. A Keycloak **role** that grants access to restricted resources.
   The example uses `inference_max`.
5. A Keycloak **protocol mapper** on the client that adds the
   authenticated user's realm roles to the access token under the
   claim name `llamastack_roles`.

## Llama Stack run.yaml configuration

Under the `server.auth` block of the distribution's `run.yaml`:

```yaml
server:
  auth:
    provider_type: oauth2_token
    config:
      jwks:
        uri: https://keycloak.example.com/realms/llamastack-demo/protocol/openid-connect/certs
      issuer: https://keycloak.example.com/realms/llamastack-demo
      audience: llamastack
```

With this configuration, Llama Stack validates every incoming request's
bearer token against the Keycloak JWKS, verifies the `iss` and `aud`
claims, and reads the `llamastack_roles` claim to determine what
restricted capabilities the caller is authorized to use.

## Token exchange and downstream calls

When Llama Stack invokes a downstream MCP server registered as a
toolgroup, the caller's token is forwarded or exchanged depending on
the gateway configuration. In clusters running **Kagenti** in front of
retrieval-hub MCP servers, the gateway performs RFC 8693 token exchange
to mint an audience-scoped downstream token before forwarding, so the
receiving MCP server only sees a token bound to its own hostname.
