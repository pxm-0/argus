# Argus M3 GitHub Pages Origin

GitHub Pages is the independent public origin for the synthetic Argus
portfolio. The workflow consumes only the allowlisted snapshot and artifact
builder scripts. It has no server network access or operator API configuration.

Configure the repository Actions secret ARGUS_PORTFOLIO_SIGNING_KEY with the
single-line base64 encoding of an Ed25519 private key before enabling
deployment. It is never committed or printed. The workflow builds and verifies
the signed artifact, records a no-route mirror receipt, and deploys that
artifact to Pages.
