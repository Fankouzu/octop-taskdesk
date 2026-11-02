"""配置加载。

优先级：环境变量 > config/config.json > 内置默认值。

本仓库是公开的，不含任何真实凭据。部署时把 config/config.example.json
复制为 config/config.json 并填入自己的值，或用 TASKDESK_* 环境变量注入。
"""

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# 查找顺序，第一个存在的文件生效
CANDIDATES = [
    os.environ.get("TASKDESK_CONFIG"),
    ROOT / "config" / "config.json",
    "/data/ledger-scripts/config.json",  # 容器内的默认落位
]


def _load():
    for c in CANDIDATES:
        if not c:
            continue
        p = Path(c)
        try:
            if p.is_file():
                with open(p, encoding="utf-8") as f:
                    return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            raise SystemExit(f"配置文件 {p} 读取失败: {e}")
    return {}


_RAW = _load()

# 标量配置到环境变量的映射
_ENV = {
    "base_token": "TASKDESK_BASE_TOKEN",
    "template_base_token": "TASKDESK_TEMPLATE_BASE_TOKEN",
    "lark_cli": "TASKDESK_LARK_CLI",
    "lark_config_dir": "TASKDESK_LARK_CONFIG_DIR",
    "identity": "TASKDESK_IDENTITY",
    "schema_path": "TASKDESK_SCHEMA",
    "table_map_path": "TASKDESK_TABLE_MAP",
    "rename_plan_path": "TASKDESK_RENAME_PLAN",
}

_DEFAULTS = {
    "lark_cli": "lark-cli",
    "identity": "bot",
    "schema_path": str(ROOT / "schema" / "base_schema.json"),
    "table_map_path": str(ROOT / "build" / "table_map.json"),
    "rename_plan_path": str(ROOT / "build" / "rename_plan.json"),
}


def get(key, default=None):
    """读单个配置项，环境变量优先。"""
    env = _ENV.get(key)
    if env and os.environ.get(env):
        return os.environ[env]
    v = _RAW.get(key)
    if v not in (None, ""):
        return v
    if default is not None:
        return default
    return _DEFAULTS.get(key)


def table(name):
    """读表 ID，如 table("demand")。"""
    env = "TASKDESK_TABLE_" + name.upper().replace("-", "_")
    if os.environ.get(env):
        return os.environ[env]
    return (_RAW.get("tables") or {}).get(name, "")


def require(*keys):
    """校验必填项，缺失时给出可操作的报错。"""
    missing = [k for k in keys if not get(k)]
    if missing:
        raise SystemExit(
            "缺少配置项：" + "、".join(missing) + "\n"
            "请复制 config/config.example.json 为 config/config.json 后填写，"
            "或设置对应的 TASKDESK_* 环境变量。"
        )


def lark_env():
    """构造调 lark-cli 所需的环境变量。"""
    env = dict(os.environ)
    cli = get("lark_cli")
    if cli and os.path.dirname(cli):
        env["PATH"] = os.path.dirname(cli) + ":" + env.get("PATH", "")
    cfg_dir = get("lark_config_dir")
    if cfg_dir:
        env["LARKSUITE_CLI_CONFIG_DIR"] = cfg_dir
    return env
