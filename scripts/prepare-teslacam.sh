#!/bin/sh
# prepare-teslacam.sh - 创建可直接识别的 exFAT 虚拟盘和标准 TeslaCam 目录
# 参数: 镜像路径 容量GB [mkexfat.py 路径]
set -e
IMG="$1"
SIZE_GB="$2"
MKEXFAT="${3:-/opt/tesla-sentry/mkexfat.py}"
IMG_MNT=/tmp/teslacam-prepare
IMG_LOOP=

[ -n "$IMG" ] && [ "$SIZE_GB" -ge 1 ] 2>/dev/null || { echo "用法: $0 <镜像> <容量GB> [mkexfat.py]" >&2; exit 2; }

cleanup() {
    rc=$?
    if [ -n "$IMG_LOOP" ]; then
        umount "$IMG_MNT" 2>/dev/null || true
        losetup -d "$IMG_LOOP" 2>/dev/null || true
    fi
    exit "$rc"
}
trap cleanup EXIT

python3 "$MKEXFAT" "$IMG" "$SIZE_GB"
[ "$SIZE_GB" -le 128 ] && exit 0

# 旧纯 Python 模板只覆盖 <=128G; 大容量使用系统 exFAT 工具。
command -v mkfs.exfat >/dev/null 2>&1 || {
    echo "大容量虚拟盘需要 exfatprogs (mkfs.exfat), 请先安装" >&2
    exit 1
}
mkdir -p "$IMG_MNT"
IMG_LOOP=$(losetup -f --show "$IMG")
# exfatprogs 在部分系统上不能直接从普通文件取得容量, 必须通过 loop 块设备。
mkfs.exfat -L TESLACAM -c 128K "$IMG_LOOP"
mount -t exfat "$IMG_LOOP" "$IMG_MNT"
mkdir -p "$IMG_MNT/TeslaCam/RecentClips" "$IMG_MNT/TeslaCam/SavedClips" \
         "$IMG_MNT/TeslaCam/SentryClips" "$IMG_MNT/TeslaCam/EncryptedClips"
sync
umount "$IMG_MNT"
losetup -d "$IMG_LOOP"
IMG_LOOP=
