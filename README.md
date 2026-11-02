# octop-taskdesk

一套跑在 [Octop](https://github.com/tencentcloud/octop) 上的**任务分发与台账系统**。

用户在飞书里对智能体说一句话，系统判断该不该建单，建单后派给对应专家干活，
干完自检、验收、回写台账，最后把结果交付给用户。台账本身是一张飞书多维表格，
人可以直接在表里看进度，也可以按部门拆权限。

## 它是怎么跑的

```
飞书单聊
   │
   ▼
┌─────────────────┐   建单/改状态   ┌──────────────┐
│  任务台 (team)   │ ──────────────▶ │ 台账员        │
│  判断/分派/自检   │                 │ (expert)     │
└─────────────────┘                 └──────┬───────┘
   │ ask_agent                            │ shell
   ▼                                      ▼
┌─────────────────┐                 ┌──────────────┐
│ 业务专家 (expert)│                 │ ledger.py    │
└─────────────────┘                 └──────┬───────┘
                                           │ lark-cli
                                           ▼
                                    ┌──────────────┐
                                    │ 飞书多维表格   │
                                    └──────────────┘
```

关键设计：**任务台不产出任何东西，只做判断和分派**；**台账只有一个写入者**；
**所有写表操作走固定脚本，不让模型自己拼 JSON**。

## 目录

```
├── config.py                   配置加载（环境变量 > config.json > 默认值）
├── config/config.example.json  配置模板，复制成 config.json 使用
├── ledger/ledger.py            台账命令行，唯一的写入口
├── tools/base-bootstrap/       从模板表格复制出一套自己的表结构
│   ├── export_schema.py        导出模板 schema
│   ├── import_schema.py        按 schema 建表建字段
│   ├── verify_schema.py        比对字段差异
│   ├── diagnose_links.py       诊断关联字段命名错配
│   ├── rename_links.py         改回被自动命名的反向关联字段
│   └── fill_links.py           补建缺失的关联字段
├── schema/base_schema.json     13 表 190 字段的结构定义（已脱敏）
├── agents/
│   ├── taskdesk/               任务台：agent.json 部署规格 + system_prompt.md
│   └── ledger-clerk/           台账员：同上
└── docs/architecture.md        分层、数据流、设计约束
```

## 快速开始

### 1. 配置

```bash
cp config/config.example.json config/config.json
```

填三个东西：`base_token`（你的多维表格）、`tables.*`（三张关键表的 table_id）、
`lark_config_dir`（lark-cli 的配置目录）。也可以全部用环境变量覆盖：

| 环境变量 | 对应配置 |
|---|---|
| `TASKDESK_CONFIG` | 配置文件路径本身 |
| `TASKDESK_BASE_TOKEN` | `base_token` |
| `TASKDESK_TABLE_DEMAND` / `TASK` / `PROJECT` | `tables.*` |
| `TASKDESK_LARK_CLI` | `lark_cli` |
| `TASKDESK_LARK_CONFIG_DIR` | `lark_config_dir` |
| `TASKDESK_IDENTITY` | `identity`（默认 `bot`） |

### 2. 建表

如果还没有表格，用模板表格复制一套：

```bash
python3 tools/base-bootstrap/export_schema.py     # 需要 template_base_token
python3 tools/base-bootstrap/import_schema.py --dry-run   # 先看要建什么
python3 tools/base-bootstrap/import_schema.py
python3 tools/base-bootstrap/verify_schema.py     # 应为 PROBLEMS: 0
```

建表用 **bot 身份**建在一个 app 自有的表格里。这样应用自动成为该表所有者，
不需要把机器人手动加进协作者列表——飞书分享面板里根本选不到智能体。

### 3. 创建 agent

照 `agents/*/agent.json` 在 Octop 里建两个 agent：`taskdesk`（kind=team）、
`ledger-clerk`（kind=expert，MCP 留空）。把各自 `system_prompt.md` 里的
`<BASE_TOKEN>`、`<... TABLE_ID>` 替换掉，粘贴进 system_prompt。

### 4. 日常使用

```bash
python3 ledger/ledger.py search "关键词"
python3 ledger/ledger.py add-demand "需求名称" "描述" P1
python3 ledger/ledger.py add-task "任务名称" "交付要求" recXXXX "专家名" 3
python3 ledger/ledger.py task-status recXXXX 开发中 0.3
python3 ledger/ledger.py demand-status recXXXX 已确认
python3 ledger/ledger.py get recXXXX task
```

状态机：

```
需求：待评审 → 已确认 → 开发中 → 已完成
任务：未开始 → 开发中 → 待验收 → 已完成
                          ↘ 已驳回 → 开发中（重做，超过 2 轮转人工）
```

## 踩过的坑

这些是实际调试出来、写进代码里的约束，改代码前先看 `docs/architecture.md`。

- **lark-cli 返回的是矩阵格式**：`data.fields` 是字段名数组，`data.data` 是行数组，
  `data.record_id_list` 是记录 ID 数组，三者按下标对应，不是对象数组。
- **`record-upsert` 的记录 ID 藏在 `data.record.record_id_list[0]`**，不在顶层。
- **MCP 的 `base` 工具调用不可靠**：模型经常把 `args` 传成字符串、乱试子命令、
  误报"需要账号授权"。所以台账写入一律走 `ledger.py`。
- **kind=team 的 host 会被强制裁剪**：只剩 `agent_list` / `ask_agent` /
  `memory_search` / `memory_get` / `current_time`，MCP 清空、技能目录置空。
  所以任务台不持有任何连接器。
- **双向关联字段的反向字段名是飞书自动起的**（用表名），需要 rename 一次；
  自关联表的反向字段不会自动建，要补。
- **人员字段写不了**：需要 open_id，脚本不碰，留给人在表里填。

## 许可

MIT
