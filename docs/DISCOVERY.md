# Argus Discovery

Generated: 2026-06-30T16:59:57Z
Scope: read-only discovery for Argus P0 on oreochiserver

## Key Findings

- Target host is Ubuntu 26.04 on `oreochiserver`; current operator user is `oreo`.
- Tailscale IPv4 is `100.75.210.83`.
- `/srv/argus` does not exist yet.
- Docker Compose projects detected: `hastur`, `intake-os`, and `uptime-kuma`.
- Additional running containers without Compose labels: `review-ui` and `dozzle`.
- Current public or broad listeners include `0.0.0.0:3000`, `0.0.0.0:4173`, and `0.0.0.0:54321`.
- Tailscale Funnel is currently on for `oreochiserver.tail0a3a58.ts.net` and proxies `/` to `127.0.0.1:8765`.
- `cloudflared` is not installed and `cloudflared.service` is not active.
- `dozzle` has `/var/run/docker.sock` mounted; P0 must not expose it publicly.

## Host
oreochiserver
  Static hostname: oreochiserver
        Icon name: computer-laptop
          Chassis: laptop
Chassis Asset Tag:  No  Asset  Tag
       Machine ID: <redacted>
          Boot ID: <redacted>
 Operating System: Ubuntu 26.04 LTS
           Kernel: Linux 7.0.0-22-generic
     Architecture: x86-64
  Hardware Vendor: ASUSTeK COMPUTER INC.
   Hardware Model: TUF Gaming FX505DT
 Hardware Version: 1.0
 Firmware Version: FX505DT.316
    Firmware Date: Thu 2021-01-28
     Firmware Age: 5y 5month 1d
Tue Jun 30 16:59:58 UTC 2026
 16:59:58 up 18 days, 20:22,  2 users,  load average: 0.10, 0.05, 0.01

## User
argus
uid=1000(argus) gid=1000(argus) groups=1000(argus),4(adm),24(cdrom),27(sudo),30(dip),46(plugdev),100(users),101(lxd),983(docker)

## Network Addresses
lo               UNKNOWN        127.0.0.1/8 ::1/128
enp2s0           UP             192.168.1.7/24 metric 100 fe80::d65d:64ff:fe65:e0d0/64
wlp4s0           UP             192.168.1.9/24 metric 600 fe80::7266:55ff:fe47:34c3/64
tailscale0       UNKNOWN        100.75.210.83/32 fd7a:115c:a1e0::2e38:d254/128 fe80::c54a:5714:7f6a:bd5d/64
br-33c3198db353  UP             172.18.0.1/16 fe80::9067:c5ff:fe96:d73f/64
br-5ae375f8cbec  DOWN           172.20.0.1/16
docker0          UP             172.17.0.1/16 fe80::bc11:c6ff:fe04:5108/64
br-f5cc4e950019  DOWN           172.19.0.1/16
vetha7b8a4e@if2  UP             fe80::84a7:41ff:fe8c:d46c/64
veth3e09684@if2  UP             fe80::ac25:4dff:fe7a:6ce2/64
br-da8565e68a1b  DOWN           172.22.0.1/16 fe80::9cac:abff:fe8a:b555/64
br-c3c3c77992e6  UP             172.23.0.1/16 fe80::30c7:1ff:fe0e:3df9/64
br-c49392d021e4  UP             172.21.0.1/16 fe80::8c35:d7ff:fee1:dcbd/64
vethb12e161@if2  UP             fe80::1481:cfff:fe11:5ed/64
veth43979f8@if2  UP             fe80::40a1:ffff:fea1:95f5/64
veth0100780@if2  UP             fe80::5826:14ff:fe5b:178f/64
vethc99326a@if2  UP             fe80::4842:c3ff:fe0c:33c1/64
veth732451f@if2  UP             fe80::74ed:31ff:fed9:9795/64
veth2d96f83@if2  UP             fe80::3099:e6ff:fe89:64aa/64

