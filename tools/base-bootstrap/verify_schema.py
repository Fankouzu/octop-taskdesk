#!/usr/bin/env python3
"""逐表比对目标表格与 schema 的字段名差异。"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config as cfg  # noqa: E402

ENV = cfg.lark_env()

SCHEMA = cfg.get("schema_path")
MAP = cfg.get("table_map_path")
DST = cfg.get("base_token", "")


def cli(args, identity=None):
    cmd = [cfg.get("lark_cli"), "base"] + args + [
        "--as", identity or cfg.get("identity"), "--format", "json"]
    p = subprocess.run(cmd, env=ENV, capture_output=True, text=True)
    try:
        return json.loads(p.stdout.strip())
    except Exception:
        return {"ok": False, "raw": p.stdout[:300], "stderr": p.stderr[:300]}


def main():
    schema = json.load(open(SCHEMA, encoding="utf-8"))
    tmap = json.load(open(MAP, encoding="utf-8"))
    total_src = total_dst = 0
    problems = []
    for t in schema["tables"]:
        src_names = [f["name"] for f in t["fields"]]
        nid = tmap.get(t["src_id"])
        if not nid:
            problems.append((t["name"], "TABLE MISSING", ""))
            continue
        res = cli(["+field-list", "--base-token", DST, "--table-id", nid])
        dst_names = [f["name"] for f in res.get("data", {}).get("fields", [])] if res.get("ok") else []
        total_src += len(src_names)
        total_dst += len(dst_names)
        missing = [n for n in src_names if n not in dst_names]
        extra = [n for n in dst_names if n not in src_names]
        status = "OK" if not missing else "MISSING"
        print(f"[{status}] {t['name']:<24} src={len(src_names):>2} dst={len(dst_names):>2}"
              + (f"  missing={missing}" if missing else "")
              + (f"  extra={extra}" if extra else ""))
        if missing:
            problems.append((t["name"], "missing fields", missing))
    print(f"\nTOTAL src={total_src} dst={total_dst} (dst extra = auto-created reverse links)")
    print("PROBLEMS:", len(problems))


if __name__ == "__main__":
    main()
