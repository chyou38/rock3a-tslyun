#!/bin/sh
# fan-control.sh - 风扇温控
# 兼容两种内核:
#   BSP (官方 Radxa Debian12): pwm-fan 驱动, hwmon 名 pwmfan, 文件 pwm1 / pwm1_enable
#   mainline (旧 Armbian):      裸 PWM, /sys/devices/platform/fe6f0000.pwm/pwm/pwmchip0/pwm0
# 配置 /etc/default/pwm-fan 每轮热读: 网页保存立即生效, 无需重启服务。
# 模式: auto=温度曲线(带启停回差) / manual=固定占空比
# 用法: fan-control.sh          常驻温控循环
#       fan-control.sh --test N 全速转 N 秒 (默认10), 用于人工确认风扇接线
CONF=/etc/default/pwm-fan

load_conf() {
    [ -f "$CONF" ] && . "$CONF"
    : "${FAN_POLL:=10}"
    : "${FAN_PERIOD:=40000}"
    : "${FAN_HYST:=500}"
    : "${FAN_MIN_DUTY:=50}"
    : "${FAN_KICK_SEC:=2}"
    : "${FAN_CURVE:=45000:0 50000:35 60000:55 70000:80 75000:100}"
    : "${FAN_MODE:=auto}"
    : "${FAN_MANUAL_DUTY:=50}"
    # 数值校验: 配置行粘连/写坏时回退默认, 避免 sleep 非法值导致空转烧 CPU
    case "$FAN_POLL" in ''|*[!0-9]*) FAN_POLL=10 ;; esac
    case "$FAN_PERIOD" in ''|*[!0-9]*) FAN_PERIOD=40000 ;; esac
    case "$FAN_MANUAL_DUTY" in ''|*[!0-9]*) FAN_MANUAL_DUTY=50 ;; esac
    case "$FAN_HYST" in ''|*[!0-9]*) FAN_HYST=500 ;; esac
    case "$FAN_MIN_DUTY" in ''|*[!0-9]*) FAN_MIN_DUTY=50 ;; esac
    case "$FAN_KICK_SEC" in ''|*[!0-9]*) FAN_KICK_SEC=2 ;; esac
    [ "$FAN_MIN_DUTY" -gt 100 ] && FAN_MIN_DUTY=100
}
load_conf

# --- 1. 优先用 BSP 的 pwm-fan hwmon (内核已建 cooling device) ---
HW=
for h in /sys/class/hwmon/hwmon*; do
    [ -r "$h/name" ] || continue
    if [ "$(cat "$h/name" 2>/dev/null)" = "pwmfan" ]; then HW="$h"; break; fi
done

if [ -n "$HW" ]; then
    SYS_MODE=hwmon
    P="$HW"
    # 1 = 手工占空比 (内核温控不再覆盖); 2 = 内核温控
    echo 1 > "$P/pwm1_enable" 2>/dev/null
else
    SYS_MODE=rawpwm
    CHIP=$(ls -d /sys/devices/platform/fe6f0000.pwm/pwm/pwmchip* 2>/dev/null | head -1)
    [ -n "$CHIP" ] || { echo "fan: 既没有 pwmfan hwmon, 也没有 pwm8 (缺 rock3a-pwm8-fan overlay?)"; exit 1; }
    [ -d "$CHIP/pwm0" ] || echo 0 > "$CHIP/export" 2>/dev/null
    P="$CHIP/pwm0"
    echo "$FAN_PERIOD" > "$P/period" 2>/dev/null
    echo normal > "$P/polarity" 2>/dev/null
    echo 1 > "$P/enable"
fi
echo "fan: driver=$SYS_MODE path=$P"

set_duty() {
    if [ "$SYS_MODE" = "hwmon" ]; then
        echo $(( 255 * $1 / 100 )) > "$P/pwm1"
        echo 1 > "$P/pwm1_enable" 2>/dev/null   # 防内核温控改回自动
    else
        echo $(( FAN_PERIOD * $1 / 100 )) > "$P/duty_cycle"
    fi
}

if [ "$1" = "--test" ]; then
    set_duty 100
    sleep "${2:-10}"
    exit 0
fi

read_temp() {
    _max=
    for z in /sys/class/thermal/thermal_zone*; do
        _ty=$(cat "$z/type" 2>/dev/null) || continue
        case "$_ty" in
            cpu-thermal|soc-thermal|gpu-thermal) ;;
            *) continue ;;
        esac
        _v=$(cat "$z/temp" 2>/dev/null) || continue
        case "$_v" in ''|*[!0-9]*) continue ;; esac
        [ "$_v" -ge 20000 ] && [ "$_v" -le 150000 ] || continue
        if [ -z "$_max" ] || [ "$_v" -gt "$_max" ]; then _max=$_v; fi
    done
    echo "$_max"
}

t=$(read_temp)
[ -n "$t" ] || { echo "fan: 找不到 cpu/soc/gpu thermal"; exit 1; }

last=0
while :; do
    load_conf
    t=$(read_temp)
    [ -n "$t" ] || { echo "fan: thermal 读取失败"; sleep "$FAN_POLL"; continue; }
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
        # 3-pin 风扇低占空比常常起转不了；自动模式只要不是停转，就给最低启动占空比
        if [ "$duty" -gt 0 ] && [ "$duty" -lt "$FAN_MIN_DUTY" ]; then duty=$FAN_MIN_DUTY; fi
    fi
    # 从停转切到转动时先全速踢一下，3-pin 风扇低占空比常常起不来
    if [ "$last" -eq 0 ] && [ "$duty" -gt 0 ]; then
        set_duty 100
        sleep "$FAN_KICK_SEC"
    fi
    set_duty "$duty"
    last=$duty
    sleep "$FAN_POLL"
done
