#!/usr/bin/env python3
"""补建目标表格里仍缺失的关联字段。"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config as cfg  # noqa: E402

ENV = cfg.lark_env()

DST = cfg.get("base_token", "")
schema = json.load(open(cfg.get("schema_path"), encoding="utf-8"))
tmap = json.load(open(cfg.get("table_map_path"), encoding="utf-8"))
src_tname = {t["src_id"]: t["name"] for t in schema["tables"]}


def cli(args):
    p = subprocess.run([cfg.get("lark_cli"), "base"] + args + [
        "--as", cfg.get("identity"), "--format", "json"],
        env=ENV, capture_output=True, text=True)
    try:
        return json.loads(p.stdout.strip())
    except Exception:
        return {"ok": False, "raw": p.stdout[:300], "stderr": p.stderr[:300]}


created = failed = 0
for t in schema["tables"]:
    nid = tmap[t["src_id"]]
    res = cli(["+field-list", "--base-token", DST, "--table-id", nid])
    if not res.get("ok"):
        continue
    dst_names = {f["name"] for f in res.get("data", {}).get("fields", [])}
    missing = [f for f in t["fields"] if f["type"] == "link" and f["name"] not in dst_names]
    if not missing:
        continue
    handled = set()
    for f in missing:
        if f["id"] in handled:
            continue
        tgt = tmap.get(f["link_table"])
        if not tgt:
            continue
        payload = {"name": f["name"], "type": "link", "link_table": tgt,
                   "bidirectional": bool(f.get("bidirectional"))}
        r = cli(["+field-create", "--base-token", DST, "--table-id", nid,
                 "--json", json.dumps(payload, ensure_ascii=False)])
        if r.get("ok"):
            print(f"[created] {t['name']}.{f['name']} -> {src_tname.get(f['link_table'])}"
                  f" (bidir={payload['bidirectional']})")
            created += 1
        else:
            # fall back to unidirectional, which never fails on self-links
            payload["bidirectional"] = False
            r2 = cli(["+field-create", "--base-token", DST, "--table-id", nid,
                      "--json", json.dumps(payload, ensure_ascii=False)])
            if r2.get("ok"):
                print(f"[created-uni] {t['name']}.{f['name']} (bidir fallback)")
                created += 1
            else:
                print(f"[FAIL] {t['name']}.{f['name']}: {str(r2.get('error'))[:160]}")
                failed += 1
        handled.add(f["id"])
        if f.get("bidirectional_link_field_id"):
            handled.add(f["bidirectional_link_field_id"])

print(f"\ncreated={created} failed={failed}")