## Listening Ports
Netid State  Recv-Q Send-Q                      Local Address:Port  Peer Address:PortProcess
udp   UNCONN 0      0                              127.0.0.54:53         0.0.0.0:*                                         uid:990 ino:10761 sk:2007 cgroup:/system.slice/systemd-resolved.service <->
udp   UNCONN 0      0                           127.0.0.53%lo:53         0.0.0.0:*                                         uid:990 ino:10759 sk:2008 cgroup:/system.slice/systemd-resolved.service <->
udp   UNCONN 0      0                      192.168.1.9%wlp4s0:68         0.0.0.0:*                                         uid:998 ino:17932727 sk:2009 cgroup:/system.slice/systemd-networkd.service <->
udp   UNCONN 0      0                      192.168.1.7%enp2s0:68         0.0.0.0:*                                         uid:998 ino:17867693 sk:200a cgroup:/system.slice/systemd-networkd.service <->
udp   UNCONN 0      0                               127.0.0.1:323        0.0.0.0:*                                         ino:17227 sk:200b cgroup:/system.slice/chrony.service <->
udp   UNCONN 0      0                                 0.0.0.0:41641      0.0.0.0:*                                         ino:15625669 sk:200c cgroup:/system.slice/tailscaled.service <->
udp   UNCONN 0      0                                   [::1]:323           [::]:*                                         ino:17228 sk:200d cgroup:/system.slice/chrony.service v6only:1 <->
udp   UNCONN 0      0      [fe80::7266:55ff:fe47:34c3]%wlp4s0:546           [::]:*                                         uid:998 ino:15621956 sk:200e cgroup:/system.slice/systemd-networkd.service v6only:1 <->
udp   UNCONN 0      0      [fe80::d65d:64ff:fe65:e0d0]%enp2s0:546           [::]:*                                         uid:998 ino:14977826 sk:200f cgroup:/system.slice/systemd-networkd.service v6only:1 <->
udp   UNCONN 0      0                                    [::]:41641         [::]:*                                         ino:15625668 sk:2010 cgroup:/system.slice/tailscaled.service v6only:1 <->
tcp   LISTEN 0      4096                              0.0.0.0:4173       0.0.0.0:*                                         ino:15489105 sk:3001 cgroup:/system.slice/docker.service <->
tcp   LISTEN 0      4096                              0.0.0.0:54321      0.0.0.0:*                                         ino:832164 sk:1 cgroup:/system.slice/docker.service <->
tcp   LISTEN 0      4096                        100.75.210.83:443        0.0.0.0:*                                         ino:9290464 sk:2002 cgroup:/system.slice/tailscaled.service <->
tcp   LISTEN 0      4096                              0.0.0.0:3000       0.0.0.0:*                                         ino:17255347 sk:2011 cgroup:/system.slice/docker.service <->
tcp   LISTEN 0      4096                        100.75.210.83:40160      0.0.0.0:*                                         ino:22114 sk:3 cgroup:/system.slice/tailscaled.service <->
tcp   LISTEN 0      4096                        127.0.0.53%lo:53         0.0.0.0:*                                         uid:990 ino:10760 sk:4 cgroup:/system.slice/systemd-resolved.service <->
tcp   LISTEN 0      4096                              0.0.0.0:22         0.0.0.0:*                                         ino:15908 sk:5 cgroup:/system.slice/ssh.socket <->
tcp   LISTEN 0      5                               127.0.0.1:8766       0.0.0.0:*    users:(("python3",pid=1744879,fd=4)) uid:1000 ino:6523218 sk:1002 cgroup:/user.slice/user-1000.slice/user@1000.service/app.slice/dupe-review-ui.service <->
tcp   LISTEN 0      4096                            127.0.0.1:8765       0.0.0.0:*                                         ino:17329158 sk:2012 cgroup:/system.slice/docker.service <->
tcp   LISTEN 0      4096                           127.0.0.54:53         0.0.0.0:*                                         uid:990 ino:10762 sk:7 cgroup:/system.slice/systemd-resolved.service <->
tcp   LISTEN 0      4096                            127.0.0.1:8081       0.0.0.0:*                                         ino:20873 sk:8 cgroup:/system.slice/docker.service <->
tcp   LISTEN 0      4096                            127.0.0.1:8080       0.0.0.0:*                                         ino:13701799 sk:3002 cgroup:/system.slice/docker.service <->
tcp   LISTEN 0      4096                            127.0.0.1:5433       0.0.0.0:*                                         ino:17193856 sk:2013 cgroup:/system.slice/docker.service <->
tcp   LISTEN 0      200                             127.0.0.1:5432       0.0.0.0:*                                         uid:105 ino:10884764 sk:2004 cgroup:/system.slice/system-postgresql.slice/postgresql@18-main.service <->
tcp   LISTEN 0      4096                            127.0.0.1:2019       0.0.0.0:*                                         uid:999 ino:18924 sk:b cgroup:/system.slice/caddy.service <->
tcp   LISTEN 0      4096                                 [::]:4173          [::]:*                                         ino:15489106 sk:3003 cgroup:/system.slice/docker.service v6only:1 <->
tcp   LISTEN 0      4096                                 [::]:54321         [::]:*                                         ino:832165 sk:c cgroup:/system.slice/docker.service v6only:1 <->
tcp   LISTEN 0      4096                                 [::]:3000          [::]:*                                         ino:17255348 sk:2014 cgroup:/system.slice/docker.service v6only:1 <->
tcp   LISTEN 0      4096                                 [::]:22            [::]:*                                         ino:15910 sk:d cgroup:/system.slice/ssh.socket v6only:1 <->
tcp   LISTEN 0      4096                                    *:80               *:*                                         uid:999 ino:18926 sk:e cgroup:/system.slice/caddy.service v6only:0 <->
tcp   LISTEN 0      4096          [fd7a:115c:a1e0::2e38:d254]:443           [::]:*                                         ino:9292939 sk:2006 cgroup:/system.slice/tailscaled.service v6only:1 <->
tcp   LISTEN 0      4096          [fd7a:115c:a1e0::2e38:d254]:57162         [::]:*                                         ino:22116 sk:10 cgroup:/system.slice/tailscaled.service v6only:1 <->

