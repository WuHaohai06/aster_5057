# QuantaAlpha 因子假设热启动库 v1

## 目的

这份热启动库将“让 LLM 自由发挥”改成“逐条检验可证伪的经济学假设”。它不是
已经验证有效的因子清单，也不是从外部网站复制的因子数据库。每条假设都必须在
CSI500 PIT 股票池中重新生成数值、评估 Rank IC、稳定性、换手和成本敏感性。

机器可读版本位于：
`config/quantaalpha/hypothesis_seed_library.yaml`。

## 使用原则

1. 一条假设单独运行一次完整工作流，默认 `StepN=5`，不要在一个 Prompt 中要求多个机制；`StepN=1` 仅生成提案。
2. 因子必须只使用信号日及以前可获得的数据；财务字段按公告日 `available_at` 加入。
3. 先生成简单基准表达式，再允许 QuantaAlpha 调整窗口、标准化和有限交互项。
4. 同时测试原方向、反方向和空假设；机制听起来合理不等于因子有效。
5. 每条结果必须保留假设、机制、预期方向、证伪条件和失败市场状态。
6. 外部目录只用于人工发现选题，不自动抓取、不复制其内容。

## 第一批 18 条假设

| 因子族 | ID | 假设简称 | 当前状态 |
|---|---|---|---|
| Beta | `beta_shrunk_rolling` | 收缩滚动 Beta | 可用现有行情运行 |
| Beta | `beta_downside_asymmetry` | 下行 Beta 不对称 | 可用现有行情运行 |
| Beta | `beta_instability` | Beta 稳定性 | 可用现有行情运行 |
| Momentum | `momentum_rank_persistence` | 排序动量持续性 | 可用现有行情运行 |
| Momentum | `momentum_market_residual` | 市场残差动量 | 可用现有行情运行 |
| Momentum | `momentum_path_quality` | 路径质量动量 | 可用现有行情运行 |
| Residual Volatility | `residual_volatility_idiosyncratic` | 特异波动率 | 可用现有行情运行 |
| Residual Volatility | `residual_volatility_downside` | 残差下行波动 | 可用现有行情运行 |
| Residual Volatility | `residual_volatility_of_volatility` | 残差波动率之波动率 | 可用现有行情运行 |
| Liquidity | `liquidity_relative_volume_impact` | 相对成交量价格冲击 | 可用现有行情运行 |
| Liquidity | `liquidity_low_volume_persistence` | 低成交量持续性 | 可用现有行情运行 |
| Liquidity | `liquidity_cap_adjusted_turnover` | 市值中性化换手率残差 | 等待流通股本/市值补齐 |
| Profitability | `profitability_cash_conversion` | 盈利现金转化率 | 等待 PIT 财务报表 |
| Profitability | `profitability_gross_assets` | 总资产毛盈利能力 | 等待 PIT 财务报表 |
| Profitability | `profitability_stable_roe` | 稳定 ROE 质量 | 等待 PIT 财务报表 |
| Growth | `growth_revenue_cash_confirmed` | 现金确认的收入增长 | 等待 PIT 财务报表 |
| Growth | `growth_asset_conservatism` | 资产扩张保守度 | 等待 PIT 财务报表 |
| Growth | `growth_net_assets_per_share` | 每股净资产增长 | 等待 PIT 财务报表 |

## 与当前数据的适配

### 现在可以运行

- 股票日收益、OHLCV；
- CSI500 PIT 成分区间；
- SH000905 基准行情；
- 因此 Beta、Momentum、Residual Volatility 以及两个不依赖股本的 Liquidity
  假设可以真实计算。

### 数据补齐后运行

- `float_shares`、`float_market_cap` 完成后运行市值中性化换手率；
- 利润表、资产负债表和现金流量表完成后运行 Profitability 与 Growth；
- 所有财务数据必须使用公告日，不能按照报告期日期提前进入信号。

### 当前不纳入

小单/大单资金流、逐笔委托、盘口价差、分析师一致预期和机构持仓因子目前没有可靠的
PIT 数据源，不进入第一版热启动库。以后即使补充，也必须单独标明数据源和可用时间。

## 外部参考的处理方式

Factors Directory 用作人工发现页面，例如排序动量、现金转化、市值中性化换手率和
每股净资产增长。其服务条款禁止自动化提取，因此项目仅保存少量页面链接作为
`discovery_reference`，所有假设、公式草图、机制与证伪测试均由 Aster 独立编写。

- https://factors.directory/zh
- https://factors.directory/zh/terms

## 推荐执行顺序

1. 先对 11 条 `ready_market` 假设逐条运行完整一轮 `StepN=5`；
2. 每个因子族最多保留 3 个通过标准评估的候选；
3. 将结果进入统一因子库并计算逐年 Rank IC、ICIR、覆盖率、换手与相关性；
4. Factor Council 同时评审数值证据和机制解释；
5. 市值和财务输入完成后，再解锁剩余 7 条，不用缺失字段构造退化公式。

