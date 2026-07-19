# Argus M4 hello-nginx Fenced Cutover

This is the first real M4 move. It is limited to the stateless `hello-nginx`
demo and requires passing private preflight and cutover-plan evidence.

Run the review-only plan first:

```bash
sudo ./scripts/argus-m4-hello-nginx-cutover --plan
```

Applying is an intentional service change: it stops the legacy source, imports
its existing image into the isolated rootless daemon, and starts a minimal
image-only target service. The target has no host mount, published port, host
network, public route, or cross-domain route. Therefore the old local endpoint
`http://127.0.0.1:18080` is retired. Target validation is internal.

```bash
sudo ./scripts/argus-m4-hello-nginx-cutover --apply \
  --acknowledge-fenced-cutover \
  --acknowledge-local-endpoint-retirement
```

If target startup or validation fails, the tool stops the target and restores
the source automatically. A successful run records only redacted private
evidence under `runtime/argus/m4/`.