## Tailscale
100.75.210.83   oreochiserver      pxm.0003@  linux    -
100.125.169.56  ipad161            pxm.0003@  iOS      -
100.97.144.94   iphone172          pxm.0003@  iOS      -
100.92.0.118    argus-mothership    pxm.0003@  windows  active; direct 192.168.1.19:41641, tx 89599268 rx 9335580
100.97.28.122   oreochibattleship  pxm.0003@  macOS    active; direct 192.168.1.11:41641, tx 31228628 rx 1345636

# Funnel on:
#     - https://oreochiserver.tail0a3a58.ts.net


### Tailscale IPv4
100.75.210.83

### Tailscale Serve

# Funnel on:
#     - https://oreochiserver.tail0a3a58.ts.net

https://oreochiserver.tail0a3a58.ts.net (Funnel on)
|-- / proxy http://127.0.0.1:8765


### Tailscale Funnel

# Funnel on:
#     - https://oreochiserver.tail0a3a58.ts.net

https://oreochiserver.tail0a3a58.ts.net (Funnel on)
|-- / proxy http://127.0.0.1:8765


## Docker
Client: Docker Engine - Community
 Version:           29.5.3
 API version:       1.54
 Go version:        go1.26.4
 Git commit:        d1c06ef
 Built:             Wed Jun  3 18:00:10 2026
 OS/Arch:           linux/amd64
 Context:           default

Server: Docker Engine - Community
 Engine:
  Version:          29.5.3
  API version:      1.54 (minimum version 1.40)
  Go version:       go1.26.4
  Git commit:       285b471
  Built:            Wed Jun  3 18:00:10 2026
  OS/Arch:          linux/amd64
  Experimental:     false
 containerd:
  Version:          v2.2.4
  GitCommit:        193637f7ee8ae5f5aa5248f49e7baa3e6164966e
 runc:
  Version:          1.3.5
  GitCommit:        v1.3.5-0-g488fc13e
 docker-init:
  Version:          0.19.0
  GitCommit:        de40ad0

