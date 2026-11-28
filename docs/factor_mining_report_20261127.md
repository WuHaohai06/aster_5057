# 因子挖掘与因子仓库盘点报告

生成时间：2026-11-27 10:30（Asia/Shanghai）
口径：`data/curated/factor_library/catalog.json`（2026-11-26 21:07 生成）+ 批处理 `factors_directory_pv_20261126_001` 运行日志

## 1. 摘要

- 昨天启动的 **Factors Directory 价量因子批处理已结束**：8 个任务，**6 成功 / 2 失败**，总耗时约 **7 小时 33 分**，结束于 04:37。
- 本批共产出 **18 个新因子**（6 批 × 3 个），但 **尚未进入因子仓库**：catalog 生成于 21:07，早于批处理完成时间，重建后仓库会从 54 个因子扩到约 **72 个**。
- 当前仓库 **54 个因子**：43 validated / 3 demo_selected / 8 candidate，其中 **44 个 research eligible**。
- 质量最好的是 **style_residual_volatility**（IC 0.058–0.074）、**conventional_low_vol**（0.064）、**style_beta**（最高 0.044）；最弱的是 **quanta_pv_b08**（组均值 -0.034）和 **conventional_momentum**（-0.036）。
- 2026 年的 research 日程已经用上最好的 style 因子（low_vol + residual_volatility + beta），但 **本批 18 个新因子还没有被评估、也没有被 Council 使用**。

## 2. 挖掘批处理进度（已结束）

| 任务 | 主题 | 开始 | 耗时 | 结果 | result.h5 |
|---|---|---|---:|---|---:|
| FD01 | rank_momentum_persistence | 21:04 | 5m24s | ✅ 成功 | 3 |
| FD02 | momentum_acceleration | 21:09 | 4m20s | ✅ 成功 | 3 |
| FD03 | intraday_overnight_reassessment | 21:13 | 2m18s | ❌ exit=1 | 3（产物在但收尾失败） |
| FD04 | money_flow_extremes | 21:16 | **3h12m** | ❌ exit=-1 | 0 |
| FD05 | normalized_price_volume_trend | 00:28 | **3h45m** | ✅ 成功 | 3 |
| FD06 | volume_ratio_non_linearity | 04:14 | 8m35s | ✅ 成功 | 3 |
| FD07 | roc_volume_confirmation | 04:22 | 10m41s | ✅ 成功 | 3 |
| FD08 | daily_path_illiquidity | 04:33 | 3m48s | ✅ 成功 | 3 |

**失败/变慢根因**：deepseek-flash 的 reasoning 先吃掉输出预算，长 prompt 下频繁返回空 content / 截断 JSON，QuantaAlpha 在 `JSON parse failed ... retrying` 上循环（FD04 从 21:16 一直重试到 00:28 才退出；FD05 同样卡了约 3 小时 45 分，最后自己恢复并成功）。

## 3. 新产出（已生成、未入库）

批处理写出了 6 个 `vendor/quantaalpha-b7ceb27/data/factorlib/all_factors_library_aster_fd_*.json`，共 18 个新因子：

| 批次 | 新因子（3 个/批） |
|---|---|
| FD01 | Rank_Aggregation_Momentum_120D_Skip10D_Mean / Median、Raw_Cumulative_Momentum_120D_Skip10D |
| FD02 | Momentum_Acceleration_60D、Volume_Confirmed_Momentum_Acceleration_60D、Volatility_Adjusted_* |
| FD05 | Quiet_Drift_Volume_Weighted_Momentum_20D、Crowded_Attention_Volume_Weighted_Momentum_20D、* |
| FD06 | Up_Down_Volume_Ratio_Log_20D、Up_Down_Volume_Ratio_ZScore_60D、Signed_Volume_Imbalance_20D |
| FD07 | Smoothed_ROC10_VolumeConfirm_5D、Unconfirmed_ROC10_Reversal_5D、RiskAdjusted_Smoothed_ROC10_* |
| FD08 | Illiquidity_Ratio_PathLength_RelVol_1D、Smoothed_Illiquidity_Ratio_5D、Normalized_PathLength_* |

> 18 个 factor_id 与当前仓库的 54 个 **无重叠**；需要 `build_factor_library` 重建 + `evaluate-all` 评估后才会进入 Council 候选池。

## 4. 当前因子仓库（54 个）

### 4.1 按来源与状态

| 来源 | 数量 | 状态说明 |
|---|---:|---|
| QuantaAlpha 挖掘 | 26 | 全部 validated（本批 18 个未计入） |
| 市场型风格因子 | 12 | 全部 validated |
| 确定性价量基线 | 6 | validated / demo_selected |
| 财报文本 LLM 因子 | 5 | candidate，覆盖率约 0.43 |
| 财报文本解析因子 | 3 | candidate，无诊断 |
| PIT 财务因子 | 2 | validated，覆盖率约 0.42–0.43，research 不合格 |

