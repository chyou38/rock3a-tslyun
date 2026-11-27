#!/usr/bin/env python3
"""tesla-live-sync.py - 车机在线只读同步 (不挂载, 不打断录制)

原理
----
虚拟U盘由 gadget 独占导出给车机, Linux 侧无法同时 mount (exFAT 非日志, 双挂载会互毁)。
但内核导出时 backing 文件本身仍可被只读打开 —— 本程序直接按 exFAT 规范解析
镜像的引导扇区 / FAT / 目录项, 沿簇链把车机写好的片段拷到归档区。

车机完全无感知: 全程 os.pread 只读, 不 mount、不写镜像。

"已完成"判定
------------
exFAT 目录项里 DataLength 在文件关闭时才落最终值, 因此必须:
  1. DataLength > 0
  2. 连续两轮扫描 (DataLength, ValidDataLength, mtime) 完全一致
才认为片段写完, 避免把半截 mp4 拷出来 (缺 moov 头放不了)。

用法
----
  tesla-live-sync.py --dump            打印镜像内 TeslaCam 目录树 (调试)
  tesla-live-sync.py --once            扫一轮就退出
  tesla-live-sync.py                   定时归档 (默认 10 分钟, 网页可自定义; 车机写入时顺延)
"""
import argparse
import datetime
import fcntl
import json
import os
import re
import struct
import sys
import threading
import time

# 配置兜底: procd 不把 init.d 的 export 传给服务进程, 这里自己读 conf
# (优先级: 显式环境变量 > /etc/tesla-sentry.conf > 代码默认值; 空值视为用默认)
def _load_conf(path="/etc/tesla-sentry.conf"):
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k.startswith("TSF_") and v and k not in os.environ:
                    os.environ[k] = v
    except OSError:
        pass


_load_conf()

IMG = os.environ.get("TSF_IMG", "/root/teslacam.img")
ARCHIVE = os.environ.get("TSF_ARCHIVE", "/archive")
MNT = os.environ.get("TSF_MNT", "/tmp/teslamnt")
LOG = os.environ.get("TSF_LIVE_LOG", "/root/tesla-live.log")
STATE = os.environ.get("TSF_LIVE_STATE", "/root/.tesla-live-state.json")
INTERVAL = int(os.environ.get("TSF_LIVE_INTERVAL", "15"))
CAR_WRITE_HOLD = float(os.environ.get("TSF_LIVE_CAR_HOLD", "30"))
# 归档调度 (2026-11-26): 不再实时搬运, 默认每 10 分钟归档一次, 间隔在网页
# 「个性化 → 虚拟硬盘 → 归档区」自定义; 「立即归档」写触发文件, 车机空闲后马上执行。
TSF_DIR = os.environ.get("TSF_DIR", "/opt/tesla-sentry")
SETTINGS_FILE = os.environ.get("TSF_SETTINGS", os.path.join(TSF_DIR, "settings.json"))
ARCHIVE_SCHED_FILE = os.path.join(TSF_DIR, "archive-sched.json")
ARCHIVE_NOW_FLAG = os.path.join(TSF_DIR, "archive-now.flag")
# 最近一轮目录探测结果: 哪个分类在写 (供页面区分"行车中"与"哨兵写入")
WRITE_CAT_FILE = os.path.join(TSF_DIR, "write-cat.json")

# 与网页 U盘管理 / 定时归档 / U盘自愈共用的跨进程锁 (那边持排他, 这里持共享)
USB_LOCK = os.environ.get("TSF_USB_LOCK", "/tmp/tsf-usb.lock")
# 归档滚动窗口(分钟), 与 sentry-viewer.py 的 TSF_RECENT_ROLL_MIN 保持一致;
# 窗口外的 RecentClips 根本不再抄进归档 —— 否则清掉的片段会被当成"新片段"重抄一遍,
# 形成 删除→重抄 的死循环, 既拖慢新片段落地又白写 eMMC
ROLL_MIN = int(os.environ.get("TSF_RECENT_ROLL_MIN", "60"))
CATS = ("SentryClips", "SavedClips", "RecentClips")
TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})-")
DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}$")
# 车机 event.json 的 camera 编号 -> 文件名后缀; 推送封面就是从这一路抽帧
CAM_SUFFIX = {0: "front", 3: "left_pillar", 4: "right_pillar",
              5: "left_repeater", 6: "right_repeater", 7: "back"}


