# Argus M3 Portfolio Artifact

Argus M3 builds a deliberately isolated public portfolio. It does not deploy a
public route from oreochiserver, expose the operator dashboard, or start a
tunnel. Deployment to an independently hosted public origin remains an
explicit later operator action.

## Contract

The input is a small, synthetic-only JSON snapshot:

    {"version":1,"projects":[{"synthetic":true,"title":"Example project","summary":"A public-safe synthetic summary.","tags":["example"],"status":"Concept"}]}

It accepts no additional fields. Private field names and values that look like
addresses, URLs, credentials, host information, paths, ports, routes, logs, or
live APIs are rejected. The build produces exactly five files: index.html,
style.css, portfolio.json, provenance.json, and provenance.sig. There are no
source maps, scripts, live API clients, or operator assets.

An OpenSSL private signing key is required outside this repository. Create the
matching public key once, also outside the repository:

    openssl genpkey -algorithm ED25519 -out /secure/argus-portfolio.key
    openssl pkey -in /secure/argus-portfolio.key -pubout -out /secure/argus-portfolio.pub

Build and validate a candidate artifact:

    scripts/argus-m3-export --snapshot /secure/public-snapshot.json --output /secure/portfolio-artifact --signing-key /secure/argus-portfolio.key --public-key /secure/argus-portfolio.pub
    scripts/argus-m3-mirror-verify --artifact /secure/portfolio-artifact --public-key /secure/argus-portfolio.pub --receipt /secure/mirror-receipt.json
    scripts/argus-m3-promotion-verify --artifact /secure/portfolio-artifact --public-key /secure/argus-portfolio.pub --mirror-receipt /secure/mirror-receipt.json

The mirror receipt is digest-bound. Any changed artifact fails the final
promotion check. The receipt proves artifact verification only; the deployment
runbook must additionally record the independently hosted mirror's no-route
and return-network checks before a public origin can serve the artifact.
