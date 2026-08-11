"""Authenticated, bounded Docker observations for one rootless trust domain."""

from __future__ import annotations

import os
import signal
import sys
import threading
from pathlib import Path

from argus_docker_collector import (
    DockerCollectorError,
    RootfulDockerCollectorServer,
    load_runtime_source,
)
from argus_observations import ObservationError


def main() -> int:
    source_id = os.environ["ARGUS_SOURCE_ID"]
    registry_path = Path(os.environ["ARGUS_SOURCE_REGISTRY"])
    stop = threading.Event()
    try:
        source = load_runtime_source(
            registry_path,
            uid=int(os.environ.get("ARGUS_SOURCE_CONFIG_UID", "0")),
            gid=int(os.environ["ARGUS_SOURCE_CONFIG_GID"]),
            mode=int(os.environ.get("ARGUS_SOURCE_CONFIG_MODE", "0640"), 8),
            expected_source_ids={source_id},
            expected_host_sources=(source_id,),
        )
        server = RootfulDockerCollectorServer(
            source,
            client_uid=int(os.environ["ARGUS_COLLECTOR_CLIENT_UID"]),
            client_gid=int(os.environ["ARGUS_COLLECTOR_CLIENT_GID"]),
            docker_socket=os.environ["ARGUS_DOCKER_SOCKET"],
            docker_socket_uid=int(os.environ["ARGUS_DOCKER_SOCKET_UID"]),
            docker_socket_gid=int(os.environ["ARGUS_DOCKER_SOCKET_GID"]),
            docker_socket_mode=int(os.environ.get("ARGUS_DOCKER_SOCKET_MODE", "0660"), 8),
            daemon_uid=int(os.environ["ARGUS_DOCKER_DAEMON_UID"]),
            daemon_gid=int(os.environ["ARGUS_DOCKER_DAEMON_GID"]),
        )
        signal.signal(signal.SIGTERM, lambda _signum, _frame: stop.set())
        signal.signal(signal.SIGINT, lambda _signum, _frame: stop.set())
        server.serve_forever(stop)
    except (DockerCollectorError, ObservationError, OSError, ValueError, KeyError):
        print("ROOTLESS_DOCKER_COLLECTOR_FAIL reason=collector-contract", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
