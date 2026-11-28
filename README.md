# Aster 5057

Aster 是一个面向 CSI500 的 AI 增强型量化研究与课程演示框架。项目将可审计的数据管线、AI 因子挖掘、多角色 Factor Council、机器学习收益预测、组合优化、Portfolio Council 和回测串成一条完整链路。

> 本项目用于 Business Literacy 课程的 Business Plan Demo 和技术可行性验证，不构成投资建议，也不应被描述为已验证的真实交易系统。`showcase_reenactment` 使用事后信息选择演示场景，所有产物必须保留 hindsight disclosure。

## 项目目标

Aster 试图展示 AI 在量化研究流程中最有价值、也最容易审计的几个位置：

1. 将经济学假设转化为可计算的候选因子；
2. 让不同角色的 AI Reviewer 基于统一证据评审因子；
3. 从财报文本中提取带页码引用的结构化因子；
4. 使用 walk-forward 机器学习生成预期收益；
5. 让 Portfolio Council 在有限、预批准的组合档位中作出选择；
6. 将所有 AI 输出交给确定性约束、组合优化和回测验证。

AI 不直接绕过数据质量门槛，不直接任意生成股票权重，也不修改回测硬约束。

## 系统架构

```mermaid
flowchart TD
    A[CSI500 PIT 股票池] --> D[Canonical Data Spine]
    B[日行情 / IC 期货] --> D
    C[结构化财务 / 财报 PDF] --> D
    D --> E[QuantaAlpha AI 因子挖掘]
    D --> F[财报 AI 多维因子]
    D --> G[传统价量与财务因子]
    E --> H[Unified Factor Library]
    F --> H
    G --> H
    H --> I[AI Factor Council]
    I --> J[Walk-forward Ridge Forecaster]
    J --> K[AI Portfolio Council]
    K --> L[CVXPY 确定性组合优化]
    L --> M[One-close-lag 回测与归因]
```

## AI 应用点

| 模块 | AI 的职责 | 确定性约束 | 当前状态 |
|---|---|---|---|
| QuantaAlpha | 根据经济学假设生成、修正因子表达式 | 数据字段、计算环境、质量门槛和回测 | 首批8条价量假设完成；第二批8条 factors.directory 热启动任务运行中 |
| Factor Council | 多角色评审统计证据、市场状态和数据质量 | PIT、覆盖率、候选集合和 fallback | 已完成真实 DeepSeek 调用 |
| 财报 AI | 从财报提取展望、需求、利润率、投资和不确定性评分 | 页码引用、公告日、空值和分数范围 | 2020–2025 六年批量解析、评分和下游回测已完成 |
| 收益预测 | walk-forward 横截面预测 | 标签成熟、训练截止日和固定模型接口 | Ridge 已接入真实数据链路 |
| Portfolio Council | 在 approved profiles 中选择组合状态 | 只能选择预批准档位，不能直接写权重 | 已完成真实 DeepSeek 调用 |

Factor Council 和 Portfolio Council 都提供两种明确分离的模式：

- `research`：只使用决策日可见的 PIT 证据；
- `showcase_reenactment`：允许事后选择课程演示场景，但必须保留固定披露，不能伪装成真实样本外预测。

## 当前进度

以下为 **2026-11-26** 的本地工作区快照。生成数据和运行产物均被 `.gitignore` 排除，不随仓库上传。

| 子系统 | 当前进度 | 状态说明 |
|---|---:|---|
| CSI500 历史候选股票池 | 1,273 只 | 来自 Qlib/Baostock 周频历史候选快照，不等同于官方逐次调整清单 |
| Canonical 日行情 | 1,814,107 行 / 827 只 | 2016-11-24 至 2026-11-24；AKShare 十年补全任务完成 1,273/1,273，保留 1 个失败记录待核查 |
| 财报 PDF | 7,352 份 | 当前原文库存；缺失文件仍需交易所补漏或 OCR 处理 |
| AI-friendly 财报 | 4,350/4,360 份完成评分 | 2020–2025 六个财年均完成；10 份失败或需补处理 |
| DeepSeek 财报因子 | 21,560 行 / 735 只 | 五个维度均已物化，并保留公告可用日和文档血缘 |
| 旧 PIT 财务原始数据 | 63,434 行 / 747 只 | 当前只有 `roeWa`、`YOYNI` 两个字段 |
| 已物化财务因子 | 28,266 行 / 351 只 | 需要用最新 747 只原始数据重新构建 |
| 市值/估值/三表补充 | 已按用户要求暂停 | 行情优先；后续恢复时继续断点下载 |
| 行业快照 | 627/628 只 | 使用当前快照，不声称历史 PIT 行业分类 |
| Unified Factor Library | 54 个因子 | 原42个因子之外，新增 Beta、Momentum、Residual Volatility、Liquidity 各3个确定性风格因子 |
| Factor Council | 已接入 | 最新 showcase 选择低波动、A01/A03 和全部五个财报 AI 因子 |
| Portfolio Council | 已接入 | 最新 showcase 选择 `defensive`，并对 3 个行业超配、3 个行业低配 |
| 组合优化与回测 | 已接入 | 最新财报链回放完成 128 次预测/优化；年化 -0.98%、Sharpe -0.13、最大回撤 -13.10% |

