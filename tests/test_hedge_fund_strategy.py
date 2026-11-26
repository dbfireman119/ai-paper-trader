import unittest

import pandas as pd

from hedge_fund_strategy import evaluate_candidates


class HedgeFundConsensusTests(unittest.TestCase):
    def setUp(self):
        self.rows = pd.DataFrame([
            {
                "code": "000001", "종목명": "상승후보", "시장": "KOSPI",
                "현재가": 1000, "등락률(%)": 1.0, "거래량비율": 2.0,
                "AI점수": 80, "거래가능": True, "추세값": 1.0,
                "모멘텀값": 1.0, "위험도": 0.2,
            },
            {
                "code": "000002", "종목명": "위험후보", "시장": "KOSDAQ",
                "현재가": 1000, "등락률(%)": 4.5, "거래량비율": 0.8,
                "AI점수": 55, "거래가능": True, "추세값": -1.0,
                "모멘텀값": -0.5, "위험도": 0.9,
            },
        ])

    def test_bull_bear_consensus_filters_risky_candidate(self):
        eligible, report = evaluate_candidates(self.rows)
        self.assertEqual(eligible["code"].tolist(), ["000001"])
        self.assertEqual(report.iloc[0]["펀드매니저판정"], "합의 통과")
        self.assertEqual(report.iloc[1]["펀드매니저판정"], "관찰/보류")

    def test_empty_input_is_safe(self):
        eligible, report = evaluate_candidates(self.rows.iloc[0:0])
        self.assertTrue(eligible.empty)
        self.assertTrue(report.empty)


if __name__ == "__main__":
    unittest.main()
