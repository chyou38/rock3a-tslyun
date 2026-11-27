#!/bin/sh
# tests/test_tsf_state.sh - 离线验证 tsf-state.sh 的回滚快照/恢复/提交纯函数
# 只操作临时目录, 不分区、不挂载、不 touch /etc。用 dash 运行:
#   dash tests/test_tsf_state.sh
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
LIB="$HERE/../scripts/tsf-state.sh"
[ -f "$LIB" ] || { echo "找不到 $LIB" >&2; exit 2; }

FAILD=0
pass=0
fail=0
ok()   { pass=$((pass + 1)); printf '  ok   %s\n' "$1"; }
bad()  { fail=$((fail + 1)); FAILD=1; printf '  FAIL %s\n' "$1"; }
check(){ if eval "$2"; then ok "$1"; else bad "$1"; fi; }

# 每个用例一份隔离的伪 /etc
new_etc() {
    CASE=$(mktemp -d "${TMPDIR:-/tmp}/tsfstate.XXXXXX")
    ETC="$CASE/etc"
    mkdir -p "$ETC/cron.d"
    TSF_ETC="$ETC"
    export TSF_ETC
    . "$LIB"
}
done_case() { rm -rf "$CASE"; }

echo "== snapshot 记录不存在文件为 absent, 存在文件保留内容 =="
new_etc
printf 'UUID=old /mnt/tsf-storage ext4 defaults 0 2\n' > "$ETC/fstab"
printf 'TSF_IMG=/old/teslacam.img\nTSF_ARCHIVE=/old/archive\n' > "$ETC/tesla-sentry.conf"
# cron 活动文件不存在, 只有 .disabled
printf '* * * * * root true\n' > "$ETC/cron.d/tesla-sentry.disabled"
SNAP="$CASE/state"
tsf_state_snapshot "$SNAP" fstab conf cron
check "snapshot 返回 0" '[ $? -eq 0 ]'
check "fstab.1.orig 存在" '[ -f "$SNAP/fstab.1.orig" ]'
check "conf.1.orig 存在" '[ -f "$SNAP/conf.1.orig" ]'
check "cron 活动文件记 absent" '[ -f "$SNAP/cron.1.orig.absent" ]'
check "cron .disabled 有内容备份" '[ -f "$SNAP/cron.2.orig" ]'
check "cron path 记录两行" '[ $(wc -l < "$SNAP/../state/cron.2.path") -ge 1 ] || [ -s "$SNAP/cron.2.path" ]'
done_case

echo "== restore 回滚被改动的文件并删除新增文件 =="
new_etc
printf 'UUID=old /mnt/tsf-storage ext4 defaults 0 2\n' > "$ETC/fstab"
printf 'TSF_IMG=/old/teslacam.img\n' > "$ETC/tesla-sentry.conf"
printf '* * * * * root true\n' > "$ETC/cron.d/tesla-sentry"
SNAP="$CASE/state"
tsf_state_snapshot "$SNAP" fstab conf cron
# 模拟失败中途的破坏性改动
printf 'UUID=NEW /mnt/tsf-storage ext4 defaults,nofail 0 2\n' > "$ETC/fstab"
printf 'TSF_IMG=/new/teslacam.img\nTSF_ARCHIVE=/new/archive\n' > "$ETC/tesla-sentry.conf"
rm -f "$ETC/cron.d/tesla-sentry"          # 被 mv 成 .disabled
printf '* * * * * root true\n' > "$ETC/cron.d/tesla-sentry.disabled"
tsf_state_restore "$SNAP"
check "restore 返回 0" '[ $? -eq 0 ]'
check "fstab 回到旧 UUID" 'grep -q "UUID=old" "$ETC/fstab"'
check "conf 回到旧 TSF_IMG" 'grep -q "TSF_IMG=/old/teslacam.img" "$ETC/tesla-sentry.conf"'
check "cron 活动文件恢复" '[ -f "$ETC/cron.d/tesla-sentry" ]'
done_case

