#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""任务台账命令行入口。所有写操作走这里，避免模型自己拼 JSON 出错。"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config as cfg  # noqa: E402

BASE = cfg.get("base_token", "")
T_DEMAND = cfg.table("demand")
T_TASK = cfg.table("task")
CLI = cfg.get("lark_cli")
IDENTITY = cfg.get("identity")

DEMAND_STATUS = ("待评审", "已确认", "开发中", "已完成")
TASK_STATUS = ("未开始", "开发中", "待验收", "已驳回", "已完成")
PRIORITY = ("P0", "P1", "P2")


def _run(args):
    env = cfg.lark_env()
    try:
        p = subprocess.run([CLI] + args, capture_output=True, text=True, env=env, timeout=120)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "命令超时"}
    out = (p.stdout or "").strip()
    try:
        d = json.loads(out)
    except Exception:
        return {"ok": False, "error": "输出无法解析", "raw": out[:400], "stderr": (p.stderr or "")[:300]}
    return d


def _record_id(d):
    data = d.get("data") or {}
    rec = data.get("record")
    if isinstance(rec, dict):
        ids = rec.get("record_id_list")
        if isinstance(ids, list) and ids:
            return ids[0]
        for k in ("record_id", "id"):
            if rec.get(k):
                return rec[k]
        if isinstance(rec.get("records"), list) and rec["records"]:
            r0 = rec["records"][0]
            return r0.get("record_id") or r0.get("id")
    ids = data.get("record_id_list")
    if isinstance(ids, list) and ids:
        return ids[0]
    for k in ("record_id", "id"):
        if data.get(k):
            return data[k]
    if isinstance(data.get("records"), list) and data["records"]:
        return data["records"][0].get("record_id")
    return None


def _upsert(table, payload, record_id=None):
    args = [
        "base", "+record-upsert",
        "--base-token", BASE,
        "--table-id", table,
        "--json", json.dumps(payload, ensure_ascii=False),
        "--as", IDENTITY,
        "--format", "json",
    ]
    if record_id:
        args += ["--record-id", record_id]
    return _run(args)


def _now_ms():
    return int(time.time() * 1000)


def out(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=1))


def _parse_rows(d):
    """lark-cli 返回的是矩阵格式：data.fields 是字段名，data.data 是行数组。"""
    data = d.get("data") or {}
    names = data.get("fields") or data.get("field_name_list") or []
    rows = data.get("data") or []
    ids = data.get("record_id_list") or []
    parsed = []
    if isinstance(rows, list) and rows and isinstance(rows[0], list):
        for i, row in enumerate(rows):
            fields = {}
            for j in range(min(len(names), len(row))):
                fields[names[j]] = row[j]
            parsed.append({"record_id": ids[i] if i < len(ids) else None, "fields": fields})
    return parsed


def _flat(v):
    if isinstance(v, list):
        parts = []
        for x in v:
            if isinstance(x, dict):
                parts.append(str(x.get("text") or x.get("name") or ""))
            else:
                parts.append(str(x))
        return "".join(parts)
    return v


def cmd_search(kw):
    d = _run([
        "base", "+record-search",
        "--base-token", BASE,
        "--table-id", T_DEMAND,
        "--keyword", kw,
        "--search-field", "需求名称",
        "--limit", "20",
        "--as", IDENTITY,
        "--format", "json",
    ])
    hits = []
    for r in _parse_rows(d):
        f = r["fields"]
        hits.append({
            "record_id": r["record_id"],
            "需求名称": _flat(f.get("需求名称")),
            "需求状态": _flat(f.get("需求状态")),
        })
    out({"ok": d.get("ok", False), "count": len(hits), "hits": hits[:10],
         "error": None if d.get("ok") else (d.get("error") or d.get("raw"))})


def cmd_add_demand(name, desc, priority="P1"):
    if priority not in PRIORITY:
        out({"ok": False, "error": f"优先级只能是 {PRIORITY}"})
        return
    payload = {
        "需求名称": name,
        "需求描述": desc,
        "需求状态": ["待评审"],
        "优先级": [priority],
        "提交日期": _now_ms(),
    }
    d = _upsert(T_DEMAND, payload)
    rid = _record_id(d)
    out({"ok": bool(d.get("ok")) and bool(rid), "record_id": rid,
         "当前状态": "待评审", "error": None if d.get("ok") else d.get("error") or d.get("raw")})


