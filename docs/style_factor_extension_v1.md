# Aster 市场型风格因子扩展 v1

## 范围

本批次只实现当前行情数据能够真实支持的四个维度，不使用 `risk_` 作为
因子 ID 前缀：

- `style_beta`：收缩 Beta、下行 Beta 不对称、Beta 稳定性；
- `style_momentum`：排序动量、市场残差动量、路径质量动量；
- `style_residual_volatility`：特异波动率、残差下行波动、残差波动率稳定性；
- `style_liquidity`：相对成交量价格冲击、低量持续性、成交量稳定性。

Profitability 与 Growth 需要收入、成本、现金流、资产、权益和股本等 PIT
三表字段。当前下载任务被用户暂停，因此本版本不使用财报 LLM 分数冒充会计
因子，也不对缺失值填零。

## PIT 与计算约束

- 股票池使用每日 `csi500_member`；
- Beta 与残差只使用信号日及以前的 SH000905 收益；
- 残差收益使用前一日已估计 Beta；
- 成交量只与同一股票自己的历史比较；
- 因子每5个交易日物化一次，下游按 `available_at` 映射到交易日并保持到下一次信号；
- Catalog 的 `validated` 只表示覆盖率和成熟观测合格，预测方向仍由 Factor Council 审查。

## 运行

```powershell
conda run -n aster_5057_whh python .\scripts\build_style_factors.py --sample-every 5
conda run -n aster_5057_quantaalpha python .\scripts\manage_factor_library.py build
conda run -n aster_5057_quantaalpha python .\scripts\manage_factor_library.py `
  evaluate-origin --origin aster_style_factors --as-of 2026-11-24 `
  --evidence-root .\data\council\style_factor_evidence_20261124
```

本地首次结果为1,880,445行、811只股票。12个因子覆盖率为95.0%–99.9%，
均通过75%数据就绪门槛；这不是收益有效性结论。