### 4.2 按因子组（组均值 IC）

| 组 | 数量 | 可研究 | 均值 IC | 最好 IC |
|---|---:|---:|---:|---:|
| **style_residual_volatility** | 3 | 3 | **0.064** | **0.074** |
| **conventional_low_vol** | 1 | 1 | **0.064** | 0.064 |
| **style_beta** | 3 | 3 | **0.027** | 0.044 |
| style_liquidity | 3 | 3 | 0.013 | 0.040 |
| style_momentum | 3 | 3 | 0.009 | 0.028 |
| quanta_pv_a03 | 2 | 2 | 0.023 | 0.024 |
| quanta_pv_a01 | 3 | 3 | 0.009 | 0.012 |
| quanta_price_volume_seed | 3 | 3 | 0.008 | 0.009 |
| conventional_reversal | 1 | 1 | 0.017 | 0.017 |
| shock_reversal | 1 | 1 | 0.005 | 0.005 |
| close_pressure | 1 | 1 | -0.003 | -0.003 |
| quanta_pv_a08 / a05 / a04 | 9 | 9 | -0.008 / -0.010 / -0.016 | — |
| quanta_pv_b11 / b12 | 6 | 6 | -0.019 / -0.018 | — |
| **quanta_pv_b08** | 3 | 3 | **-0.034** | -0.032 |
| **conventional_momentum** | 1 | 1 | **-0.036** | -0.036 |
| filing_*（5 组） | 5 | 0 | -0.011（均值） | 0.003 |
| filing_text | 3 | 0 | 0（无诊断） | — |
| financial_* | 2 | 0 | 0.007 / 0.012 | — |

### 4.3 IC 最高的 10 个因子

| 因子 | 组 | IC | ICIR | 覆盖率 |
|---|---|---:|---:|---:|
| residual_volatility_idiosyncratic | style_residual_volatility | 0.0739 | 0.39 | 1.00 |
| conventional_low_vol | conventional_low_vol | 0.0642 | 0.34 | 0.99 |
| residual_volatility_of_volatility | style_residual_volatility | 0.0599 | 0.38 | 1.00 |
| residual_volatility_downside | style_residual_volatility | 0.0584 | 0.31 | 1.00 |
| beta_instability | style_beta | 0.0443 | 0.39 | 1.00 |
| liquidity_relative_volume_impact | style_liquidity | 0.0397 | 0.19 | 1.00 |
| beta_shrunk_252 | style_beta | 0.0363 | 0.14 | 1.00 |
| momentum_rank_persistence | style_momentum | 0.0276 | 0.16 | 0.95 |
| liquidity_volume_instability | style_liquidity | 0.0258 | 0.27 | 1.00 |
| 4e9bb089…（quanta_pv_a03） | quanta_pv_a03 | 0.0236 | 0.31 | 1.00 |

## 5. 这些因子现在被谁用

- **2026 research 季度日程**（证据链修复后）：low_vol + style_residual_volatility，Q1/Q4 再加 style_beta —— 已经是仓库里 IC 最好的一批。
- **showcase / narrative demo 的 8 组**：low_vol、quanta_pv_a03、quanta_pv_a01、5 个 filing 组 —— 其中 filing 组 IC 为负且覆盖率仅 0.43，并不是最优组合。
- **本批 18 个新 FD 因子**：尚未评估、尚未被任何 Council 使用。

## 6. 风险与待办

1. **新因子未入库**：重建 catalog 后预计 54 → 72；需要跑 `evaluate-all`（按 origin/group 分块，约 10–15 分钟）后再刷新 Council 证据包，否则新因子永远进不了候选池。
2. **主 catalog 里常规因子诊断仍停在 2025-12-31**：季度证据刷新用的是 `data/council/quarterly_evidence/<cutoff>/library` 的副本，主 catalog 没有被覆盖（有意为之）。对外报告时要说明“季度决策用的是刷新副本，主 catalog 的 as_of 较旧”。
3. **符号方向冲突**：quanta_pv_b08 / b11 / b12、conventional_momentum 的 IC 为负，但注册的 expected_direction 为正，Council 会因此拒选 —— 需要清理注册元数据或明确反向使用。
4. **filing 因子覆盖率 0.43**，达不到 research 门槛（0.75），目前只在 showcase 里出现，建议要么补数据、要么从 demo 因子组里移除。
5. **FD03/FD04 失败**：FD04 无产物；FD03 有 3 个 h5 但收尾 exit=1，可单独重跑或人工检查 backtest 结果。

