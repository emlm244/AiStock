from aistock.agent import ObjectiveThresholds
from aistock.audit import AuditConfig, AuditLogger
from aistock.brokers.management import (
    AllocationResult,
    BrokerReconciliationService,
    CapitalAllocationEngine,
    ContractRegistry,
)
from aistock.config import ContractSpec, RiskLimits


class StubBroker:
    def __init__(self, positions: dict[str, tuple[float, float]]):
        self._positions = positions

    def get_positions(self) -> dict[str, tuple[float, float]]:
        return self._positions


def test_contract_registry_persists(tmp_path):
    path = tmp_path / "contracts.json"
    registry = ContractRegistry(str(path))
    registry.register(ContractSpec(symbol="AAPL", exchange="NASDAQ", currency="USD"))

    # Reload to ensure persistence
    registry2 = ContractRegistry(str(path))
    assert "AAPL" in registry2.symbols()
    assert registry2.get("AAPL").exchange == "NASDAQ"


def test_capital_allocation_engine_respects_thresholds():
    risk = RiskLimits(
        max_position_fraction=0.25,
        per_symbol_notional_cap=50_000,
        max_single_position_units=500,
        per_trade_risk_pct=0.01,
    )
    engine = CapitalAllocationEngine(risk)
    thresholds = ObjectiveThresholds(max_position_fraction_cap=0.10)
    allocations = engine.build_allocations(
        equity=100_000,
        prices={"AAPL": 100.0},
        thresholds=thresholds,
    )
    result = allocations["AAPL"]
    assert result.max_units == 100.0  # 10% of equity -> 10_000 / 100
    assert result.per_trade_risk == 1000.0


def test_broker_reconciliation_detects_drift(tmp_path):
    registry = ContractRegistry(str(tmp_path / "contracts.json"))
    registry.register(ContractSpec(symbol="AAPL", exchange="NASDAQ"))

    audit = AuditLogger(AuditConfig(log_path=str(tmp_path / "audit.jsonl"), state_root=str(tmp_path / "state")))

    broker = StubBroker({"AAPL": (300.0, 150.0), "MSFT": (10.0, 200.0)})
    service = BrokerReconciliationService(broker, registry, audit_logger=audit, tolerance=0.1)
    allocations = {
        "AAPL": AllocationResult(symbol="AAPL", max_notional=20_000.0, max_units=200.0, per_trade_risk=800.0),
    }
    report = service.reconcile(["AAPL", "GOOG"], allocations)

    assert "GOOG" in report.missing_contracts
    assert any(drift.symbol == "AAPL" and drift.severity == "excess" for drift in report.position_drift)
    assert "MSFT" in report.orphan_positions
    assert report.recommendations, "Expected recommendations to be generated"

    # Audit log should contain reconciliation event
    tail = audit.tail(limit=1)
    assert tail and tail[0]["action"] == "broker_reconciliation"
