#!/bin/sh
# tslbox: 飞书 API 专用路由，走 4G(end1)。
# 盒子默认路由在 wlp1s0 上；该网络当前无外网时，飞书 API 会报 No route to host。
# 这里只把飞书 CDN 的 112.28/112.29 网段固定到 4G 网关，不影响局域网/Tailscale。
set -u
IP_BIN=/usr/bin/ip
GW=192.168.70.1
IF=end1
for _ in $(seq 1 30); do
    if "$IP_BIN" -4 addr show dev "$IF" 2>/dev/null | grep -q "192.168.70."; then
        break
    fi
    sleep 2
done
"$IP_BIN" route replace 112.28.0.0/16 via "$GW" dev "$IF" 2>/dev/null || true
"$IP_BIN" route replace 112.29.0.0/16 via "$GW" dev "$IF" 2>/dev/null || true
