#!/bin/sh
# Starts as root only to adopt the Docker socket's group and to give /data to the service user, then drops to that
# user with no capabilities. The socket's group differs between hosts, so it is read here instead of being configured.
set -eu
socket=/var/run/docker.sock
if [ ! -S "$socket" ]; then
    echo "llm4om: mount the host's Docker socket at $socket; the sandbox runs generated code in Docker." >&2
    exit 1
fi
# Data copied in with `docker compose cp` or left by another image may belong to someone else.
find /data ! -user llm4om -exec chown llm4om:llm4om {} +
exec setpriv --reuid=llm4om --regid=llm4om --groups="$(stat -c %g "$socket")" --no-new-privs -- "$@"
