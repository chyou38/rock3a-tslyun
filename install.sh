#!/bin/sh
# TSL Sentry Box (ROCK 3A) - 一键安装脚本
# 用法: sudo ./install.sh [选项]
#   --size GB        虚拟U盘容量, 默认 64
#   --port PORT      网页端口, 默认 80
#   --archive DIR    归档区路径, 默认 /archive
#   --dir DIR        安装目录, 默认 /opt/tesla-sentry
#   -h, --help       显示帮助
set -e

SIZE_GB=64
PORT=80
ARCHIVE=/archive
TSF_DIR=/opt/tesla-sentry

while [ $# -gt 0 ]; do
    case "$1" in
        --size)    SIZE_GB="$2"; shift 2 ;;
        --port)    PORT="$2"; shift 2 ;;
        --archive) ARCHIVE="$2"; shift 2 ;;
        --dir)     TSF_DIR="$2"; shift 2 ;;
        -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
        *) echo "未知参数: $1 (用 --help 查看)"; exit 1 ;;
    esac
done

IMG="$TSF_DIR/teslacam.img"
CONF=/etc/tesla-sentry.conf

say() { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[ERROR]\033[0m %s\n' "$*" >&2; exit 1; }

# ---------------- 0. 权限与环境 ----------------
[ "$(id -u)" = "0" ] || die "请用 root 运行 (sudo ./install.sh)"
SRC_DIR=$(cd "$(dirname "$0")" && pwd)
[ -f "$SRC_DIR/sentry-viewer.py" ] || die "找不到 sentry-viewer.py, 请在项目根目录运行"

MODEL=$(tr -d '\000' < /proc/device-tree/model 2>/dev/null || true)
case "$MODEL" in
    *"ROCK 3A"*) ;;
    *) die "本脚本仅适配 Radxa ROCK 3A (RK3568), 当前主板: ${MODEL:-未知}" ;;
esac

PYTHON=$(command -v python3 || true)
[ -n "$PYTHON" ] || die "需要 python3 (apt install python3)"