def log(msg):
    line = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    try:
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def usb_shared_lock():
    """拿共享锁; 别人(网页挂载/归档/自愈)持排他锁时返回 None, 本轮直接跳过"""
    fd = None
    try:
        fd = os.open(USB_LOCK, os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        return fd
    except OSError:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        return None


def usb_unlock(fd):
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        os.close(fd)
    except OSError:
        pass


def dos_time(raw):
    """exFAT 32bit 时间 → epoch 近似值"""
    if not raw:
        return 0
    sec = (raw & 0x1F) * 2
    minute = (raw >> 5) & 0x3F
    hour = (raw >> 11) & 0x1F
    day = (raw >> 16) & 0x1F
    month = (raw >> 21) & 0x0F
    year = ((raw >> 25) & 0x7F) + 1980
    try:
        return int(time.mktime((year, month, day, hour, minute, sec, 0, 0, -1)))
    except Exception:
        return 0


class Entry:
    __slots__ = ("name", "is_dir", "cluster", "size", "vdl", "mtime", "no_fat_chain", "valid")

    def __init__(self, name, is_dir, cluster, size, vdl, mtime, no_fat_chain, valid):
        self.name = name
        self.is_dir = is_dir
        self.cluster = cluster
        self.size = size
        self.vdl = vdl
        self.mtime = mtime
        self.no_fat_chain = no_fat_chain
        self.valid = valid

    def __repr__(self):
        return "<%s %s size=%d vdl=%d>" % ("DIR" if self.is_dir else "FILE", self.name, self.size, self.vdl)


class ExFat:
    """最小 exFAT 只读解析器 (只依赖标准库)"""

    def __init__(self, path):
        self.path = path
        self.fd = os.open(path, os.O_RDONLY)
        self.fd_ino = os.fstat(self.fd).st_ino
        self.base = 0
        vbr = os.pread(self.fd, 512, 0)
        if vbr[3:11] != b"EXFAT   ":
            lba = struct.unpack_from("<I", vbr, 446 + 8)[0]
            self.base = lba * 512
            vbr = os.pread(self.fd, 512, self.base)
        if len(vbr) < 512 or vbr[3:11] != b"EXFAT   ":
            raise ValueError("不是 exFAT 卷: %s" % path)
        self.part_offset = struct.unpack_from("<Q", vbr, 64)[0]
        self.vol_len = struct.unpack_from("<Q", vbr, 72)[0]
        self.fat_offset = struct.unpack_from("<I", vbr, 80)[0]
        self.fat_len = struct.unpack_from("<I", vbr, 84)[0]
        self.heap_offset = struct.unpack_from("<I", vbr, 88)[0]
        self.cluster_count = struct.unpack_from("<I", vbr, 92)[0]
        self.root_cluster = struct.unpack_from("<I", vbr, 96)[0]
        self.vol_flags = struct.unpack_from("<H", vbr, 106)[0]
        self.bytes_per_sector = 1 << vbr[108]
        self.cluster_size = self.bytes_per_sector << vbr[109]
        self.num_fats = vbr[110]
        # 多 FAT 时由 VolumeFlags bit0 指定活动 FAT
        self.active_fat = self.fat_offset
        if self.num_fats > 1 and (self.vol_flags & 0x1):
            self.active_fat += self.fat_len
        self.heap_byte = self.heap_offset * self.bytes_per_sector

    # ---------- 底层读取 ----------
    def pread(self, n, off):
        out = os.pread(self.fd, n, off + self.base)
        return out

    def cluster_off(self, cluster):
        return self.heap_byte + (cluster - 2) * self.cluster_size

    def read_cluster(self, cluster):
        return self.pread(self.cluster_size, self.cluster_off(cluster))

    def fat_next(self, cluster):
        ent = self.pread(4, self.active_fat * self.bytes_per_sector + cluster * 4)
        if len(ent) < 4:
            return 0xFFFFFFFF
        return struct.unpack("<I", ent)[0]

    def chain(self, first, max_clusters=None):
        """遍历簇链, 返回簇号列表"""
        if first < 2:
            return []
        limit = max_clusters or self.cluster_count
        out = []
        c = first
        while 2 <= c < (self.cluster_count + 2) and len(out) < limit:
            out.append(c)
            nxt = self.fat_next(c)
            if nxt >= 0xFFFFFFF7:  # EOC 区间
                break
            if nxt < 2 or nxt == c:
                break
            c = nxt
        return out

    def clusters_for(self, entry):
        """文件占用簇列表: NoFatChain 位表示连续分配"""
        n = (entry.size + self.cluster_size - 1) // self.cluster_size
        if n <= 0:
            return []
        if entry.no_fat_chain:
            return list(range(entry.cluster, entry.cluster + n))
        return self.chain(entry.cluster, n)

    def read_file(self, entry, limit=None):
        """按簇链读取文件内容 (可分块迭代)"""
        remain = entry.size if limit is None else min(entry.size, limit)
        for c in self.clusters_for(entry):
            if remain <= 0:
                break
            data = self.read_cluster(c)
            if not data:
                break
            chunk = data[:remain]
            remain -= len(chunk)
            yield chunk

    # ---------- 目录解析 ----------
    @staticmethod
    def _set_checksum(buf):
        cs = 0
        for i, b in enumerate(buf):
            if i in (2, 3):
                continue
            cs = ((cs << 15) | (cs >> 1)) & 0xFFFF
            cs = (cs + b) & 0xFFFF
        return cs

    def list_dir(self, cluster, size=0):
        """解析目录簇链, 返回 Entry 列表"""
        if size > 0:
            clist = self.clusters_for(Entry("", True, cluster, size, size, 0, False, True))
        else:
            clist = self.chain(cluster, 64)
        data = b"".join(self.read_cluster(c) for c in clist)
        entries = []
        i = 0
        total = len(data)
        while i + 32 <= total:
            etype = data[i]
            if etype == 0x00:  # 目录结束
                break
            if etype != 0x85:
                i += 32
                continue
            sec_count = data[i + 1]
            set_end = i + 32 * (1 + sec_count)
            if sec_count < 2 or set_end > total:
                break
            raw = data[i:set_end]
            ok = self._set_checksum(raw) == struct.unpack_from("<H", raw, 2)[0]
            attrs = struct.unpack_from("<H", raw, 4)[0]
            mtime = dos_time(struct.unpack_from("<I", raw, 12)[0])
            name = ""
            first = size_ = vdl = 0
            no_chain = False
            for j in range(sec_count):
                sec = raw[32 * (1 + j):32 * (2 + j)]
                st = sec[0]
                if st == 0xC0:
                    flags = sec[1]
                    vdl = struct.unpack_from("<Q", sec, 8)[0]
                    first = struct.unpack_from("<I", sec, 20)[0]
                    size_ = struct.unpack_from("<Q", sec, 24)[0]
                    no_chain = bool(flags & 0x02)
                elif st == 0xC1:
                    name += sec[2:32].decode("utf-16-le", "ignore")
            # 文件名在 0xC1 项里以 NUL 填充到末尾: 取第一个 NUL 之前最可靠
            # (NameLength 字段在部分实现里是字符数而非字节数, 不可全信)
            name = name.split("\x00")[0]
            if not name or name in (".", ".."):
                i = set_end
                continue
            entries.append(Entry(name, bool(attrs & 0x10), first, size_, vdl, mtime, no_chain, ok))
            i = set_end
        return entries

    def find(self, entries, name):
        low = name.lower()
        for e in entries:
            if e.name.lower() == low:
                return e
        return None

    def close(self):
        try:
            os.close(self.fd)
        except Exception:
            pass


# ---------------- 同步逻辑 ----------------
def safe_dest(*parts):
    p = os.path.join(ARCHIVE, *parts)
    rp = os.path.realpath(p)
    if not rp.startswith(os.path.realpath(ARCHIVE) + os.sep):
        raise ValueError("目标越界: %s" % rp)
    return rp


def same_file(path, size):
    try:
        return os.path.getsize(path) == size
    except OSError:
        return False


def same_content(dest, entry, exfat):
    """归档区已有文件与车机镜像中的片段逐字节比对。
    只比大小会漏掉同尺寸就地改写(车机复用同一 exFAT 簇、覆盖写同一事件名),
    那类改动在归档区留下的是旧内容。这里按块流式比较, 不整读进内存。
    返回 True=内容一致(可跳过), False=不同或读取失败(需要重抄)。"""
    try:
        if os.path.getsize(dest) != entry.size:
            return False
        with open(dest, "rb") as f:
            off = 0
            for chunk in exfat.read_file(entry):
                if not chunk:
                    continue
                if f.read(len(chunk)) != chunk:
                    return False
                off += len(chunk)
        return off == entry.size
    except OSError:
        return False
    except Exception:
        return False


_CW_MT = 0
_CW_TS = -100.0


def _car_writing():
    """镜像唯一写入者是车机(本服务全程 pread 只读), mtime 10s 内动过 = 车机正在写。"""
    global _CW_MT, _CW_TS
    now = time.time()
    try:
        mt = os.stat(IMG).st_mtime_ns
        if _CW_MT and mt != _CW_MT:
            _CW_TS = now
        _CW_MT = mt
    except OSError:
        pass
    return now - _CW_TS < 10.0


HOT_FILE = "/tmp/tsf-prewarm-hot"


def _mark_hot(dest):
    """通知 viewer 优先预热刚搬完的文件(落地即预热); 队列超 200KB 截断防失控。"""
    try:
        with open(HOT_FILE, "a", encoding="utf-8") as f:
            f.write(dest + "\n")
        if os.path.getsize(HOT_FILE) > 200000:
            with open(HOT_FILE, encoding="utf-8") as f:
                lines = f.readlines()[-200:]
            with open(HOT_FILE, "w", encoding="utf-8") as f:
                f.writelines(lines)
    except OSError:
        pass


def touch_write_cat():
    """只刷新 write-cat.json 的 ts(保留原有分类标志)。
    哨兵优先通道一次要搬几十~几百 MB, 期间主循环被占住、探测更新不了,
    这里每搬 1MB 续一次心跳, 免得 30 秒后盒子误判"哨兵写入已结束"而锁盘。"""
    try:
        with open(WRITE_CAT_FILE, encoding="utf-8") as f:
            j = json.load(f)
        j["ts"] = time.time()
        tmp = WRITE_CAT_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(j, f)
        os.replace(tmp, WRITE_CAT_FILE)
    except (OSError, ValueError):
        pass


def copy_entry(exfat, entry, dest_path, hold=True):
    """把镜像里的文件写到归档区, 返回写入字节数。
    hold=True: 车机写入期间暂停搬运(车机第一优先), 车机空闲再续。
    hold=False: 哨兵/手动保存走优先通道, 车机在写也只做小让步, 不整段停。"""
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    tmp = dest_path + ".part"
    written = 0
    pace_bytes = 0
    with open(tmp, "wb") as f:
        for chunk in exfat.read_file(entry):
            f.write(chunk)
            written += len(chunk)
            pace_bytes += len(chunk)
            if pace_bytes >= 1048576:
                if hold:
                    # 车机正在写盘 -> 暂停搬运直到车机空闲 (车机写入第一优先)
                    while _car_writing():
                        time.sleep(1.0)
                elif _car_writing():
                    # 哨兵优先通道: 只让一小步, 不把整轮归档挂起
                    time.sleep(0.15)
                if not hold:
                    touch_write_cat()
                pace_bytes = 0
        f.flush()
        os.fsync(f.fileno())
    if written != entry.size:
        os.unlink(tmp)
        raise IOError("读取不完整 %d/%d" % (written, entry.size))
    os.replace(tmp, dest_path)
    return written


def iter_media(exfat, dir_entry, prefix=()):
    """遍历目录, 产出 (相对路径元组, 文件 Entry)"""
    if not dir_entry or not dir_entry.is_dir:
        return
    try:
        entries = exfat.list_dir(dir_entry.cluster, dir_entry.size)
    except Exception as e:
        log("读取目录失败 %s: %s" % (dir_entry.name, e))
        return
    for e in entries:
        if not e.valid:
            continue
        if e.is_dir:
            yield from iter_media(exfat, e, prefix + (e.name,))
        elif (e.name.lower().endswith(".mp4") or e.name.lower() == "event.json") and e.size > 0:
            yield prefix, e


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(st):
    """原子写状态文件; 失败必须留痕。
    早期实现静默吞掉异常, eMMC 满/只读时进度永远写不进去, 页面看不到原因,
    每轮都从旧状态重扫重抄。现在写失败记一条日志(限频), 便于定位。"""
    global _STATE_FAIL_TS
    try:
        with open(STATE + ".tmp", "w") as f:
            json.dump(st, f)
        os.replace(STATE + ".tmp", STATE)
        _STATE_FAIL_TS = 0.0
        return True
    except Exception as ex:
        now = time.time()
        if now - _STATE_FAIL_TS >= 300:
            _STATE_FAIL_TS = now
            log("状态文件写入失败 %s: %s (同步进度可能无法保存)" % (STATE, ex))
        try:
            os.unlink(STATE + ".tmp")
        except OSError:
            pass
        return False


def scan(exfat, cats=None, newest_events=None):
    """返回 {(分类, 事件名, 文件名): Entry}
    newest_events: 每个分类只扫最新 N 个事件目录(哨兵优先通道用, 避免每秒重扫全部历史)。"""
    found = {}
    try:
        root = exfat.list_dir(exfat.root_cluster)
    except Exception as e:
        log("读根目录失败: %s" % e)
        return found
    cam = exfat.find(root, "TeslaCam")
    if not cam or not cam.is_dir:
        return found
    cat_list = exfat.list_dir(cam.cluster, cam.size)
    for cat in CATS:
        if cats and cat not in cats:
            continue
        catdir = exfat.find(cat_list, cat)
        if not catdir or not catdir.is_dir:
            continue
        if cat == "RecentClips":
            # 平铺文件: 按文件名时间戳分组, 让网页能按事件展示
            try:
                items = exfat.list_dir(catdir.cluster, catdir.size)
            except Exception:
                continue
            for e in items:
                if e.is_dir or not e.name.lower().endswith(".mp4") or e.size <= 0 or not e.valid:
                    continue
                m = TS_RE.match(e.name)
                group = m.group(1) if m else "_misc"
                found[(cat, group, e.name)] = e
        else:
            evs = []
            try:
                for e in exfat.list_dir(catdir.cluster, catdir.size):
                    if e.is_dir and DIR_RE.match(e.name or ""):
                        evs.append(e)
            except Exception:
                continue
            evs.sort(key=lambda e: e.name)
            if newest_events:
                evs = evs[-int(newest_events):]
            for ed in evs:
                for prefix, e in iter_media(exfat, ed, (ed.name,)):
                    found[(cat, prefix[0], e.name)] = e
    return found


def ev_dt(ev):
    """事件目录名即片段起始时间 (2026-11-05_16-30-39)"""
    try:
        return datetime.datetime.strptime(ev[:19], "%Y-%m-%d_%H-%M-%S")
    except (ValueError, TypeError):
        return None


# 墓碑: sentry-viewer.py 清理盒子侧哨兵/手动保存归档时把 "分类/事件名" 记进 /archive/.pruned,
# 这里读到就跳过 —— 车机 U 盘上还留着的旧事件若不跳过, 会被当成新片段重抄回来,
# 形成 删除→重抄 的死循环 (和 RecentClips 滚动窗口同理)
def load_pruned():
    try:
        with open(os.path.join(ARCHIVE, ".pruned"), encoding="utf-8", errors="ignore") as f:
            return set(x.strip() for x in f if "/" in x)
    except OSError:
        return set()


def _read_small(exfat, entry, limit=8192):
    """读小文件(event.json 之类)的内容; 只读前 limit 字节, 出错返回空。"""
    out = b""
    try:
        for chunk in exfat.read_file(entry):
            out += chunk
            if len(out) >= limit:
                break
    except Exception:
        return b""
    return out


def sentry_rank(exfat, cur):
    """哨兵/手动保存事件内的搬运顺序: event.json 最前, 触发摄像头那一路其次,
    然后前视, 其余最后 —— 保证推送封面能最早抽到帧。"""
    ranks = {}
    meta_cache = {}
    for (cat, ev, name), _e in cur.items():
        if cat not in ("SentryClips", "SavedClips"):
            continue
        if name == "event.json":
            ranks[(cat, ev, name)] = 0
            continue
        if not name.lower().endswith(".mp4"):
            ranks[(cat, ev, name)] = 4
            continue
        m = meta_cache.get((cat, ev))
        if m is None:
            m = {}
            ej = cur.get((cat, ev, "event.json"))
            if ej:
                try:
                    m = json.loads(_read_small(exfat, ej).decode("utf-8", "ignore")) or {}
                except Exception:
                    m = {}
            meta_cache[(cat, ev)] = m
        cam = m.get("camera")
        cam = str(cam).strip()
        suffix = CAM_SUFFIX.get(int(cam)) if cam.isdigit() else None
        own = name.rsplit("-", 1)[-1][:-4]
        if suffix and own == suffix:
            ranks[(cat, ev, name)] = 1
        elif own == "front":
            ranks[(cat, ev, name)] = 2
        else:
            ranks[(cat, ev, name)] = 3
    return ranks


def roll_min():
    """行车记录归档窗口(分钟), 由页面「行车记录保留」决定, 1 小时~7 天。"""
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            s = json.load(f) or {}
        v = int(s.get("recent_keep_min", 60) or 60)
    except Exception:
        v = 60
    return max(60, min(v, 10080))


def do_sync(exfat, state, quiet=False, cats=None, hold=True, newest_events=None, progress=None):
    """跑一轮; 返回 (新增文件数, 字节数)
    progress(done, total, done_bytes, total_bytes, force) 用于网页展示「已归档百分比」:
    total 是本轮扫描到的有效片段, done 是其中已在归档区(或刚搬完)的片段。"""
    cur = scan(exfat, cats, newest_events)
    pruned = load_pruned()
    # 只收滚动窗口内的 RecentClips: 以车机 U 盘上最新的片段为锚点
    cut = None
    rm = int(os.environ.get("TSF_RECENT_ROLL_MIN") or roll_min())
    if rm > 0:
        newest = None
        for (cat, ev, _name) in cur:
            if cat == "RecentClips":
                d = ev_dt(ev)
                if d and (newest is None or d > newest):
                    newest = d
        if newest:
            cut = newest - datetime.timedelta(minutes=rm)
    pending_key = "__pending__"
    pending = state.get(pending_key, {})
    new_pending = {}
    # 只跑某一类(哨兵优先通道)时, 保留其它分类的待确认签名, 别把它们的进度冲掉
    if cats:
        for k, v in pending.items():
            if k.split("/")[0] not in cats:
                new_pending[k] = v
    items = list(cur.items())
    if cats and "SentryClips" in cats:
        try:
            ranks = sentry_rank(exfat, cur)
        except Exception:
            ranks = {}
        items.sort(key=lambda kv: (ranks.get(kv[0], 9), kv[0][2]))
    copied = 0
    bytes_ = 0
    total = 0
    done = 0
    total_bytes = 0
    done_bytes = 0
    processed = 0
    cmp_cache = state.setdefault("__cmp__", {})
    ready = []
    for (cat, ev, name), e in items:
        processed += 1
        # 大批量首轮建立基线时也要分段落盘, 避免中途重启后整轮重扫。
        if processed % CHECKPOINT_EVERY == 0:
            state[pending_key] = new_pending
            save_state(state)
        if "%s/%s" % (cat, ev) in pruned:
            continue            # 已被盒子侧定期清理, 不再重抄
        if cut is not None and cat == "RecentClips":
            d = ev_dt(ev)
            if d and d < cut:
                continue          # 超出归档窗口, 留在车机里, 不再抄
        key = "%s/%s/%s" % (cat, ev, name)
        sig = [e.size, e.vdl, e.mtime]
        dest = safe_dest(cat, ev, name)
        total += 1
        total_bytes += e.size
        if same_file(dest, e.size):
            # 同尺寸不代表同内容: 车机复用事件名/簇覆盖写时, 归档区留着旧字节。
            # 首次观察只建立签名基线, 不读取旧归档内容; 之后只有签名变化才逐字节复核。
            prev = cmp_cache.get(key)
            if prev == sig:
                done += 1
                done_bytes += e.size
                continue
            if prev is None:
                # 旧状态文件没有 __cmp__ 时不能把所有历史归档全读一遍,
                # 否则 59GB 首轮会打满 U 盘 I/O; 先记基线, 后续签名变化再复核。
                cmp_cache[key] = sig
                done += 1
                done_bytes += e.size
                continue
            if same_content(dest, e, exfat):
                cmp_cache[key] = sig
                done += 1
                done_bytes += e.size
                continue
        # 需要连续两轮签名一致才认为写完
        if pending.get(key) != sig:
            new_pending[key] = sig
            if not quiet:
                log("发现新片段(待确认): %s (%d bytes)" % (key, e.size))
            continue
        ready.append((key, e, dest, sig))
    if progress:
        progress(done, total, done_bytes, total_bytes, True)
    for (key, e, dest, sig) in ready:
        try:
            n = copy_entry(exfat, e, dest, hold=hold)
            copied += 1
            bytes_ += n
            done += 1
            done_bytes += n
            _mark_hot(dest)
            cmp_cache[key] = sig
            log("已同步 %s (%d KB)" % (key, n // 1024))
            if progress:
                progress(done, total, done_bytes, total_bytes, False)
        except Exception as ex:
            log("同步失败 %s: %s" % (key, ex))
            new_pending[key] = sig
    if progress:
        progress(done, total, done_bytes, total_bytes, True)
    state[pending_key] = new_pending
    save_state(state)
    return copied, bytes_


def dump(exfat):
    root = exfat.list_dir(exfat.root_cluster)
    print("根目录 (%d 项):" % len(root))
    for e in root:
        print("  %s %-30s size=%-10d %s" % ("DIR " if e.is_dir else "FILE", e.name, e.size,
                                            "" if e.valid else "[checksum bad]"))
    cam = exfat.find(root, "TeslaCam")
    if not cam:
        print("! 没有 TeslaCam 目录")
        return
    for cat in CATS:
        c = exfat.find(exfat.list_dir(cam.cluster, cam.size), cat)
        if not c:
            print("%s: 不存在" % cat)
            continue
        items = exfat.list_dir(c.cluster, c.size)
        print("%s: %d 项" % (cat, len(items)))
        for it in items[:8]:
            print("   %s %-40s size=%d" % ("DIR " if it.is_dir else "FILE", it.name, it.size))


def probe_sig(exfat):
    """轻量探测: 只列最近 2 个事件目录的目录项(不读文件内容), 返回哨兵/手动保存的签名。
    只扫每个分类最新 2 个事件: 新告警/手动保存必然落在最新事件里, 这样一次探测
    从 ~430ms(1400+ 条目) 降到 ~60ms, 撑得住 1 秒一轮。"""
    out = {}
    try:
        root = exfat.list_dir(exfat.root_cluster)
        cam = exfat.find(root, "TeslaCam")
        if not cam or not cam.is_dir:
            return out
        cat_list = exfat.list_dir(cam.cluster, cam.size)
        for cat in ("SentryClips", "SavedClips"):
            catdir = exfat.find(cat_list, cat)
            if not catdir or not catdir.is_dir:
                continue
            evs = []
            for e in exfat.list_dir(catdir.cluster, catdir.size):
                if e.is_dir and DIR_RE.match(e.name or ""):
                    evs.append(e)
            evs.sort(key=lambda e: e.name)
            for ed in evs[-2:]:
                for _prefix, e in iter_media(exfat, ed):
                    ev_name = ed.name
                    out["%s/%s/%s" % (cat, ev_name, e.name)] = (e.size, e.mtime)
    except Exception as e:
        log("目录探测失败: %s" % e)
    return out


_CAR_WRITE = {"mtime": None, "changed": 0.0}

# 状态文件写入失败的限频时间戳 (save_state 使用), 0=从未失败
_STATE_FAIL_TS = 0.0
# 长循环中每处理多少个条目保存一次状态 (断点续跑)
CHECKPOINT_EVERY = 200


def _cat_changed(sig, old, cat):
    """某分类下是否有文件新增/变大/变时间 (old 为上一轮签名)。"""
    pre = cat + "/"
    if old is None:
        return False
    for k, v in sig.items():
        if k.startswith(pre) and old.get(k) != v:
            return True
    for k in old:
        if k.startswith(pre) and k not in sig:
            return True
    return False


_DRIVE_HINT = {"key": None, "val": None}
_REC_CACHE = {"ts": 0.0, "entry": None}


def _newest_recent_front(exfat, refresh=20.0):
    """RecentClips 一小时缓冲有几百个文件, 每秒全列一次太贵(~300ms)。
    这里按 20 秒缓存最新前视文件; 新文件最晚 20 秒被发现, 对判定足够。"""
    global _REC_CACHE
    now = time.time()
    if _REC_CACHE["entry"] is not None and now - _REC_CACHE["ts"] < refresh:
        return _REC_CACHE["entry"]
    root = exfat.list_dir(exfat.root_cluster)
    cam = exfat.find(root, "TeslaCam")
    if not cam or not cam.is_dir:
        return _REC_CACHE["entry"]
    cat_list = exfat.list_dir(cam.cluster, cam.size)
    rec = exfat.find(cat_list, "RecentClips")
    if not rec or not rec.is_dir:
        return _REC_CACHE["entry"]
    files = []
    for e in exfat.list_dir(rec.cluster, rec.size):
        if not e.is_dir and (e.name or "").lower().endswith("-front.mp4") and e.size > 0:
            files.append(e)
    if files:
        files.sort(key=lambda e: e.name)
        _REC_CACHE = {"ts": now, "entry": files[-1]}
    return _REC_CACHE["entry"]


def probe_driving(exfat):
    """判断车机最新行车记录前视片段里有没有 SEI 遥测: 有=真在行车, 没有=停车哨兵在录像。
    Tesla 停车状态下哨兵仍在循环写 RecentClips, 但停车片段不含车辆遥测 SEI;
    只看 "RecentClips 在写" 会把停车哨兵误判成行车, 所以要再看这一位。
    只读每类最新前视片段的头 3MB, 按文件名+大小缓存, 每分钟最多读一次。"""
    global _DRIVE_HINT
    try:
        newest = _newest_recent_front(exfat)
        if newest is None:
            return None
        key = newest.name
        if _DRIVE_HINT.get("key") == key and _DRIVE_HINT.get("val") is not None:
            return _DRIVE_HINT["val"]
        if newest.size < 1048576:
            # 文件刚建还没写够: 同一文件沿用上轮结论, 新文件沿用上一段的结论
            # (停车哨兵录像一分钟换一个文件, 不能在这个缝里误判成行车而锁盘)
            prev = _DRIVE_HINT.get("val")
            if _DRIVE_HINT.get("key") != key:
                _DRIVE_HINT = {"key": key, "val": prev}
            return prev
        buf = b""
        try:
            for chunk in exfat.read_file(newest):
                buf += chunk
                if len(buf) >= 3 * 1048576:
                    break
        except Exception:
            return None
        # 行车片段的每个视频帧都带 SEI: NAL 头 06 05 32 42 42 42 69
        val = buf.count(b"\x42\x42\x42\x69") >= 3
        _DRIVE_HINT = {"key": key, "val": val}
        return val
    except Exception as e:
        log("行车判定失败: %s" % e)
        return None


def publish_write_cat(sig, old, driving=None, recent=False):
    """把"哪一类正在写"落到文件, 页面据此区分行车记录(行车中)与哨兵/手动保存。
    recent 由镜像 mtime 判定(车机一写盘就变), 不再依赖列 RecentClips 目录。"""
    flags = {"recent": bool(recent),
             "sentry": _cat_changed(sig, old, "SentryClips"),
             "saved": _cat_changed(sig, old, "SavedClips"),
             "driving": driving,
             "ts": time.time()}
    try:
        tmp = WRITE_CAT_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(flags, f)
        os.replace(tmp, WRITE_CAT_FILE)
    except OSError:
        pass


# 探测独立成线程: 定时归档一次要搬几百 MB、还会因车机写盘暂停几十秒,
# 放在主循环里会把 write-cat 卡成旧的, 页面就会误报"车机正在写入/上锁"。
# 线程用自己的只读句柄, 每秒固定更新状态, 不受搬运阻塞。
PROBE_URGENT = threading.Event()


def probe_loop():
    x = None
    last_sig = None
    while True:
        try:
            st = os.stat(IMG)
            if x is None or st.st_ino != x.fd_ino:
                if x is not None:
                    try:
                        x.close()
                    except Exception:
                        pass
                x = ExFat(IMG)
            sig = probe_sig(x)
            recent = (time.time() - st.st_mtime) < 12
            if last_sig is None:
                publish_write_cat(sig, None, None, False)   # 基线, 不补推历史
                last_sig = sig
            else:
                drv = probe_driving(x) if recent else None
                publish_write_cat(sig, last_sig, drv, recent)
                if (_cat_changed(sig, last_sig, "SentryClips")
                        or _cat_changed(sig, last_sig, "SavedClips")):
                    PROBE_URGENT.set()
                last_sig = sig
        except Exception as e:
            log("状态探测失败: %s" % e)
        time.sleep(1)


def car_busy():
    """车机最近 CAR_WRITE_HOLD 秒内写过镜像 -> True。
    在线同步会读同一个镜像文件, 车机写入期间必须让路, 避免抢 U 盘 I/O 触发主机 reset。"""
    try:
        mt = os.stat(IMG).st_mtime_ns
    except OSError:
        return False
    now = time.time()
    if _CAR_WRITE["mtime"] is None:
        # 首次观测没有历史可对比: 用文件自身 mtime 推断最近一次写入时间,
        # 不能把"本次看到它的时刻"当成写时刻, 否则每次启动都误判为车机在写。
        _CAR_WRITE["mtime"] = mt
        _CAR_WRITE["changed"] = mt / 1e9
    elif mt != _CAR_WRITE["mtime"]:
        _CAR_WRITE["mtime"] = mt
        _CAR_WRITE["changed"] = now
    return (now - _CAR_WRITE["changed"]) < CAR_WRITE_HOLD


def archive_interval_min():
    """网页设置的归档间隔(分钟), 默认 10, 范围 1-1440。每轮现读, 改完即生效。"""
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            v = int(json.load(f).get("archive_interval_min", 10) or 10)
    except Exception:
        v = 10
    return max(1, min(v, 1440))


def write_sched(last, running, copied=0, msg="", progress=None):
    try:
        old = {}
        try:
            with open(ARCHIVE_SCHED_FILE, encoding="utf-8") as f:
                old = json.load(f)
        except Exception:
            old = {}
        rec = {"last": last, "running": running, "copied": copied,
               "msg": msg, "interval_min": archive_interval_min(),
               "ts": time.time()}
        if progress:
            rec.update(progress)
        elif last:
            # 哨兵优先通道/顺延等小状态沿用上一轮的整体归档百分比, 不要冲成 0;
            # last=0 表示服务刚起还没跑过完整一轮, 旧百分比不能带过来
            for k in ("done", "total", "pct", "done_bytes", "total_bytes"):
                if k in old:
                    rec[k] = old[k]
        tmp = ARCHIVE_SCHED_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rec, f)
        os.replace(tmp, ARCHIVE_SCHED_FILE)
    except OSError:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=int, default=INTERVAL)
    args = ap.parse_args()

    exfat = None
    last_wait_log = 0.0
    while exfat is None:
        try:
            if not os.path.exists(IMG):
                raise ValueError("镜像不存在: %s" % IMG)
            exfat = ExFat(IMG)
        except Exception as e:
            # --dump/--once 保持原有失败语义; 常驻服务则等待初始化/车机格式化完成。
            if args.dump or args.once:
                log("解析镜像失败: %s" % e)
                return 1
            now = time.time()
            if now - last_wait_log >= 300:
                log("等待有效 exFAT 镜像: %s" % e)
                last_wait_log = now
            time.sleep(max(15, args.interval))

    if args.dump:
        dump(exfat)
        exfat.close()
        return 0

    log("在线同步启动: %s (簇 %dB, %d 簇)" % (IMG, exfat.cluster_size, exfat.cluster_count))
    state = load_state()
    if args.once:
        # --once 必须与常驻服务走同一套约束: 先看挂载点(网页管理中/归档占用时 /archive
        # 可能没挂真实存储, 直接写会把片段落到系统盘), 再拿共享锁避免和网页挂载/归档抢 U 盘。
        if os.path.ismount(MNT):
            log("单轮跳过: %s 仍是挂载点, U 盘正被网页管理/归档占用" % MNT)
            exfat.close()
            return 0
        lk = usb_shared_lock()
        if lk is None:
            log("单轮跳过: U 盘被其它任务占用 (%s), 无法取得共享锁" % USB_LOCK)
            exfat.close()
            return 0
        try:
            if car_busy():
                log("单轮跳过: 车机正在写 U 盘 (车机第一优先), 停车后再跑")
                return 0
            n, b = do_sync(exfat, state)
            log("单轮完成: %d 个新片段, %.1f MB" % (n, b / 1048576))
            return 0
        finally:
            usb_unlock(lk)
            exfat.close()

    # 定时归档调度: 每 5s 醒一次, 到点(间隔可在网页自定义, 默认10分钟)或收到
    # 「立即归档」触发文件才搬; 车机正在写盘 / 网页管理U盘 / 持锁冲突一律顺延。
    last_run = 0.0
    try:
        with open(ARCHIVE_SCHED_FILE, encoding="utf-8") as f:
            last_run = float(json.load(f).get("last") or 0)
        if last_run > time.time():
            last_run = 0.0
    except Exception:
        last_run = 0.0
    last_car_log = 0.0
    lock_miss = 0
    # 哨兵/手动保存优先通道: 独立线程每 1 秒轻扫一次, 不读视频内容;
    # 一旦 SentryClips/SavedClips 出现变化就置位, 主线程立刻小步搬运。
    threading.Thread(target=probe_loop, daemon=True).start()
    write_sched(last_run, False, msg=("等待下一轮归档" if last_run else "等待首轮归档"))
    prog_mark = {"t": 0.0}

    def on_progress(done, total, done_bytes, total_bytes, force=False):
        now = time.time()
        if not force and now - prog_mark["t"] < 1.5:
            return
        prog_mark["t"] = now
        pct = None
        if total_bytes > 0:
            # 向下取整: 差一个片段也不要提前显示 100%
            pct = max(0, min(100, int(done_bytes * 100.0 / total_bytes)))
        elif total > 0:
            pct = max(0, min(100, int(done * 100.0 / total)))
        write_sched(last_run, True, msg="归档中", progress={
            "done": done, "total": total, "pct": pct,
            "done_bytes": done_bytes, "total_bytes": total_bytes})

    while True:
        time.sleep(1)
        now = time.time()
        if PROBE_URGENT.is_set():
            # 哨兵优先通道也不得抢车机写盘: 等车机空闲后再搬。
            if car_busy():
                time.sleep(2)
                continue
            PROBE_URGENT.clear()
            lk = usb_shared_lock()
            if lk is None:
                continue                    # U 盘正被占用, 下一轮再试
            try:
                n, b = do_sync(exfat, state, cats=("SentryClips", "SavedClips"),
                               hold=False, newest_events=2)
                if n:
                    log("哨兵优先同步: %d 个片段, %.1f MB" % (n, b / 1048576))
                    write_sched(last_run, False, copied=n,
                                msg="哨兵优先同步 %d 个片段" % n)
                else:
                    # 第一轮只记 pending(等连续两轮签名一致), 若本轮没搬成,
                    # 下一轮立刻再确认一次, 别等到定时归档。
                    pend = state.get("__pending__", {})
                    if any(k.startswith(("SentryClips/", "SavedClips/")) for k in pend):
                        PROBE_URGENT.set()
            except Exception as e:
                log("哨兵优先同步失败: %s" % e)
            finally:
                usb_unlock(lk)
            continue
        trig = os.path.exists(ARCHIVE_NOW_FLAG)
        iv = archive_interval_min() * 60
        due = (time.time() - last_run) >= iv
        if not (trig or due):
            continue
        if car_busy():
            now = time.time()
            if now - last_car_log >= 60:
                log("车机正在写 U 盘, 归档顺延 (给 OTG 让路)")
                last_car_log = now
            write_sched(last_run, False, msg="车机写入中, 归档顺延")
            continue
        if os.path.ismount(MNT):
            continue
        lk = usb_shared_lock()
        if lk is None:
            lock_miss += 1
            if lock_miss in (1, 20, 80):
                log("跳过本轮: U盘被网页管理/归档占用, 或锁文件不可写 (%s), 连续 %d 轮" % (USB_LOCK, lock_miss))
            continue
        lock_miss = 0
        try:
            try:
                st = os.stat(IMG)
                if st.st_ino != exfat.fd_ino:
                    log("镜像 inode 变化, 重新打开")
                    exfat.close()
                    exfat = ExFat(IMG)
            except OSError as ex:
                log("镜像不可读: %s" % ex)
                continue
            write_sched(last_run, True, msg="归档中")
            n, b = do_sync(exfat, state, progress=on_progress)
            last_run = time.time()
            if trig:
                try:
                    os.unlink(ARCHIVE_NOW_FLAG)
                except OSError:
                    pass
            write_sched(last_run, False, copied=n,
                        msg="本轮 %d 个新片段, %.1f MB" % (n, b / 1048576))
            if n:
                log("定时归档完成: %d 个新片段, %.1f MB%s" % (n, b / 1048576, " (立即归档)" if trig else ""))
        except Exception as e:
            log("归档异常: %s" % e)
            write_sched(last_run, False, msg="归档异常: %s" % str(e)[:120])
        finally:
            usb_unlock(lk)


if __name__ == "__main__":
    sys.exit(main() or 0)
