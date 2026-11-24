# Aster Unified Factor Library v1

## 目标

Factor Library 是因子定义、数值、版本、血缘、诊断和生命周期状态的统一入口。它解决此前四种来源格式不同的问题：

- 框架内置价量因子：Python 公式 + 共享 Parquet；
- QuantaAlpha 因子：JSON 定义 + HDF5 Series；
- PIT 财务因子：标准长表 Parquet；
- 财报文本因子：标准长表 Parquet + 文档证据。

正式 Catalog 位于 `data/curated/factor_library`。

## 当前内容

| 来源 | 数量 | 默认状态 |
|---|---:|---|
| 确定性价量因子 | 6 | `validated`，其中3个已标记 `demo_selected` |
| QuantaAlpha AI 挖掘 | 3 | `candidate` |
| PIT 财务因子 | 2 | `validated`，但暂不满足研究覆盖率门槛 |
| 财报文本因子 | 3 | `candidate`，当前为两份文档的烟雾数据 |

共14个唯一 `factor_id`。

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

- Research 导出：6个价量因子，6个均有完整诊断。
- Showcase 导出：14个因子；8个已有完整诊断。
- QuantaAlpha 3个因子已有完整数值，但还缺统一的逐因子覆盖率、成熟 RankIC 和换手诊断。
- 文本3因子只有两份财报，不满足正式诊断条件。

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

`scripts/run_real_pipeline.ps1` 会自动发现默认 Catalog。内置价量组继续使用同一套确定性实时计算；当 Factor Council 选择 Catalog 中的外部 group（例如 `quanta_shock_reversal`）时，回测器会将该 group 展开为对应的全部因子 ID，读取标准 Parquet，按交易日和股票对齐，并把 Catalog digest 和实际 feature IDs 写入回放 manifest。
