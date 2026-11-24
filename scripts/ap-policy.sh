#!/bin/sh
# tsf-ap-policy.sh - 自动模式策略: WiFi 或有线任一可用 -> 热点关; 两者都无 -> 热点开
CONF=/etc/tsf-ap.conf
[ -f "$CONF" ] && . "$CONF"
[ "${AP_ENABLE:-0}" = "auto" ] || exit 0
STA=$(ls /sys/class/net | grep '^wl' | head -1)
# 有线接口名随内核变: 旧 Armbian 是 end0, Radxa BSP 是 end1; 按默认路由识别,
# 避免新系统上 auto 策略把已经插着网线的状态误判成“无网络”而白开热点。
pick_wan() {
    for n in $(ip -4 route show default 2>/dev/null | sed -n 's/.* dev \([^ ]*\).*/\1/p'); do
        case "$n" in end*|eth*) echo "$n"; return ;; esac
    done
    ip -4 route show default 2>/dev/null | sed -n 's/.* dev \([^ ]*\).*/\1/p' | head -1
}
WAN=$(pick_wan)
[ -n "$WAN" ] || WAN=end1
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