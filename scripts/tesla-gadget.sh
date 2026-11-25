#!/bin/sh
# tesla-gadget.sh - 把镜像文件导出为 USB 虚拟U盘 (mass_storage)
# 用法: tesla-gadget.sh on|off|status|restore
#
# 设计要点:
#  - 只在现有 gadget 里"追加" mass_storage 功能, 不动 ncm/acm, 所以 USB 网卡和串口不中断
#  - 绑定失败自动回滚, 避免设备从 USB 上消失
#  - 所有设备路径自动探测, 不写死

[ -f /etc/tesla-sentry.conf ] && . /etc/tesla-sentry.conf

: "${TSF_DIR:=/opt/tesla-sentry}"
: "${TSF_IMG:=$TSF_DIR/teslacam.img}"
: "${TSF_LOG_DIR:=$TSF_DIR}"
IMG="$TSF_IMG"
LOG="$TSF_LOG_DIR/tesla-gadget.log"
CONF_NAME="${TSF_GADGET_CONFIG:-c.1}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

# --- 自动探测 ---
find_gadget() {
    if [ -n "$TSF_GADGET" ] && [ -d "$TSF_GADGET" ]; then echo "$TSF_GADGET"; return 0; fi
    for d in /sys/kernel/config/usb_gadget/*/; do
        [ -d "$d/configs" ] && { echo "${d%/}"; return 0; }
    done
    return 1
}

ensure_gadget() {
    # configfs 重启后必然清空: ROCK 3A 等设备没有预建 gadget 时自动创建。
    mkdir -p /sys/kernel/config
    mountpoint -q /sys/kernel/config 2>/dev/null || mount -t configfs none /sys/kernel/config 2>/dev/null || true
    [ -d /sys/kernel/config/usb_gadget ] || modprobe libcomposite 2>/dev/null || true
    [ -d /sys/kernel/config/usb_gadget ] || return 1
    G="${TSF_GADGET:-/sys/kernel/config/usb_gadget/g1}"
    mkdir -p "$G/strings/0x409" "$G/configs/$CONF_NAME/strings/0x409" || return 1
    SERIAL="${TSF_USB_SERIAL:-$(cut -c1-16 /etc/machine-id 2>/dev/null)}"
    [ -n "$SERIAL" ] || SERIAL="TSF3A0001"
    printf '%s' "${TSF_USB_VID:-0x0525}" > "$G/idVendor"
    printf '%s' "${TSF_USB_PID:-0xa4a5}" > "$G/idProduct"
    printf '%s' "0x0200" > "$G/bcdUSB"
    printf '%s' "0x0100" > "$G/bcdDevice"
    printf '%s' "$SERIAL" > "$G/strings/0x409/serialnumber"
    printf '%s' "TSL Sentry" > "$G/strings/0x409/manufacturer"
    printf '%s' "TeslaCam Virtual USB" > "$G/strings/0x409/product"
    printf '%s' "TSL Sentry Storage" > "$G/configs/$CONF_NAME/strings/0x409/configuration"
    printf '%s' "250" > "$G/configs/$CONF_NAME/MaxPower"
}

if ! GADGET=$(find_gadget); then
    ensure_gadget || { echo "ERROR: 无法创建 USB gadget (libcomposite/configfs)"; exit 1; }
    GADGET=$(find_gadget) || { echo "ERROR: USB gadget 创建后仍不可用"; exit 1; }
fi
UDC=$(ls /sys/class/udc/ 2>/dev/null | head -1)
[ -z "$UDC" ] && { echo "ERROR: 没有 USB Device 控制器 (UDC)"; exit 1; }

# configfs 里的配置名可能不叫 c.1
[ -d "$GADGET/configs/$CONF_NAME" ] || CONF_NAME=$(ls "$GADGET/configs" 2>/dev/null | head -1)

FUNC_DIR="$GADGET/functions/mass_storage.0"
LINK="$GADGET/configs/$CONF_NAME/massstorage"

state() { cat "/sys/class/udc/$UDC/state" 2>/dev/null; }
bind()   { echo "$UDC" > "$GADGET/UDC"; }
unbind() { echo "" > "$GADGET/UDC"; }

status() {
    echo "gadget : $GADGET (config=$CONF_NAME)"
    echo "udc    : $UDC  state=$(state)"
    echo "lun    : $(cat "$FUNC_DIR/lun.0/file" 2>/dev/null || echo '未挂载')"
    if [ -f "$IMG" ]; then
        echo "image  : $IMG ($(du -sh "$IMG" 2>/dev/null | cut -f1) 实际占用)"
    else
        echo "image  : 未创建 ($IMG) — 请在网页首页配置存储"
    fi
    echo "--- gadget 功能 ---"
    ls "$GADGET/configs/$CONF_NAME/" 2>/dev/null | grep -v '^max_speed$'
}

do_on() {
    # 首次部署不预建镜像: 服务先保持等待, 等用户在网页里选择硬盘并创建后再导出。
    [ -f "$IMG" ] || { echo "WAIT: 虚拟U盘未创建: $IMG (请在网页首页配置存储)"; exit 0; }
    if [ -e "$FUNC_DIR" ] && [ "$(cat "$FUNC_DIR/lun.0/file" 2>/dev/null)" = "$IMG" ]; then
        # 功能已存在但 UDC 可能因重启/同步处于解绑状态, 必要时只恢复绑定。
        [ "$(cat "$GADGET/UDC" 2>/dev/null)" = "$UDC" ] || { bind; sleep 1; }
        echo "ALREADY-ON"; exit 0
    fi

    # 功能已存在、只是 LUN 被主机 eject(介质为空)或指向别的文件:
    # 热换介质, 绝不 unbind 整个 gadget —— unbind 会把 ncm 网卡和 ACM 串口一起摘掉,
    # 主机侧看到的是"整台设备重新插拔", 就是 dmesg 里成对出现的 device reset。
    if [ -e "$FUNC_DIR" ]; then
        cur="$(cat "$FUNC_DIR/lun.0/file" 2>/dev/null)"
        log "=== ON(hot): lun '${cur:-empty}' -> $IMG (no rebind) ==="
        if [ -n "$cur" ] && [ "$cur" != "$IMG" ]; then
            echo 1 > "$FUNC_DIR/lun.0/forced_eject" 2>/dev/null || true
        fi
        if echo "$IMG" > "$FUNC_DIR/lun.0/file" 2>/dev/null; then
            st=$(state)
            log "state after hot switch: $st"
            echo "TESLA-GADGET-ON-HOT (state=$st)"
            exit 0
        fi
        log "hot switch rejected (host locked medium?), fallback to rebind"
    fi

    log "=== ON: exporting $IMG ==="
    unbind; sleep 1

    mkdir -p "$FUNC_DIR"
    echo 1 > "$FUNC_DIR/lun.0/removable"
    echo "$IMG" > "$FUNC_DIR/lun.0/file"
    # 链接已存在(含悬空链接)时不要再 ln, configfs 下会报 Operation not permitted
    if [ ! -L "$LINK" ] && [ ! -e "$LINK" ]; then ln -sf "$FUNC_DIR" "$LINK"; fi

    if ! bind; then
        log "UDC BIND WRITE FAILED"
        echo "ERROR: UDC 绑定写入失败: $UDC"; exit 1
    fi
    sleep 1
    st=$(state)
    log "state after bind: $st"
    # 未插车机/电脑时 not attached 是正常等待状态, 不能据此删除功能或判服务失败。
    case "$st" in
        configured|addressed|suspended)
            echo "TESLA-GADGET-ON (state=$st)" ;;
        "not attached")
            echo "TESLA-GADGET-ON (waiting for USB host)" ;;
        *)
            log "host state not ready: $st (gadget remains bound)"
            echo "TESLA-GADGET-ON (state=$st)" ;;
    esac
}

do_off() {
    log "=== OFF: removing mass_storage (hot) ==="
    if [ ! -e "$FUNC_DIR" ]; then echo "ALREADY-OFF"; exit 0; fi
    # 热摘: 先清 LUN 让主机看到介质移除, 再删链接/目录; 不再 unbind 整个 gadget,
    # 否则网卡和串口会跟着断一次。
    echo "" > "$FUNC_DIR/lun.0/file" 2>/dev/null || true
    rm -f "$LINK" 2>/dev/null
    rmdir "$FUNC_DIR" 2>/dev/null || true
    log "state: $(state)"
    echo "TESLA-GADGET-OFF (state=$(state))"
}

# 只重新绑定 UDC (镜像管理模式结束后用)
do_restore() {
    bind; sleep 2
    log "restore bind, state=$(state)"
    echo "RESTORED (state=$(state))"
}

case "$1" in
    on)      do_on ;;
    off)     do_off ;;
    restore) do_restore ;;
    status)  status ;;
    *) echo "用法: $0 on|off|restore|status"; exit 2 ;;
esac
