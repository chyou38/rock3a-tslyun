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
ENC_KIND=${10:-h264}
FFMPEG=${FFMPEG:-/opt/rkmpp/bin/ffmpeg}
FFPROBE=${FFPROBE:-/opt/rkmpp/bin/ffprobe}

[ -e /dev/mpp_service ] || { echo "没有 /dev/mpp_service" >&2; exit 2; }
[ -x "$FFMPEG" ] || { echo "没有 ffmpeg-rockchip" >&2; exit 2; }
# 注意: 不能写成 ffmpeg ... | grep -q (pipefail 下 grep 提前退出会让管道返回 141)
ENCODERS=$("$FFMPEG" -hide_banner -encoders 2>/dev/null || true)
case "$ENCODERS" in *h264_rkmpp*) ;; *) echo "ffmpeg 不带 rkmpp" >&2; exit 2 ;; esac
# 高画质档可选 HEVC(同画质省 ~23% 体积, 实测编码还快一点); 没有 hevc_rkmpp 就退回 h264
ENC=h264_rkmpp
if [ "$ENC_KIND" = "hevc" ]; then
    case "$ENCODERS" in *hevc_rkmpp*) ENC=hevc_rkmpp ;; *) echo "没有 hevc_rkmpp, 用 h264" >&2 ;; esac
fi
TAG=(); [ "$ENC" = "hevc_rkmpp" ] && TAG=(-tag:v hvc1)
# 码控分档 (2026-11-25 实测 58s 素材@720p):
#   360p/480p 用 CBR: 弱网播放码率平整, 体积比 VBR 小 ~16%
#   720p+ 用 VBR + QP 限幅: 暗部/噪点不会把码率顶爆, 体积小 ~6%, 画质 SSIM 0.978 不变
if [ "$BITRATE" -le 950 ]; then
    RC=(-rc_mode 1)
else
    RC=(-rc_mode 0 -qp_init 26 -qp_min 22 -qp_max 40)
fi

IFS=, read -r CODEC SW SH < <("$FFPROBE" -v error -select_streams v:0 \
    -show_entries stream=codec_name,width,height -of csv=p=0 "$SRC")
[ -n "${SW:-}" ] && [ -n "${SH:-}" ] || { echo "无法读取源尺寸" >&2; exit 2; }

case "$CODEC" in
    h264|avc1)      DEC=h264_rkmpp ;;
    hevc|h265|hev1) DEC=hevc_rkmpp ;;
    mpeg4)          DEC=mpeg4_rkmpp ;;
    *) echo "MPP 不支持输入编码: $CODEC" >&2; exit 2 ;;
esac

# 目标框内等比缩放, 宽高四舍五入到 16 的倍数(至少 16)
# 2026-11-25 实测: 1440x932 / 960x622 / 480x310 这类非 16 对齐高度在 iOS/部分安卓浏览器
# 会被判定为不可硬解而退回软解("没有解码, 很慢"); 对齐后用 932->928 / 622->624 / 310->304,
# 比例变化 <0.5%, 肉眼不可见。取整用四舍五入, 不用向上取整, 免得 310->320 拉伸 3%。
PW=$W
PH=$(( (SH * W + SW / 2) / SW ))
if [ "$PH" -gt "$H" ]; then PH=$H; PW=$(( (SW * H + SH / 2) / SH )); fi
PW=$(( ((PW + 8) / 16) * 16 )); PH=$(( ((PH + 8) / 16) * 16 ))
[ "$PW" -lt 16 ] && PW=16
[ "$PH" -lt 16 ] && PH=16

# 预缓冲: -t 必须放在 -i 前, 解码到 N 秒就收工
LIM=(); [ "$LIMIT" -gt 0 ] && LIM=(-t "$LIMIT")

# force_original_aspect_ratio=disable: 默认 decrease 会让 RGA 按源比例 fit, 720p 框 960x624
# 被缩成 960x622(非16对齐), 360p 也变成 470x304(宽非16); disable 后强制输出 PWxPH(全16对齐)。
# reset_sar=1: 不加时产物 SAR 不是 1:1(实测 2353:2345 / 20996:21105), 浏览器按 SAR 校正后
# videoWidth/Height 变成 963x624 / 1440x933, 画面轻微变形且部分播放器会绕开常规硬解路径。
# 2026-11-25 实测: 加这两个参数耗时 5.13s vs 5.15s, 零代价。
RK_VF="scale_rkrga=w=${PW}:h=${PH}:format=nv12:force_original_aspect_ratio=disable:reset_sar=1,fps=${FPS}"
# 第二选择: RGA 初始化失败时退回软件缩放(仍硬解硬编)
SW_VF="scale=${PW}:${PH}:flags=bilinear,setsar=1,fps=${FPS}"
BASE=("$FFMPEG" -nostdin -hide_banner -loglevel error -y "${LIM[@]}"
      -hwaccel rkmpp -hwaccel_output_format drm_prime
      -c:v "$DEC" -i "$SRC"
      -map 0:v:0 -map '0:a?' -c:a copy
      -c:v "$ENC" "${RC[@]}" -b:v "${BITRATE}k" -maxrate "${MAXRATE}k" -bufsize "${BUF}k"
      "${TAG[@]}" -g $((FPS * 2)) -movflags +faststart -f mp4)

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