### Containers
NAMES                     IMAGE                        STATUS                  PORTS
review-ui                 dupe-engine-worker:v0.10.9   Up 19 hours             127.0.0.1:8765->8765/tcp
intake-os-api-1           intake-os-api                Up 20 hours             0.0.0.0:3000->3000/tcp, [::]:3000->3000/tcp
intake-os-postgres-1      postgres:16-alpine           Up 21 hours (healthy)   127.0.0.1:5433->5432/tcp
intake-os-web-1           intake-os-web                Up 21 hours             3001/tcp
hastur                    hastur:local                 Up 2 days (healthy)     0.0.0.0:4173->4173/tcp, [::]:4173->4173/tcp
intake-os-local-proxy-1   caddy:2                      Up 3 days               80/tcp, 443/tcp, 2019/tcp, 443/udp, 127.0.0.1:8080->8080/tcp
uptime-kuma               louislam/uptime-kuma:1       Up 2 weeks (healthy)    0.0.0.0:54321->3001/tcp, [::]:54321->3001/tcp
dozzle                    amir20/dozzle:latest         Up 2 weeks              127.0.0.1:8081->8080/tcp

### Networks
NETWORK ID     NAME                                  DRIVER    SCOPE
3a5e29a9c6ea   bridge                                bridge    local
da8565e68a1b   dupe-engine-repo_default              bridge    local
f5cc4e950019   dupe_engine_v0_10_7_project_default   bridge    local
5ae375f8cbec   dupe_engine_v0_10_8_project_default   bridge    local
c3c3c77992e6   hastur_default                        bridge    local
22c7f26b8740   host                                  host      local
c49392d021e4   intake-os_default                     bridge    local
e9545877d526   none                                  null      local
33c3198db353   uptime-kuma_default                   bridge    local

### Volumes
DRIVER    VOLUME NAME
local     intake-os_caddy_config
local     intake-os_caddy_data
local     intake-os_intake_os_pgdata
local     intake-os_intake_os_postgres_data
local     uptime-kuma_uptime-kuma-data

### Compose Projects
NAME                STATUS              CONFIG FILES
hastur              running(1)          /home/oreo/hastur/compose.yml
intake-os           running(4)          /home/oreo/intake-os/docker-compose.yml,/home/oreo/intake-os/docker-compose.server.yml
uptime-kuma         running(1)          /srv/apps/uptime-kuma/docker-compose.yml

### Compose Labels
NAMES                     project       working dir             config files
review-ui
intake-os-api-1           intake-os     /home/oreo/intake-os    /home/oreo/intake-os/docker-compose.yml
intake-os-postgres-1      intake-os     /home/oreo/intake-os    /home/oreo/intake-os/docker-compose.yml
intake-os-web-1           intake-os     /home/oreo/intake-os    /home/oreo/intake-os/docker-compose.server.yml
hastur                    hastur        /home/oreo/hastur       /home/oreo/hastur/compose.yml
intake-os-local-proxy-1   intake-os     /home/oreo/intake-os    /home/oreo/intake-os/docker-compose.server.yml
uptime-kuma               uptime-kuma   /srv/apps/uptime-kuma   /srv/apps/uptime-kuma/docker-compose.yml
dozzle

### Container Mounts
/review-ui bind:/data/runs->/data/runs; bind:/data/review_ui_jobs->/data/review_ui_jobs;
/intake-os-api-1
/intake-os-postgres-1 volume:/var/lib/docker/volumes/intake-os_intake_os_pgdata/_data->/var/lib/postgresql/data;
/intake-os-web-1
/hastur bind:/home/oreo/.ssh->/root/.ssh; bind:/home/oreo/hastur/data->/app/data; bind:/home/oreo/hastur/auth->/app/auth;
/intake-os-local-proxy-1 volume:/var/lib/docker/volumes/intake-os_caddy_data/_data->/data; volume:/var/lib/docker/volumes/intake-os_caddy_config/_data->/config; bind:/home/oreo/intake-os/deploy/Caddyfile.server->/etc/caddy/Caddyfile;
/uptime-kuma volume:/var/lib/docker/volumes/uptime-kuma_uptime-kuma-data/_data->/app/data;
/dozzle bind:/var/run/docker.sock->/var/run/docker.sock;

