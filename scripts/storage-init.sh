#!/bin/sh
# storage-init.sh - 整块 USB 硬盘重新分区, 按比例创建虚拟U盘与归档区
# 参数: 磁盘设备(如 /dev/sda) 虚拟U盘GB 归档区GB; 调用前网页已做 USB 磁盘与序列号确认
set -e
DEV="$1"
SIZE_GB="$2"
ARCHIVE_GB="$3"
MNT=/mnt/tsf-storage
DATA=$MNT/tsf-data
CONF=/etc/tesla-sentry.conf
TSF_DIR=$(cd "$(dirname "$0")" && pwd)

[ -b "$DEV" ] || { echo "不是块设备: $DEV" >&2; exit 1; }
[ "$SIZE_GB" -ge 4 ] 2>/dev/null || { echo "虚拟U盘容量无效" >&2; exit 1; }
if [ "$SIZE_GB" -gt 128 ] && ! command -v mkfs.exfat >/dev/null 2>&1; then
    echo "大容量虚拟盘需要 exfatprogs (mkfs.exfat), 请先安装后再初始化" >&2
    exit 1
fi

cleanup() {
    rc=$?
    [ -f /etc/cron.d/tesla-sentry.disabled ] && mv /etc/cron.d/tesla-sentry.disabled /etc/cron.d/tesla-sentry
    if [ "$rc" -ne 0 ]; then
        systemctl --no-block restart tesla-gadget.service tesla-live.service 2>/dev/null || true
    fi
    exit "$rc"
}
trap cleanup EXIT

[ -f /etc/cron.d/tesla-sentry ] && mv /etc/cron.d/tesla-sentry /etc/cron.d/tesla-sentry.disabled
systemctl stop tesla-gadget.service tesla-live.service || true
systemctl stop mnt-tsf-storage.mount 2>/dev/null || true

umount "$MNT" 2>/dev/null || true
for OLD_PART in $(lsblk -lnpo NAME "$DEV"); do
    [ "$OLD_PART" = "$DEV" ] && continue
    umount "$OLD_PART" 2>/dev/null || true
done

# 整盘只建一个 ext4 分区; 虚拟U盘镜像与归档目录都在该分区内
printf 'label: dos\nstart=2048, type=83\n' | sfdisk "$DEV"
command -v partprobe >/dev/null 2>&1 && partprobe "$DEV" || true
udevadm settle
sleep 2
case "$DEV" in
    *[0-9]) PART="${DEV}p1" ;;
    *) PART="${DEV}1" ;;
esac
[ -b "$PART" ] || { echo "新分区未出现: $PART" >&2; exit 1; }
mkfs.ext4 -F "$PART"
UUID=$(blkid -s UUID -o value "$PART")
[ -n "$UUID" ] || { echo "读取新盘 UUID 失败" >&2; exit 1; }
# 先更新挂载配置, 再挂载和恢复服务, 避免沿用上一块盘。
sed -i "\|[[:space:]]$MNT[[:space:]]|d" /etc/fstab
echo "UUID=$UUID $MNT ext4 defaults,nofail 0 2" >> /etc/fstab
systemctl daemon-reload
mkdir -p "$MNT"
mount "$PART" "$MNT"

mkdir -p "$DATA/archive/SentryClips" "$DATA/archive/SavedClips" "$DATA/archive/RecentClips" \
         "$DATA/archive/.skins" "$DATA/archive/boombox-queue" "$DATA/archive/boombox-done" \
         "$DATA/archive/files" "$DATA/cache/thumbs" "$DATA/cache/tel-cache"

sh "$TSF_DIR/prepare-teslacam.sh" "$DATA/teslacam.img" "$SIZE_GB" "$TSF_DIR/mkexfat.py"

sed -i "s|^TSF_IMG=.*|TSF_IMG=$DATA/teslacam.img|; s|^TSF_ARCHIVE=.*|TSF_ARCHIVE=$DATA/archive|; s|^TSF_CACHE=.*|TSF_CACHE=$DATA/cache|; s|^TSF_BOX_MAX_GB=.*|TSF_BOX_MAX_GB=$ARCHIVE_GB|" "$CONF"

systemctl restart tesla-gadget.service tesla-live.service
echo "initialized $SIZE_GB $ARCHIVE_GB"