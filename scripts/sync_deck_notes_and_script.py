"""Sync slides 9-11 speaker notes and the CIO speech script with the new figures."""

from __future__ import annotations

import shutil
from pathlib import Path

from pptx import Presentation

ROOT = Path(r"D:\courses\5057\aster_develop")
DECK = ROOT / "slides/Aster_Group_7_Final_v2.pptx"
SCRIPT = ROOT / "slides/CIO_Speech_Script.txt"
BACKUP = ROOT / "slides/CIO_Speech_Script_backup_20261127.txt"

NOTES = {
    9: """Presenter: CIO · WU Haohai   |   Suggested time: 0:30
Script: slides/CIO_Speech_Script.txt

The setup: a CSI 500 A-share universe, hedged with CSI 500 (IC) index futures, benchmarked as a tactical-beta product between market-neutral and index-enhanced. Net exposure −50 to +20 percent, gross up to 166, with the council setting direction monthly and the book rebalanced every five trading days. The test runs 1,183 trading days from January 2022 to November 2026, on market data, point-in-time financials, filings and a 72-factor library, after stock and futures costs and contract rolls, before fund fees.

Source: data/curated/factor_library/catalog.json; data/portfolio/narrative_demo/narrative_monthly_v3.""",
    10: """Presenter: CIO · WU Haohai   |   Suggested time: 0:40
Script: slides/CIO_Speech_Script.txt

Outputs. 1,860 sell-side research reports and 4,350 annual reports read. The library now holds 72 factors, including 8 filing-derived factors; 44 QuantaAlpha factors were mined and validated. Efficient, high quality, large scale, multi-dimensional.

The call I care about is July 2026. With the tech complex rolling over, the council cut equity from 78 to 59 percent, lifted the hedge from 25 to 73, and ran a 10 percent underweight in computers, communications and general equipment. The CSI 500 fell 17 percent that month; the book returned 4.5 percent. Not a better forecast, a faster no.

Figures verified against catalog.json (72 total, 61 validated, 8 candidate, 44 QuantaAlpha) and the July 2026 report.

Source: data/curated/factor_library/catalog.json; data/portfolio/narrative_demo/narrative_monthly_v3/reports/2026-07-01.json.""",
    11: """Presenter: CIO · WU Haohai   |   Suggested time: 0:40
Script: slides/CIO_Speech_Script.txt

Backtest performance. 2022 to 2026: 12.5 percent a year, Sharpe 1.14, maximum drawdown 9.85 percent, trough March 2024. Over the same window the CSI 500 price index fell 16.66 percent and drew down 39.5 percent from its peak. The 2026 showcase returned 16.8 percent against the index −19.89, with a 6.58 drawdown.

The exposure behind those numbers: beta −0.07, average futures short 52.2 percent, gross never above 166, cash never below 15.2, turnover 14.7 times a year. This is a tactical-beta, actively hedged book. The 2026 figures are a disclosed showcase reenactment, not a live track record. Tang will now show the machinery.

Source: data/portfolio/narrative_demo/narrative_monthly_v3/run/metrics.json.""",
}

PAGE_9_10 = """PAGE 09  |  STRATEGY SCENARIO
Time: 0:30
=====================================================================

[EN]
The setup: a CSI 500 A-share universe, hedged with CSI 500 (IC) index futures, benchmarked as a tactical-beta product between market-neutral and index-enhanced. Net exposure −50 to +20 percent, gross up to 166, with the council setting direction monthly and the book rebalanced every five trading days. The test runs 1,183 trading days from January 2022 to November 2026, on market data, point-in-time financials, filings and a 72-factor library, after stock and futures costs and contract rolls, before fund fees.

[ZH]
设置是：中证 500 A 股股票池，用中证 500（IC）股指期货对冲，定位为战术 beta 产品，介于市场中性产品和指数增强产品之间。净敞口 −50% 到 +20%，总敞口最高 166%，委员会按月定方向，每五个交易日调仓。测试跑 1,183 个交易日，2022 年 1 月到 2026 年 11 月，用行情、PIT 财务数据、公告和 72 因子库；扣股票、期货成本和合约展期，未扣基金费用。

=====================================================================
PAGE 10  |  AI RESEARCH OUTPUTS
Time: 0:40
=====================================================================

[EN]
Outputs. 1,860 sell-side research reports and 4,350 annual reports read. The library now holds 72 factors, including 8 filing-derived factors; 44 QuantaAlpha factors were mined and validated. Efficient, high quality, large scale, multi-dimensional.

The call I care about is July 2026. With the tech complex rolling over, the council cut equity from 78 to 59 percent, lifted the hedge from 25 to 73, and ran a 10 percent underweight in computers, communications and general equipment. The CSI 500 fell 17 percent that month; the book returned 4.5 percent. Not a better forecast, a faster no.

[ZH]
产出。读了 1,860 份卖方研报、4,350 份年报。因子库现在有 72 个因子，其中 8 个来自公告；44 个 QuantaAlpha 因子经过挖掘和验证。高效、高质量、大量、多维度。

我最在意的是 2026 年 7 月那次判断。科技板块开始转弱时，委员会把股票从 78% 降到 59%，对冲从 25% 提到 73%，并对计算机、通信和通用设备低配 10%。那个月中证 500 跌了 17%，组合赚了 4.5%。不是预测更准，而是能更早说“不”。

=====================================================================
"""

