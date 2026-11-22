#!/bin/sh
# TSL Sentry Box (ROCK 3A) - 卸载脚本
# 用法: sudo ./uninstall.sh [--purge]
#   默认   停服务 / 恢复 USB 导出 / 删除程序与缓存 / 保留镜像和归档录像数据
#   --purge 连稀疏镜像、归档区一起删除 (不可恢复!)
set -e

PURGE=0
[ "$1" = "--purge" ] && PURGE=1

[ "$(id -u)" = "0" ] || { echo "请用 root 运行"; exit 1; }
. /etc/tesla-sentry.conf 2>/dev/null || true
: "${TSF_DIR:=/opt/tesla-sentry}"
: "${TSF_IMG:=$TSF_DIR/teslacam.img}"
: "${TSF_ARCHIVE:=/archive}"
: "${TSF_MNT:=/tmp/teslamnt}"
: "${TSF_CACHE:=$TSF_DIR/cache}"

echo "==> 停止服务 (systemd)"
if command -v systemctl >/dev/null 2>&1; then
    for svc in tesla-gadget sentry-viewer tesla-live pwm-fan-control tsf-ap-policy.timer tsf-hotspot; do
        systemctl disable --now "$svc" 2>/dev/null || true
    done
    systemctl stop hostapd.service dnsmasq.service 2>/dev/null || true
fi

# 兜底收掉残留进程 (rc.local / 手动启动的实例)
for pat in sentry-viewer.py tesla-live-sync.py tesla-sync.sh usb-selfheal.sh fan-control.sh; do
    pkill -f "$pat" 2>/dev/null || true
done

echo "==> 恢复 USB 导出 (移除 mass_storage)"
if [ -f "$TSF_DIR/tesla-gadget.sh" ]; then
    sh "$TSF_DIR/tesla-gadget.sh" off 2>/dev/null || true
fi
[ -n "$TSF_MNT" ] && umount "$TSF_MNT" 2>/dev/null || true

echo "==> 清理 systemd 单元与定时任务"
rm -f /etc/systemd/system/tesla-gadget.service \
      /etc/systemd/system/sentry-viewer.service \
      /etc/systemd/system/tesla-live.service \
      /etc/systemd/system/pwm-fan-control.service \
      /etc/systemd/system/tsf-hotspot.service \
      /etc/systemd/system/tsf-ap-policy.service \
      /etc/systemd/system/tsf-ap-policy.timer
rm -f /etc/cron.d/tesla-sentry
[ -f /etc/crontab ] && sed -i '/tesla-sync.sh/d;/usb-selfheal.sh/d' /etc/crontab 2>/dev/null || true
if command -v systemctl >/dev/null 2>&1; then
    systemctl daemon-reload 2>/dev/null || true
    systemctl restart cron 2>/dev/null || true
fi

echo "==> 删除程序文件与缓存"
rm -f "$TSF_DIR/sentry-viewer.py" "$TSF_DIR/tesla-live-sync.py" \
      "$TSF_DIR/tesla-gadget.sh" "$TSF_DIR/tesla-sync.sh" \
      "$TSF_DIR/usb-selfheal.sh" "$TSF_DIR/tesla-img.sh" \
      "$TSF_DIR/storage-init.sh" "$TSF_DIR/storage-use.sh" \
      "$TSF_DIR/prepare-teslacam.sh" "$TSF_DIR/mkexfat.py" \
      "$TSF_DIR/tsf-ap.sh" "$TSF_DIR/ap-policy.sh" "$TSF_DIR/fan-control.sh" \
      "$TSF_DIR/tsf-check.sh" "$TSF_DIR/uninstall.sh" "$TSF_DIR/auth.conf" \
      "$TSF_DIR"/*.log
rm -rf "$TSF_DIR/fonts" "$TSF_CACHE/thumbs" "$TSF_CACHE/tel-cache" \
       /etc/hostapd/tsf-ap.conf /etc/dnsmasq.d/tsf-ap.conf
rm -f /etc/tesla-sentry.conf /etc/tsf-ap.conf /etc/default/pwm-fan

if [ "$PURGE" = "1" ]; then
    echo "==> [--purge] 删除镜像与归档录像 (不可恢复)"
    # 防呆: 配置缺失或被改坏时不要误删根目录
    case "$TSF_IMG" in ""|"/") echo "    镜像路径异常, 跳过";; *) rm -f "$TSF_IMG" || true;; esac
    case "$TSF_ARCHIVE" in ""|"/") echo "    归档路径异常, 跳过";; *) rm -rf "$TSF_ARCHIVE" || true;; esac
    rmdir "$TSF_DIR" 2>/dev/null || true
else
    echo "==> 保留录像数据: $TSF_IMG , $TSF_ARCHIVE"
    echo "    需要彻底清除请加 --purge"
    echo "    注意: 网页登录凭据 auth.conf 已删除, 重装会生成新密码"
fi

echo "==> 卸载完成"
