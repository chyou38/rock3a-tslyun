#!/bin/sh
# tsf-state.sh - storage-init.sh / storage-use.sh 的「可回滚状态快照」纯函数库
#
# 设计目标: 只做文件与文本层面的备份/恢复/比对, 不分区、不挂载、不碰设备节点,
# 因此可以在任意普通机器上用 dash 离线单元测试 (tests/test_tsf_state.sh)。
# 调用方 (storage-init.sh / storage-use.sh) 在改动任何系统状态之前先 snapshot,
# 失败时 restore; 成功后再 commit (丢弃备份并保留本次改动)。
#
# 被管理/备份的"提交点":
#   fstab    : /etc/fstab            —— 挂载配置, 先写后挂载时最容易留下半成品
#   conf     : /etc/tesla-sentry.conf —— TSF_IMG/TSF_ARCHIVE/TSF_CACHE 路径
#   cron     : /etc/cron.d/tesla-sentry (及其 .disabled 改名) —— 中断期间停用
# 备份目录放在同一文件系统 (/etc 下) 以便 mv 原子, 且不跨盘。
#
# 用法 (被 source):
#   . "$TSF_DIR/tsf-state.sh"
#   TSF_STATE_DIR=/etc/.tsf-rollback
#   tsf_state_snapshot "$TSF_STATE_DIR" fstab conf cron || fail
#   ... 改文件 ...
#   tsf_state_restore "$TSF_STATE_DIR" || fail   # 失败路径
#   tsf_state_commit  "$TSF_STATE_DIR"           # 成功路径
#
# 每个提交点的备份文件按 <name>.<which> 命名, which ∈ orig|bak;
#   orig 是快照时刻原文件的内容 (不存在时记 (.absent) 标记文件);
#   bak  是 <name> 对应的真实文件路径, 供 restore 知道写回哪里。
set -u

# 把提交点名映射为需要备份/恢复的真实文件路径 (输出到 stdout)。
# cron 提交点实际涉及两个路径: 活动文件与 .disabled; 返回两行。
tsf_state_paths() {
    _name="$1"
    _etc="${TSF_ETC:-/etc}"
    case "$_name" in
        fstab) echo "$_etc/fstab" ;;
        conf)  echo "$_etc/tesla-sentry.conf" ;;
        cron)  echo "$_etc/cron.d/tesla-sentry"
               echo "$_etc/cron.d/tesla-sentry.disabled" ;;
        *)     echo "未知提交点: $_name" >&2; return 2 ;;
    esac
}

# 快照: 把每个提交点的原文件内容写入备份目录, 不存在则写 .absent。
# 只在"本次运行"首次成功前调用一次; 重复调用会覆盖, 由调用方保证顺序。
tsf_state_snapshot() {
    _dir="$1"; shift
    [ -n "$_dir" ] || { echo "tsf_state_snapshot: 缺少备份目录" >&2; return 2; }
    mkdir -p "$_dir" || return 1
    for _name in "$@"; do
        _paths=$(tsf_state_paths "$_name") || return $?
        _i=0
        for _p in $_paths; do
            _i=$((_i + 1))
            _dest="$_dir/$_name.$_i.orig"
            printf '%s\n' "$_p" > "$_dir/$_name.$_i.path" || return 1
            if [ -f "$_p" ]; then
                cp -p "$_p" "$_dest" || return 1
            else
                : > "$_dest.absent" || return 1
            fi
        done
    done
    return 0
}

# 恢复: 用备份内容写回 (不存在过的文件删除), 幂等, 可重复调用。
tsf_state_restore() {
    _dir="$1"
    [ -n "$_dir" ] || { echo "tsf_state_restore: 缺少备份目录" >&2; return 2; }
    _rc=0
    for _pf in "$_dir"/*.path; do
        [ -f "$_pf" ] || continue
        _prefix=${_pf%.path}
        _p=$(cat "$_pf")
        [ -n "$_p" ] || continue
        if [ -f "$_prefix.orig" ]; then
            mkdir -p "$(dirname "$_p")" || { _rc=1; continue; }
            cp -p "$_prefix.orig" "$_p.tmp.$$" && mv -f "$_p.tmp.$$" "$_p" || { _rc=1; rm -f "$_p.tmp.$$"; }
        elif [ -f "$_prefix.orig.absent" ]; then
            rm -f "$_p"
        fi
    done
    return $_rc
}

# 提交: 丢弃备份, 让本次改动成为新的基线。
tsf_state_commit() {
    _dir="$1"
    [ -n "$_dir" ] || return 2
    rm -rf "$_dir"
}

# 判断某个提交点是否"已备份且尚未提交"。用于 cleanup 只在改动过时才恢复。
tsf_state_has() {
    _dir="$1"; _name="$2"
    [ -f "$_dir/$_name.1.path" ]
}
