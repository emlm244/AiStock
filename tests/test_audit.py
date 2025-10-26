import json

from aistock.audit import AuditConfig, AuditLogger, ComplianceReporter, StateStore


def test_audit_logger_hash_chain(tmp_path):
    config = AuditConfig(
        log_path=str(tmp_path / "audit.jsonl"),
        state_root=str(tmp_path / "state"),
    )
    logger = AuditLogger(config)
    first = logger.append("ingest", "system")
    second = logger.append("train", "system")

    assert second["prev_hash"] == first["hash"]
    tail = logger.tail(limit=2)
    assert tail[-1]["hash"] == second["hash"]


def test_state_store_writes_payload(tmp_path):
    store = StateStore(str(tmp_path / "state"))
    path = store.write("ingestion", "manifest", {"entries": 1})
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["entries"] == 1


def test_compliance_reporter_summary(tmp_path):
    config = AuditConfig(
        log_path=str(tmp_path / "audit.jsonl"),
        state_root=str(tmp_path / "state"),
    )
    logger = AuditLogger(config)
    logger.append("event", "tester", details={"status": "ok"})
    reporter = ComplianceReporter(logger)
    summary = reporter.build_summary(limit=1)
    assert summary["count"] == 1
    assert summary["entries"][0]["action"] == "event"
