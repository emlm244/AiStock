import json
from decimal import Decimal
from pathlib import Path

from aistock.engine import BacktestResult
from aistock.ml.pipeline import TrainingResult
from aistock.promotion import ModelPromotionService, PromotionConfig, PromotionPolicy


def _training_result(path: Path, name: str, train: float, test: float) -> TrainingResult:
    model_file = path / f"{name}.json"
    model_file.write_text(json.dumps({"name": name}))
    return TrainingResult(
        model_path=str(model_file),
        train_accuracy=train,
        test_accuracy=test,
        samples=200,
    )


def _backtest_result(sharpe: float = 0.8, drawdown: str = "0.10", total_return: str = "0.05", trades: int = 25) -> BacktestResult:
    return BacktestResult(
        trades=[],
        equity_curve=[],
        metrics={
            "sharpe": sharpe,
            "sortino": 0.7,
            "total_trades": trades,
        },
        max_drawdown=Decimal(drawdown),
        total_return=Decimal(total_return),
        win_rate=0.6,
    )


def test_promotion_approves_and_persists_model(tmp_path):
    config = PromotionConfig(
        registry_dir=str(tmp_path / "models"),
        active_model_path=str(tmp_path / "models" / "active" / "model.json"),
        manifest_path=str(tmp_path / "state" / "manifest.json"),
        policy=PromotionPolicy(),
    )
    service = ModelPromotionService(config)

    training = _training_result(tmp_path, "modelA", train=0.65, test=0.6)
    backtest = _backtest_result()

    decision = service.promote(training, backtest)

    assert decision.approved
    assert decision.model_id is not None
    assert decision.report_path is not None
    assert Path(decision.report_path).exists()

    active_path = Path(config.active_model_path)
    assert active_path.exists()
    assert json.loads(active_path.read_text()) == {"name": "modelA"}

    manifest = json.loads(Path(config.manifest_path).read_text())
    assert manifest[-1]["status"] == "approved"
    assert manifest[-1]["model_id"] == decision.model_id


def test_promotion_rejects_when_metrics_fail(tmp_path):
    config = PromotionConfig(
        registry_dir=str(tmp_path / "models"),
        active_model_path=str(tmp_path / "models" / "active" / "model.json"),
        manifest_path=str(tmp_path / "state" / "manifest.json"),
        policy=PromotionPolicy(),
    )
    service = ModelPromotionService(config)

    training = _training_result(tmp_path, "modelB", train=0.65, test=0.4)
    backtest = _backtest_result()

    decision = service.promote(training, backtest)

    assert not decision.approved
    assert decision.reason is not None
    assert "test_accuracy_below_threshold" in decision.reason

    active_path = Path(config.active_model_path)
    assert not active_path.exists()

    manifest = json.loads(Path(config.manifest_path).read_text())
    assert manifest[-1]["status"] == "rejected"
    assert manifest[-1]["model_id"] is None


def test_rollback_reverts_to_previous_model(tmp_path):
    import time

    config = PromotionConfig(
        registry_dir=str(tmp_path / "models"),
        active_model_path=str(tmp_path / "models" / "active" / "model.json"),
        manifest_path=str(tmp_path / "state" / "manifest.json"),
        policy=PromotionPolicy(),
    )
    service = ModelPromotionService(config)

    training_a = _training_result(tmp_path, "modelC", train=0.66, test=0.6)
    decision_a = service.promote(training_a, _backtest_result())

    # Small delay to ensure different timestamps (model_id is timestamp-based to the second)
    time.sleep(1.1)

    training_b = _training_result(tmp_path, "modelD", train=0.67, test=0.61)
    _ = service.promote(training_b, _backtest_result())

    active_path = Path(config.active_model_path)
    assert json.loads(active_path.read_text()) == {"name": "modelD"}

    rolled_back_id = service.rollback()
    assert rolled_back_id == decision_a.model_id
    assert json.loads(active_path.read_text()) == {"name": "modelC"}

    manifest = json.loads(Path(config.manifest_path).read_text())
    statuses = [entry["status"] for entry in manifest]
    assert statuses[-3:] == ["approved", "approved", "rollback"]
