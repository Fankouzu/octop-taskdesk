#!/usr/bin/env python3
"""按 schema 在一个 app 自有的多维表格里重建结构（bot 身份）。

三轮执行：
  Round 1  建表（只带主字段）
  Round 2  每张表批量建非关联字段
  Round 3  建关联字段，src->dst 表 ID 重映射，跳过自动创建的反向字段

用法：python3 import_schema.py [--dry-run]
"""
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
TABLE_MAP_OUT = cfg.get("table_map_path")
IDENTITY = cfg.get("identity")
DRY = "--dry-run" in sys.argv

# Primary field (record title) per table — must be the identifying field.
PRIMARY = {
    "项目表": "项目名称",
    "开发任务表": "任务名称",
    "需求表": "需求名称",
    "每日问题跟踪表": "问题",
    "版本迭代表": "版本号",
    "10 月·13每日问题跟踪表": "问题",
    "每日问题跟踪表 10月15日": "问题",
    "10 月13开发任务表": "任务名称",
    "10月12日开发任务表 ": "任务名称",
    "开发任务表 10月15日": "任务名称",
    "1.0功能验收表": "验收项",
    "1.0版本问题总结表": "问题",
    "灵猫企管1.0功能清单": "功能名称",
}

# 模板表名可能带尾随空格，统一归一化后再查
PRIMARY = {k.strip(): v for k, v in PRIMARY.items()}

# field props worth carrying over, per type
KEEP = ("multiple", "style", "description", "default_value", "property")


def cli(args, identity=IDENTITY):
    cmd = [cfg.get("lark_cli"), "base"] + args + ["--as", identity, "--format", "json"]
    if DRY:
        cmd.insert(3, "--dry-run")
    p = subprocess.run(cmd, env=ENV, capture_output=True, text=True)
    out = p.stdout.strip()
    try:
        return json.loads(out)
    except Exception:
        return {"ok": False, "raw": out[:600], "stderr": p.stderr[:600]}


def clean_field(f, tbl_map):
    """Convert an exported field object into a +field-create payload."""
    t = f["type"]
    payload = {"name": f["name"], "type": t}
    if t == "link":
        payload["link_table"] = tbl_map[f["link_table"]]
        payload["bidirectional"] = bool(f.get("bidirectional"))
        return payload
    if t == "select":
        opts = []
        for o in f.get("options") or []:
            item = {"name": o.get("name")}
            if o.get("hue"):
                item["hue"] = o["hue"]
            if o.get("lightness"):
                item["lightness"] = o["lightness"]
            opts.append(item)
        payload["options"] = opts
        if "multiple" in f:
            payload["multiple"] = bool(f["multiple"])
        return payload
    for k in KEEP:
        v = f.get(k)
        if v is not None and k != "default_value":
            payload[k] = v
    return payload


def main():
    schema = json.load(open(SCHEMA, encoding="utf-8"))
    tables = schema["tables"]
    print(f"tables to build: {len(tables)}  dry_run={DRY}\n")

    # ---- round 1: tables ----
    tbl_map = {}   # src table id -> new table id
    built = []     # (src_table, new_id, primary_field_id)
    for t in tables:
        wanted = PRIMARY.get(t["name"])
        pick = None
        if wanted:
            pick = next((f for f in t["fields"]
                         if f["name"] == wanted and f["type"] == "text"), None)
            if pick is None:
                print(f"[warn] {t['name']}: primary '{wanted}' not found as text field")
        if pick is None:
            texts = [f for f in t["fields"] if f["type"] == "text"]
            pick = texts[0] if texts else t["fields"][0]
        primary = pick
        payload = clean_field(primary, {k: k for k in [x["src_id"] for x in tables]})
        res = cli(["+table-create", "--base-token", DST, "--name", t["name"],
                   "--fields", json.dumps([payload], ensure_ascii=False)])
        if not res.get("ok"):
            print(f"[FAIL table] {t['name']}: {json.dumps(res.get('error'), ensure_ascii=False)}")
            continue
        d = res.get("data", {})
        nid = (d.get("table_id")
               or (d.get("table") or {}).get("id")
               or (d.get("table") or {}).get("table_id") or "")
        if not nid:
            print(f"[?? table] {t['name']} -> no id in {json.dumps(d, ensure_ascii=False)[:300]}")
            continue
        tbl_map[t["src_id"]] = nid
        built.append((t, nid, primary["id"]))
        print(f"[table ok] {t['name']:<24} {nid}  (primary: {primary['name']})")

    # ---- round 2: non-link fields ----
    print("\n--- round 2: fields ---")
    for t, nid, primary_id in built:
        payloads = []
        for f in t["fields"]:
            if f["id"] == primary_id or f["type"] == "link":
                continue
            payloads.append(clean_field(f, tbl_map))
        if not payloads:
            continue
        res = cli(["+field-create", "--base-token", DST, "--table-id", nid,
                   "--json", json.dumps(payloads, ensure_ascii=False)])
        if res.get("ok"):
            created = res.get("data", {}).get("created")
            print(f"[ok] {t['name']:<24} +{created if created is not None else len(payloads)} fields")
        else:
            err = res.get("error", {})
            print(f"[FAIL fields] {t['name']}: {err.get('message')}")
            fail = res.get("data", {}).get("failed") or res.get("data", {}).get("errors")
            if fail:
                print("   ", json.dumps(fail, ensure_ascii=False)[:800])

    # ---- round 3: link fields (bidirectional reverse is auto-created) ----
    print("\n--- round 3: links ---")
    handled = set()
    links = []
    for t, nid, primary_id in built:
        for f in t["fields"]:
            if f["type"] != "link":
                continue
            if f["id"] in handled:
                continue
            tgt = tbl_map.get(f["link_table"])
            if not tgt:
                print(f"[skip link] {t['name']}.{f['name']}: target {f['link_table']} missing")
                continue
            handled.add(f["id"])
            if f.get("bidirectional_link_field_id"):
                handled.add(f["bidirectional_link_field_id"])
            links.append((t["name"], nid, clean_field(f, {f["link_table"]: tgt})))

    for tname, nid, payload in links:
        res = cli(["+field-create", "--base-token", DST, "--table-id", nid,
                   "--json", json.dumps(payload, ensure_ascii=False)])
        mark = "ok" if res.get("ok") else "FAIL"
        extra = "" if res.get("ok") else " :: " + str(res.get("error", {}).get("message"))
        print(f"[{mark} link] {tname}.{payload['name']}{extra}")

    Path(TABLE_MAP_OUT).parent.mkdir(parents=True, exist_ok=True)
    json.dump(tbl_map, open(TABLE_MAP_OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\ntable map written to {TABLE_MAP_OUT}")


if __name__ == "__main__":
    main()
