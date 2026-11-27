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
TSF_STATE_DIR=${TSF_STATE_DIR:-/etc/.tsf-state}

[ -b "$DEV" ] || { echo "不是块设备: $DEV" >&2; exit 1; }
[ "$SIZE_GB" -ge 4 ] 2>/dev/null || { echo "虚拟U盘容量无效" >&2; exit 1; }
[ "$ARCHIVE_GB" -ge 4 ] 2>/dev/null || { echo "归档区容量无效 (至少 4G)" >&2; exit 1; }
# 不信任调用方传进来的数字: 现读整盘容量, 虚拟盘+归档区超过实际容量就拒绝,
# 否则 sfdisk/mkfs 之后 prepare-teslacam 会写爆整盘或直接失败在半路。
DISK_BYTES=$(blockdev --getsize64 "$DEV" 2>/dev/null || true)
[ -n "$DISK_BYTES" ] && [ "$DISK_BYTES" -gt 0 ] 2>/dev/null || { echo "读取整盘容量失败: $DEV" >&2; exit 1; }
DISK_GB=$((DISK_BYTES / 1073741824))
WANT_GB=$((SIZE_GB + ARCHIVE_GB))
[ "$WANT_GB" -le "$DISK_GB" ] || {
    echo "虚拟盘 ${SIZE_GB}G + 归档区 ${ARCHIVE_GB}G = ${WANT_GB}G 超出整盘容量 ${DISK_GB}G" >&2
    exit 1
}
if [ "$SIZE_GB" -gt 128 ] && ! command -v mkfs.exfat >/dev/null 2>&1; then
    echo "大容量虚拟盘需要 exfatprogs (mkfs.exfat), 请先安装后再初始化" >&2
    exit 1
fi
# 设备身份二次核实: 调用方已按序列号确认过, 这里再拒绝系统盘与正在使用的盘,
# 避免设备名在页面上点确认后被热插拔换成别的盘 (例如 /dev/sda 变成 eMMC)。
case "$DEV" in
    /dev/mmcblk*|/dev/nvme*|"") echo "拒绝初始化系统盘或无效设备: $DEV" >&2; exit 1 ;;
esac
ROOT_SRC=$(findmnt -n -o SOURCE / 2>/dev/null || true)
case "$ROOT_SRC" in
    "$DEV"|"$DEV"[0-9]*|"$DEV"p[0-9]*) echo "拒绝格式化系统根分区所在磁盘: $DEV" >&2; exit 1 ;;
esac

# 回滚库: 只做文件层面的 snapshot/restore/commit, 不分区、不挂载。
# 载入失败直接退出: 没有回滚能力就不该动 /etc。
. "$TSF_DIR/tsf-state.sh"
TSF_COMMITTED=0

cleanup() {
    rc=$?
    # 失败路径: 先把 fstab/conf 恢复到执行前，再重启服务让它回到旧盘。
    # 成功路径已 commit，restore 找不到备份目录，等同空操作。
    tsf_state_restore "$TSF_STATE_DIR" 2>/dev/null || true
    [ -f /etc/cron.d/tesla-sentry.disabled ] && mv /etc/cron.d/tesla-sentry.disabled /etc/cron.d/tesla-sentry
    if [ "$rc" -ne 0 ]; then
        systemctl daemon-reload 2>/dev/null || true
        systemctl --no-block restart tesla-gadget.service tesla-live.service 2>/dev/null || true
    fi
    exit "$rc"
}
trap cleanup EXIT

# 在任何破坏性动作之前先记录 fstab / conf / cron 原状。
tsf_state_snapshot "$TSF_STATE_DIR" fstab conf cron || { echo "无法创建回滚快照" >&2; exit 1; }

[ -f /etc/cron.d/tesla-sentry ] && mv /etc/cron.d/tesla-sentry /etc/cron.d/tesla-sentry.disabled
systemctl stop tesla-gadget.service tesla-live.service || true
systemctl stop mnt-tsf-storage.mount 2>/dev/null || true

# 卸载失败不能继续: 还挂着就分区/格式化会毁掉正在写的文件系统, 半卸载状态写
# 分区表还可能让内核继续用旧分区视图。这里必须停。
umount "$MNT" 2>/dev/null || true
if mountpoint -q "$MNT" 2>/dev/null; then
    echo "无法卸载 $MNT (仍在使用), 已中止初始化, 请先关闭占用该挂载点的任务" >&2
    exit 1
fi
for OLD_PART in $(lsblk -lnpo NAME "$DEV"); do
    [ "$OLD_PART" = "$DEV" ] && continue
    umount "$OLD_PART" 2>/dev/null || {
        echo "无法卸载分区 $OLD_PART, 已中止初始化" >&2
        exit 1
    }
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
# 这之后任何步骤失败, cleanup 会把 fstab/conf 恢复为本脚本启动前的内容。
sed -i "\|[[:space:]]$MNT[[:space:]]|d" /etc/fstab
echo "UUID=$UUID $MNT ext4 defaults,nofail 0 2" >> /etc/fstab
systemctl daemon-reload
mkdir -p "$MNT"
mount "$PART" "$MNT"

mkdir -p "$DATA/archive/SentryClips" "$DATA/archive/SavedClips" "$DATA/archive/RecentClips" \
         "$DATA/archive/.skins" "$DATA/archive/boombox-queue" "$DATA/archive/boombox-done" \
         "$DATA/archive/files" "$DATA/cache/thumbs" "$DATA/cache/tel-cache"

sh "$TSF_DIR/prepare-teslacam.sh" "$DATA/teslacam.img" "$SIZE_GB" "$TSF_DIR/mkexfat.py"

sed -i "s|^TSF_IMG=.*|TSF_IMG=$DATA/teslacam.img|; s|^TSF_ARCHIVE=.*|TSF_ARCHIVE=$DATA/archive|; s|^TSF_CACHE=.*|TSF_CACHE=$DATA/cache|" "$CONF"

systemctl restart tesla-gadget.service tesla-live.service
# 成功: 丢弃快照, 让新配置成为基线; 之后 cleanup 不再回滚。
tsf_state_commit "$TSF_STATE_DIR"
TSF_COMMITTED=1
echo "initialized $SIZE_GB $ARCHIVE_GB"