五个财报 AI 因子的全期 CSI500 覆盖率约为 42.6%–42.8%，低于正式研究政策的 75% 门槛。因此它们在主 Catalog 中仍是 `candidate`；课程演示使用独立的低覆盖 `showcase_reenactment` 政策，并保留固定 hindsight disclosure，不能据此声称真实样本外有效。

新增的12个市场型风格因子不使用 `risk_` 前缀，统一分为 `style_beta`、`style_momentum`、`style_residual_volatility` 和 `style_liquidity`。它们已通过覆盖率与成熟观测门槛，但预测价值仍需 Council 根据 IC、方向、冗余和机制逐组判断。Profitability 与 Growth 因子仍等待 PIT 三表补齐。

计划中的下一批候选因子按六个普通因子族组织，不使用 `risk_` 前缀：

- Beta：3 个候选；
- Momentum：3 个候选；
- Residual Volatility：3 个候选；
- Liquidity：3 个候选；
- Profitability：3 个候选；
- Growth：3 个候选。

合计 18 个候选，进入统一因子库后再由 Factor Council 评审。

## 目录结构

```text
Aster_5057_whh/
├── config/                       # Council、QuantaAlpha、期货等版本化配置
├── docs/                         # 架构、Prompt、数据语义和运行说明
├── scripts/                      # 下载、构建、Council、回测与审计入口
├── src/
│   ├── aster_data/               # 数据采集、标准化、因子库和财报处理
│   ├── aster_quantalpha/         # QuantaAlpha / Qlib 数据适配
│   ├── aster_council/            # AI Factor Council
│   └── aster_portfolio/          # 预测、优化、回测与 Portfolio Council
├── tests/                        # 单元与集成测试
├── requirements-data.txt
├── requirements-council.txt
├── requirements-portfolio.txt
└── requirements-quantaalpha-constraints.txt
```

以下目录只存在于本地运行环境，不会提交到 Git：

- `data/`：行情、PDF、Parquet、因子值和回测产物；
- `run/`：状态、checkpoint、审计运行与加密凭据；
- `logs/`、`log/`：运行日志；
- `vendor/`：本地第三方源码镜像。

## 环境

项目当前使用两个隔离的 Conda 环境。

### 数据、组合与回测环境

```powershell
conda create -n aster_5057_whh python=3.11 -y
conda activate aster_5057_whh
pip install -r requirements-data.txt
pip install -r requirements-portfolio.txt
pip install -r requirements-council.txt
```

核心版本包括 `pyqlib==0.9.7`、`akshare==1.20.65`、`pyarrow==17.0.0`、`pypdf==6.4.0` 和 `cvxpy>=1.5,<2`。

### QuantaAlpha 环境

```powershell
conda create -n aster_5057_quantaalpha python=3.11 -y
conda activate aster_5057_quantaalpha
pip install -r requirements-quantaalpha-constraints.txt
pip install -r requirements-council.txt
```

本地验证使用 QuantaAlpha commit `b7ceb27`。`vendor/` 不提交到仓库，使用者需要自行获取相同版本并遵守其许可证。

运行 Python 模块前设置源码路径：

```powershell
$env:PYTHONPATH = "$PWD\src"
```

PowerShell 入口会优先使用当前已激活的同名 Conda 环境，也支持通过 `ASTER_DATA_PYTHON` 和 `ASTER_QUANTA_PYTHON` 指定 Python 可执行文件；仓库中不包含任何本机用户名或绝对 Conda 路径。

## API 凭据

不要把 DeepSeek API Key 写进 README、配置、命令历史或提交记录。Windows 环境可使用 DPAPI 保存当前用户加密凭据：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\set_quantaalpha_secret.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\test_quantaalpha_llm.ps1
```

凭据保存在 `run/secrets/`，该目录已被 Git 忽略。也可以只在当前终端临时设置：

```powershell
$env:DEEPSEEK_API_KEY = "<your-key>"
$env:DEEPSEEK_BASE_URL = "https://api.deepseek.com"
$env:DEEPSEEK_MODEL = "deepseek-flash"
```

## 数据管线

查看后台任务：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\manage_data_downloads.ps1 -Action status
```

