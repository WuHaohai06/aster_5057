from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from aster_data.style_factors import STYLE_FACTOR_DEFINITIONS, build_style_factors


def test_style_factor_builder_emits_pit_canonical_rows(tmp_path: Path) -> None:
    dates = pd.bdate_range("2022-01-03", periods=340)
    instruments = ["SH000905", *[f"SH{600000 + index:06d}" for index in range(8)]]
    rows = []
    for instrument_index, instrument in enumerate(instruments):
        rng = np.random.default_rng(100 + instrument_index)
        returns = rng.normal(0.0002 + instrument_index * 0.00001, 0.012, len(dates))
        close = 100.0 * np.cumprod(1.0 + returns)
        volume = 1_000_000.0 * np.exp(rng.normal(0.0, 0.2, len(dates)))
        for date, price, amount in zip(dates, close, volume, strict=True):
            rows.append(
                {
                    "date": date,
                    "instrument": instrument,
                    "close": price,
                    "volume": amount,
                    "csi500_member": instrument != "SH000905",
                }
            )
    market_path = tmp_path / "market.parquet"
    pd.DataFrame(rows).to_parquet(market_path, index=False)
    result = build_style_factors(
        market_path=market_path,
        output_root=tmp_path / "style",
        sample_every=5,
    )
    frame = pd.read_parquet(result["path"])
    assert set(frame["factor_id"]) == set(STYLE_FACTOR_DEFINITIONS)
    assert set(frame["origin"]) == {"aster_style_factors"}
    assert (frame["available_at"] == frame["date"]).all()
    assert frame["instrument"].nunique() == 8
