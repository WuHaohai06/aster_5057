import unittest

from aster_data.filing_sources import (
    _clean_title,
    _exchange_for,
    _is_full_report,
    _matches_report_type,
)


class FilingSourceHelpersTest(unittest.TestCase):
    def test_title_filter_distinguishes_full_report_from_summary(self) -> None:
        self.assertTrue(_is_full_report("贵州茅台2024年年度报告"))
        self.assertFalse(_is_full_report("贵州茅台2024年年度报告摘要"))
        self.assertFalse(_is_full_report("贵州茅台2024年年度报告（英文版）"))

    def test_cninfo_highlight_markup_is_removed(self) -> None:
        self.assertEqual(_clean_title("2024年<em>年度报告</em>"), "2024年年度报告")

    def test_exchange_is_inferred_from_security_code(self) -> None:
        self.assertEqual(_exchange_for("600519"), "sse")
        self.assertEqual(_exchange_for("000001"), "szse")

    def test_report_type_filter_excludes_other_periodic_reports(self) -> None:
        self.assertTrue(_matches_report_type("贵州茅台2024年年度报告", "annual"))
        self.assertFalse(_matches_report_type("贵州茅台2025年第一季度报告", "annual"))
        self.assertTrue(_matches_report_type("平安银行2024年半年度报告", "semiannual"))


if __name__ == "__main__":
    unittest.main()
