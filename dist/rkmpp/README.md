# RKMPP ffmpeg / ffprobe（BSP 硬解硬编）

本目录是 ROCK 3A（RK3568）在 **Radxa 官方 Debian 12 BSP** 下自编译的 ffmpeg-rockchip 产物，用于 H.264/H.265 硬解、`h264_rkmpp` 硬编和 `scale_rkrga` 硬件缩放。

| 文件 | 说明 |
|---|---|
| `rkmpp-bin.tar.gz` | 已 strip 的 `ffmpeg` / `ffprobe` 二进制（解包到 `/opt/rkmpp/bin`） |
| `install-rkmpp.sh` | 解包、检查运行时依赖、软链 `/usr/local/bin` 与 `/usr/bin`、写 `TSF_FFMPEG` / `TSF_FFPROBE` |
| `deps.txt` | Debian 12 运行时依赖；重建时才需要 dev 包 |

## 安装

```sh
cd dist/rkmpp
sudo bash install-rkmpp.sh -y
sudo systemctl restart sentry-viewer
```

脚本会把原系统 `ffmpeg` / `ffprobe` 首次备份为 `*.debian-orig`，回退时移回即可。

## 验证

```sh
ffmpeg -version | head -2
ffmpeg -hide_banner -encoders | grep rkmpp
ffmpeg -hide_banner -filters | grep rkrga
ls -l /dev/mpp_service /dev/rga
```

没有 `/dev/mpp_service` 的 mainline 内核无法使用硬解/硬编；本包只适用于 BSP。
