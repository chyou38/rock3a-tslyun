#!/bin/sh
# tsf-ap-policy.sh - 自动模式策略: WiFi 或有线任一可用 -> 热点关; 两者都无 -> 热点开
CONF=/etc/tsf-ap.conf
[ -f "$CONF" ] && . "$CONF"
[ "${AP_ENABLE:-0}" = "auto" ] || exit 0
STA=$(ls /sys/class/net | grep '^wl' | head -1)
WAN=end0
WIFI_ON=0
[ -n "$STA" ] && iw dev "$STA" link 2>/dev/null | grep -q 'Connected to' && WIFI_ON=1
WIRED_ON=0
ip -4 -o addr show "$WAN" 2>/dev/null | grep -q 'inet ' && WIRED_ON=1
DESIRED=0
[ "$WIFI_ON" = "0" ] && [ "$WIRED_ON" = "0" ] && DESIRED=1
ACTIVE=$(systemctl is-active tsf-hotspot 2>/dev/null)
if [ "$DESIRED" = "1" ] && [ "$ACTIVE" != "active" ]; then
    systemctl start tsf-hotspot 2>/dev/null && logger -t tsf-ap-policy "hotspot ON (no network)"
elif [ "$DESIRED" = "0" ] && [ "$ACTIVE" = "active" ]; then
    systemctl stop tsf-hotspot 2>/dev/null && logger -t tsf-ap-policy "hotspot OFF (wifi=$WIFI_ON wired=$WIRED_ON)"
fi
exit 0