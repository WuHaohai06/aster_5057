from aster_data.filing_factor_batch import fiscal_year


def test_fiscal_year_from_annual_report_title():
    assert fiscal_year("某公司2025年年度报告") == 2025
    assert fiscal_year("某公司2025年年度报告（修订版）") == 2025
    assert fiscal_year("某公司2025年半年度报告") is None