say "检查 USB Gadget 支持..."
GADGET=""
for d in /sys/kernel/config/usb_gadget/*/; do
    [ -d "$d/configs" ] && { GADGET="${d%/}"; break; }
done
[ -n "$GADGET" ] || die "未发现 USB gadget (configfs 未挂载或设备不支持 Device 模式)"
[ -n "$(ls /sys/class/udc/ 2>/dev/null | head -1)" ] || die "未发现 UDC 控制器"

if ! grep -qw exfat /proc/filesystems 2>/dev/null; then
    modprobe exfat 2>/dev/null || true
    grep -qw exfat /proc/filesystems 2>/dev/null || die "内核不支持 exFAT (需要 CONFIG_EXFAT_FS)"
fi

if [ -r /proc/config.gz ]; then
    zcat /proc/config.gz 2>/dev/null | grep -q "CONFIG_USB_F_MASS_STORAGE=y" \
        || echo "  [警告] 内核配置未见 CONFIG_USB_F_MASS_STORAGE, 仍会尝试 (见 README 硬件要求)"
fi

FREE_MB=$(df -Pm "$(dirname "$TSF_DIR")" 2>/dev/null | awk 'NR==2{print $4}')
[ -z "$FREE_MB" ] && FREE_MB="?"
say "存储空闲: ${FREE_MB}MB, 计划镜像 ${SIZE_GB}G (稀疏文件, 按实际写入占用)"

# 容量余量: 镜像是稀疏文件, 预置文件系统后初始只占几十 KB; 但车机持续录像会
# 逐步把它写满, 镜像 + 归档 + 系统必须留出余量, 否则磁盘写满后块设备返回
# I/O 错误, 车机会把 U 盘判为「读不出/需要格式化」。
# 经验值: 64G 镜像在哨兵 4 路约 8.4G/小时下可滚动录制 7 小时以上, 足够日常使用。
if [ "$FREE_MB" != "?" ]; then
    NEED_MB=$((SIZE_GB * 1024 + 20480))    # 镜像满容量 + 至少 20G 归档/系统余量
    if [ "$FREE_MB" -lt "$NEED_MB" ]; then
        echo "  [警告] 空闲 ${FREE_MB}MB 可能放不下 ${SIZE_GB}G 镜像+归档余量(约 ${NEED_MB}MB)"
        echo "         车机录像会逐步写满镜像; 空间紧张请降低容量, 例如:"
        echo "           sudo ./install.sh --size 32"
    fi
fi

# 缓存目录 (缩略图/遥测/合成临时文件): 固定在安装目录下
CACHE_DIR="$TSF_DIR/cache"
mkdir -p "$CACHE_DIR/thumbs" "$CACHE_DIR/tel-cache" 2>/dev/null || true

# ffmpeg 探测: 缩略图与部分导出功能依赖, 缺了只是没有缩略图
FFMPEG="$(command -v ffmpeg 2>/dev/null || true)"
FFPROBE="$(command -v ffprobe 2>/dev/null || true)"
if [ -x "$FFMPEG" ]; then say "ffmpeg: $FFMPEG"
else echo "  [提示] 未找到 ffmpeg, 列表缩略图会缺失 (装一个即可: apt install ffmpeg)"; fi

# ---------------- 1. 目录与文件 ----------------
say "安装到 $TSF_DIR ..."
mkdir -p "$TSF_DIR"
cp "$SRC_DIR/sentry-viewer.py"      "$TSF_DIR/sentry-viewer.py"
cp "$SRC_DIR/tesla-live-sync.py"    "$TSF_DIR/tesla-live-sync.py"
cp "$SRC_DIR/scripts/tesla-gadget.sh" "$TSF_DIR/tesla-gadget.sh"
cp "$SRC_DIR/scripts/tesla-sync.sh"   "$TSF_DIR/tesla-sync.sh"
cp "$SRC_DIR/scripts/usb-selfheal.sh" "$TSF_DIR/usb-selfheal.sh"
cp "$SRC_DIR/scripts/tesla-img.sh"    "$TSF_DIR/tesla-img.sh"
cp "$SRC_DIR/scripts/storage-use.sh"  "$TSF_DIR/storage-use.sh"
cp "$SRC_DIR/scripts/storage-init.sh" "$TSF_DIR/storage-init.sh"
cp "$SRC_DIR/scripts/prepare-teslacam.sh" "$TSF_DIR/prepare-teslacam.sh"
cp "$SRC_DIR/scripts/tsf-vpu-transcode.sh" "$TSF_DIR/tsf-vpu-transcode.sh"
cp "$SRC_DIR/scripts/tsf-check.sh"    "$TSF_DIR/tsf-check.sh"
cp "$SRC_DIR/scripts/mkexfat.py"     "$TSF_DIR/mkexfat.py"
cp "$SRC_DIR/scripts/tsf-ap.sh"      "$TSF_DIR/tsf-ap.sh"
cp "$SRC_DIR/scripts/ap-policy.sh"   "$TSF_DIR/ap-policy.sh"
cp "$SRC_DIR/scripts/fan-control.sh" "$TSF_DIR/fan-control.sh"
chmod +x "$TSF_DIR"/*.sh "$TSF_DIR"/*.py

mkdir -p "$ARCHIVE"/SentryClips "$ARCHIVE"/SavedClips "$ARCHIVE"/RecentClips \
         "$ARCHIVE"/.skins "$ARCHIVE"/boombox-queue "$ARCHIVE"/boombox-done "$ARCHIVE"/files

# ---------------- 2. 镜像 ----------------
# 已经在跑的设备: 复用当前正在导出的镜像, 避免重装后车机看到一块空盘
CUR_EXPORT=""
for f in "$GADGET"/functions/mass_storage*/lun.0/file; do
    [ -f "$f" ] || continue
    CUR_EXPORT=$(cat "$f" 2>/dev/null)
    [ -n "$CUR_EXPORT" ] && break
done
if [ -n "$CUR_EXPORT" ] && [ -f "$CUR_EXPORT" ]; then
    IMG="$CUR_EXPORT"
    say "检测到已在导出的镜像, 沿用它: $IMG"
fi

# 新部署: 直接生成完整的 exFAT 文件系统 + TeslaCam 目录, 车机插上就能
# 识别容量并开始录制, 不再弹「格式化 USB 设备」。
# 旧版只建了全零空盘, 这里检测到没有 exFAT 签名也会补写一次 (安全: 镜像里
# 已有任何数据时 mkexfat.py 会拒绝覆盖)。
if [ -f "$IMG" ]; then
    MAGIC=$(dd if="$IMG" bs=1 skip=3 count=5 2>/dev/null)
    if [ "$MAGIC" = "EXFAT" ]; then
        say "镜像已存在且有 exFAT, 跳过: $IMG"
    else
        say "镜像没有文件系统 (旧版空盘), 补写 exFAT + TeslaCam: $IMG"
        sh "$SRC_DIR/scripts/prepare-teslacam.sh" "$IMG" "$SIZE_GB" "$SRC_DIR/scripts/mkexfat.py"
        sync
    fi
