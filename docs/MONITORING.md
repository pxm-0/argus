# Monitoring: btop-Style Toggle

## Goal

Provide a btop-inspired monitor panel in the private dashboard without embedding a terminal or exposing sensitive host data.

## Architecture

```text
systemd timer
      |
      v
collect_metrics.py
      |
      v
control-plane/dashboard/public/metrics.json
      |
      v
dashboard monitor toggle
```

## Dashboard Behavior

The monitor panel is hidden by default.

Button states:

```text
Show Monitor
Hide Monitor
```

When open, dashboard fetches `/metrics.json` every `refreshSeconds` from `monitoring.json`.

When closed, dashboard stops fetching metrics.

## Metrics to Show

P0 metrics:

- timestamp
- hostname
- uptime seconds
- load average
- CPU percent
- memory total/used/percent
- swap total/used/percent
- disk total/used/percent for `/`
- network rx/tx by interface
- Docker container status
- Docker stats if available
- safe top processes by process name only
- thermal temperature if available

## Forbidden Data

The collector must not read or expose:

- environment variables
- process command-line arguments
- container env
- Docker inspect output
- secret files
- `.env` contents
- tokens
- database connection strings

Allowed commands:

```bash
docker ps --format '{{json .}}'
docker stats --no-stream --format '{{json .}}'
ps -eo pid,comm,%cpu,%mem --sort=-%cpu
```

Disallowed commands:

```bash
env
printenv
docker inspect
cat /proc/*/environ
ps aux
ps -ef
```

## Metrics JSON Shape

```json
{
  "timestamp": "2026-06-30T00:00:00Z",
  "hostname": "oreochiserver",
  "uptimeSeconds": 123456,
  "load": {
    "one": 0.42,
    "five": 0.36,
    "fifteen": 0.31
  },
  "cpu": {
    "percent": 18.4
  },
  "memory": {
    "totalBytes": 16777216000,
    "usedBytes": 6291456000,
    "percent": 37.5
  },
  "disk": {
    "mount": "/",
    "totalBytes": 1000000000000,
    "usedBytes": 380000000000,
    "percent": 38.0
  },
  "docker": {
    "containers": [
      {
        "name": "uptime-kuma",
        "image": "louislam/uptime-kuma",
        "status": "Up 2 days"
      }
    ]
  },
  "processes": [
    {
      "pid": 1234,
      "name": "caddy",
      "cpuPercent": 1.2,
      "memoryPercent": 0.8
    }
  ]
}
```

## UI Layout

```text
+--------------------------------+
| CPU      ########..   34%       |
| RAM      #####.....   51%       |
| DISK     ###.......   28%       |
| LOAD     0.42 0.36 0.31         |
+--------------------------------+
| Containers                     |
| uptime-kuma       Up           |
| intake-os         Up           |
+--------------------------------+
| Top Processes                  |
| caddy             1.2%          |
| dockerd           0.8%          |
+--------------------------------+
```

Use plain CSS. No CDN. No external JS. No remote fonts.

## Systemd

Templates:

```text
templates/systemd/argus-metrics.service
templates/systemd/argus-metrics.timer
```

P0 install command:

```bash
sudo cp /srv/argus/systemd/argus-metrics.service /etc/systemd/system/argus-metrics.service
sudo cp /srv/argus/systemd/argus-metrics.timer /etc/systemd/system/argus-metrics.timer
sudo systemctl daemon-reload
sudo systemctl enable --now argus-metrics.timer
```

## Acceptance

```bash
python3 /srv/argus/control-plane/monitoring/collect_metrics.py
python3 -m json.tool /srv/argus/control-plane/dashboard/public/metrics.json >/dev/null
```

Then dashboard must show monitor only after toggle.
