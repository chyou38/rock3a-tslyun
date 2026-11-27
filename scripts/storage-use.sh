#!/bin/sh
# storage-use.sh - 把 TSL Sentry 的镜像/归档/缓存切换到指定 USB 分区
# 由 sentry-viewer.py 调用; 调用前已校验目标为 USB 分区且为 ext4
set -e
DEV="$1"
MNT=/mnt/tsf-storage
NEW=/mnt/tsf-new
DATA=$MNT/tsf-data
CONF=/etc/tesla-sentry.conf
TSF_DIR=$(cd "$(dirname "$0")" && pwd)
TSF_STATE_DIR=${TSF_STATE_DIR:-/etc/.tsf-state}

[ -b "$DEV" ] || { echo "不是块设备: $DEV" >&2; exit 1; }
IMG=$(sed -n 's/^TSF_IMG=//p' "$CONF")
ARCHIVE=$(sed -n 's/^TSF_ARCHIVE=//p' "$CONF")
CACHE=$(sed -n 's/^TSF_CACHE=//p' "$CONF")
CUR=$(findmnt -n -T "$IMG" -o SOURCE 2>/dev/null || true)
[ "$CUR" = "$DEV" ] && { echo "already"; exit 0; }

# 回滚库: 只做文件层面的 snapshot/restore/commit。
. "$TSF_DIR/tsf-state.sh"

cleanup() {
    rc=$?
    umount "$NEW" 2>/dev/null || true
    # 失败路径: 恢复 fstab/conf/cron; 已移走的镜像/归档/缓存原样搬回原处。
    # 成功路径已 commit, restore 为空操作; MOVED 记录为回滚提供搬运线索。
    tsf_state_restore "$TSF_STATE_DIR" 2>/dev/null || true
    [ -f /etc/cron.d/tesla-sentry.disabled ] && mv /etc/cron.d/tesla-sentry.disabled /etc/cron.d/tesla-sentry
    if [ "$rc" -ne 0 ]; then
        rollback_moves
        systemctl daemon-reload 2>/dev/null || true
        systemctl --no-block restart tesla-gadget.service tesla-live.service 2>/dev/null || true
    fi
    exit "$rc"
}
trap cleanup EXIT

# 记录已完成的 mv, 供失败时逆序搬回。格式: 每行 "SRC<TAB>DST"。
MOVED_FILE=
rollback_moves() {
    [ -n "$MOVED_FILE" ] && [ -f "$MOVED_FILE" ] || return 0
    # 逆序回滚: 后搬的先搬回, 保持原相对位置。
    tac "$MOVED_FILE" 2>/dev/null | while IFS="	" read -r src dst; do
        [ -n "$src" ] && [ -n "$dst" ] || continue
        if [ -e "$dst" ] && [ ! -e "$src" ]; then
            mv "$dst" "$src" 2>/dev/null || true
        fi
    done
    rm -f "$MOVED_FILE" 2>/dev/null || true
}

# 执行一次可回滚的搬运: 目标必须不存在, 成功后记入 MOVED_FILE。
safe_move() {
    src="$1"; dst="$2"
    [ -e "$src" ] || return 0
    [ -e "$dst" ] && return 0          # 目标已存在: 与旧行为一致, 不覆盖
    mv "$src" "$dst"
    printf '%s\t%s\n' "$src" "$dst" >> "$MOVED_FILE"
}

tsf_state_snapshot "$TSF_STATE_DIR" fstab conf cron || { echo "无法创建回滚快照" >&2; exit 1; }
MOVED_FILE=$(mktemp "${TMPDIR:-/tmp}/tsf-moved.XXXXXX")

[ -f /etc/cron.d/tesla-sentry ] && mv /etc/cron.d/tesla-sentry /etc/cron.d/tesla-sentry.disabled
systemctl stop tesla-gadget.service tesla-live.service || true
# 取消上一块盘遗留的挂载等待, 允许无盘/换盘后继续操作。
systemctl stop mnt-tsf-storage.mount 2>/dev/null || true

mkdir -p "$NEW"
mount "$DEV" "$NEW"
mkdir -p "$NEW/tsf-data"
ADOPT=0
if [ -f "$NEW/tsf-data/teslacam.img" ]; then
    # 已经初始化过的盘直接接管, 不覆盖镜像, 也不从另一块盘搬数据。
    ADOPT=1
elif [ -e "$NEW/tsf-data/teslacam.img" ]; then
    echo "目标盘镜像路径存在但不是普通文件, 为避免覆盖已停止" >&2
    exit 1
fi

if [ "$ADOPT" -eq 0 ]; then
    [ -f "$IMG" ] || { echo "目标盘和当前存储都没有可用镜像, 请改用初始化" >&2; exit 1; }
    # 每步都通过 safe_move: 失败时 cleanup 逆序搬回。
    safe_move "$IMG" "$NEW/tsf-data/teslacam.img"
    if [ -d "$ARCHIVE" ]; then
        safe_move "$ARCHIVE" "$NEW/tsf-data/archive"
    fi
    if [ -d "$CACHE" ]; then
        safe_move "$CACHE" "$NEW/tsf-data/cache"
    fi
fi

mkdir -p "$NEW/tsf-data/archive/SentryClips" "$NEW/tsf-data/archive/SavedClips" \
         "$NEW/tsf-data/archive/RecentClips" "$NEW/tsf-data/archive/.skins" \
         "$NEW/tsf-data/archive/boombox-queue" "$NEW/tsf-data/archive/boombox-done" \
         "$NEW/tsf-data/archive/files" "$NEW/tsf-data/cache/thumbs" "$NEW/tsf-data/cache/tel-cache"

sed -i "s|^TSF_IMG=.*|TSF_IMG=$DATA/teslacam.img|; s|^TSF_ARCHIVE=.*|TSF_ARCHIVE=$DATA/archive|; s|^TSF_CACHE=.*|TSF_CACHE=$DATA/cache|" "$CONF"

umount "$NEW"
umount "$MNT" 2>/dev/null || true
UUID=$(blkid -s UUID -o value "$DEV")
[ -n "$UUID" ] || { echo "读取新盘 UUID 失败" >&2; exit 1; }
# 必须在启动依赖服务之前写入新 UUID; 否则会继续等待上一块盘。
sed -i "\|[[:space:]]$MNT[[:space:]]|d" /etc/fstab
echo "UUID=$UUID $MNT ext4 defaults,nofail 0 2" >> /etc/fstab
systemctl daemon-reload
mkdir -p "$MNT"
mount "$DEV" "$MNT"

systemctl restart tesla-gadget.service tesla-live.service
# 成功: 丢弃快照与搬运记录, 新位置成为基线。
tsf_state_commit "$TSF_STATE_DIR"
[ -n "$MOVED_FILE" ] && rm -f "$MOVED_FILE" 2>/dev/null || true
if [ "$ADOPT" -eq 1 ]; then
    echo "adopted"
else
    echo "switched"
fi
