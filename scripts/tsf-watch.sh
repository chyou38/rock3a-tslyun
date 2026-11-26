#!/bin/sh
# tsf-watch.sh - 常驻巡检: 每 10s 采一轮关键指标, 事件落日志, 异常立刻记 ALERT
# 日志: /opt/tesla-sentry/watch.log (按大小轮转, 保留 1 份 .1)
# 用法: tsf-watch.sh start|stop|status|tail

LOG=/opt/tesla-sentry/watch.log
PIDF=/run/tsf-watch.pid
INTERVAL=10
# CmaFree 在 RK3568 上长期 0-1MB 属正常波动, 默认不再推飞书告警
# 需要恢复时: 在 tsf-watch.service 里设 Environment=TSF_WATCH_ALERT_CMA=1
ALERT_CMA=${TSF_WATCH_ALERT_CMA:-0}
# 服务停服(部署重启的几秒空窗)默认不推飞书, 只记一行 note;
# 需要恢复: tsf-watch.service 里设 Environment=TSF_WATCH_ALERT_SVC=1
ALERT_SVC=${TSF_WATCH_ALERT_SVC:-0}

# 告警开关: 由网页「推送 → 巡检告警」写入, 每轮重读; 只有勾选的才推飞书, 其余只记日志
FLAGS=/opt/tesla-sentry/watch-flags.conf

alert() {
    echo "[$(date '+%m-%d %H:%M:%S')] ALERT $*" >> "$LOG"
    # 同步推飞书(经 viewer 回环接口, 复用推送配置, 相同告警 10 分钟去重); 失败不影响巡检
    curl -s -m 8 -X POST --data-binary "[$(date '+%m-%d %H:%M:%S')] $*" \
        http://127.0.0.1/api/watch/alert >/dev/null 2>&1 || true
}
note()  { echo "[$(date '+%m-%d %H:%M:%S')] $*" >> "$LOG"; }

rotate() {
    sz=$(stat -c %s "$LOG" 2>/dev/null || echo 0)
    [ "$sz" -gt 20000000 ] && { mv -f "$LOG" "$LOG.1" 2>/dev/null; note "log rotated"; }
}

run() {
    echo $$ > "$PIDF"
    note "watch start (interval=${INTERVAL}s)"
    last_reset=-1; last_null=-1; last_lun=""; last_state=""; last_mem=0; last_bad="x"
    while :; do
        # 开关每轮重读: 网页上改了立刻生效, 不用重启巡检
        [ -r "$FLAGS" ] && . "$FLAGS" 2>/dev/null || true
        rotate
        ts=$(date '+%H:%M:%S')
        # USB gadget
        st=$(cat /sys/class/udc/fcc00000.usb/state 2>/dev/null || echo "?")
        lun=$(cat /sys/kernel/config/usb_gadget/g1/functions/mass_storage.0/lun.0/file 2>/dev/null || echo "")
        [ "$st" != "$last_state" ] && { note "usb state: $last_state -> $st"; last_state="$st"; }
        if [ "$lun" != "$last_lun" ]; then
            if [ -z "$lun" ]; then
                if [ "${W_LUN:-1}" = 1 ]; then alert "LUN EMPTY (host ejected?)"
                else note "LUN EMPTY (alert off)"; fi
            else note "LUN -> ${lun##*/}"; fi
            last_lun="$lun"
        fi
        # kernel USB / MPP counters
        nr=$(dmesg 2>/dev/null | grep -c 'dwc3 fcc00000.usb: device reset')
        nn=$(dmesg 2>/dev/null | grep -c 'check buffer found NULL pointer')
        if [ "$last_reset" -ge 0 ] && [ "$nr" -gt "$last_reset" ]; then
            note "usb reset +$((nr - last_reset)) (total $nr)"
        fi
        if [ "$last_null" -ge 0 ] && [ "$nn" -gt "$last_null" ]; then
            if [ "${W_MPP:-1}" = 1 ]; then alert "mpp buffer NULL +$((nn - last_null)) (total $nn)"
            else note "mpp buffer NULL +$((nn - last_null)) (alert off)"; fi
        fi
        last_reset=$nr; last_null=$nn
        # memory / load / temp
        ma=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo)
        cf=$(awk '/CmaFree/{print int($2/1024)}' /proc/meminfo)
        ld=$(cut -d' ' -f1 /proc/loadavg)
        tp=$(awk '{printf "%.0f", $1/1000}' /sys/class/thermal/thermal_zone0/temp 2>/dev/null)
        if [ "$ma" -lt 150 ]; then
            if [ "${W_MEM:-1}" = 1 ]; then alert "MemAvailable low: ${ma}MB"
            else note "MemAvailable low: ${ma}MB (alert off)"; fi
        fi
        [ "$ALERT_CMA" = 1 ] && [ "$cf" -lt 2 ] && [ "$last_mem" -ge 2 ] && alert "CmaFree low: ${cf}MB"
        last_mem=$cf
        # services: 只在状态变化时记一行; 默认不推飞书(部署重启的短暂停服不该打扰)
        svcbad=""
        for s in sentry-viewer tesla-gadget tesla-live; do
            systemctl is-active --quiet "$s" 2>/dev/null || svcbad="$svcbad $s"
        done
        if [ "$svcbad" != "$last_bad" ]; then
            if [ -n "$svcbad" ]; then
                svcon=${W_SVC:-0}          # dash 不支持嵌套默认值, 分两步取
                [ -n "$TSF_WATCH_ALERT_SVC" ] && svcon=$TSF_WATCH_ALERT_SVC
                if [ "$svcon" = 1 ]; then alert "service$svcbad NOT active"
                else note "service$svcbad NOT active (alert off)"; fi
            else note "service all active"; fi
            last_bad="$svcbad"
        fi
        # OOM / panic in kernel ring
        no=$(dmesg 2>/dev/null | grep -c -iE 'out of memory|oom-kill|kernel panic')
        if [ "$no" -gt 0 ]; then
            if [ "${W_OOM:-1}" = 1 ]; then alert "kernel OOM/panic lines: $no"
            else note "kernel OOM/panic lines: $no (alert off)"; fi
        fi
        note "hb mem=${ma}M cma=${cf}M load=$ld temp=${tp}C usb=$st lun=$([ -n "$lun" ] && echo ok || echo EMPTY) reset=$nr null=$nn"
        sleep "$INTERVAL"
    done
}

case "$1" in
    start)
        if [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF" 2>/dev/null)" 2>/dev/null; then
            echo "already running pid=$(cat "$PIDF")"; exit 0
        fi
        setsid sh "$0" _run </dev/null >/dev/null 2>&1 &
        sleep 1
        echo "started pid=$(cat "$PIDF" 2>/dev/null)"
        ;;
    _run) run ;;
    stop)
        [ -f "$PIDF" ] && kill "$(cat "$PIDF")" 2>/dev/null && rm -f "$PIDF" && echo stopped || echo "not running"
        ;;
    status)
        if [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF" 2>/dev/null)" 2>/dev/null; then
            echo "running pid=$(cat "$PIDF")"; tail -3 "$LOG"
        else echo "not running"; fi
        ;;
    tail) tail -f "$LOG" ;;
    *) echo "usage: $0 start|stop|status|tail"; exit 2 ;;
esac