def cmd_add_task(name, desc, demand_id, expert, due_days="3"):
    try:
        days = int(due_days)
    except Exception:
        days = 3
    payload = {
        "任务名称": name,
        "任务详细说明": desc,
        "任务状态": ["未开始"],
        "责任专家": expert,
        "开始日期": _now_ms(),
        "截止日期": _now_ms() + days * 86400000,
        "驳回轮次": 0,
    }
    if demand_id:
        payload["关联需求"] = [demand_id]
    d = _upsert(T_TASK, payload)
    rid = _record_id(d)
    out({"ok": bool(d.get("ok")) and bool(rid), "record_id": rid, "关联需求": demand_id,
         "error": None if d.get("ok") else d.get("error") or d.get("raw")})


def cmd_task_status(record_id, status, progress=None):
    if status not in TASK_STATUS:
        out({"ok": False, "error": f"任务状态只能是 {TASK_STATUS}"})
        return
    payload = {"任务状态": [status]}
    if status in ("开发中", "待验收"):
        payload["开始日期"] = _now_ms()
    if status == "已驳回":
        payload["驳回轮次"] = 1
    if progress is not None:
        try:
            payload["当日进度"] = float(progress)
        except Exception:
            pass
    d = _upsert(T_TASK, payload, record_id=record_id)
    out({"ok": bool(d.get("ok")), "record_id": record_id, "当前状态": status,
         "error": None if d.get("ok") else d.get("error") or d.get("raw")})


def cmd_demand_status(record_id, status):
    if status not in DEMAND_STATUS:
        out({"ok": False, "error": f"需求状态只能是 {DEMAND_STATUS}"})
        return
    d = _upsert(T_DEMAND, {"需求状态": [status]}, record_id=record_id)
    out({"ok": bool(d.get("ok")), "record_id": record_id, "当前状态": status,
         "error": None if d.get("ok") else d.get("error") or d.get("raw")})


def cmd_get(record_id, table="task"):
    tid = T_TASK if table == "task" else T_DEMAND
    d = _run(["base", "+record-get", "--base-token", BASE, "--table-id", tid,
              "--record-id", record_id, "--as", IDENTITY, "--format", "json"])
    rows = _parse_rows(d)
    fields = {k: _flat(v) for k, v in (rows[0]["fields"].items() if rows else [])}
    out({"ok": bool(d.get("ok")), "record_id": record_id, "fields": fields,
         "error": None if d.get("ok") else (d.get("error") or d.get("raw"))})


USAGE = """用法：
  ledger.py search <关键词>
  ledger.py add-demand "<名称>" "<描述>" [P0|P1|P2]
  ledger.py add-task "<名称>" "<说明>" <需求record_id> "<责任专家>" [几天]
  ledger.py task-status <任务record_id> <状态> [进度0-1]
  ledger.py demand-status <需求record_id> <状态>
  ledger.py get <record_id> [task|demand]
"""


def main(argv):
    if len(argv) < 2:
        print(USAGE)
        return
    cfg.require("base_token")
    if not T_DEMAND or not T_TASK:
        raise SystemExit(
            "缺少表配置：tables.demand 和 tables.task 必须填。"
            "参见 config/config.example.json。"
        )
    cmd = argv[1]
    try:
        if cmd == "search":
            cmd_search(argv[2])
        elif cmd == "add-demand":
            cmd_add_demand(argv[2], argv[3] if len(argv) > 3 else "", argv[4] if len(argv) > 4 else "P1")
        elif cmd == "add-task":
            cmd_add_task(argv[2], argv[3], argv[4], argv[5], argv[6] if len(argv) > 6 else "3")
        elif cmd == "task-status":
            cmd_task_status(argv[2], argv[3], argv[4] if len(argv) > 4 else None)
        elif cmd == "demand-status":
            cmd_demand_status(argv[2], argv[3])
        elif cmd == "get":
            cmd_get(argv[2], argv[3] if len(argv) > 3 else "task")
        else:
            print(USAGE)
    except IndexError:
        print(USAGE)


if __name__ == "__main__":
    main(sys.argv)
