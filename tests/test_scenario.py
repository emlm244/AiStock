import unittest
from datetime import datetime, timezone
from decimal import Decimal

from aistock.data import Bar
from aistock.scenario import GapScenario, ScenarioRunner


class ScenarioTests(unittest.TestCase):
    def test_gap_scenario(self):
        ts = datetime(2024, 1, 1, 9, 30, tzinfo=timezone.utc)
        bars = [
            Bar(symbol="AAPL", timestamp=ts, open=Decimal("100"), high=Decimal("101"), low=Decimal("99"), close=Decimal("100"), volume=1000),
            Bar(symbol="AAPL", timestamp=ts.replace(minute=31), open=Decimal("101"), high=Decimal("102"), low=Decimal("100"), close=Decimal("101"), volume=1000),
        ]
        scenario = GapScenario(name="gap_test", gap_percentage=Decimal("5"), bars_to_skip=0)
        runner = ScenarioRunner([scenario])
        result = runner.run({"AAPL": bars})
        modified = result["gap_test"]["AAPL"][0]
        self.assertNotEqual(modified.close, bars[0].close)


if __name__ == "__main__":
    unittest.main()
