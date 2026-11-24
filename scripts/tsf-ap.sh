#!/bin/sh
# tsf-ap.sh - 个人热点 (hostapd + dnsmasq + NAT), up/down 由 tsf-hotspot.service 调用
# 配置 /etc/tsf-ap.conf: AP_ENABLE AP_SSID AP_PSK AP_HW_MODE AP_CHANNEL
CONF=/etc/tsf-ap.conf
[ -f "$CONF" ] && . "$CONF"
: "${AP_ENABLE:=0}" "${AP_SSID:=TeslaSentry}" "${AP_PSK:=12345678}"
: "${AP_HW_MODE:=g}" "${AP_CHANNEL:=6}"
: "${AP_DNS1:=223.5.5.5}" "${AP_DNS2:=}"
STA=$(ls /sys/class/net | grep '^wl' | head -1)
AP=ap0
IW=$(command -v iw || echo /usr/sbin/iw)
pick_wan() {
    for n in $(ip -4 route show default 2>/dev/null | sed -n 's/.* dev \([^ ]*\).*/\1/p'); do
        case "$n" in end*|eth*) echo "$n"; return ;; esac
    done
    ip -4 route show default 2>/dev/null | sed -n 's/.* dev \([^ ]*\).*/\1/p' | head -1
}
WAN=$(pick_wan)
[ -n "$WAN" ] || WAN=end1
SUBNET=192.168.50

case "$1" in
up)
    if [ "$AP_ENABLE" = "auto" ]; then
        WIFI_ON=0
        [ -n "$STA" ] && $IW dev "$STA" link 2>/dev/null | grep -q 'Connected to' && WIFI_ON=1
        WIRED_ON=0
        ip -4 -o addr show "$WAN" 2>/dev/null | grep -q 'inet ' && WIRED_ON=1
        if [ "$WIFI_ON" = "1" ] || [ "$WIRED_ON" = "1" ]; then
            echo "auto mode: network present (wifi=$WIFI_ON wired=$WIRED_ON), hotspot stays off"
            exit 0
        fi
    elif [ "$AP_ENABLE" != "1" ]; then
        exit 0
    fi
    [ -n "$STA" ] || { echo "no wifi iface"; exit 1; }
    if [ ! -d "/sys/class/net/$AP" ]; then
        $IW dev "$STA" interface add "$AP" type __ap || exit 1
    fi
    ip link set "$AP" up
    ip addr replace "$SUBNET.1/24" dev "$AP"
    sysctl -w net.ipv4.ip_forward=1 >/dev/null
    mkdir -p /etc/hostapd /etc/dnsmasq.d
    {
        echo "interface=$AP"
        echo "driver=nl80211"
        echo "ssid=$AP_SSID"
        echo "hw_mode=$AP_HW_MODE"
        echo "channel=$AP_CHANNEL"
        echo "country_code=CN"
        echo "ieee80211d=1"
        echo "ieee80211n=1"
        [ "$AP_HW_MODE" = "a" ] && { echo "ieee80211ac=1"; echo "ieee80211h=1"; }
        echo "wmm_enabled=1"
        echo "auth_algs=1"
        echo "wpa=2"
        echo "wpa_key_mgmt=WPA-PSK"
        echo "rsn_pairwise=CCMP"
        echo "wpa_passphrase=$AP_PSK"
    } > /etc/hostapd/tsf-ap.conf
    ln -sf /etc/hostapd/tsf-ap.conf /etc/hostapd/hostapd.conf
    {
        echo "interface=$AP"
        echo "bind-interfaces"
        echo "listen-address=$SUBNET.1"
        echo "port=53"
        echo "no-resolv"
        echo "server=$AP_DNS1"
        [ -n "$AP_DNS2" ] && echo "server=$AP_DNS2"
        echo "cache-size=1000"
        echo "dhcp-authoritative"
        echo "dhcp-range=$SUBNET.100,$SUBNET.200,12h"
        echo "dhcp-option=3,$SUBNET.1"
        if [ -n "$AP_DNS2" ]; then
            echo "dhcp-option=6,$AP_DNS1,$AP_DNS2,$SUBNET.1"
        else
            echo "dhcp-option=6,$AP_DNS1,$SUBNET.1"
        fi
    } > /etc/dnsmasq.d/tsf-ap.conf
    sed -i 's|^DAEMON_CONF=.*|DAEMON_CONF=/etc/hostapd/tsf-ap.conf|' /etc/default/hostapd
    grep -q '^DAEMON_CONF=' /etc/default/hostapd || echo 'DAEMON_CONF=/etc/hostapd/tsf-ap.conf' >> /etc/default/hostapd
    systemctl unmask hostapd.service 2>/dev/null
    if [ "$AP_CHANNEL" -gt 14 ] 2>/dev/null; then
        FREQ=$((5000 + AP_CHANNEL * 5))
        PHY=$(basename "$(readlink /sys/class/net/$STA/phy80211)") 
        if $IW phy "$PHY" info 2>/dev/null | grep -E "\* ${FREQ}\.0 MHz" | grep -q 'no IR'; then
            echo "channel $AP_CHANNEL ($FREQ MHz) no IR on this card, skip hotspot"
            exit 0
        fi
    fi
    systemctl reset-failed hostapd.service 2>/dev/null
    systemctl restart hostapd.service
    systemctl is-active --quiet hostapd.service || { echo "hostapd failed to start"; exit 1; }
    # wpa_supplicant 重启后 ap0 可能被重建, 重申地址再拉 dnsmasq
    ip addr replace "$SUBNET.1/24" dev "$AP"
    systemctl restart dnsmasq.service
    IPT=/usr/sbin/iptables
    # 客户端默认路由可能走有线(end1)也可能走 WiFi(wlp1s0), 两条出口都要 NAT
    for o in end0 end1 wlp1s0; do
        $IPT -t nat -D POSTROUTING -o "$o" -j MASQUERADE 2>/dev/null
        $IPT -D FORWARD -i "$AP" -o "$o" -j ACCEPT 2>/dev/null
        $IPT -D FORWARD -i "$o" -o "$AP" -m state --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null
    done
    for w in end1 wlp1s0; do
        ip -4 -o addr show "$w" 2>/dev/null | grep -q 'inet ' || continue
        $IPT -t nat -A POSTROUTING -o "$w" -j MASQUERADE
        $IPT -A FORWARD -i "$AP" -o "$w" -j ACCEPT
        $IPT -A FORWARD -i "$w" -o "$AP" -m state --state RELATED,ESTABLISHED -j ACCEPT
    done
    echo "hotspot up: $AP_SSID ch$AP_CHANNEL ($AP_HW_MODE)"
    ;;
down)
    systemctl stop hostapd.service dnsmasq.service 2>/dev/null
    IPT=/usr/sbin/iptables
    for o in end0 end1 wlp1s0; do
        $IPT -t nat -D POSTROUTING -o "$o" -j MASQUERADE 2>/dev/null
        $IPT -D FORWARD -i "$AP" -o "$o" -j ACCEPT 2>/dev/null
        $IPT -D FORWARD -i "$o" -o "$AP" -m state --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null
    done
    if [ -d "/sys/class/net/$AP" ]; then
        ip link set "$AP" down 2>/dev/null
        $IW dev "$AP" del 2>/dev/null
    fi
    sysctl -w net.ipv4.ip_forward=0 >/dev/null
    echo "hotspot down"
    ;;
*)
    echo "usage: $0 up|down"; exit 2
    ;;
esac