echo "== restore 删除快照时并不存在、后来新增的文件 =="
new_etc
printf 'UUID=old /mnt/tsf-storage ext4 defaults 0 2\n' > "$ETC/fstab"
SNAP="$CASE/state"
tsf_state_snapshot "$SNAP" fstab conf
printf 'TSF_IMG=/new/teslacam.img\n' > "$ETC/tesla-sentry.conf"   # conf 快照时为 absent
tsf_state_restore "$SNAP"
check "restore 返回 0" '[ $? -eq 0 ]'
check "fstab 保留" '[ -f "$ETC/fstab" ]'
check "原不存在的 conf 被删除" '[ ! -e "$ETC/tesla-sentry.conf" ]'
done_case

echo "== restore 幂等: 连续两次恢复不报错 =="
new_etc
printf 'UUID=old /mnt/tsf-storage ext4 defaults 0 2\n' > "$ETC/fstab"
SNAP="$CASE/state"
tsf_state_snapshot "$SNAP" fstab
printf 'UUID=X /mnt/tsf-storage ext4 defaults 0 2\n' > "$ETC/fstab"
tsf_state_restore "$SNAP"; r1=$?
tsf_state_restore "$SNAP"; r2=$?
check "第一次 restore 成功" '[ $r1 -eq 0 ]'
check "第二次 restore 成功" '[ $r2 -eq 0 ]'
check "fstab 稳定为旧值" 'grep -q "UUID=old" "$ETC/fstab"'
done_case

echo "== commit 丢弃备份, 之后 restore 不再回滚 =="
new_etc
printf 'UUID=old /mnt/tsf-storage ext4 defaults 0 2\n' > "$ETC/fstab"
SNAP="$CASE/state"
tsf_state_snapshot "$SNAP" fstab
printf 'UUID=NEW /mnt/tsf-storage ext4 defaults,nofail 0 2\n' > "$ETC/fstab"
tsf_state_commit "$SNAP"
check "commit 后备份目录删除" '[ ! -d "$SNAP" ]'
tsf_state_restore "$SNAP"
check "commit 后 restore 不改文件" 'grep -q "UUID=NEW" "$ETC/fstab"'
done_case

echo "== has 判定未提交 =="
new_etc
printf 'x\n' > "$ETC/fstab"
SNAP="$CASE/state"
tsf_state_snapshot "$SNAP" fstab
tsf_state_has "$SNAP" fstab && ok "未提交时 has 为真" || bad "未提交时 has 为真"
tsf_state_commit "$SNAP"
tsf_state_has "$SNAP" fstab && bad "提交后 has 应为假" || ok "提交后 has 为假"
done_case

echo "== safe_move 记录搬运, 逆序回滚可还原原位 =="
new_etc
# 抽 storage-use.sh 里的 safe_move / rollback_moves 逻辑做独立验证
MOVED_FILE="$CASE/moved"
: > "$MOVED_FILE"
safe_move() {
    src="$1"; dst="$2"
    [ -e "$src" ] || return 0
    [ -e "$dst" ] && return 0
    mv "$src" "$dst"
    printf '%s\t%s\n' "$src" "$dst" >> "$MOVED_FILE"
}
rollback_moves() {
    [ -n "$MOVED_FILE" ] && [ -f "$MOVED_FILE" ] || return 0
    tac "$MOVED_FILE" 2>/dev/null | while IFS="	" read -r src dst; do
        [ -n "$src" ] && [ -n "$dst" ] || continue
        if [ -e "$dst" ] && [ ! -e "$src" ]; then
            mv "$dst" "$src" 2>/dev/null || true
        fi
    done
    rm -f "$MOVED_FILE" 2>/dev/null || true
}
mkdir -p "$CASE/src/archive" "$CASE/src/cache"
printf 'img\n' > "$CASE/src/teslacam.img"
printf 'a\n' > "$CASE/src/archive/a"
mkdir -p "$CASE/dst"
safe_move "$CASE/src/teslacam.img" "$CASE/dst/teslacam.img"
safe_move "$CASE/src/archive" "$CASE/dst/archive"
check "第一步搬运后源消失" '[ ! -e "$CASE/src/teslacam.img" ] && [ -f "$CASE/dst/teslacam.img" ]'
check "MOVED 记录 2 行" '[ $(wc -l < "$MOVED_FILE") -eq 2 ]'
# 模拟中途失败: 只搬了 2 个, 第三个(cache)失败
rollback_moves
check "回滚后镜像回原位" '[ -f "$CASE/src/teslacam.img" ] && [ ! -e "$CASE/dst/teslacam.img" ]'
check "回滚后归档回原位" '[ -d "$CASE/src/archive" ] && [ ! -e "$CASE/dst/archive" ]'
check "回滚后 MOVED 清除" '[ ! -f "$MOVED_FILE" ]'
done_case

