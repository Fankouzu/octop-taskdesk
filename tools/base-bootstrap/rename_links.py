#!/usr/bin/env python3
"""把自动创建的反向关联字段改回原始名称。需先跑 diagnose_links.py 生成计划。"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config as cfg  # noqa: E402

ENV = cfg.lark_env()

DST = cfg.get("base_token", "")
plan = json.load(open(cfg.get("rename_plan_path"), encoding="utf-8"))


def cli(args):
    p = subprocess.run([cfg.get("lark_cli"), "base"] + args + [
        "--as", cfg.get("identity"), "--format", "json"],
        env=ENV, capture_output=True, text=True)
    try:
        return json.loads(p.stdout.strip())
    except Exception:
        return {"ok": False, "raw": p.stdout[:300], "stderr": p.stderr[:300]}


def field_payload(f):
    """Turn a field-get result into a PUT payload."""
    out = {"name": f["name"], "type": f["type"]}
    for k in ("multiple", "style", "description", "property",
              "link_table", "bidirectional", "options", "default_value"):
        v = f.get(k)
        if v is not None:
            out[k] = v
    if out["type"] == "select":
        out["options"] = [{"name": o.get("name")} for o in (f.get("options") or [])]
    return out


ok = fail = 0
for item in plan:
    if not item.get("field_id"):
        continue
    g = cli(["+field-get", "--base-token", DST, "--table-id", item["table_id"],
             "--field-id", item["field_id"]])
    if not g.get("ok"):
        print(f"[get FAIL] {item['table']}.{item['from']}: {str(g.get('error'))[:120]}")
        fail += 1
        continue
    f = g.get("data", {}).get("field") or g.get("data", {})
    payload = field_payload(f)
    payload["name"] = item["to"]
    r = cli(["+field-update", "--base-token", DST, "--table-id", item["table_id"],
             "--field-id", item["field_id"], "--json",
             json.dumps(payload, ensure_ascii=False), "--yes"])
    if r.get("ok"):
        print(f"[rename ok] {item['table']}: {item['from']} -> {item['to']}")
        ok += 1
    else:
        print(f"[rename FAIL] {item['table']}.{item['from']}: {str(r.get('error'))[:160]}")
        fail += 1

print(f"\nrenamed={ok} failed={fail}")
