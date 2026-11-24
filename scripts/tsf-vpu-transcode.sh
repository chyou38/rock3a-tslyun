#!/bin/bash
# RK3568 ffmpeg-rockchip 全硬件转码:
#   h264_rkmpp/hevc_rkmpp 硬解 -> scale_rkrga 硬件缩放(DRM_PRIME 零拷贝) -> h264_rkmpp 硬编
# 输出标准 H.264 MP4(faststart + 原音轨), 供远程 360p/480p/720p 播放。
# 参数与旧版一致: SRC DST W H FPS BITRATE(kbps) MAXRATE(kbps) BUF(kbps) LIMIT(秒,0=完整)
# 退出码: 0 成功; 2 环境/编码不支持; 3 RGA+软件都失败; 4 输出为空; 5 预缓冲时长不足
set -euo pipefail

SRC=${1:?source mp4 required}
DST=${2:?destination mp4 required}
W=${3:-480}; H=${4:-360}; FPS=${5:-24}
BITRATE=${6:-600}; MAXRATE=${7:-900}; BUF=${8:-1800}; LIMIT=${9:-0}
FFMPEG=${FFMPEG:-/opt/rkmpp/bin/ffmpeg}
FFPROBE=${FFPROBE:-/opt/rkmpp/bin/ffprobe}

[ -e /dev/mpp_service ] || { echo "没有 /dev/mpp_service" >&2; exit 2; }
[ -x "$FFMPEG" ] || { echo "没有 ffmpeg-rockchip" >&2; exit 2; }
# 注意: 不能写成 ffmpeg ... | grep -q (pipefail 下 grep 提前退出会让管道返回 141)
ENCODERS=$("$FFMPEG" -hide_banner -encoders 2>/dev/null || true)
case "$ENCODERS" in *h264_rkmpp*) ;; *) echo "ffmpeg 不带 rkmpp" >&2; exit 2 ;; esac

IFS=, read -r CODEC SW SH < <("$FFPROBE" -v error -select_streams v:0 \
    -show_entries stream=codec_name,width,height -of csv=p=0 "$SRC")
[ -n "${SW:-}" ] && [ -n "${SH:-}" ] || { echo "无法读取源尺寸" >&2; exit 2; }

case "$CODEC" in
    h264|avc1)      DEC=h264_rkmpp ;;
    hevc|h265|hev1) DEC=hevc_rkmpp ;;
    mpeg4)          DEC=mpeg4_rkmpp ;;
    *) echo "MPP 不支持输入编码: $CODEC" >&2; exit 2 ;;
esac

# 目标框内等比缩放, 宽高取偶数
PW=$W
PH=$(( (SH * W + SW / 2) / SW ))
if [ "$PH" -gt "$H" ]; then PH=$H; PW=$(( (SW * H + SH / 2) / SH )); fi
PW=$(( (PW + 1) / 2 * 2 )); PH=$(( (PH + 1) / 2 * 2 ))

# 预缓冲: -t 必须放在 -i 前, 解码到 N 秒就收工
LIM=(); [ "$LIMIT" -gt 0 ] && LIM=(-t "$LIMIT")

# 第一选择: 解码输出 DRM_PRIME, RGA 直接缩放, 不经过 CPU
RK_VF="scale_rkrga=w=${PW}:h=${PH}:format=nv12,fps=${FPS}"
# 第二选择: RGA 初始化失败时退回软件缩放(仍硬解硬编)
SW_VF="scale=${PW}:${PH}:flags=bilinear,fps=${FPS}"
BASE=("$FFMPEG" -nostdin -hide_banner -loglevel error -y "${LIM[@]}"
      -hwaccel rkmpp -hwaccel_output_format drm_prime
      -c:v "$DEC" -i "$SRC"
      -map 0:v:0 -map '0:a?' -c:a copy
      -c:v h264_rkmpp -b:v "${BITRATE}k" -maxrate "${MAXRATE}k" -bufsize "${BUF}k"
      -g $((FPS * 2)) -movflags +faststart -f mp4)

set +e
"${BASE[@]}" -vf "$RK_VF" "$DST"
RC=$?
if [ $RC -ne 0 ] || [ ! -s "$DST" ]; then
    echo "RGA 缩放失败, 退回软件缩放(硬解硬编)" >&2
    "${BASE[@]}" -vf "$SW_VF" "$DST"
    RC=$?
fi
set -e
[ $RC -eq 0 ] && [ -s "$DST" ] || { echo "硬转失败" >&2; exit 3; }

if [ "$LIMIT" -gt 0 ]; then
    OUT_DUR=$("$FFPROBE" -v error -show_entries format=duration -of default=nw=1:nk=1 "$DST" 2>/dev/null || echo 0)
    awk -v d="$OUT_DUR" -v n="$LIMIT" 'BEGIN { exit !(d >= n - 0.6) }' || {
        echo "预缓冲时长不足: ${OUT_DUR}s < ${LIMIT}s" >&2; exit 5; }
fi

echo "hw: ${PW}x${PH}@${FPS} ${BITRATE}kbps $(du -h "$DST" | cut -f1)"
