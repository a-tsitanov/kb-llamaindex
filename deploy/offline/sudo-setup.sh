#!/bin/bash
# One-time root setup for the offline cluster. Run ON EACH SERVER as:
#
#   sudo bash ~/offline/stack/deploy/offline/sudo-setup.sh srv01   # on 10.10.113.11
#   sudo bash ~/offline/stack/deploy/offline/sudo-setup.sh srv02   # on 10.10.113.12
#   sudo bash ~/offline/stack/deploy/offline/sudo-setup.sh srv03   # on 10.10.113.13
#
# Idempotent: safe to re-run. Every step prints what it does; nothing touches
# the network config (srv03 /23 mask is only REPORTED — agree with the network team).
set -euo pipefail

ROLE="${1:?usage: sudo-setup.sh srv01|srv02|srv03}"
OFF=/home/pitcher/offline
NTP_SERVER=10.10.113.11
LAN=10.10.112.0/23        # covers 10.10.113.0/24 and srv03's /23

step() { echo; echo "=== $*"; }
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }

step "1. hostname + /etc/hosts"
case "$ROLE" in
  srv01) HN=ext22-srv01 ;; srv02) HN=ext22-srv02 ;; srv03) HN=ext22-srv03 ;;
  *) echo "bad role $ROLE"; exit 1 ;;
esac
if [ "$(hostnamectl --static)" != "$HN" ]; then
  hostnamectl set-hostname "$HN"
  sed -i "s/^127\.0\.1\.1.*/127.0.1.1 $HN/" /etc/hosts
  echo "hostname -> $HN"
fi
grep -q "ext22-srv01-lan" /etc/hosts || cat >> /etc/hosts <<'EOF'
10.10.113.11 ext22-srv01-lan srv01
10.10.113.12 ext22-srv02-lan srv02
10.10.113.13 ext22-srv03-lan srv03
EOF

step "2. checksums of the offline bundle"
(cd $OFF/debs && sha256sum -c --quiet SHA256SUMS) && echo "debs OK"

step "3. install packages (docker, chrony, pigz, rdma/opensm, ipmitool) — local .deb only"
# Plain dpkg: apt offline either prefers the archive URI or (with repos hidden)
# hits "Pathname to install is not absolute". The bundle is dependency-complete
# (verified with `apt-get -s`: 28 installs, 1 removal). chrony conflicts with
# systemd-timesyncd, so remove that first; dpkg orders the rest within one call.
if dpkg -s systemd-timesyncd >/dev/null 2>&1; then
  dpkg --remove systemd-timesyncd
fi
dpkg -i $OFF/debs/*.deb
dpkg --audit && echo "dpkg state clean"

step "4. docker: daemon.json + group"
mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": {"max-size": "50m", "max-file": "3"},
  "live-restore": true,
  "default-address-pools": [{"base": "172.30.0.0/16", "size": 24}],
  "default-ulimits": {"nofile": {"Name": "nofile", "Soft": 1048576, "Hard": 1048576}}
}
EOF
systemctl enable --now containerd docker
systemctl restart docker
usermod -aG docker pitcher
docker info --format 'docker {{.ServerVersion}} root={{.DockerRootDir}}'

step "5. sysctl"
cat > /etc/sysctl.d/90-kb.conf <<'EOF'
vm.max_map_count = 262144
vm.swappiness = 10
fs.file-max = 2097152
fs.inotify.max_user_watches = 524288
net.core.somaxconn = 4096
net.ipv4.tcp_keepalive_time = 300
EOF
sysctl --system >/dev/null && echo "sysctl applied"

step "6. NTP (chrony): srv01 = server for the LAN, srv02/03 = clients"
if [ "$ROLE" = srv01 ]; then
  cat > /etc/chrony/chrony.conf <<EOF
# no internet: srv01 is the time source for the cluster (local clock)
local stratum 8
allow $LAN
driftfile /var/lib/chrony/chrony.drift
makestep 1 -1
rtcsync
EOF
else
  cat > /etc/chrony/chrony.conf <<EOF
server $NTP_SERVER iburst
driftfile /var/lib/chrony/chrony.drift
makestep 1 -1
rtcsync
EOF
fi
systemctl enable --now chrony
systemctl restart chrony
sleep 3; chronyc tracking | grep -E "Reference|System time" || true

step "7. models -> /opt/models"
mkdir -p /opt/models
cp -n $OFF/models/*.gguf /opt/models/ 2>/dev/null || true
chmod 755 /opt/models; chmod 644 /opt/models/*.gguf
ls -la /opt/models

step "8. firewall"
if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
  ufw allow from $LAN
  echo "ufw: allowed $LAN"
else
  echo "ufw inactive — nothing to do"
fi

step "9. InfiniBand subnet manager (srv01 only)"
if [ "$ROLE" = srv01 ]; then
  systemctl enable --now opensm && sleep 5
  ibstat 2>/dev/null | grep -E "State|Rate" || true
fi

step "10. report (no changes)"
ip -br a | grep -v '^lo'
echo "netplan:"; grep -h -A3 "addresses" /etc/netplan/*.yaml 2>/dev/null || true
command -v storcli64 >/dev/null && storcli64 /c0 show || echo "storcli not installed (physical disks behind RAID unknown)"

echo; echo "DONE $ROLE. Re-login as pitcher (or run 'newgrp docker') to use docker without sudo."