else
    say "创建 ${SIZE_GB}G 稀疏镜像并预置 exFAT + TeslaCam 目录 ..."
    sh "$SRC_DIR/scripts/prepare-teslacam.sh" "$IMG" "$SIZE_GB" "$SRC_DIR/scripts/mkexfat.py"
    sync
fi
ls -lh "$IMG"

# ---------------- 3. 配置 ----------------
say "写入配置 $CONF ..."
cat > "$CONF" <<EOF
# TSL Sentry Box (ROCK 3A) 配置 (由 install.sh 生成)
TSF_DIR=$TSF_DIR
TSF_IMG=$IMG
TSF_ARCHIVE=$ARCHIVE
TSF_MNT=/tmp/teslamnt
TSF_LOOP=/dev/loop3
TSF_PORT=$PORT
TSF_IDLE=600
TSF_USB_TIMEOUT=300
TSF_LOSETUP=
TSF_GADGET=$GADGET
TSF_CACHE=$CACHE_DIR
TSF_FFMPEG=$FFMPEG
TSF_FFPROBE=$FFPROBE
TSF_USB_LOCK=/tmp/tsf-usb.lock

# ---- 归档清理 / 在线同步参数 (改完重启服务生效; 0 = 关闭对应策略) ----
# 这些参数写进 conf, 由程序启动时自行读取; 改完重启服务生效。
TSF_RECENT_ROLL_MIN=60
TSF_RECENT_KEEP_MIN=60
# 归档默认按容量滚动: 剩余低于额度 10% 时从最旧事件删到剩余 15%。
# 额度实时 = 整盘容量 - 虚拟U盘容量, 不写死; 天数/体积上限默认关闭, 需要再开。
TSF_ARC_FREE_MIN_PCT=10
TSF_ARC_FREE_TARGET_PCT=15
TSF_BOX_KEEP_DAYS=0
TSF_BOX_MAX_GB=0
TSF_FREE_MIN_MB=4096
TSF_FREE_TARGET_MB=10240
TSF_LIVE_INTERVAL=15
EOF

# ---------------- 3.4 热点与风扇默认配置 ----------------
# 热点三态: auto = 既没连上 WiFi 也没有有线 IP 时自动开; 1 = 常开; 0 = 关闭
if [ ! -f /etc/tsf-ap.conf ]; then
    cat > /etc/tsf-ap.conf <<EOF
AP_ENABLE=auto
AP_SSID=TeslaSentry
AP_PSK=12345678
AP_HW_MODE=g
AP_CHANNEL=6
AP_BAND=auto
AP_CH_MODE=auto
AP_CH_MANUAL=6
EOF
    chmod 600 /etc/tsf-ap.conf
    say "已生成热点配置 /etc/tsf-ap.conf (默认 auto, SSID TeslaSentry, 密码 12345678)"
fi
if [ ! -f /etc/default/pwm-fan ]; then
    cat > /etc/default/pwm-fan <<EOF
FAN_MODE=auto
FAN_MANUAL_DUTY=50
EOF
fi

# ---------------- 3.5 访问认证 ----------------
AUTH_CONF="$TSF_DIR/auth.conf"
if [ -f "$AUTH_CONF" ]; then
    say "认证配置已存在, 保持不动: $AUTH_CONF"
else
    AUTH_PASS=$(head -c 96 /dev/urandom | tr -dc 'a-z2-9' | head -c 10)
    cat > "$AUTH_CONF" <<EOF
# 网页登录凭据 (改完执行 /etc/init.d/tesla-viewer restart 生效)
# 删掉本文件 = 关闭认证, 只有内网使用时才建议这么干
user=admin
pass=$AUTH_PASS
ttl=2592000
EOF
    chmod 600 "$AUTH_CONF"
    say "已生成网页登录账号 -> admin / $AUTH_PASS   (已写入 $AUTH_CONF, 请记好)"
fi

