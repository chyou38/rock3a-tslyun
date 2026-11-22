#!/bin/sh
# fan-control.sh - ROCK 3A 3-pin PWM 风扇座 (pwm8 m0) 温控启动
# 配置 /etc/default/pwm-fan 每轮热读: 网页保存立即生效, 无需重启服务。
# 模式: auto=温度曲线(带启停回差) / manual=固定占空比
# 用法: fan-control.sh          常驻温控循环
#       fan-control.sh --test N 全速转 N 秒 (默认10), 用于人工确认风扇接线
CONF=/etc/default/pwm-fan
load_conf() {
    [ -f "$CONF" ] && . "$CONF"
    : "${FAN_POLL:=10}"
    : "${FAN_PERIOD:=40000}"
    : "${FAN_HYST:=3000}"
    : "${FAN_CURVE:=45000:0 50000:35 60000:55 70000:80 75000:100}"
    : "${FAN_MODE:=auto}"
    : "${FAN_MANUAL_DUTY:=50}"
    # 数值校验: 配置行粘连/写坏时回退默认, 避免 sleep 非法值导致空转烧 CPU
    case "$FAN_POLL" in ''|*[!0-9]*) FAN_POLL=10 ;; esac
    case "$FAN_PERIOD" in ''|*[!0-9]*) FAN_PERIOD=40000 ;; esac
    case "$FAN_MANUAL_DUTY" in ''|*[!0-9]*) FAN_MANUAL_DUTY=50 ;; esac
    case "$FAN_HYST" in ''|*[!0-9]*) FAN_HYST=3000 ;; esac
}
load_conf

CHIP=$(ls -d /sys/devices/platform/fe6f0000.pwm/pwm/pwmchip* 2>/dev/null | head -1)
[ -n "$CHIP" ] || { echo "fan: pwm8 未启用 (缺 rock3a-pwm8-fan overlay?)"; exit 1; }
[ -d "$CHIP/pwm0" ] || echo 0 > "$CHIP/export"
P="$CHIP/pwm0"
echo "$FAN_PERIOD" > "$P/period" 2>/dev/null
echo normal > "$P/polarity" 2>/dev/null
echo 1 > "$P/enable"
set_duty() { echo $(( FAN_PERIOD * $1 / 100 )) > "$P/duty_cycle"; }

if [ "$1" = "--test" ]; then
    set_duty 100
    sleep "${2:-10}"
    exit 0
fi

TZ=
for z in /sys/class/thermal/thermal_zone*; do
    if [ "$(cat "$z/type" 2>/dev/null)" = "cpu-thermal" ]; then TZ="$z/temp"; break; fi
done
[ -n "$TZ" ] || { echo "fan: 找不到 cpu-thermal"; exit 1; }

last=-1
while :; do
    load_conf
    t=$(cat "$TZ")
    if [ "$FAN_MODE" = "manual" ]; then
        duty=$FAN_MANUAL_DUTY
    else
        set -- $FAN_CURVE
        OFF_T=${1%%:*}
        duty=100; prev_t=0; prev_d=0; first=1
        for pt in $FAN_CURVE; do
            tt=${pt%%:*}; dd=${pt##*:}
            if [ "$t" -le "$tt" ]; then
                if [ "$first" = 1 ]; then
                    duty=$dd
                else
                    duty=$(( prev_d + (dd - prev_d) * (t - prev_t) / (tt - prev_t) ))
                fi
                break
            fi
            prev_t=$tt; prev_d=$dd; first=0; duty=$dd
        done
        if [ "$last" -ge 0 ]; then
            # 启停回差: 避免在启动温度附近频繁启停
            if [ "$duty" -eq 0 ] && [ "$last" -gt 0 ] && [ "$t" -gt $(( OFF_T - FAN_HYST )) ]; then duty=$last; fi
            if [ "$duty" -gt 0 ] && [ "$last" -eq 0 ] && [ "$t" -lt $(( OFF_T + FAN_HYST )) ]; then duty=0; fi
            diff=$(( duty - last )); [ "$diff" -lt 0 ] && diff=$(( -diff ))
            [ "$diff" -lt 5 ] && duty=$last
        fi
    fi
    set_duty "$duty"
    last=$duty
    sleep "$FAN_POLL"
done