export type Lang = "en" | "zh" | "dual";

const STORAGE_KEY = "aster-console-lang";

function initial(): Lang {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved === "en" || saved === "zh" || saved === "dual") return saved;
  } catch {
    /* ignore */
  }
  return "en";
}

let current: Lang = initial();

export function getLang(): Lang {
  return current;
}

export function setLang(lang: Lang) {
  current = lang;
  try {
    window.localStorage.setItem(STORAGE_KEY, lang);
  } catch {
    /* ignore */
  }
}

const ZH: Record<string, string> = {
  "Command Center": "指挥中心",
  "Factor Library": "因子库",
  "AI Council": "AI 委员会",
  "Filing Intelligence": "公告智能",
  "Portfolio Replay": "组合回放",
  "Research pipeline": "研究流水线",
  "Live system map": "实时系统图",
  "Background jobs": "后台任务",
  "Live sanitised status": "脱敏实时状态",
  "Signal leaderboard": "信号排行榜",
  "Canonical diagnostics": "标准诊断",
  "View library": "查看因子库",
  "Latest Council state": "最新委员会状态",
  "Historical accepted artifact": "历史已接受产物",
  "Inspect ballots and evidence": "查看投票与证据",
  "Open Council": "打开委员会",
  "Explore factors": "浏览因子",
  "FACTOR CATALOG": "因子目录",
  "AI-MINED": "AI 挖掘",
  "FILING INTELLIGENCE": "公告智能",
  "LATEST REPLAY": "最新回放",
  "Research system summary": "研究系统概览",
  "WORKSPACE LIVE": "工作区在线",
  "AUTO REFRESH": "自动刷新",
  "RANK IC": "Rank IC",
  "ICIR": "ICIR",
  "Catalog explorer": "因子目录浏览器",
  "Search · filter · inspect": "搜索 · 筛选 · 查看",
  "Search factor, group or hypothesis": "搜索因子、分组或假设",
  "All origins": "全部来源",
  "All lifecycle states": "全部生命周期",
  Candidate: "候选",
  Validated: "已验证",
  "Demo selected": "Demo 入选",
  "Sort: Rank IC": "排序：Rank IC",
  "Sort: Coverage": "排序：覆盖率",
  "Sort: Name": "排序：名称",
  Factor: "因子",
  Origin: "来源",
  Lifecycle: "生命周期",
  Coverage: "覆盖率",
  Turnover: "换手",
  Redundancy: "冗余度",
  COVERAGE: "覆盖率",
  TURNOVER: "换手",
  "Economic hypothesis": "经济学假设",
  Mechanism: "机制",
  "EXPECTED DIRECTION": "预期方向",
  "Signal construction": "信号构建",
  "Falsification criteria": "证伪条件",
  "No explicit criterion registered.": "未登记明确证伪条件。",
  "Yearly Rank IC": "年度 Rank IC",
  "CATALOG ID": "目录 ID",
  ARTIFACT: "产物",
  PIT: "PIT",
  "BOUNDED MULTI-AGENT GOVERNANCE": "有边界的多智能体治理",
  "AI Council Chamber": "AI 委员会会议厅",
  "Candidate groups": "候选因子组",
  "Mechanism + deterministic diagnostics": "机制 + 确定性诊断",
  "MEDIAN RANK IC": "中位 Rank IC",
  "MAX CORR": "最大相关性",
  "Independent ballots": "独立投票",
  "Reviewer-level audit trail": "评审员级审计轨迹",
  "Independent reviewer": "独立评审员",
  CONFIDENCE: "置信度",
  "No historical vote for this newly eligible group.": "该新入选组尚无历史投票。",
  "Chair decision": "主席决策",
  SELECTED: "已选中",
  DISABLED: "已禁用",
  "ANNUALISED RETURN": "年化收益",
  "saved replay": "已保存回放",
  SHARPE: "夏普",
  "realised risk-adjusted": "已实现风险调整",
  "MAX DRAWDOWN": "最大回撤",
  "peak-to-trough": "峰谷回撤",
  "MAX ABS BETA": "最大 |β|",
  "after futures hedge": "期货对冲后",
  "Equity curve": "净值曲线",
  "Interactive saved replay": "交互式已保存回放",
  "COURSE DEMO · NOT ADVICE": "课程 Demo · 非投资建议",
  "Exposure & cost": "敞口与成本",
  "Deterministic controls": "确定性约束",
  "Mean gross exposure": "平均总敞口",
  "Total cost fraction": "累计成本占比",
  "Stock turnover": "股票换手",
  "Futures turnover": "期货换手",
  Interpretation: "解读",
  "What this run proves": "这条回放能证明什么",
  "No replay curve available.": "没有可用的回放曲线。",
  "No portfolio replay is available.": "没有可用的组合回放。",
  Aster: "Aster",
  "CSI 500": "CSI 500",
  NAV: "净值",
  DD: "回撤",
  "PARSED DOCUMENTS": "已解析文档",
  "GENERATED FACTOR ROWS": "生成因子行",
  "TOKEN USAGE": "Token 用量",
  "OCR QUEUE": "OCR 队列",
  "Annual batches": "年度批次",
  "Financial narrative dimensions": "财务叙事维度",
  SCORED: "已评分",
  Research: "研究",
  Showcase: "展示",
  WORKSPACE: "工作区",
  "AS OF": "截至",
  SYNC: "同步",
  "Live feed": "实时数据",
  "Snapshot unavailable": "快照不可用",
  "Booting research console": "正在启动研究控制台",
  "Loading the audited workspace snapshot…": "正在加载可审计的工作区快照…",
  "Close navigation": "关闭导航",
  "Close factor details": "关闭因子详情",
  "visible / ": "可见 / ",
  " total": " 总计",
  "No numeric progress reported": "未报告数值进度",
  "Not started": "未开始",
  "Management outlook": "管理层展望",
  "Demand strength": "需求强度",
  "Margin pressure": "毛利压力",
  "Capex intensity": "资本开支强度",
  "Risk level": "风险水平",
  "Forward-looking strategy and operating confidence": "前瞻战略与经营信心",
  "Evidence of product and market demand": "产品与市场需求证据",
  "Pricing, cost and impairment pressure": "定价、成本与减值压力",
  "Investment burden and expansion intensity": "投资负担与扩张强度",
  "Disclosed operating and balance-sheet risks": "披露的经营与资产负债表风险",
  "Market Regime": "市场状态",
  "Factor Evidence": "因子证据",
  "Risk & Data": "风险与数据",
  "Input cutoff": "输入截止日",
  "Council report": "委员会报告",
  "Latest report": "最新报告",
  "DETERMINISTIC OPTIMISATION + COUNCIL PROFILE": "确定性优化 + 委员会档位",
  "UNIFIED FACTOR CATALOG": "统一因子目录",
  "DOCUMENT → AI-FRIENDLY EVIDENCE → FACTOR ROWS": "文档 → AI 友好证据 → 因子行",
  "MONTHLY DEMO · beta 0.2 · tech-crash shorts": "月频 Demo · β0.2 · 做空科技",
  "QUARTERLY DEMO · beta 0.4": "季频 Demo · β0.4",
  "SHOWCASE DEMO · beta ±0.5": "展示 Demo · β±0.5",
  "passed lifecycle validation": "通过生命周期验证",
  "QuantaAlpha candidates": "QuantaAlpha 候选因子",
  "reports scored": "份报告已评分",
  "annualised return · disclosed run": "年化收益 · 已披露回放",
  "Rank IC": "Rank IC",
  "Data spine": "数据主干",
  "Filing intelligence": "公告智能",
  "AI factor mining": "AI 因子挖掘",
  "Canonical evaluation": "标准评估",
  "Factor Council": "因子委员会",
  "Portfolio replay": "组合回放",
  "QUARTERLY COUNCIL LAB": "季度委员会实验室",
  "Unified AI Council Replay": "统一 AI 委员会回放",
  "Each quarter runs two sequential agendas: factor selection first, then portfolio exposure and industry allocation. Challenge the combined package or accept it once.": "每个季度依次运行两个议程：先选因子，再定组合敞口与行业配置。可以质疑整包，也可以一次接受。",
  "Starting…": "启动中…",
  "Start interactive quarterly replay": "开始交互式季度回放",
  "Run automatic quarterly replay": "运行自动季度回放",
  "Factor Agenda selects the alpha inputs. Portfolio Agenda then sets the approved beta profile and industry tilts. One instruction reruns both prompts.": "因子议程选择 alpha 输入，组合议程随后设定获批的 β 档位与行业 tilt。一条指令会同时重跑两个 prompt。",
  "New session": "新会话",
  "Research-mode node: only evidence available by the recorded cutoff may influence either agenda.": "研究模式节点：只有记录截止日前可得的证据才能影响两个议程。",
  "Bounded profile, beta target and industry policy": "有边界的档位、β 目标与行业政策",
  PROFILE: "档位",
  STOCK: "股票",
  "TARGET β": "目标 β",
  TILT: "TILT",
  OVERWEIGHT: "超配",
  UNDERWEIGHT: "低配",
  "SHARED WEB EVIDENCE": "共享网页证据",
  "YOUR INSTRUCTION TO BOTH AGENDAS": "给两个议程的指令",
  "Example: Reconsider factor redundancy first, then reassess beta and industry concentration using the revised factor package.": "示例：先重新考虑因子冗余，再用修订后的因子包重估 β 与行业集中度。",
  "Rerun both agendas": "重跑两个议程",
  "Package accepted": "整包已接受",
  "Council deliberating…": "委员会审议中…",
  "Accept decision package": "接受决策包",
  "Next segment": "下一段",
  "Run segment": "运行该段",
  "Computing…": "计算中…",
  Ready: "就绪",
  "Live segment playback": "实时分段回放",
  Pause: "暂停",
  Play: "播放",
  sessions: "个交易日",
  "Run and play the accepted segment to reveal its path.": "运行并播放已接受的段，即可看到其路径。",
  "Human-guided two-agenda reconsideration": "人工引导的双议程重审",
  "AI quarterly package": "AI 季度决策包",
  Neutral: "中性",
  "CSI500 data, AI factor mining, mechanism review, portfolio optimisation and backtesting, in one auditable research surface.": "CSI500 数据、AI 因子挖掘、机制评审、组合优化与回测，汇聚在同一个可审计的研究界面。",
  "One research object, from economic hypothesis and canonical diagnostics to the Council lifecycle.": "从经济学假设、标准诊断到 Council 生命周期的统一研究对象。",
  "Three independent reviewers submit evidence-based votes; the Chair forms the final factor-group selection inside code constraints.": "三位独立 Reviewer 提交证据化投票，Chair 在代码约束内形成最终因子组选择。",
  "Mechanism review has been upgraded, but this page shows a historical Council run.": "机制评审已升级，但当前展示的是历史 Council 运行。",
  "The new packet carries mechanism fields; per-group mechanism ratings appear after the Council is re-run.": "新版 packet 已包含机制字段；重新运行 Council 后会出现逐组机制评级。",
  "NAV, drawdown, Beta and cost come from saved replayable runs; not a representation of future performance.": "净值、回撤、Beta 与成本来自保存的可重放运行；不代表未来投资表现。",
  "This curve shows that data, forecasting, optimisation, IC hedging and portfolio replay run under one audit contract. It is not a formal conclusion on strategy efficacy.": "这条曲线证明数据、预测、优化、IC 对冲和组合回放能够在同一套审计契约下运行。它不是对策略有效性的正式结论。",
  "Filing text is structurally parsed, citation-located and scored by DeepSeek, then converted into PIT factor records.": "财报原文经过结构化解析、引用定位和 DeepSeek 评分，最终转换为 PIT 因子记录。",
  "AI-NATIVE RESEARCH OPERATING SYSTEM": "AI 原生研究操作系统",
  "From raw evidence": "从原始证据",
  "to bounded decisions.": "到有边界的决策。",
  visible: "可见",
  total: "总计",
  PACKET: "PACKET",
  "FALLBACK USED": "使用回退",
  ACCEPTED: "已接受",
  confidence: "置信度",
  "SCORING LIVE": "评分中",
  COMPLETE: "完成",
  "parse failure": "解析失败",
  "five dimensions per successful report": "每份成功报告五个维度",
  "prompt + completion": "输入 + 输出",
  "documents requiring fallback": "需要回退的文档",
  "factor rows": "因子行",
  "2020-2025 completion ledger": "2020-2025 完成台账",
  "Structured AI output": "结构化 AI 输出",
  "ANNUAL REPORT BATCHES": "年报批次",
  "scoreable reports completed": "份可评分报告已完成",
  candidate: "候选",
  validated: "已验证",
  "demo selected": "Demo 入选",
};

