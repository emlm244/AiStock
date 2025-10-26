import datetime
import tempfile
from pathlib import Path

from scripts.generate_synthetic_dataset import _generate_series, _write_csv


def test_generate_series_creates_monotonic_data():
    start = datetime.datetime(2020, 1, 2, tzinfo=datetime.timezone.utc)
    end = datetime.datetime(2020, 1, 10, tzinfo=datetime.timezone.utc)
    rows = _generate_series(
        symbol="TEST",
        start=start,
        end=end,
        step=datetime.timedelta(days=1),
        base_price=100.0,
        seed=42,
    )

    assert len(rows) == 9
    timestamps = [datetime.datetime.fromisoformat(row["timestamp"]) for row in rows]
    assert timestamps == sorted(timestamps)
    assert all(float(row["close"]) > 0 for row in rows)
    assert all(float(row["volume"]) >= 1000 for row in rows)


def test_write_csv_outputs_expected_headers():
    start = datetime.datetime(2020, 1, 2, tzinfo=datetime.timezone.utc)
    end = datetime.datetime(2020, 1, 3, tzinfo=datetime.timezone.utc)
    rows = _generate_series(
        symbol="ABC",
        start=start,
        end=end,
        step=datetime.timedelta(days=1),
        base_price=50.0,
        seed=1,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "ABC.csv"
        _write_csv(path, rows)
        contents = path.read_text().splitlines()
        assert contents[0] == "timestamp,open,high,low,close,volume"
        assert len(contents) == len(rows) + 1