## Caddy
active
enabled
● caddy.service - Caddy
     Loaded: loaded (/usr/lib/systemd/system/caddy.service; enabled; preset: enabled)
     Active: active (running) since Thu 2026-06-11 20:37:56 UTC; 2 weeks 4 days ago
 Invocation: 8401945d19284d459f0dd8ae8b616ac0
       Docs: https://caddyserver.com/docs/
   Main PID: 2012 (caddy)
      Tasks: 12 (limit: 19447)
     Memory: 48.2M (peak: 48.9M)
        CPU: 1min 38.046s
     CGroup: /system.slice/caddy.service
             └─2012 /usr/bin/caddy run --environ --config /etc/caddy/Caddyfile

Jun 20 20:37:56 oreochiserver caddy[2012]: {"level":"info","ts":1781987876.9118059,"logger":"tls","msg":"storage cleaning happened too recently; skipping for now","storage":"FileStorage:/var/lib/caddy/.local/share/caddy","instance":"c69cfdc8-8ba5-41da-be1d-6f3e53d2e5e7","try_again":1782074276.911793,"try_again_in":86399.999995111}
Jun 20 20:37:56 oreochiserver caddy[2012]: {"level":"info","ts":1781987876.9120247,"logger":"tls","msg":"finished cleaning storage units"}
Jun 21 20:37:56 oreochiserver caddy[2012]: {"level":"info","ts":1782074276.8583314,"logger":"tls","msg":"cleaning storage unit","storage":"FileStorage:/var/lib/caddy/.local/share/caddy"}
Jun 21 20:37:56 oreochiserver caddy[2012]: {"level":"info","ts":1782074276.8600209,"logger":"tls","msg":"finished cleaning storage units"}
Jun 22 20:37:56 oreochiserver caddy[2012]: {"level":"info","ts":1782160676.8262131,"logger":"tls","msg":"storage cleaning happened too recently; skipping for now","storage":"FileStorage:/var/lib/caddy/.local/share/caddy","instance":"c69cfdc8-8ba5-41da-be1d-6f3e53d2e5e7","try_again":1782247076.8262017,"try_again_in":86399.99999567}
Jun 22 20:37:56 oreochiserver caddy[2012]: {"level":"info","ts":1782160676.8264248,"logger":"tls","msg":"finished cleaning storage units"}
Jun 23 20:37:56 oreochiserver caddy[2012]: {"level":"info","ts":1782247076.8246052,"logger":"tls","msg":"cleaning storage unit","storage":"FileStorage:/var/lib/caddy/.local/share/caddy"}
Jun 23 20:37:56 oreochiserver caddy[2012]: {"level":"info","ts":1782247076.829749,"logger":"tls","msg":"finished cleaning storage units"}
Jun 24 20:37:56 oreochiserver caddy[2012]: {"level":"info","ts":1782333476.9216816,"logger":"tls","msg":"cleaning storage unit","storage":"FileStorage:/var/lib/caddy/.local/share/caddy"}
Jun 24 20:37:56 oreochiserver caddy[2012]: {"level":"info","ts":1782333476.926805,"logger":"tls","msg":"finished cleaning storage units"}
Jun 25 20:37:56 oreochiserver caddy[2012]: {"level":"info","ts":1782419876.8223596,"logger":"tls","msg":"storage cleaning happened too recently; skipping for now","storage":"FileStorage:/var/lib/caddy/.local/share/caddy","instance":"c69cfdc8-8ba5-41da-be1d-6f3e53d2e5e7","try_again":1782506276.8223472,"try_again_in":86399.999995251}
Jun 25 20:37:56 oreochiserver caddy[2012]: {"level":"info","ts":1782419876.8225734,"logger":"tls","msg":"finished cleaning storage units"}
Jun 26 20:37:56 oreochiserver caddy[2012]: {"level":"info","ts":1782506276.9245372,"logger":"tls","msg":"cleaning storage unit","storage":"FileStorage:/var/lib/caddy/.local/share/caddy"}
Jun 26 20:37:56 oreochiserver caddy[2012]: {"level":"info","ts":1782506276.93011,"logger":"tls","msg":"finished cleaning storage units"}
Jun 27 20:37:56 oreochiserver caddy[2012]: {"level":"info","ts":1782592676.9188857,"logger":"tls","msg":"storage cleaning happened too recently; skipping for now","storage":"FileStorage:/var/lib/caddy/.local/share/caddy","instance":"c69cfdc8-8ba5-41da-be1d-6f3e53d2e5e7","try_again":1782679076.9188747,"try_again_in":86399.99999567}
Jun 27 20:37:56 oreochiserver caddy[2012]: {"level":"info","ts":1782592676.919094,"logger":"tls","msg":"finished cleaning storage units"}
Jun 28 20:37:56 oreochiserver caddy[2012]: {"level":"info","ts":1782679076.8259838,"logger":"tls","msg":"cleaning storage unit","storage":"FileStorage:/var/lib/caddy/.local/share/caddy"}
Jun 28 20:37:56 oreochiserver caddy[2012]: {"level":"info","ts":1782679076.8316884,"logger":"tls","msg":"finished cleaning storage units"}
Jun 29 20:37:56 oreochiserver caddy[2012]: {"level":"info","ts":1782765476.9153469,"logger":"tls","msg":"cleaning storage unit","storage":"FileStorage:/var/lib/caddy/.local/share/caddy"}
Jun 29 20:37:56 oreochiserver caddy[2012]: {"level":"info","ts":1782765476.9171412,"logger":"tls","msg":"finished cleaning storage units"}
v2.11.4 h1:XKxkMTgNSizEvKG6QHue6cAsFOteU2qA61w2tKkCWi0=