echo "== 失败注入: storage-init 在准备镜像阶段失败时 fstab/conf 必须回到原状 =="
new_etc
# 构造一个与 storage-init.sh 同构的极简流程: 快照 -> 改 fstab/conf -> 假失败 -> cleanup restore
printf 'UUID=OLD /mnt/tsf-storage ext4 defaults 0 2\n' > "$ETC/fstab"
printf 'TSF_IMG=/old/teslacam.img\nTSF_ARCHIVE=/old/archive\nTSF_CACHE=/old/cache\n' > "$ETC/tesla-sentry.conf"
printf '* * * * * root true\n' > "$ETC/cron.d/tesla-sentry"
SNAP="$CASE/state"
tsf_state_snapshot "$SNAP" fstab conf cron
# 模拟已经写入新 UUID 和新路径
printf 'UUID=NEW /mnt/tsf-storage ext4 defaults,nofail 0 2\n' > "$ETC/fstab"
printf 'TSF_IMG=/new/teslacam.img\nTSF_ARCHIVE=/new/archive\nTSF_CACHE=/new/cache\n' > "$ETC/tesla-sentry.conf"
rm -f "$ETC/cron.d/tesla-sentry"; printf '* * * * * root true\n' > "$ETC/cron.d/tesla-sentry.disabled"
# 失败路径: 未 commit 直接 restore
tsf_state_restore "$SNAP"
check "fstab 回到 OLD UUID" 'grep -q "UUID=OLD" "$ETC/fstab"'
check "fstab 不含 NEW" '! grep -q "UUID=NEW" "$ETC/fstab"'
check "conf 回到旧路径" 'grep -q "TSF_IMG=/old/teslacam.img" "$ETC/tesla-sentry.conf"'
check "conf 不含新路径" '! grep -q "/new/" "$ETC/tesla-sentry.conf"'
check "cron 活动文件恢复" '[ -f "$ETC/cron.d/tesla-sentry" ]'
done_case

echo "== 成功路径: commit 后 cleanup 不误回滚 =="
new_etc
printf 'UUID=OLD /mnt/tsf-storage ext4 defaults 0 2\n' > "$ETC/fstab"
printf 'TSF_IMG=/old/teslacam.img\n' > "$ETC/tesla-sentry.conf"
SNAP="$CASE/state"
tsf_state_snapshot "$SNAP" fstab conf
printf 'UUID=NEW /mnt/tsf-storage ext4 defaults,nofail 0 2\n' > "$ETC/fstab"
printf 'TSF_IMG=/new/teslacam.img\n' > "$ETC/tesla-sentry.conf"
tsf_state_commit "$SNAP"
# cleanup 仍会调用 restore, 此时备份已删, 应空操作
tsf_state_restore "$SNAP" 2>/dev/null || true
check "成功后 fstab 保留 NEW" 'grep -q "UUID=NEW" "$ETC/fstab"'
check "成功后 conf 保留新路径" 'grep -q "TSF_IMG=/new/teslacam.img" "$ETC/tesla-sentry.conf"'
done_case

echo "== 快照目录中的 .path 不含空行 (dash 下 read 安全) =="
new_etc
printf 'x\n' > "$ETC/fstab"
SNAP="$CASE/state"
tsf_state_snapshot "$SNAP" fstab conf cron
check "conf.path 记录了真实路径" 'grep -q "tesla-sentry.conf" "$SNAP/conf.1.path"'
check "cron 有两条 path 记录" '[ -f "$SNAP/cron.1.path" ] && [ -f "$SNAP/cron.2.path" ]'
done_case

echo
echo "合计: $pass 通过, $fail 失败"
[ "$FAILD" -eq 0 ] || exit 1
