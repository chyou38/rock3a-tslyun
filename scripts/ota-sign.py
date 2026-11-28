#!/usr/bin/env python3
"""给 OTA 清单 version.json 生成 SHA-256 与 Ed25519 签名。

私钥不放进仓库，默认从环境变量 TSF_OTA_SIGN_KEY 读取，或用 --key 指定。
签名规则必须和 sentry-viewer.py 的 _ota_manifest_payload 完全一致：
去掉 sig 与内部 _ 前缀字段后，json.dumps(sort_keys=True, separators=(",", ":"),
ensure_ascii=False) 的字节。
"""
import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIDECARS = [
    "scripts/tesla-gadget.sh",
    "scripts/tesla-sync.sh",
    "scripts/usb-selfheal.sh",
    "scripts/tesla-img.sh",
    "scripts/tsf-check.sh",
    "tesla-live-sync.py",
]


def payload(j):
    body = {k: v for k, v in j.items() if k != "sig" and not str(k).startswith("_")}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default=os.environ.get("TSF_OTA_SIGN_KEY", ""),
                    help="Ed25519 私钥 PEM（不要提交到仓库）")
    ap.add_argument("--manifest", default=str(ROOT / "version.json"))
    ap.add_argument("--version", default="")
    args = ap.parse_args()
    if not args.key or not os.path.isfile(args.key):
        print("缺少私钥: 用 --key 或 TSF_OTA_SIGN_KEY 指定 Ed25519 私钥 PEM", file=sys.stderr)
        return 2
    mf = Path(args.manifest)
    j = json.loads(mf.read_text(encoding="utf-8"))
    if args.version:
        j["version"] = args.version
    hashes = {}
    for rel in ["sentry-viewer.py"] + SIDECARS:
        p = ROOT / rel
        if not p.is_file():
            print("缺少文件: %s" % p, file=sys.stderr)
            return 2
        hashes[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    j["sha256"] = hashes
    j.pop("sig", None)
    body = payload(j)
    with tempfile.TemporaryDirectory(prefix="ota-sign-") as td:
        inp = os.path.join(td, "payload.bin")
        sig = os.path.join(td, "sig.bin")
        with open(inp, "wb") as f:
            f.write(body)
        r = subprocess.run(["openssl", "pkeyutl", "-sign", "-inkey", args.key,
                            "-rawin", "-in", inp, "-out", sig],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print("签名失败: %s" % (r.stderr or r.stdout), file=sys.stderr)
            return 1
        raw = Path(sig).read_bytes()
    if len(raw) != 64:
        print("签名长度异常: %d" % len(raw), file=sys.stderr)
        return 1
    j["sig"] = base64.b64encode(raw).decode("ascii")
    mf.write_text(json.dumps(j, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("已签名 %s (version=%s, files=%d)" % (mf, j.get("version"), len(hashes)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
