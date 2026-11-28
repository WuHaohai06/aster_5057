# Interactive Council 测试记录（2026-11-27）

## 1. 目的

验证在 Interactive Replay（showcase / 前视展示）里，向 "YOUR INSTRUCTION TO BOTH AGENDAS" 输入一条人工指令后：

1. Factor Agenda + Portfolio Agenda 是否会重新运行且通过校验；
2. 因子组与组合档位是否真的变化；
3. 2026 Q3（2026-07-01 ~ 2026-09-30）的回测绩效是否变化。

## 2. 环境

- Console: http://127.0.0.1:8765
- API: `/api/replay/sessions`、`/api/replay/{session_id}/nodes/{node_id}/rethink|accept|run`
- Server: uvicorn PID 14992（2026-11-27 14:02 启动，已加载 DPAPI 中的 DeepSeek key）
- Replay 节点来源：`data/council/quarterly_evidence/<cutoff>` + 最新 council artifacts
- 本测试所有节点均为 `mode: "showcase_reenactment"`、`uses_hindsight: true`，**不是 research/PIT**

## 3. 操作步骤

### 3.1 创建 interactive session

```http
POST /api/replay/sessions?automatic=false
```

返回 session `c598592688094a45af270c4767aefd8a`，20 个节点（2021-12-31 ~ 2026-09-30）。
目标节点：

- node_id: `factor-council-2026-06-30`
- decision_at: 2026-06-30
- segment: 2026-07-01 ~ 2026-09-30
- mode: showcase_reenactment
- 初始 round-0：`quarterly_automatic_proposal`，8 个因子组
  - conventional_low_vol
  - quanta_pv_a03
  - quanta_pv_a01
  - filing_demand_strength / filing_management_outlook / filing_uncertainty / filing_investment_intensity / filing_margin_pressure
- 初始组合：`balanced`，target_beta 0.00，tilt 0.00
- 该 round-0 的组合模型为 `deterministic-policy`

### 3.2 新建测试 session 并提交 prompt

新建 session：`680a513971f84f398cc33740e30a401d`

提交：

```http
POST /api/replay/680a513971f84f398cc33740e30a401d/nodes/factor-council-2026-06-30/rethink
Content-Type: application/json

{
  "instruction": "Reconsider factor redundancy: keep only one short-horizon reversal sleeve, keep conventional_low_vol as the defensive anchor, disable momentum groups whose 2026 Rank IC is unstable, and keep the approved portfolio profile and industries unchanged."
}
```

结果：

- 耗时 **46.1 秒**；
- node 从 1 个 round 变为 2 个；
- round-1：`human_reconsideration`，**valid = true**，无 validation error；
- selected_groups 变为：
  - conventional_low_vol
  - **conventional_reversal**（新增）
  - quanta_pv_a03
  - **不再包含 quanta_pv_a01**（被去掉）
  - 4 个 filing 组保留
- portfolio round-1：**defensive**，target_beta **-0.15**，industry_active_tilt **0.10**。

### 3.3 尝试 accept + run（session 内）

```http
POST /api/replay/680a513971f84f398cc33740e30a401d/nodes/factor-council-2026-06-30/accept
```

→ 成功，accepted_round_id = `round-1`。

```http
POST /api/replay/680a513971f84f398cc33740e30a401d/nodes/factor-council-2026-06-30/run
```

→ **HTTP 409 Conflict**：

> earlier Council nodes must be accepted first

原因：interactive session 的后续节点必须在前面所有节点 accepted 之后才能 run；本 session 只接受了 2026-06-30，前面 18 个节点仍是 draft。

### 3.4 尝试基线 accept + run

新建 session：`72b277fc98c54f01aa20a8c410690876`

```http
POST /api/replay/72b277fc98c54f01aa20a8c410690876/nodes/factor-council-2026-06-30/accept
```

→ **HTTP 409 Conflict**：

> wait for the two AI agendas before accepting the package

原因：seed 的 round-0 组合模型是 `deterministic-policy`，accept 被 explicitly 拒绝，必须先跑 AI 的两个议程。

### 3.5 绕过 session 限制：直接构建 schedule + 跑 pipeline

从 session `680a...` 的节点数据构建两个版本的 schedule：

- 节点范围：2021-12-31 ~ 2026-06-30，共 19 个 entry
- prompt 版：2026-06-30 使用 round-1（defensive -0.15）；其余节点用 round-0
- baseline 版：全部节点使用 round-0（balanced 0.00）

输出目录：

```
run/replay_compare/
  prompt/
    factor_schedule.json
    portfolio_schedule.json
    run/            # pipeline 输出
  baseline/
    factor_schedule.json
    portfolio_schedule.json
    run/
```

执行：

```powershell
scripts\run_real_pipeline.ps1 `
  -StartDate 2019-01-01 `
  -EndDate 2026-09-30 `
  -OutputRoot run\replay_compare\<variant>\run `
  -FactorSchedule run\replay_compare\<variant>\factor_schedule.json `
  -PortfolioSchedule run\replay_compare\<variant>\portfolio_schedule.json
```

耗时：

- prompt run：14:32:54 → 14:37:05（约 4 分钟）
- baseline run：14:37:08 → 14:41:12（约 4 分钟）

输出：`metrics.json`、`daily.csv`、`manifest.json`、`target_weights.csv` 等。

## 4. 结果

| 指标 | baseline（round-0） | prompt（round-1） | 变化 |
|---|---:|---:|---:|
| Q3 2026 收益 | -9.18% | **+1.10%** | +10.3 pts |
| 2026 YTD | -7.84% | **+2.60%** | +10.4 pts |
| 全期年化 | -5.57% | -3.90% | +1.7 pts |
| Sharpe | -0.70 | -0.48 | +0.22 |
| 最大回撤 | -35.64% | **-30.43%** | +5.2 pts |
| Q3 平均 β | 0.00 | **-0.14** | 转空 |

保存文件：`run/replay_compare/comparison.json`

## 5. 解释与限制

1. 这是 **showcase / 前视**测试，不是 research/PIT；Q3 改善包含“提前知道 7 月科技崩盘”的前视成分。
2. 改善主要来自组合降 β（0.00 → -0.14）与防御行业，而不是单纯因子替换；prompt 同时触发了两个议程。
3. 当前 Interactive Replay 的 UI 无法直接跳到 2026-06-30 跑 segment：
   - 后续节点 run 要求前面所有节点 accepted；
   - 前面节点的 seeded 组合是 deterministic-policy，accept 被拒；
   - 需要“从指定节点开始 / 单节点演示”的功能，或先对前 18 个节点逐一跑 AI 议程。
4. 本次对比是**直接调用 pipeline + 手工 schedule**，不是 UI 的 "Run segment" 按钮路径；UI 路径受 3 的限制。

## 6. 相关文件

- Session 数据：`run/aster_console/replay_sessions/680a513971f84f398cc33740e30a401d/`
- Prompt 结果 round：`factor-council-2026-06-30_round-1.json`
- Portfolio 结果：`factor-council-2026-06-30_round-1_portfolio.json`
- 回测对比：`run/replay_compare/`
