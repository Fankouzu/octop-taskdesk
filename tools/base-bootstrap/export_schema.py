#!/usr/bin/env python3
"""导出飞书多维表格结构（表 + 字段 + 视图）为 JSON，使用 user 身份。

用法：python3 export_schema.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config as cfg  # noqa: E402

ENV = cfg.lark_env()

SRC = cfg.get("template_base_token", "")
SCHEMA_OUT = cfg.get("schema_path")


def cli(args, identity="user"):
    cmd = [cfg.get("lark_cli"), "base"] + args + ["--as", identity, "--format", "json"]
    p = subprocess.run(cmd, env=ENV, capture_output=True, text=True)
    out = p.stdout.strip()
    try:
        return json.loads(out)
    except Exception:
        return {"ok": False, "raw": out[:400], "stderr": p.stderr[:400]}


def main():
    tl = cli(["+table-list", "--base-token", SRC])
    if not tl.get("ok"):
        print("table-list failed:", json.dumps(tl, ensure_ascii=False)[:400])
        return 1
    tables = tl["data"]["tables"]
    result = {"base_token": SRC, "tables": []}
    for t in tables:
        tid, tname = t["id"], t["name"]
        fl = cli(["+field-list", "--base-token", SRC, "--table-id", tid])
        vw = cli(["+view-list", "--base-token", SRC, "--table-id", tid])
        fields = fl.get("data", {}).get("fields", []) if fl.get("ok") else []
        views = vw.get("data", {}).get("views", []) if vw.get("ok") else []
        result["tables"].append({
            "name": tname, "src_id": tid,
            "fields": fields,
            "views": [{"name": v.get("name"), "type": v.get("type")} for v in views],
            "errs": {"fields": None if fl.get("ok") else fl.get("error"), 
                     "views": None if vw.get("ok") else vw.get("error")},
        })
        types = {}
        for f in fields:
            types[f.get("type")] = types.get(f.get("type"), 0) + 1
        print(f"[{tname}] {len(fields)} fields, views={len(views)} :: {types}")
    with open(SCHEMA_OUT, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1)
    print(f"written {SCHEMA_OUT}")

    # type census across all tables
    allt = {}
    for t in result["tables"]:
        for f in t["fields"]:
            allt[f.get("type")] = allt.get(f.get("type"), 0) + 1
    print("TYPE CENSUS:", json.dumps(allt, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
