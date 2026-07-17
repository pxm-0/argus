# Argus M3 GitHub Pages Origin

GitHub Pages is the independent public origin for the synthetic Argus
portfolio. The workflow consumes only the allowlisted snapshot and artifact
builder scripts. It has no server network access or operator API configuration.

The workflow creates a fresh Ed25519 signing key inside its ephemeral runner.
The private key is deleted when the run ends; the public key is represented by
the signed artifact provenance and the GitHub Actions run is the provenance
anchor. The workflow builds and verifies the signed artifact, records a
no-route mirror receipt, and deploys that artifact to Pages.