PAGE_11 = """PAGE 11  |  BACKTEST PERFORMANCE
Time: 0:40
=====================================================================

[EN]
Backtest performance. 2022 to 2026: 12.5 percent a year, Sharpe 1.14, maximum drawdown 9.85 percent, trough March 2024. Over the same window the CSI 500 price index fell 16.66 percent and drew down 39.5 percent from its peak. The 2026 showcase returned 16.8 percent against the index −19.89, with a 6.58 drawdown.

The exposure behind those numbers: beta −0.07, average futures short 52.2 percent, gross never above 166, cash never below 15.2, turnover 14.7 times a year. This is a tactical-beta, actively hedged book. The 2026 figures are a disclosed showcase reenactment, not a live track record. Tang will now show the machinery behind it.

[ZH]
回测表现。2022 到 2026：年化 12.5%，夏普 1.14，最大回撤 9.85%，谷底在 2024 年 3 月。同一窗口，中证 500 价格指数跌了 16.66%，自身峰谷回撤 39.5%。2026 年 showcase 收益 16.8%，指数 −19.89%，回撤 6.58%。

这些数字背后的敞口：beta −0.07、平均期货空头 52.2%、总敞口最高 166%、现金最低 15.2%、换手一年 14.7 倍。这是一个主动对冲的战术 beta 账本；2026 的数字是披露过的 showcase 重演，不是实盘记录。接下来 Tang 会讲这套机器本身。

=====================================================================
"""


def main() -> int:
    if not BACKUP.exists():
        shutil.copy2(SCRIPT, BACKUP)
    presentation = Presentation(DECK)
    for number, text in NOTES.items():
        slide = presentation.slides[number - 1]
        slide.notes_slide.notes_text_frame.text = text
    try:
        presentation.save(DECK)
    except PermissionError as error:
        print(f"WARN deck locked, notes not saved: {error}")

    text = SCRIPT.read_text(encoding="utf-8")
    text = text.replace("Deck: Aster_Group_7_Final_v1.pptx", "Deck: Aster_Group_7_Final_v2.pptx")
    text = text.replace(
        "Last updated: 2026-11-26  (aligned to the current slides)",
        "Last updated: 2026-11-27  (aligned to Final_v2, slides 09-11)",
    )
    start = text.index("PAGE 09  |  STRATEGY SCENARIO")
    end = text.index("PAGE 11  |  BACKTEST PERFORMANCE")
    text = text[:start] + PAGE_9_10 + text[end:]
    start = text.index("PAGE 11  |  BACKTEST PERFORMANCE")
    end = text.index("Q&A PREP (not spoken)")
    text = text[:start] + PAGE_11 + text[end:]
    qa_old = """- "Why annualised 8.2% and not 25%?" 25.55% is cumulative over three years; 8.2% is per year.
- "What drawdown?" 5.14%, trough in December 2023.
- "Why 6% per name?" That was the research portfolio; the fund limit is 3%, which is why a compliant rerun is the next step.
- "Did AI produce these returns?" AI produced candidate signals and factors; the return figures come from the tested portfolio.
- "Was the Shanghai story a real fund?" A discretionary manager at a roadshow; the label is his, not ours."""
    qa_new = """- "Why annualised 12.5% and not 73.7%?" 73.7% is cumulative over five years; 12.5% is per year.
- "What drawdown?" 9.85%, trough in March 2024.
- "Is the 2026 number live?" No. It is a disclosed showcase reenactment with hindsight; the research-mode baseline is negative.
- "Why 6% per name?" That was the research portfolio; the fund limit is 3%, which is why a compliant rerun is the next step.
- "Did AI produce these returns?" AI produced candidate signals and factors; the return figures come from the tested portfolio.
- "Was the Shanghai story a real fund?" A discretionary manager at a roadshow; the label is his, not ours."""
    if qa_old not in text:
        print("WARN: Q&A block not matched")
    text = text.replace(qa_old, qa_new)
    SCRIPT.write_text(text, encoding="utf-8")
    print("notes and script updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
