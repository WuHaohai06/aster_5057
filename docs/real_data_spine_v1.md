# Aster 真实数据主干 v1

## 数据层次

真实数据主干分为三层，任何研究脚本都不应直接修改上一层文件：

1. `data/raw`：AKShare/东方财富、Qlib/Yahoo、Baostock 和中金所月度归档的原始检查点；
2. `data/curated`：PIT CSI500 区间、统一后复权股票面板、逐合约 IC 和滞后换月连续收益；
3. `data/portfolio`：预测、目标权重、组合回放和审计 manifest。

所有关键产物均记录 SHA-256。AKShare 是股票日线主候选源，Yahoo 只补空缺和交叉核验。统一市场面板按 `(date, instrument)` 去重时优先 AKShare。

## 后台任务管理

查询四个下载任务：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\manage_data_downloads.ps1 `
  -Action status -IncludeAkshare -IncludeIc
```

只启动缺失的任务，不终止活动任务：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\manage_data_downloads.ps1 `
  -Action ensure -IncludeAkshare -IncludeIc `
  -StartDate 2016-11-24 -EndDate 2026-11-24
```

AKShare 遇东方财富限流时写入 `rate_limited` 状态并等待 300 秒，不做高频重试。活动但心跳陈旧的进程只报告，不会被管理器自动杀死。

## PIT 股票池

```powershell
$env:PYTHONPATH = "$PWD\src"
python .\scripts\build_csi500_pit_universe.py `
  --snapshot-root .\data\raw\qlib_full\csi500_snapshots `
  --output-root .\data\curated\csi500_universe `
  --requested-end 2026-11-24
```

没有正式调整公告时，输出明确标记为周度候选，不冒充精确官方有效日。正式调整文件采用 `effective_date,instrument,action,source_id`，示例位于 `config/csi500_official_adjustments.example.csv`。

## 股票市场层

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_real_data_spine.ps1 `
  -EndDate 2026-11-24
```

Yahoo 原始 OHLC 使用 `adjclose / close` 比率调整；AKShare 文件使用明确的 `hfq` 口径。带时区的源时间戳按其前十位交易所日期解析，禁止先转 UTC 导致日期后移。

## IC 期货层

`aster_data.ic_futures` 下载中金所官方月度 ZIP，保留各合约 OHLC、成交量、持仓量、结算价和前结算价。连续序列使用当日收盘后的持仓量/成交量决定下一交易日合约；每日收益优先使用同一合约相邻收盘价，换月价差不会混入期货收益。

研究配置位于 `config/futures/ic.yaml`。合约乘数为显式字段；12% 保证金只是研究假设，不表示历史交易所保证金。

## 真实数据总入口

数据全部完成后运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_real_pipeline.ps1 `
  -StartDate 2018-01-01 -EndDate 2026-11-24
```

也可以传入 Factor Council 和 Portfolio Council 的 `decision.json`。LLM 只选择批准的因子组或组合档位；权重、beta、总敞口、保证金和换手仍由确定性代码约束。

## 当前边界

- 周度 Baostock 成分是候选 PIT 股票池，仍需正式 CSI 调整公告覆盖；
- AKShare/东方财富会限流，全量任务必须低频、断点续跑；
- 当前统一市场层尚未加入涨跌停、ST、停牌成交恢复、上市天数和 ADV 容量模型；
- QuantaAlpha 和财报 AI 结果已经进入统一因子注册表、Factor Council 与回测；当前主要边界是财报因子覆盖率仍低于正式研究门槛。
- 行业分类使用当前快照用于课程演示，不冒充历史 PIT 行业分类。
