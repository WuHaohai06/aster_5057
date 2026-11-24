# 组合回测、约束优化与 AI Portfolio Council v1

## 已打通的链路

当前版本实现了一个可审计的最小闭环：

1. 日频 OHLCV 输入生成 6 组价量特征；
2. walk-forward Ridge 只使用信号日可见、且标签已经成熟的数据训练并生成横截面预期收益；
3. 历史收益估计收缩协方差和个股市场 beta；
4. CVXPY 联合求解股票多头权重与 IC 空头对冲权重；
5. 信号在下一交易日生效，计入股票和期货换手成本，逐日漂移并计算净值；
6. AI Council 只能从预先批准的 `defensive`、`balanced`、`opportunistic` 三档策略中选择；
7. Council 决定可以重新注入回测器，验证“证据包 -> AI 决策 -> 确定性优化 -> 回测”的交接。

合成市场只用于基建烟测，负收益或安全回退不代表策略结论，也不会为了展示效果而调整数据。

## 硬约束与 AI 边界

优化器始终执行以下确定性约束：单票不超过 3%，股票预算、总敞口、beta 区间、现金覆盖期货保证金、换手上限、不可交易股票权重为零，以及可选的逐票交易容量上限。求解顺序为 CLARABEL，失败时才退到 SCS。

AI 不直接生成权重、期货手数或约束数字。三个评审分别检查 alpha 证据、组合风险、执行与流动性，主席只能选择一个批准档位。角色不符、漏投档位、引用未知证据、日期错误、JSON 不合法或主席选择未批准档位时，系统自动使用 `balanced`。原始调用、投票、决定和 SHA-256 manifest 全部落盘。

这意味着 AI 用于“有限策略状态选择”，凸优化器用于“数值决策”。生产系统不得让 LLM 绕过风险约束。

## 烟测命令

从仓库根目录执行：

一键执行完整合成链路（会产生 4 次 DeepSeek 调用）：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_portfolio_full_chain_smoke.ps1
```

也可以逐段执行以便检查中间产物：

```powershell
$env:PYTHONPATH = "$PWD\src"
python .\scripts\run_portfolio_smoke.py `
  --output-root .\data\portfolio\synthetic_smoke `
  --profile balanced

python .\scripts\build_portfolio_council_smoke.py `
  --portfolio-smoke-root .\data\portfolio\synthetic_smoke `
  --output .\run\portfolio_council_smoke\packet.json

powershell -ExecutionPolicy Bypass -File .\scripts\run_portfolio_council.ps1 `
  -PacketPath .\run\portfolio_council_smoke\packet.json `
  -OutputRoot .\data\portfolio_council\smoke_live_runs
```

将 Council 决定真正交回优化和回测层：

```powershell
$decision = Get-ChildItem .\data\portfolio_council\smoke_live_runs -Directory |
  Sort-Object LastWriteTime -Descending | Select-Object -First 1
python .\scripts\replay_synthetic_portfolio_decision.py `
  --decision (Join-Path $decision.FullName "decision.json") `
  --output-root .\data\portfolio\synthetic_council_replay
```

## 主要产物

- `daily.csv`：每日净值、股票/期货贡献、成本、敞口和是否调仓；
- `target_weights.csv`：每次调仓的目标股票权重；
- `forecast_diagnostics.csv`：每个信号日的训练截止日、样本量和预测分布；
- `optimization_diagnostics.csv`：每次求解的状态、beta、保证金、换手和约束余量；
- `metrics.json` 与 `manifest.json`：回测摘要和内容哈希；
- Council 运行目录中的 `packet.json`、`ballots/`、`calls/`、`decision.json` 与哈希 manifest。

## 接真实数据前仍需完成

当前打通的是基建闭环，不等于生产级 CSI500 回测。接真实数据时必须完成：

- 把 Aster/Qlib 的 PIT CSI500 成分、复权日线和可交易状态映射为回测矩阵；
- 把 QuantaAlpha 的候选因子经过 Factor Council 后，接入相同的 walk-forward 预测接口；
- 使用真实 IC 主力/次主力合约、合约乘数、保证金变化和可复现换月规则，替换连续合成期货；
- 加入停牌、涨跌停、ST、上市天数、ADV 容量、冲击成本和成交失败模型；
- 将连续期货权重转换为整数合约，并记录舍入后的实际 beta；
- 用正式指数调整公告重建成分有效日，避免用周度候选快照冒充精确 PIT；
- 设定扩展/滚动窗口、费用、基准和训练冻结规则后再做样本外评估。

在这些适配完成前，结果只能证明代码链路、时序约束和安全降级有效，不能用于投资判断。