const INDUSTRY_EN: Record<string, string> = {
  "货币金融服务": "Monetary financial services",
  "资本市场服务": "Capital market services",
  "其他金融业": "Other financial services",
  "医药制造业": "Pharmaceuticals",
  "食品制造业": "Food manufacturing",
  "农副食品加工业": "Agricultural food processing",
  "酒、饮料和精制茶制造业": "Beverages & refined tea",
  "计算机、通信和其他电子设备制造业": "Computers, communications & electronics",
  "软件和信息技术服务业": "Software & IT services",
  "互联网和相关服务": "Internet services",
  "电信、广播电视和卫星传输服务": "Telecom, broadcasting & satellite",
  "电力、热力生产和供应业": "Power & heat production",
  "燃气生产和供应业": "Gas production & supply",
  "水的生产和供应业": "Water production & supply",
  "煤炭开采和洗选业": "Coal mining & washing",
  "石油、煤炭及其他燃料加工业": "Oil, coal & fuel processing",
  "有色金属冶炼和压延加工业": "Non-ferrous metal smelting",
  "有色金属矿采选业": "Non-ferrous metal mining",
  "黑色金属冶炼和压延加工业": "Ferrous metal smelting",
  "黑色金属矿采选业": "Ferrous metal mining",
  "化学原料和化学制品制造业": "Chemicals",
  "化学纤维制造业": "Chemical fibres",
  "橡胶和塑料制品业": "Rubber & plastics",
  "非金属矿物制品业": "Non-metallic minerals",
  "金属制品业": "Metal products",
  "通用设备制造业": "General equipment",
  "专用设备制造业": "Special equipment",
  "电气机械和器材制造业": "Electrical machinery",
  "汽车制造业": "Automobiles",
  "铁路、船舶、航空航天和其他运输设备制造业": "Rail, ship & aerospace",
  "仪器仪表制造业": "Instruments & meters",
  "其他制造业": "Other manufacturing",
  "家具制造业": "Furniture",
  "造纸和纸制品业": "Paper & paper products",
  "文教、工美、体育和娱乐用品制造业": "Culture, sports & leisure goods",
  "纺织服装、服饰业": "Textiles & apparel",
  "土木工程建筑业": "Civil engineering",
  "建筑安装业": "Building installation",
  "建筑装饰、装修和其他建筑业": "Building decoration",
  "房地产业": "Real estate",
  "批发业": "Wholesale",
  "零售业": "Retail",
  "住宿业": "Accommodation",
  "餐饮业": "Catering",
  "道路运输业": "Road transport",
  "铁路运输业": "Rail transport",
  "水上运输业": "Water transport",
  "航空运输业": "Air transport",
  "多式联运和运输代理业": "Multimodal transport",
  "装卸搬运和仓储业": "Handling & warehousing",
  "邮政业": "Postal services",
  "电信、广播电视和卫星传输服务 ": "Telecom, broadcasting & satellite",
  "商务服务业": "Business services",
  "租赁业": "Leasing",
  "专业技术服务业": "Professional technical services",
  "研究和试验发展": "Research & development",
  "生态保护和环境治理业": "Environmental services",
  "公共设施管理业": "Public facility management",
  "新闻和出版业": "News & publishing",
  "广播、电视、电影和录音制作业": "Broadcasting, TV & film",
  "教育": "Education",
  "卫生": "Healthcare",
  "体育": "Sports",
  "农业": "Agriculture",
  "林业": "Forestry",
  "畜牧业": "Animal husbandry",
  "渔业": "Fishery",
  "农、林、牧、渔专业及辅助性活动": "Agriculture support services",
  "开采专业及辅助性活动": "Mining support services",
  "综合": "Conglomerates",
  Unknown: "Unknown",
};