# ---------------- 4. 服务 ----------------
[ -d /etc/systemd/system ] || die "本脚本仅支持 systemd (Armbian / Debian 13); 其他 init 系统未适配"
say "安装 systemd 服务 ..."
cat > /etc/systemd/system/tesla-gadget.service <<EOF
[Unit]
Description=TSL Sentry virtual USB drive
After=local-fs.target
[Service]
Type=oneshot
RemainAfterExit=yes
EnvironmentFile=-$CONF
ExecStart=/bin/sh $TSF_DIR/tesla-gadget.sh on
ExecStop=/bin/sh $TSF_DIR/tesla-gadget.sh off
[Install]
WantedBy=multi-user.target
EOF
cat > /etc/systemd/system/sentry-viewer.service <<EOF
[Unit]
Description=TSL Sentry web viewer
After=network.target tesla-gadget.service
[Service]
Type=simple
EnvironmentFile=-$CONF
ExecStart=$PYTHON $TSF_DIR/sentry-viewer.py
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
EOF
cat > /etc/systemd/system/tesla-live.service <<EOF
[Unit]
Description=TSL Sentry live read-only sync (no mount)
After=tesla-gadget.service
[Service]
Type=simple
EnvironmentFile=-$CONF
ExecStart=$PYTHON $TSF_DIR/tesla-live-sync.py
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
EOF
# 个人热点 / 自动策略 / 风扇温控 (unit 内路径按实际安装目录替换)
for u in tsf-hotspot.service tsf-ap-policy.service tsf-ap-policy.timer pwm-fan-control.service; do
    sed "s|/opt/tesla-sentry|$TSF_DIR|g" "$SRC_DIR/systemd/$u" > "/etc/systemd/system/$u"
done
# hostapd 只在热点需要时由 tsf-ap.sh 拉起, 禁止开机抢跑 (旧版曾因此反复重启)
systemctl disable --now hostapd.service >/dev/null 2>&1 || true
command -v hostapd >/dev/null 2>&1 || echo "  [提示] 未安装 hostapd, 个人热点不可用 (apt install hostapd dnsmasq)"
mkdir -p /etc/cron.d
cat > /etc/cron.d/tesla-sentry <<EOF
*/10 * * * * root /bin/sh $TSF_DIR/tesla-sync.sh >/dev/null 2>&1
*/2 * * * * root /bin/sh $TSF_DIR/usb-selfheal.sh >/dev/null 2>&1
EOF
systemctl daemon-reload
systemctl enable tesla-gadget.service sentry-viewer.service tesla-live.service \
    pwm-fan-control.service tsf-ap-policy.timer >/dev/null 2>&1
# ---------------- 5. 启动 ----------------
say "启动虚拟U盘 ..."
sh "$TSF_DIR/tesla-gadget.sh" on || echo "  [警告] 虚拟U盘启动失败, 见 $TSF_DIR/tesla-gadget.log"

# 中文字体: 设备端烧录行车信息水印时由 libass 使用。
# 没有字体时导出会明确提示"缺少中文字体"(也可以在导出面板点「安装字体」补), 不影响其它功能。
if ! ls "$TSF_DIR"/fonts/*.ttf "$TSF_DIR"/fonts/*.otf >/dev/null 2>&1; then
    say "下载中文字体 (水印用, 约 17MB) ..."
    mkdir -p "$TSF_DIR/fonts"
    FT="$TSF_DIR/fonts/NotoSansSC.ttf"
    for U in \
        "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf" \
        "https://gcore.jsdelivr.net/gh/google/fonts@main/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf" \
        "https://ghfast.top/https://raw.githubusercontent.com/google/fonts/main/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf" \
        "https://raw.githubusercontent.com/google/fonts/main/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf"
    do
        curl -sL --max-time 600 -o "$FT.part" "$U" 2>/dev/null || continue
        SZ=$(wc -c < "$FT.part" 2>/dev/null || echo 0)
        if [ "$SZ" -gt 2000000 ]; then
            mv -f "$FT.part" "$FT"
            echo "  [OK] 字体已安装 ($((SZ/1048576))MB)"
            break
        fi
        rm -f "$FT.part"
    done
    [ -f "$FT" ] || echo "  [提示] 字体下载失败, 不影响其它功能; 进网页 → 导出面板 → 点「安装字体」即可补上"
fi

say "启动查看器 ..."
systemctl restart sentry-viewer.service || true

say "启动实时同步 (车机无感读取) ..."
systemctl restart tesla-live.service || true
systemctl restart pwm-fan-control.service || true
systemctl restart tsf-ap-policy.timer || true
sleep 2

IP=$(ip route 2>/dev/null | awk '/default/{print $3; exit}')
say "完成!"
echo
echo "  虚拟U盘镜像 : $IMG ($(du -sh "$IMG" 2>/dev/null | cut -f1) 实际占用)"
echo "  归档区      : $ARCHIVE"
if [ "$PORT" = "80" ]; then
    echo "  查看器      : http://<设备IP>"
else
    echo "  查看器      : http://<设备IP>:$PORT"
fi
[ -n "$IP" ] && echo "  当前网关    : $IP"
echo
echo "  下一步: 把设备插到车上 -> 车机提示格式化USB -> 确认 -> 哨兵正常录制"
echo "  状态检查: sh $TSF_DIR/tesla-gadget.sh status"
echo "  归档日志: $TSF_DIR/tesla-sync.log"
