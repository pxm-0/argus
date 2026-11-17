# Config Model

P0 separates workload identity from privacy and access policy.

## Files

```text
config/workloads.json   # app/runtime identity
config/privacy.json     # current privacy classification
config/access.json      # reviewed desired access and a non-Cloudflare effective baseline
config/access.effective.json  # server-applied effective access (ignored; D028)
config/policy.json      # guardrails and transition rules
config/routes.json      # current route definitions
config/exposure.json    # provider capabilities and Cloudflare planning
config/monitoring.json  # monitoring behavior
```

## `workloads.json`

Purpose: describe the workload as a neutral unit.

Must contain:

- id
- name
- description
- lifecycle
- kind
- paths
- runtime
- network
- health
- actions
- migration

Must not contain permanent public/private/company/demo policy.

Example:

```json
{
  "version": 1,
  "workloads": [
    {
      "id": "intake-os",
      "name": "Intake OS",
      "description": "Application workload.",
      "lifecycle": "active",
      "kind": "web-app",
      "paths": {
        "root": "/srv/argus/workloads/intake-os",
        "source": "/srv/argus/workloads/intake-os/source",
        "manifest": "/srv/argus/workloads/intake-os/manifest.json",
        "legacy": "/home/oreo/intake-os"
      },
      "runtime": {
        "type": "docker-compose",
        "composePath": "/srv/argus/workloads/intake-os/source/docker-compose.server.yml",
        "composeProject": "intake-os",
        "service": ""
      },
      "network": {
        "localUrl": "http://127.0.0.1:8080",
        "internalPort": 8080
      },
      "health": {
        "enabled": true,
        "url": "http://127.0.0.1:8080/health",
        "expectedStatus": 200,
        "timeoutSeconds": 3
      },
      "actions": {
        "open": true,
        "health": true,
        "logs": false,
        "restart": false,
        "deploy": false,
        "accessToggle": true,
        "privacyToggle": true
      },
      "migration": {
        "status": "planned",
        "originalPath": "/home/oreo/intake-os",
        "compatibilitySymlink": false
      }
    }
  ]
}
```

## `privacy.json`

Purpose: current privacy classification.

Allowed states:

```text
unclassified
personal
internal
sensitive
restricted
```

Example:

```json
{
  "version": 1,
  "defaultPrivacy": "unclassified",
  "states": ["unclassified", "personal", "internal", "sensitive", "restricted"],
  "workloads": {
    "intake-os": {
      "privacy": "sensitive",
      "reason": "Initial operator classification.",
      "updatedAt": "",
      "updatedBy": "argus"
    },
    "uptime-kuma": {
      "privacy": "restricted",
      "reason": "Infrastructure/admin dashboard.",
      "updatedAt": "",
      "updatedBy": "argus"
    }
  }
}
```

## `access.json`

Purpose: reviewed desired access, URLs and an effective baseline (D028).

- `desired` and `urls` live only here and change only through a reviewed PR. `access.apply` from the
  dashboard, API or CLI may only re-apply the reviewed desired state.
- `effective`, `lastAppliedAt` and `lastError` here are a reviewed baseline. The baseline effective is
  `none`, `local` or `tailnet`, never a Cloudflare state (doctor and a unit test enforce it).
- The server never writes this file. The M1 access writer writes those three fields into the ignored
  `config/access.effective.json`:

  ```json
  {"version": 1, "workloads": {"<id>": {"effective": "<state>", "lastAppliedAt": "<iso>", "lastError": "<text>"}}}
  ```

  Exactly those keys, all strings, and the state must be in `states`. Every reader (policy, dashboard,
  admission, doctor, reconcile, `m1 verify`) sees the baseline merged with the overlay. A missing overlay
  gives the baseline; a malformed one makes every loader exit non-zero. Overlay entries for workloads
  that are not tracked are ignored and doctor warns about them.

Allowed states:

```text
none
local
tailnet
cloudflare-protected
cloudflare-public
```

Example:

