#!/bin/sh
# teslabox-usb-irq.sh - 把 DWC3 OTG 中断钉到最后一个 CPU 核
#
# 背景: 播放/转码把 0-2 核打满时, 若 dwc3 中断也落在这些核上, OTG 内核处理会被
#       饿死, 车机写 U 盘超时 → device reset 风暴 → 车机判定 U 盘弹出。
# 方案: 网页/转码服务 CPUAffinity=0-2 (见 install.sh), 本脚本把 dwc3 中断独占
#       最后一核, 两边互不抢占。开机由 teslabox-usb-irq.service 执行一次。
irq=$(awk '/dwc3/{gsub(":","",$1);print $1;exit}' /proc/interrupts)
[ -n "$irq" ] || exit 0
last=$(( $(nproc) - 1 ))
[ "$last" -ge 0 ] || last=0
echo "$last" > "/proc/irq/$irq/smp_affinity_list" 2>/dev/null || true