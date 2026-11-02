#!/usr/bin/env python3
"""诊断源 schema 与目标表格之间的关联字段命名错配。"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config as cfg  # noqa: E402

ENV = cfg.lark_env()

DST = cfg.get("base_token", "")
SCHEMA = cfg.get("schema_path")
MAP = cfg.get("table_map_path")
PLAN_OUT = cfg.get("rename_plan_path")

schema = json.load(open(SCHEMA, encoding="utf-8"))
tmap = json.load(open(MAP, encoding="utf-8"))
src_name = {t["src_id"]: t["name"] for t in schema["tables"]}
plan = []


def cli(args):
    p = subprocess.run([cfg.get("lark_cli"), "base"] + args + [
        "--as", cfg.get("identity"), "--format", "json"],
        env=ENV, capture_output=True, text=True)
    try:
        return json.loads(p.stdout.strip())
    except Exception:
        return {"ok": False, "raw": p.stdout[:200]}


for t in schema["tables"]:
    nid = tmap[t["src_id"]]
    res = cli(["+field-list", "--base-token", DST, "--table-id", nid])
    dst_fields = res.get("data", {}).get("fields", []) if res.get("ok") else []
    dst_by_link = {}
    for f in dst_fields:
        if f.get("type") == "link":
            dst_by_link.setdefault(f.get("link_table") or f.get("table_id"), []).append(f)
    src_links = [f for f in t["fields"] if f["type"] == "link"]
    dst_names = {f["name"] for f in dst_fields}
    print(f"\n=== {t['name']} ===")
    for f in src_links:
        want_target = tmap.get(f["link_table"])
        cands = dst_by_link.get(want_target, [])
        exact = [c for c in cands if c["name"] == f["name"]]
        if exact:
            print(f"  ok    {f['name']}  -> {src_name.get(f['link_table'], f['link_table'])}")
        else:
            # candidate whose name is not one of the source field names (auto-named)
            src_names_here = {x["name"] for x in t["fields"]}
            auto = [c for c in cands if c["name"] not in src_names_here]
            tag = auto[0]["name"] if auto else "(none)"
            print(f"  RENAME {tag!r} -> {f['name']!r}   [target {src_name.get(f['link_table'])}] id={auto[0]['id'] if auto else '-'}")
            if auto:
                plan.append({"table_id": nid, "field_id": auto[0]["id"],
                             "from": auto[0]["name"], "to": f["name"],
                             "table": t["name"]})

Path(PLAN_OUT).parent.mkdir(parents=True, exist_ok=True)
json.dump(plan, open(PLAN_OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"\nrename plan: {len(plan)} fields -> {PLAN_OUT}")