## 7. 建议的下一步（按优先级）

1. 重建因子库并评估 18 个新因子（`manage_factor_library.py build` → `evaluate-all` 分块）；
2. 用新的 catalog 重跑一次季度证据刷新（2025-12-31 / 2026-03-31 / 06-30 / 09-30），让 Council 看到新因子；
3. 清理负 IC 组的 expected_direction；
4. 决定 filing 因子去留；
5. 单独重跑 FD04（以及 FD03 的收尾）。

---

## 8. 入库结果（2026-11-27 10:34 更新）

已完成：`manage_factor_library build` + 按组 `evaluate-all`（as_of = 2026-11-24）。

- 因子总数：**54 → 72**
- 状态：**validated 61 / demo_selected 3 / candidate 8**
- 新因子：18 个，全部通过覆盖率与观测数门槛（coverage 1.00，obs ≥ 24），自动从 candidate 升为 validated
- 证据目录：`data/council/quanta_evidence_fd_20261127/<group>/`
- catalog digest：`295dc65e5ca555c7ed281bb6f3c8b972deafaeffed77314ac613e9c25cf2e784`

### 新因子 IC（按 rank_ic_mean 排序）

| 因子 | 组 | IC | ICIR | 2026 IC |
|---|---|---:|---:|---:|
| Unconfirmed_ROC10_Reversal_5D | quanta_fd_fd07 | **0.0254** | 0.15 | **0.0529** |
| Quiet_Volume_Return_Correlation_20D | quanta_fd_fd05 | **0.0223** | 0.20 | **0.0347** |
| Rank_Aggregation_Momentum_120D_Skip10D_Mean | quanta_fd_fd01 | 0.0199 | 0.11 | -0.0053 |
| Rank_Aggregation_Momentum_120D_Skip10D_Median | quanta_fd_fd01 | 0.0150 | 0.09 | 0.0040 |
| Raw_Cumulative_Momentum_120D_Skip10D | quanta_fd_fd01 | -0.0115 | -0.06 | -0.0833 |
| Quiet_Drift_Volume_Weighted_Momentum_20D | quanta_fd_fd05 | -0.0116 | -0.07 | -0.0152 |
| Up_Down_Volume_Ratio_ZScore_60D | quanta_fd_fd06 | -0.0166 | -0.13 | -0.0433 |
| RiskAdjusted_Smoothed_ROC10_VolumeConfirm | quanta_fd_fd07 | -0.0248 | -0.15 | -0.0716 |
| Volatility_Adjusted_Momentum_Acceleration_60D | quanta_fd_fd02 | -0.0257 | -0.16 | -0.0141 |
| Smoothed_ROC10_VolumeConfirm_5D | quanta_fd_fd07 | -0.0283 | -0.17 | -0.0617 |
| Up_Down_Volume_Ratio_Log_20D | quanta_fd_fd06 | -0.0301 | -0.22 | -0.0684 |
| Signed_Volume_Imbalance_20D | quanta_fd_fd06 | -0.0304 | -0.22 | -0.0689 |
| Momentum_Acceleration_60D | quanta_fd_fd02 | -0.0329 | -0.20 | -0.0233 |
| Volume_Confirmed_Momentum_Acceleration_60D | quanta_fd_fd02 | -0.0385 | -0.25 | -0.0290 |
| Crowded_Attention_Volume_Weighted_Momentum_20D | quanta_fd_fd05 | -0.0440 | -0.28 | -0.0793 |
| Illiquidity_Ratio_PathLength_RelVol_1D | quanta_fd_fd08 | -0.0461 | -0.27 | -0.1087 |
| Smoothed_Illiquidity_Ratio_5D | quanta_fd_fd08 | -0.0507 | -0.27 | -0.1249 |
| Normalized_PathLength_Rank_1D | quanta_fd_fd08 | -0.0598 | -0.35 | -0.1266 |

### 解读与注意

- 正向可用：**Unconfirmed_ROC10_Reversal_5D**（2026 IC +0.053）、**Quiet_Volume_Return_Correlation_20D**（+0.035）；两个 Rank Momentum 接近 0。
- 强负向：**fd08 的 3 个非流动性因子**（-0.046 ~ -0.060，2026 年 -0.11 ~ -0.13）、**fd05 Crowded_Attention**（-0.044）、fd06 的成交量比三项（-0.03）。
- 注册元数据里 `expected_direction` 统一写成正向，所以负 IC 因子仍会被 Council 以“方向冲突”拒选。若要使用，需要么反向登记（明确负向暴露）、么在 Council 里允许负向因子。
- 主 catalog 的常规因子诊断仍停在 2025-12-31（季度刷新用的是副本），本次入库没有改变这一点。