## Git
git version 2.53.0
/srv/argus does not exist

## Cloudflare
cloudflared not found
inactive
not-found

## Existing Compose Files
/home/oreo/dupe-engine/docker-compose.worker.yml
/home/oreo/dupe-engine/docker-compose.yml
/home/oreo/hastur-upload/compose.yml
/home/oreo/hastur/compose.yml
/home/oreo/intake-os/docker-compose.server.yml
/home/oreo/intake-os/docker-compose.yml
/srv/apps/dupe-engine/dupe-engine-repo/docker-compose.worker.yml
/srv/apps/dupe-engine/dupe-engine-repo/docker-compose.yml
/srv/apps/dupe-engine/dupe_engine_v0_10_7_project/docker-compose.yml
/srv/apps/dupe-engine/dupe_engine_v0_10_8_project/docker-compose.yml
/srv/apps/hello-nginx/docker-compose.yml
/srv/apps/uptime-kuma/docker-compose.yml

## Existing Env Files, Names Only
/home/oreo/hastur-upload/.env.example
/home/oreo/hastur/.env
/home/oreo/hastur/.env.before-public-crawl
/home/oreo/hastur/.env.example
/home/oreo/intake-os/.env.example
/home/oreo/intake-os/.env.server
/home/oreo/intake-os/.env.server.example
/home/oreo/intake-os/apps/web/.env.local.example
/srv/apps/dupe-engine/dupe-engine-repo/.env
/srv/apps/dupe-engine/dupe_engine_v0_10_7_project/.env
/srv/apps/dupe-engine/dupe_engine_v0_10_7_project/.env.example
/srv/apps/dupe-engine/dupe_engine_v0_10_8_project/.env
/srv/apps/dupe-engine/dupe_engine_v0_10_8_project/.env.example

## Existing Workload-Like Paths
/home/oreo/.docker
/home/oreo/intake-os
/home/oreo/intake-os/apps
/srv/apps
/srv/apps/uptime-kuma
/srv/backups/postgres
