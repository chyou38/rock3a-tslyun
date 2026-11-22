#!/bin/bash
# ROCK 3A mainline: rkvdec 硬解 + FFmpeg 多核缩放/编码。
# 仅用于已经实测的远程低码率档位; 不写死重启后可能变化的 video 节点编号。
set -euo pipefail

SRC=${1:?source mp4 required}
DST=${2:?destination mp4 required}
W=${3:-480}
H=${4:-360}
FPS=${5:-15}
BITRATE=${6:-600}
MAXRATE=${7:-900}
BUF=${8:-1800}
LIMIT=${9:-0}                 # >0 时只生成前 N 秒预缓冲; 0=完整转码
FFMPEG=${FFMPEG:-ffmpeg}
FFPROBE=${FFPROBE:-ffprobe}
GST=${GST_LAUNCH:-gst-launch-1.0}

VIDEO=""
for name in /sys/class/video4linux/video*/name; do
    [ -r "$name" ] || continue
    if [ "$(cat "$name")" = "rkvdec" ]; then
        VIDEO=/dev/$(basename "$(dirname "$name")")
        break
    fi
done
MEDIA=""
for dev in /dev/media*; do
    [ -e "$dev" ] || continue
    if media-ctl -d "$dev" -p 2>/dev/null | grep -q 'driver.*rkvdec'; then
        MEDIA=$dev
        break
    fi
done
if [ -z "$VIDEO" ] || [ -z "$MEDIA" ]; then
    echo "未找到 rkvdec stateless 硬解节点" >&2
    exit 2
fi

IFS=, read -r CODEC SW SH < <("$FFPROBE" -v error -select_streams v:0 \
    -show_entries stream=codec_name,width,height -of csv=p=0 "$SRC")
[ -n "$SW" ] && [ -n "$SH" ] || { echo "无法读取源视频尺寸" >&2; exit 2; }

# H.264 可直接输出 NV12。HEVC Main 10 则先降帧、按目标比例缩放,
# 再把 10bit 转成 8bit NV12, 避免通过本地管道搬运 4K 原始帧。
PW=$SW
PH=$SH
if [ "$CODEC" = "hevc" ] || [ "$CODEC" = "h265" ]; then
    DECODER=(h265parse ! v4l2slh265dec video-device="$VIDEO" media-device="$MEDIA")
    PW=$W
    PH=$(( (SH * W + SW / 2) / SW ))
    if [ "$PH" -gt "$H" ]; then
        PH=$H
        PW=$(( (SW * H + SH / 2) / SH ))
    fi
    PW=$(( (PW + 1) / 2 * 2 ))
    PH=$(( (PH + 1) / 2 * 2 ))
    POST=(videorate ! "video/x-raw,framerate=${FPS}/1" !
          videoscale ! "video/x-raw,width=${PW},height=${PH}" !
          videoconvert ! video/x-raw,format=NV12 ! fdsink fd=1 sync=false)
elif [ "$CODEC" = "h264" ]; then
    DECODER=(h264parse ! v4l2slh264dec video-device="$VIDEO" media-device="$MEDIA")
    POST=(videorate ! "video/x-raw,format=NV12,framerate=${FPS}/1" ! fdsink fd=1 sync=false)
else
    echo "VPU 暂不支持输入编码: $CODEC" >&2
    exit 2
fi

# 原始帧只用于盒子本地管道, 不走网络; 远程发送的仍是重新编码后的低码率 H.264。
# 预缓冲模式用 FFmpeg -t 截断输出; GStreamer 写端随后收到 SIGPIPE 属预期,
# 只要 FFmpeg 成功且产物时长足够就视为成功。
FFMPEG_LIMIT=()
if [ "$LIMIT" -gt 0 ]; then
    FFMPEG_LIMIT=(-t "$LIMIT")
fi
set +e
"$GST" -q filesrc location="$SRC" ! qtdemux ! "${DECODER[@]}" ! "${POST[@]}" | \
"$FFMPEG" -y -hide_banner -loglevel error \
    -f rawvideo -pixel_format nv12 -video_size "${PW}x${PH}" -framerate "$FPS" -i pipe:0 \
    -i "$SRC" -map 0:v:0 -map '1:a?' \
    -vf "scale=${W}:${H}:force_original_aspect_ratio=decrease:flags=lanczos" \
    -c:v libx264 -preset ultrafast -threads "${TSF_VPU_ENC_THREADS:-4}" \
    -b:v "${BITRATE}k" -maxrate "${MAXRATE}k" -bufsize "${BUF}k" \
    -c:a copy -movflags +faststart -f mp4 "${FFMPEG_LIMIT[@]}" "$DST"
PIPE_RC=("${PIPESTATUS[@]}")
set -e
GST_RC=${PIPE_RC[0]}
FF_RC=${PIPE_RC[1]}
if [ "$FF_RC" -ne 0 ]; then
    exit "$FF_RC"
fi
if [ "$GST_RC" -ne 0 ] && [ "$LIMIT" -le 0 ]; then
    exit "$GST_RC"
fi
if [ "$LIMIT" -gt 0 ]; then
    OUT_DUR=$("$FFPROBE" -v error -show_entries format=duration -of default=nw=1:nk=1 "$DST" 2>/dev/null || echo 0)
    awk -v d="$OUT_DUR" -v n="$LIMIT" 'BEGIN { exit !(d >= n - 0.6) }' || {
        echo "预缓冲时长不足: ${OUT_DUR}s < ${LIMIT}s" >&2
        exit 3
    }
fi
