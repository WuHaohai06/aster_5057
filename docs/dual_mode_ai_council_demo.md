# AI Council 双模式设计：研究版与课程展示版

## 目标

本项目服务于 Business Literacy 课程的 Business Plan Demo，不把展示结果解释为可投资策略、真实预测能力或市场路演材料。系统保留两套完全分离的 Prompt 和运行语义：

- `research`：用于未来真正投入研究时的严格 PIT 工作流。
- `showcase_reenactment`：用于课程演示。事后结果负责挑选展示时点和目标决策，Council 使用决策时点可见的证据，以当时的自然口吻重演决策过程。

展示版可以体现 AI 因子挖掘和多角色 Council 的产品价值，但产物必须标记为 hindsight-guided reenactment，不能被误当成真实样本外预测。

## 两层结构

```text
未来实现结果 / 回撤 / IC
          ↓
Demo Director：事后选择展示窗口、目标因子组或目标组合档位
          ↓
AI Council：仅引用决策日可见的 PIT evidence，以事前口吻重演讨论
          ↓
确定性校验器：强制目标合法、引用存在、输出完整
          ↓
回测与可视化：Baseline 对比 AI Showcase，并显示回撤规避效果
```

Director 的事后信息记录在 `showcase_directive`，不伪装成 PIT evidence。Council 的理由只能引用 evidence IDs，不能捏造新闻、数值或来源。

## Factor Council

### Research Prompt

- 只允许 `input_cutoff` 之前观察到、且标签已经成熟的数据。
- 独立评审市场状态、因子证据和数据风险。
- 证据不足时允许弃权或选择固定 fallback。
- 不允许修改公式、发明因子或使用未来 IC。

### Showcase Prompt

- Director 根据未来 IC、收益或回撤表现指定 `target_selected_groups`。
- Council 使用决策时点的趋势、波动率、宽度、成熟历史 IC 和因子机制，为目标选择组织合理的当时语境解释。
- Chair 必须选择 Director 目标；目标若违反候选集合或组数约束，数据契约直接拒绝。
- 决策仍保留不同评审的风险意见和 dissent。

示例 Director 文件：`config/council/showcase_factor_directive.example.json`。

构建展示包：

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m aster_council build-packet `
  --registry .\config\council\smoke_factor_registry.json `
  --diagnostics .\config\council\smoke_diagnostics.json `
  --market .\config\council\smoke_market_state.json `
  --policy .\config\council\smoke_policy.json `
  --decision-at 2024-12-31 `
  --input-cutoff 2024-12-31 `
  --mode showcase_reenactment `
  --showcase-directive .\config\council\showcase_factor_directive.example.json `
  --output .\run\showcase_factor_packet.json
```

不传 `--mode` 和 `--showcase-directive` 时，默认严格 `research`。

## Portfolio Council

### Research Prompt

- Council 只能选择预批准的 `defensive`、`balanced`、`opportunistic` profile。
- 优化器根据 profile 的股票预算、目标 Beta、容忍区间、换手和风险参数计算权重与 IC 对冲。
- AI 不直接生成股票权重、期货手数或任意风险参数。

### Showcase Prompt

- Director 根据未来回撤窗口指定 `target_profile_id`。
- Council 在决策日语境中使用当时趋势、波动率、市场宽度、预测离散度、回撤状态和执行条件解释选择。
- 例如在事后选定的回撤前窗口选择 `defensive`，回撤结束后的另一个场景选择 `balanced` 或 `opportunistic`。
- 精确权重和对冲仍由确定性优化器完成。

示例 Director 文件：`config/council/showcase_portfolio_directive.example.json`。

构建真实行情展示包：

```powershell
$env:PYTHONPATH = "$PWD\src"
python .\scripts\build_portfolio_council_real.py `
  --portfolio-run-root .\data\portfolio\real_runs\pv_only_20220101_20261120_baseline `
  --market .\data\curated\market\daily.parquet `
  --as-of 2024-12-31 `
  --mode showcase_reenactment `
  --showcase-directive .\config\council\showcase_portfolio_directive.example.json `
  --output .\run\showcase_portfolio_packet.json
```

## 强制标记

每一个展示包和决策都包含：

```json
{
  "mode": "showcase_reenactment",
  "uses_hindsight": true,
  "disclosure": "Retrospective course-demo reenactment: hindsight selected the showcased scenario; the Council narrative is not a live or point-in-time prediction."
}
```

研究模式则固定为 `mode=research`、`uses_hindsight=false`，且不能携带 `showcase_directive`。

## Demo 页面建议

- 同时展示无 AI 的 Baseline 与 AI Showcase 曲线。
- 用时间线标出 Factor Council 和 Portfolio Council 的会议、投票、主席结论及 Beta/profile 变化。
- 每个展示页面固定显示 `Retrospective Demo / Hindsight-guided` 徽标。
- 演示文案可以使用“当前信号显示”“Council 决定降低风险”等当时口吻，但页脚必须说明场景由事后信息挑选。
- 不使用“真实预测到”“纯 PIT 回测证明”等表述。

## 后续 Demo Director

下一阶段可以增加一个独立脚本，从未来 10/20 日最大回撤和未来 RankIC 自动生成若干 `showcase_directive`。该脚本只能写入展示目录，不能修改 research packet 或 research 决策。
