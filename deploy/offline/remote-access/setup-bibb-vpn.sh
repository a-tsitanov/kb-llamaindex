#!/bin/bash
# Persistent L2TP/IPsec VPN "BIBB" on the gateway PC (.31, Ubuntu 26.04, systemd-networkd)
# so the offline cluster (10.10.113.0/24) and the GPU node (10.10.151.0/24) are
# reachable from it — and therefore from anywhere through the existing keygo
# reverse SSH tunnel:
#     ssh -p 2222 -L 4000:10.10.113.12:4000 user@158.160.224.22   # LLM on localhost:4000
#     ssh -J user@158.160.224.22:2222 pitcher@10.10.113.11          # cluster SSH
#
# SPLIT TUNNEL ONLY: no default route through the VPN (it would cut the keygo
# reverse tunnel and wg0), only the two /24s above.
#
# Run ONCE on .31:   sudo bash setup-bibb-vpn.sh
# Asks for the IPsec pre-shared key and the VPN password (stored root-only, 0600).
# Idempotent: re-running rewrites the configs and restarts the services.
set -euo pipefail

VPN_SERVER=109.167.225.58
VPN_USER=bic-ext-22
ROUTES="10.10.113.0/24 10.10.151.0/24"
PROBE=10.10.113.11

[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
step() { echo; echo "=== $*"; }

step "1. packages (strongswan IKEv1 PSK + xl2tpd + pppd)"
DEBIAN_FRONTEND=noninteractive apt-get install -y -q \
  strongswan-swanctl charon-systemd libcharon-extra-plugins xl2tpd ppp >/dev/null
echo ok

step "2. secrets (input hidden)"
if [ -f /etc/swanctl/conf.d/bibb-secrets.conf ] && [ "${RESET_SECRETS:-0}" != 1 ]; then
  echo "kept existing secrets (re-enter with: RESET_SECRETS=1 sudo -E bash $0)"
else
  read -rsp "IPsec pre-shared key (общий ключ L2TP): " PSK; echo
  read -rsp "VPN password for ${VPN_USER}: " VPNPASS; echo
  [ -n "$PSK" ] && [ -n "$VPNPASS" ] || { echo "empty secret"; exit 1; }
  umask 077
  cat > /etc/swanctl/conf.d/bibb-secrets.conf <<S
secrets {
  ike-bibb {
    id = ${VPN_SERVER}
    secret = "${PSK}"
  }
}
S
  # chap-secrets: client server secret ip
  grep -v "^\"\?${VPN_USER}\"\? " /etc/ppp/chap-secrets 2>/dev/null > /etc/ppp/chap-secrets.new || true
  printf '"%s" * "%s" *\n' "$VPN_USER" "$VPNPASS" >> /etc/ppp/chap-secrets.new
  mv /etc/ppp/chap-secrets.new /etc/ppp/chap-secrets
  chmod 600 /etc/swanctl/conf.d/bibb-secrets.conf /etc/ppp/chap-secrets
  unset PSK VPNPASS
  echo "stored (0600)"
fi

step "3. IPsec (IKEv1, PSK, transport mode for L2TP udp/1701)"
cat > /etc/swanctl/conf.d/bibb.conf <<C
connections {
  bibb {
    version = 1
    remote_addrs = ${VPN_SERVER}
    proposals = aes256-sha256-modp2048,aes256-sha1-modp2048,aes256-sha1-modp1024,aes128-sha1-modp1024,3des-sha1-modp1024,default
    encap = yes
    dpd_delay = 30s
    rekey_time = 8h
    local {
      auth = psk
    }
    remote {
      auth = psk
      id = %any
    }
    children {
      l2tp {
        mode = transport
        local_ts = dynamic[udp/l2tp]
        remote_ts = dynamic[udp/l2tp]
        esp_proposals = aes256-sha1,aes128-sha1,3des-sha1,aes256-sha256,default
        start_action = start
        dpd_action = restart
        close_action = start
      }
    }
  }
}
C
systemctl enable --now strongswan >/dev/null 2>&1 || systemctl enable --now strongswan-swanctl >/dev/null 2>&1 || true
swanctl --load-all || { echo "swanctl --load-all FAILED (see above)"; exit 1; }
echo ok

step "4. L2TP (xl2tpd) + PPP options (no default route, MTU 1280)"
cat > /etc/xl2tpd/xl2tpd.conf <<X
[global]
port = 1701

[lac bibb]
lns = ${VPN_SERVER}
pppoptfile = /etc/ppp/options.l2tpd.bibb
length bit = yes
autodial = yes
redial = yes
redial timeout = 15
max redials = 1000000
X
cat > /etc/ppp/options.l2tpd.bibb <<P
name ${VPN_USER}
remotename bibb
noauth
refuse-eap
refuse-pap
nodefaultroute
noipdefault
usepeerdns
noccp
mtu 1280
mru 1280
lcp-echo-interval 20
lcp-echo-failure 4
ipparam bibb
P
# routes for the cluster/GPU subnets only, added when the ppp link comes up
cat > /etc/ppp/ip-up.d/50-bibb-routes <<R
#!/bin/sh
[ "\$PPP_IPPARAM" = bibb ] || [ "\$6" = bibb ] || exit 0
for net in ${ROUTES}; do ip route replace "\$net" dev "\$PPP_IFACE" ; done
R
chmod 755 /etc/ppp/ip-up.d/50-bibb-routes
# do NOT let resolvconf/usepeerdns hijack the system DNS
rm -f /etc/ppp/ip-up.d/0000usepeerdns 2>/dev/null || true
echo ok

step "5. watchdog (every 2 min: if ${PROBE} unreachable, restart IPsec + L2TP)"
cat > /usr/local/sbin/bibb-vpn-watchdog <<W
#!/bin/sh
ping -c2 -W3 ${PROBE} >/dev/null 2>&1 && exit 0
logger -t bibb-vpn "probe ${PROBE} failed — restarting VPN"
swanctl --terminate --ike bibb >/dev/null 2>&1 || true
swanctl --initiate --child l2tp >/dev/null 2>&1 || true
sleep 3
systemctl restart xl2tpd
W
chmod 755 /usr/local/sbin/bibb-vpn-watchdog
cat > /etc/systemd/system/bibb-vpn-watchdog.service <<U
[Unit]
Description=BIBB VPN watchdog
After=network-online.target
[Service]
Type=oneshot
ExecStart=/usr/local/sbin/bibb-vpn-watchdog
U
cat > /etc/systemd/system/bibb-vpn-watchdog.timer <<T
[Unit]
Description=BIBB VPN watchdog every 2 minutes
[Timer]
OnBootSec=90s
OnUnitActiveSec=2min
[Install]
WantedBy=timers.target
T
systemctl daemon-reload
systemctl enable --now bibb-vpn-watchdog.timer >/dev/null
echo ok

step "6. connect"
swanctl --initiate --child l2tp 2>&1 | tail -2 || true
systemctl enable xl2tpd >/dev/null 2>&1
systemctl restart xl2tpd
for i in $(seq 1 30); do ip -br a | grep -q '^ppp' && break; sleep 2; done
ip -br a | grep '^ppp' || { echo "ppp link not up — see: journalctl -u xl2tpd -u strongswan -n 80"; exit 1; }
sleep 3
ip route | grep ppp
ping -c2 -W3 ${PROBE} && echo "VPN OK: ${PROBE} reachable"
echo; echo "default route (must still be wifi, not ppp):"; ip route show default
