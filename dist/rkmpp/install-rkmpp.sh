#!/bin/bash
# ffmpeg-rockchip 一键恢复 (重装系统/换盘后, /opt 被清空时用)
#
# 背景: RK3568 (ROCK 3A) 上把系统 ffmpeg 换成自编译的 ffmpeg-rockchip(9.1),
#       才能用 h264_rkmpp 硬编 + h264_rkmpp/hevc_rkmpp 硬解 + scale_rkrga 硬件缩放。
#       本包只含 strip 后的 ffmpeg/ffprobe(静态链 libav*), 运行时依赖系统的 librga/librockchip_mpp 等。
#
# 用法 (在盒子上):
#   sudo bash install-rkmpp.sh [-y]
#       -y  缺依赖时直接用 apt 装 (要能联网/配好代理)
#
# 安装后:
#   /usr/local/bin/ffmpeg /usr/bin/ffmpeg /usr/local/bin/ffprobe /usr/bin/ffprobe -> /opt/rkmpp/bin/*
#   /etc/tesla-sentry.conf 写 TSF_FFMPEG / TSF_FFPROBE
#   旧版 debian ffmpeg 备份为 *.debian-orig (首次安装时)
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
TARBALL=${TARBALL:-$HERE/rkmpp-bin.tar.gz}
DEST=${DEST:-/opt}
AUTO_APT=0
[ "${1:-}" = "-y" ] && AUTO_APT=1

[ "$(id -u)" = "0" ] || { echo "请用 root 运行: sudo bash $0" >&2; exit 1; }
[ -f "$TARBALL" ] || { echo "找不到 $TARBALL (和本脚本放同一目录)" >&2; exit 1; }
[ -e /dev/mpp_service ] || echo "警告: 没有 /dev/mpp_service, 需要 Radxa BSP 内核, 否则硬解硬编不可用"

# 1) 解包
echo "[1/4] 解包到 $DEST/rkmpp"
mkdir -p "$DEST"
tar xzf "$TARBALL" -C "$DEST"
chmod +x "$DEST/rkmpp/bin/ffmpeg" "$DEST/rkmpp/bin/ffprobe"

# 2) 运行时库检查 (缺了就直接硬转失败, 提前拦)
DEPS="libdrm2 zlib1g libharfbuzz0b libfribidi0 libass9 librga2 libfontconfig1 libfreetype6 \
libexpat1 libpng16-16 libxml2 libssl3 libvpx7 libwebpmux3 libwebp7 libmp3lame0 libopus0 \
libvorbis0a libvorbisenc2 libx264-164 libx265-199 librockchip-mpp1 libglib2.0-0 libicu72 \
liblzma5 libogg0 libnuma1 libpcre2-8-0 libbrotli1 libgraphite2-3 libstdc++6 libgcc-s1 libc6"
echo "[2/4] 检查运行时依赖"
MISSING=""
for p in $DEPS; do
    dpkg -s "$p" >/dev/null 2>&1 || MISSING="$MISSING $p"
done
if [ -n "$MISSING" ]; then
    echo "缺少: $MISSING"
    if [ "$AUTO_APT" = "1" ]; then
        apt-get update && apt-get install -y --no-install-recommends $MISSING
    else
        echo "请先装: apt-get install -y --no-install-recommends $MISSING  (或加 -y 参数自动装)"
        exit 2
    fi
else
    echo "依赖齐全"
fi
if ldd "$DEST/rkmpp/bin/ffmpeg" | grep -q "not found"; then
    echo "仍有库缺失:" >&2
    ldd "$DEST/rkmpp/bin/ffmpeg" | grep "not found" >&2
    exit 2
fi

# 3) 替换系统 ffmpeg (旧的原版留 .debian-orig 备份, 需要回退时 mv 回来)
echo "[3/4] 软链系统 ffmpeg/ffprobe"
for p in /usr/local/bin/ffmpeg /usr/bin/ffmpeg /usr/local/bin/ffprobe /usr/bin/ffprobe; do
    mkdir -p "$(dirname "$p")"
    if [ -e "$p" ] && [ ! -L "$p" ] && [ ! -e "$p.debian-orig" ]; then
        cp -a "$p" "$p.debian-orig"
        echo "  备份 $(basename "$p") -> $(basename "$p").debian-orig"
    fi
    ln -sf /opt/rkmpp/bin/"$(basename "$p")" "$p"
done

# 4) 写应用配置
echo "[4/4] 写 TSF_FFMPEG / TSF_FFPROBE"
CONF=/etc/tesla-sentry.conf
touch "$CONF"
sed -i '/^TSF_FFMPEG=/d;/^TSF_FFPROBE=/d' "$CONF" 2>/dev/null || true
printf 'TSF_FFMPEG=/opt/rkmpp/bin/ffmpeg\nTSF_FFPROBE=/opt/rkmpp/bin/ffprobe\n' >> "$CONF"

echo "--- 验证 ---"
/opt/rkmpp/bin/ffmpeg -version 2>&1 | head -2
echo "编码器:"; /opt/rkmpp/bin/ffmpeg -hide_banner -encoders 2>/dev/null | grep -E "_rkmpp" || true
echo "滤镜:";   /opt/rkmpp/bin/ffmpeg -hide_banner -filters 2>/dev/null | grep -E "rkrga" || true
echo "OK. 若已是运行中, 重启服务: sudo systemctl restart sentry-viewer"