十年 CSI500 数据：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_full_download.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\start_parallel_financial.ps1
```

历史市值、估值、财务三表和行业：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_factor_input_download.ps1
```

该任务使用 checkpoint 和原子写入，重启相同区间会跳过已完成文件。财务报表以 `NOTICE_DATE` 作为 `available_at`，行业历史以变更日期生效。

财报原件和解析：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_filing_download.ps1
python .\scripts\parse_filings.py --limit 10
python .\scripts\generate_filing_text_factors.py `
  --parsed-root .\data\curated\filings_ai `
  --output-root .\data\curated\factors\filing_text `
  --mode deterministic
```

LLM 模式要求每个非空评分都包含有效财报页码引用。当前接口一次调用同时评估 management outlook、demand strength、margin resilience、investment intensity 和 uncertainty。

按单个完整财年并行解析并生成 DeepSeek 因子：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_filing_factor_year.ps1 `
  -FiscalYear 2025 `
  -ParseWorkers 6 `
  -LlmWorkers 8
```

进度写入 `run/filing_factor_2025/status.json`，最终因子和证据写入 `data/curated/factors/filing_analysis/2025/`。相同财年重新启动会复用已完成的 PDF 和 LLM checkpoints。

## QuantaAlpha 因子挖掘

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\prepare_quantaalpha_data.ps1
python .\scripts\validate_quantaalpha_deployment.py
powershell -ExecutionPolicy Bypass -File .\scripts\run_quantaalpha.ps1 `
  -Direction "Test a price-volume hypothesis on CSI500 with PIT-safe inputs"
```

经济学假设与可复制 Prompt 见 [docs/quantaalpha_price_volume_hypotheses.md](docs/quantaalpha_price_volume_hypotheses.md)。
六个因子族的 18 条热启动假设见 [docs/quantaalpha_factor_seed_library.md](docs/quantaalpha_factor_seed_library.md)，
机器可读配置位于 `config/quantaalpha/hypothesis_seed_library.yaml`。

## Unified Factor Library

因子库统一管理因子定义、数值、SHA-256 lineage、PIT 资格、diagnostics、生命周期和 Council 输入导出。

```powershell
python .\scripts\manage_factor_library.py build
python .\scripts\manage_factor_library.py validate
python .\scripts\manage_factor_library.py list
python .\scripts\manage_factor_library.py evaluate-quanta `
  --as-of 2026-11-24 `
  --evidence-root .\data\council\quanta_evidence_2026
python .\scripts\manage_factor_library.py export-council `
  --mode research `
  --output .\data\curated\factor_library\exports\research
```

详见 [docs/factor_library_v1.md](docs/factor_library_v1.md)。

## Factor Council

Council 使用三个 Reviewer 和一个 Chair。模型输出必须符合 Pydantic schema，引用已知 evidence ID，并满足代码侧候选集合和组数限制；验证失败时使用固定 fallback。每个候选因子同时提供经济学假设、机制解释、预期方向、证伪条件和来源。三位 Reviewer 必须逐组提交结构化机制评审，包括机制支持度、PIT 一致性和可证伪性；遗漏任一候选组的机制评审会触发 fallback。

## Aster Research Console

交互式前端位于 `apps/aster-console`，提供流程总览、因子库、因子详情、
AI Council、六年财报智能和组合回放页面。实时模式由 FastAPI 服务聚合本地任务状态，
通过 SSE 通知与 15 秒轮询自动刷新。Portfolio Replay 另提供有边界的 Human-in-the-loop
流程：同一个 Unified Council 固定按季度运行两套顺序 Prompt。Factor Agenda 先给出因子池，
Portfolio Agenda 再读取该结论和共享证据，选择受限的 beta 档位与行业倾斜。人可以最多复议
三轮；每次复议都会按顺序重跑两套 Prompt，接受后同时生成 factor schedule 和 portfolio
schedule，再异步运行真实回测。组合信号与调仓仍为每 5 个交易日一次。
自动模式也使用相同的季度节点，只是自动接受各季度初始结论并一次性运行完整 schedule。
接受的轮次、人工指令、模型调用、约束校验和产物摘要全部写入本地审计目录。
API 不会向浏览器暴露 API Key、原始 PDF、大型 Parquet、日志路径或本机绝对路径。

每个季度 Council 在结构化决策前调用 DeepSeek Search API。Research 模式只允许决策截止日
以前、最近 365 天且相关度达标的网页证据；Showcase 模式保留明确的事后披露。搜索来源、
拒绝原因、内容哈希和引用 ID 均保存到会话审计目录。详见
[docs/council_web_research_v1.md](docs/council_web_research_v1.md)。

```powershell
# 首次启动会安装 requirements-console.txt 并构建前端
powershell -ExecutionPolicy Bypass -File .\scripts\start_aster_console_live.ps1
# 浏览器打开 http://127.0.0.1:8765/

# 停止后台服务
powershell -ExecutionPolicy Bypass -File .\scripts\stop_aster_console_live.ps1
```

