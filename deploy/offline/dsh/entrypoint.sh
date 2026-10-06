#!/bin/sh
# Home patch is re-applied on every start so config lives in the image/repo,
# while sessions/credentials persist in the /data volume.
set -e
mkdir -p "$DSH_HOME"
cp /opt/dsh/cordis.patch.yml "$DSH_HOME/cordis.patch.yml"
# Local plugins → web profile node_modules + declared dependency (re-synced every
# start so an existing /data volume picks up a rebuilt image).
PROFILE="$DSH_HOME/profiles/web"
if [ -f "$PROFILE/package.json" ]; then
  for src in /opt/dsh/plugins/*/; do
    pkg=$(basename "$src")
    rm -rf "$PROFILE/node_modules/$pkg"
    mkdir -p "$PROFILE/node_modules"
    cp -r "$src" "$PROFILE/node_modules/$pkg"
    node -e '
      const fs = require("fs"), f = process.argv[1], pkg = process.argv[2];
      const m = JSON.parse(fs.readFileSync(f, "utf8"));
      m.dependencies = m.dependencies || {};
      if (!m.dependencies[pkg]) { m.dependencies[pkg] = "file:/opt/dsh/plugins/" + pkg; fs.writeFileSync(f, JSON.stringify(m, null, 2) + "\n"); }
    ' "$PROFILE/package.json" "$pkg"
  done
fi
# Loopback only (dsh refuses 0.0.0.0: the UI has no auth and the agent has a
# bash tool). The compose service uses network_mode: host → srv01 127.0.0.1.
# Optional LAN exposure through the allowlisted L4 proxy (see lan-proxy.mjs).
if [ -n "$LAN_BIND" ]; then
  ( while true; do node /opt/dsh/lan-proxy.mjs; sleep 2; done ) &
fi
# shellcheck disable=SC2086 — DSH_TRUSTED_HOST is a space-separated list
TRUSTED=""
for h in ${DSH_TRUSTED_HOST:-localhost:3080}; do TRUSTED="$TRUSTED --trusted-host $h"; done
exec dsh --profile web --host 127.0.0.1 --port 3080 --no-open $TRUSTED "$@"