export function localized(en?: string | null, zh?: string | null): string {
  const e = (en || "").trim();
  const z = (zh || "").trim();
  if (!e && !z) return "";
  if (current === "en") return e || z;
  if (current === "zh") return z || e;
  return [e, z].filter(Boolean).join("\n");
}

export function actionLabel(action: string): string {
  const labels: Record<string, string> = { enable: "启用", disable: "禁用", abstain: "弃权" };
  const zh = labels[action];
  if (current === "en" || !zh) return action;
  return current === "zh" ? zh : `${action} / ${zh}`;
}

export function factorCount(count: number): string {
  if (current === "zh") return `${count} 个因子`;
  const en = `${count} factor${count === 1 ? "" : "s"}`;
  return current === "dual" ? `${en} / ${count} 个因子` : en;
}

export function localizedList(en?: string[] | null, zh?: string[] | null): string[] {
  const e = en ?? [];
  const z = zh ?? [];
  if (current === "en") return e.length ? e : z;
  if (current === "zh") return z.length ? z : e;
  return [...e, ...z];
}

export function tr(text: string): string {
  if (current === "en") return text;
  const zh = ZH[text];
  if (!zh || zh === text) return text;
  return current === "zh" ? zh : `${text} / ${zh}`;
}

export function trIndustry(name: string): string {
  const en = INDUSTRY_EN[name];
  if (current === "en") return en ?? name;
  if (current === "zh") return name;
  return en ? `${name} / ${en}` : name;
}