如需临时公网演示，先安装 `cloudflared`，保持本地服务运行，然后执行
`scripts/start_aster_console_tunnel.ps1`。Quick Tunnel URL 是公开地址；正式或
持续分享应使用 Named Tunnel 并在 Cloudflare Access 设置访问控制。项目内部
没有重新加入登录页。

静态降级版本仍可通过 `python scripts/export_dashboard_snapshot.py` 生成。产品规划见
[docs/aster_console_frontend_plan.md](docs/aster_console_frontend_plan.md)。

```powershell
python .\scripts\build_factor_council_packet.py `
  --registry .\data\council\real_evidence\factor_registry.json `
  --diagnostics .\data\council\real_evidence\factor_diagnostics.json `
  --market .\data\council\real_evidence\market_state.json `
  --policy .\config\council\real_policy.json `
  --decision-at 2025-12-31 `
  --input-cutoff 2025-12-31 `
  --output .\run\factor_packet.json

powershell -ExecutionPolicy Bypass -File .\scripts\run_factor_council.ps1 `
  -PacketPath .\run\factor_packet.json
```

详见 [docs/ai_factor_council_v1.md](docs/ai_factor_council_v1.md) 和 [docs/dual_mode_ai_council_demo.md](docs/dual_mode_ai_council_demo.md)。

## 组合优化、回测和 Portfolio Council

真实数据链路：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_real_data_spine.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\run_real_pipeline.ps1 `
  -StartDate 2018-01-01 `
  -EndDate 2025-12-31
```

合成基础设施 smoke test：

```powershell
python .\scripts\run_portfolio_smoke.py `
  --output-root .\data\portfolio\synthetic_smoke
powershell -ExecutionPolicy Bypass -File .\scripts\run_portfolio_full_chain_smoke.ps1
```

Portfolio Council 只能选择 `defensive`、`balanced`、`opportunistic`。股票权重、IC 对冲、换手、Beta、总敞口、保证金和成本仍由确定性代码控制。详见 [docs/portfolio_backtest_and_ai_council_v1.md](docs/portfolio_backtest_and_ai_council_v1.md)。

季度 Replay 的双 Prompt 串联、人工接受边界和审计产物见
[docs/unified_council_two_prompt_v1.md](docs/unified_council_two_prompt_v1.md)。

回测已使用预构建 NumPy 特征矩阵、向量化 Beta 估计和免重复特征分解的收缩协方差实现。
本机真实数据短窗口从约 80 秒降至约 38 秒，指标仅有浮点尾差；详见
[docs/backtest_performance_v1.md](docs/backtest_performance_v1.md)。

## 测试

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m pytest tests -q
```

Smoke 结果仅验证基础设施，不应被当作真实研究证据。

## 数据与研究语义

- CSI500 周频候选快照不等同于中证指数公司官方成分调整历史；
- Yahoo adjusted bars 是公开数据 fallback，不是最终生产级 A 股行情源；
- 所有财务与财报因子必须以公告日作为 `available_at`；
- 当前市值、成交额和换手率仍在补齐，不能把缺失值误认为零；
- AI 生成的因子必须经过覆盖率、冗余、稳定性和回测诊断；
- Council 只负责有限决策，数值约束由代码执行；
- `showcase_reenactment` 是明确披露的课程演示模式，不代表真实预测能力。

## Git 与大文件

仓库只应提交源码、配置、文档、测试和 requirements。不要提交 API Key、DPAPI 文件、`.env`、行情、PDF、Parquet、HDF5、模型缓存、运行产物、本地 Conda 环境或第三方源码镜像。

首次提交前建议执行：

```powershell
git init
git status --short
git add README.md .gitignore config docs scripts src tests requirements-*.txt
git status --short
```

提交前确认 `data/`、`run/`、`logs/`、`vendor/` 和任何密钥文件没有进入 staged changes。

## 进一步文档

- [Real Data Spine](docs/real_data_spine_v1.md)
- [Financial and Research Pipeline](docs/financial_factor_and_research_pipeline_v1.md)
- [Factor Library](docs/factor_library_v1.md)
- [AI Factor Council](docs/ai_factor_council_v1.md)
- [Portfolio and AI Council](docs/portfolio_backtest_and_ai_council_v1.md)
- [Research / Showcase Dual Mode](docs/dual_mode_ai_council_demo.md)

## License

当前工作区尚未包含开源许可证。在公开发布或接受外部贡献前，请根据课程和第三方依赖要求补充 `LICENSE`，并核对 Qlib、QuantaAlpha、数据源和其他依赖的许可证与使用条款。