```json
{
  "version": 1,
  "defaultAccess": "tailnet",
  "states": ["none", "local", "tailnet", "cloudflare-protected", "cloudflare-public"],
  "workloads": {
    "intake-os": {
      "desired": "tailnet",
      "effective": "tailnet",
      "urls": {
        "local": "http://127.0.0.1:8080",
        "tailnet": "https://oreochiserver.tail0a3a58.ts.net:8444",
        "cloudflare": ""
      },
      "lastAppliedAt": "",
      "lastError": ""
    }
  }
}
```

## `policy.json`

Purpose: guardrails.

Example:

```json
{
  "version": 1,
  "defaultDecision": "deny-public",
  "rules": {
    "allowDashboardPrivacyToggle": true,
    "allowDashboardAccessToggle": true,
    "requireConfirmationForCloudflareProtected": true,
    "requireConfirmationForCloudflarePublic": true,
    "requireSecondConfirmationForRestrictedPublic": true,
    "requireAuthForDashboardMutations": true,
    "allowRestrictedToCloudflarePublic": false,
    "allowSensitiveToCloudflarePublic": false,
    "allowRestrictedToCloudflareProtected": true,
    "allowSensitiveToCloudflareProtected": true,
    "allowUnclassifiedToCloudflarePublic": true,
    "allowTailnetForAll": true
  },
  "blockedTargets": ["postgres", "docker-socket", "host-ssh", "control-api"],
  "confirmationPhrases": {
    "cloudflare-public": "publish publicly",
    "restricted-cloudflare-public": "override restricted public exposure"
  }
}
```

## `routes.json`

Purpose: record dashboard and workload routes.

Tailnet workload routes use the Tailscale Serve standard (`mode: "tailscale-serve"`,
a `https://<magicdns-fqdn>:<port>` URL). See
[TAILSCALE_ACCESS_STANDARD.md](TAILSCALE_ACCESS_STANDARD.md).

Example:

```json
{
  "version": 1,
  "dashboard": {
    "bind": "tailscale",
    "port": 8088,
    "url": "http://oreochiserver:8088"
  },
  "api": {
    "bind": "127.0.0.1",
    "port": 8099,
    "public": false
  },
  "workloadRoutes": {
    "intake-os": {
      "tailnet": {
        "enabled": true,
        "mode": "tailscale-serve",
        "url": "https://oreochiserver.tail0a3a58.ts.net:8444"
      },
      "cloudflare": {
        "enabled": false,
        "hostname": "",
        "mode": "disabled",
        "requiresAuth": true
      }
    }
  }
}
```

## `exposure.json`

Purpose: provider capability/planning.

Example:

```json
{
  "version": 1,
  "defaultProvider": "tailscale",
  "providers": {
    "tailscale": {
      "enabled": true,
      "default": true,
      "notes": "Primary private access path."
    },
    "cloudflare": {
      "enabled": false,
      "provisioned": true,
      "default": false,
      "allowQuickTunnels": false,
      "allowNamedTunnels": false,
      "requireAccessPolicy": true,
      "configPath": "/srv/argus/cloudflare/planned-ingress.yml",
      "publicAllowlist": []
    }
  }
}
```

`publicAllowlist` lists `{"workloadId": "...", "hostnames": ["..."]}` entries: the
only routes that may ever become `cloudflare-protected` or `cloudflare-public`
effective (D027). Its only entry is `nodens-production` (`nodens.dev`, `www.nodens.dev`); any malformed entry allows nothing.

## `monitoring.json`

Purpose: metrics behavior.

Example:

```json
{
  "version": 1,
  "enabled": true,
  "mode": "snapshot",
  "refreshSeconds": 3,
  "dashboardToggle": true,
  "publicMetricsPath": "/srv/argus/control-plane/dashboard/public/metrics.json",
  "historyEnabled": true,
  "historyPath": "/srv/argus/runtime/metrics-history/metrics.jsonl",
  "include": {
    "cpu": true,
    "load": true,
    "memory": true,
    "disk": true,
    "network": true,
    "docker": true,
    "processes": true,
    "temperatures": true
  },
  "processes": {
    "limit": 8,
    "showCommandArgs": false
  },
  "security": {
    "redactSecrets": true,
    "doNotExposeEnv": true,
    "doNotExposeCommandArgs": true
  }
}
```
