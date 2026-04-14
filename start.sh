#!/usr/bin/env bash
set -e

umask "${UMASK:-022}"

init_conf() {
  local dir="/config"
  [[ -d "$dir" ]] || return 0

  rm -f "$dir/hosts" "$dir/hostname" "$dir/resolv.conf" 2>/dev/null || true

  local files=(gallery-dl.conf gallery-dl.yaml gallery-dl.yml gallery-dl.toml
               config.json config.yaml config.yml config.toml)
  for f in "${files[@]}"; do
    [[ -f "$dir/$f" ]] && return 0
  done

  mv -n /usr/src/app/docs/gallery-dl.conf "$dir" 2>/dev/null || true
}

init_conf

echo -e "\033[0;32mINFO:\033[0m     Starting process as UID=$(id -u) GID=$(id -g)"

# If running as root (legacy behaviour), drop to appuser via su-exec.
# When compose sets `user: "1000:1000"`, we start as that user directly.
if [[ "$(id -u)" -eq 0 ]]; then
  : "${UID:=1000}"
  : "${GID:=1000}"
  chown -R "$UID:$GID" /usr/src/app 2>/dev/null || true
  exec su-exec "$UID:$GID" python3 -m gallery_dl_server --port "$CONTAINER_PORT"
fi

exec python3 -m gallery_dl_server --port "$CONTAINER_PORT"
