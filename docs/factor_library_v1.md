# Aster Unified Factor Library v1

## 目标

Factor Library 是因子定义、数值、版本、血缘、诊断和生命周期状态的统一入口。它解决此前四种来源格式不同的问题：

- 框架内置价量因子：Python 公式 + 共享 Parquet；
- QuantaAlpha 因子：JSON 定义 + HDF5 Series；
- PIT 财务因子：标准长表 Parquet；
- 财报文本因子：标准长表 Parquet + 文档证据；
- 财报 AI 因子：六年年报批量评分 + 公告日可用性。

正式 Catalog 位于 `data/curated/factor_library`。

## 当前内容

| 来源 | 数量 | 默认状态 |
|---|---:|---|
| 确定性价量因子 | 6 | `validated`，其中3个已标记 `demo_selected` |
| QuantaAlpha AI 挖掘 | 26 | 按 canonical evaluation 结果处于 `validated`、`demo_selected` 或 `candidate` |
| PIT 财务因子 | 2 | `validated`，但暂不满足研究覆盖率门槛 |
| 财报文本因子 | 3 | `candidate`，当前为两份文档的烟雾数据 |
| 财报 AI 因子 | 5 | `candidate`；有完整诊断和回测接入，但覆盖率低于研究门槛 |
| 市场型风格因子 | 12 | `validated`；Beta、Momentum、Residual Volatility、Liquidity 各3个 |

共54个唯一 `factor_id`。风格因子名称不使用 `risk_` 前缀，并以四个 `style_*` group 供 Council 选择。

## 标准数值结构

所有可加载因子统一为长表：

```text
date
available_at
instrument
factor_id
factor_group
value
origin
source_id
version
```

`available_at <= date` 是硬约束。QuantaAlpha 的 MultiIndex HDF5 会在构建时转换为该格式的 Parquet。

## Catalog 结构

每个 `FactorRecord` 包含：

- ID、显示名、分组、family、来源和版本；
- 生命周期状态及状态理由；
- 公式、描述和实现位置；
- PIT、research/demo eligibility；
- 数值文件路径、格式、SHA-256、行数、股票数和日期范围；
- IC、ICIR、覆盖率、换手和相关性等诊断摘要；
- 标签和源文件血缘。

主要文件：

```text
data/curated/factor_library/
├── catalog.json                 # 完整机器可读 Catalog
├── catalog.parquet              # 展示/分析友好的扁平 Catalog
├── manifest.json                # Catalog 哈希与状态统计
├── lifecycle_events.json        # 状态变更审计
├── definitions/<factor_id>.json # 单因子定义
├── values/quantaalpha/...        # 标准化后的 QuantaAlpha 数值
├── values/filing_ai/v1.parquet   # 五个六年财报 AI 因子
└── exports/
    ├── research/                 # 严格研究版 Council 输入
    └── showcase/                 # 展示版 Council 输入
```

## 生命周期

```text
candidate → validated → council_approved → demo_selected
     └──────────────→ retired ←──────────────┘
```

- `candidate`：已登记，但诊断或审批不足；
- `validated`：数值和基本诊断通过；
- `council_approved`：研究 Council 批准；
- `demo_selected`：课程展示 Council 选中，不等同于研究批准；
- `retired`：停止使用但保留历史记录。

每次状态变更必须提供 `reason` 和 `actor`，并写入审计文件。

## 命令

构建或刷新：

```powershell
$env:PYTHONPATH = "$PWD\src"
python .\scripts\manage_factor_library.py build
```

深度校验所有哈希、Schema、行数和 PIT 日期：

```powershell
python .\scripts\manage_factor_library.py validate
```

查询：

```powershell
python .\scripts\manage_factor_library.py list
python .\scripts\manage_factor_library.py list --status candidate
python .\scripts\manage_factor_library.py show 9c723bf116fe662e
```

状态变更：

```powershell
python .\scripts\manage_factor_library.py set-status 9c723bf116fe662e demo_selected `
  --reason "Selected for the course demonstration" `
  --actor "factor-council-showcase"
```

导出 Council 输入：

```powershell
python .\scripts\manage_factor_library.py export-council `
  --mode research --output .\data\curated\factor_library\exports\research

python .\scripts\manage_factor_library.py export-council `
  --mode showcase --output .\data\curated\factor_library\exports\showcase
```

## 当前门槛结果

- 26个 QuantaAlpha 因子已经统一转换为 canonical Parquet，并可使用同一评估器计算覆盖率、成熟 Rank IC、换手和冗余；
- 五个财报 AI 因子共21,560行、735只股票，统一映射到公告日之后的首个交易日并向前保持至下一次披露；
- 五个财报 AI 因子的全期覆盖率约42.6%–42.8%，低于正式研究政策的75%，因此仍为 `candidate` 且 `research_eligible=false`；
- 2021-12-31 演示截面覆盖率约29.75%–30.23%，有169个成熟日度 IC 观测；独立 showcase 政策允许其进入课程演示，但不会改变主 Catalog 的研究状态；
- 三个确定性财报文本因子仍是两份文档的 smoke 数据，不满足正式诊断条件。
- 12个市场型风格因子按5个交易日采样物化，共约188万行；覆盖率95.0%–99.9%，已通过统一数据就绪门槛。`validated` 只表示可研究，不表示 Council 必须选择。

缺少诊断的候选因子会保留在展示 Registry 中，但不会通过 Factor Council 的确定性证据门槛。

## Python 读取

```python
from pathlib import Path
from aster_data.factor_library import load_catalog, load_factor_values

catalog = load_catalog(Path("data/curated/factor_library/catalog.json"))
values = load_factor_values(
    project_root=Path("."),
    catalog_path=Path("data/curated/factor_library/catalog.json"),
    factor_id="conventional_low_vol",
)
```

回测和 Council 应引用 Catalog 的 `catalog_digest`，从而把一次运行固定到明确的因子库版本。

`scripts/run_real_pipeline.ps1` 会自动发现默认 Catalog。内置价量组继续使用同一套确定性实时计算；当 Factor Council 选择外部 group 时，回测器会将该 group 展开为对应的全部因子 ID，读取标准 Parquet，将 `available_at` 映射到下一交易日后再向前填充，并把 Catalog digest 和实际 feature IDs 写入回放 manifest。最新财报 showcase 回放的 manifest 明确记录了全部五个 `filing_*` 特征。
