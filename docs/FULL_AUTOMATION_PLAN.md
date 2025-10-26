# Full Automation Plan

This document captures the system architecture needed to evolve AIStock from a semi‑automated research loop into a fully orchestrated, self-governing trading platform. The goal is to minimise human intervention while preserving transparency, safety, and regulatory compliance throughout the pipeline.

---

## 1. Data Acquisition Service

### Objectives
- Pull multi-asset OHLCV data continuously from vetted providers (broker APIs, official exchange feeds, or commercial datasets).
- Enforce data hygiene: duplicate suppression, gap detection, timezone normalisation, and quality thresholds.
- Persist raw and curated artefacts for reproducibility and audits.

### Proposed Architecture
```
Source API(s) ──► Fetcher ──► Raw Lake (immutable) ──► Validator ──► Curated Store
                             │                        │
                             └──► Metadata Logger  ───┘
```

1. **Fetcher**: Polls APIs on a schedule with provider-specific throttling and exponential backoff. Supports multiple asset classes, so it needs per-source configuration (tick size, session hours, rate limits). Adds trace metadata (request id, bytes fetched, checksum).
2. **Raw Lake**: Append-only filesystem or object store (e.g., `/data/raw/{source}/{symbol}/{date}.csv.gz`). Immutable storage ensures we can reproduce the exact dataset underpinning any decision.
3. **Validator**: Invokes the existing `DataIngestionService` to de-duplicate, merge, and manifest last-processed timestamps. Extended checks:
   - Gap detection vs. expected sampling frequency.
   - Volume/price sanity thresholds to flag anomalies.
   - Report generation (counts, gaps, QC warnings) pushed to observability system.
4. **Curated Store**: Structured directory used by research/backtest/ML services (`data/curated/{symbol}.csv`).
5. **Metadata Logger**: Writes ingestion stats to a tamper-proof log (e.g., append-only JSONL with signature or hashed backups) for audit.

### Interfaces
- YAML/JSON config listing sources, credentials, throttle windows.
- CLI: `python3 -m aistock.fetch --config configs/source_foo.yml --since 2024-01-01` (supports backfilling).
- Scheduler integration (cron, Airflow, etc.) to run fetcher + validator pipeline at defined intervals.

### Deployment Notes
- Run in isolated environment with restricted API keys.
- Provide configuration hooks for IP whitelisting, rotating credentials, and provider-specific heartbeats.

---

## 2. Model Promotion Pipeline

### Objectives
- Automatically retrain strategies against fresh curated data.
- Validate models via multi-horizon backtests, scenario stress tests, and statistical guardrails.
- Promote or rollback models based on approval policies.

### Workflow
1. **Training Service**
   - builds on the existing ML pipeline (`train_model`), now parameterised for multiple symbols, lookbacks, and alternative algorithms (e.g., logistic regression, gradient boosting).
   - version-tagged models stored with metadata (training window, features, hyperparameters, evaluation metrics).

2. **Validation Suite**
   - Batch run `BacktestRunner` across standard and stressed scenarios (volatility spikes, gaps, etc.).
   - Calculate calibration metrics via `calibrate_objectives` plus custom checks (max slippage, drawdown distribution).
   - Summarise results in a signed report (JSON + optional PDF) stored alongside the model artefact.

3. **Promotion Control**
   - Policy engine compares metrics against thresholds (Sharpe, drawdown, hit rate, scenario-specific criteria).
   - If all gates pass, copy model into the “live” registry (e.g., `models/active/model.json`) and update a promotion manifest.
   - If gates fail, trigger alerts (email/Slack) and keep current model active.
   - Optional multi-stage approvals: auto-promotion in paper accounts, manual sign-off for live trading.

4. **Rollback**
   - Track N latest approved models; allow quick revert if live metrics degrade (tie into adaptive agent’s monitoring).

### Artefacts
- `models/{id}/model.json`
- `models/{id}/report.json` (training/validation metadata)
- `models/active/model.json` (symlink or copy of promoted model)
- Promotion manifest including timestamp, operator id (if manual), metrics snapshot.

### Automation
- Integrate with the autopilot: after each successful run, automatically advance through training → validation → (if approved) promotion.
- Provide CLI + API endpoints for manual overrides and querying model history.

---

## 3. State, Audit, and Compliance Layer

### Objectives
- Make every adaptive decision, dataset change, and deployment step auditable.
- Store artefacts immutably (or with hash chains) to satisfy regulatory retention requirements.

### Components
1. **State Store**
   - Versioned storage for ingestion manifests, autopilot reports, calibration outputs, promoted models, and risk thresholds.
   - Suggested structure: `state/{yyyy-mm-dd}/{pipeline_step}/...`

2. **Audit Log**
   - Append-only log capturing: timestamp, action, actor (human or service), input artefacts, output artefacts, hash digests.
   - Implement simple JSONL + SHA256 chain (each entry signs previous hash) for tamper detection.
   - Optionally mirror logs to off-site storage or use a lightweight blockchain/notary service.

3. **Dashboard / Reports**
   - Generate daily or per-run summaries (ingestion stats, model health, risk threshold changes).
   - Surface via CLI command + optional static HTML report or integration with dashboards (Grafana, Kibana).

4. **Alerting**
   - Hook autopilot outcomes (success, validation failure, promotion, rollback) into notification channels (email, Slack, PagerDuty).

---

## 4. Broker Change Management

### Objectives
- Ensure live broker settings (contracts, subscriptions, account limits) stay consistent with the autopilot outputs.
- Enforce regulatory guardrails (capital allocations, leverage limits) automatically.

### Strategy
1. **Contract Registry**
   - YAML/JSON describing each asset class (equities, ETFs, futures, options, crypto, FX) with required IBKR fields (secType, exchange, currency, multiplier, trading hours).
   - Autopilot updates this registry when new symbols enter the curated universe.

2. **Capital Allocation Engine**
   - Given thresholds + risk limits, compute per-symbol notional caps, order sizes, and leverage allowances.
   - Emit `broker_config.json` consumed by live sessions.

3. **API Synchronisation**
   - Service that reconciles the local contract/risk view with broker API state (positions, contract details, margin settings).
   - Detect drift (e.g., missing contracts, misaligned currency, margin requirements) and either auto-correct or alert human operator.

4. **Regulatory Compliance**
   - Integrate checks for pattern day trading, regional disclosure requirements, market access restrictions (e.g., restricted securities lists).
   - Provide override mechanism for compliance officers.

5. **Resilience**
   - Maintain hot/warm standby configurations.
   - Implement graceful degradation (e.g., revert to known-good configuration on failure, pause trading when reconciliation fails).

---

## 5. Orchestration & Scheduling

### Objectives
- Execute the end-to-end pipeline deterministically on a schedule.
- Provide retries, failure notifications, and manual task triggers.

### Options
1. **Cron + Supervisors**
   - Simple: use OS cron jobs with scripts that trigger the autopilot, ingestion, and reconciliation services in sequence.
   - Add systemd or supervisord for long-running daemons (webhooks, API listeners).
2. **Airflow / Prefect / Dagster**
   - Declarative DAG capturing dependencies (“ingest raw” → “validate” → “train” → “backtest” → “promote” → “sync broker”).
   - Built-in retry policies, scheduling, and monitoring UI.
3. **Custom Scheduler (Python)**
   - Build a lightweight orchestrator inside `aistock.orchestration`, leveraging APScheduler or simple event loops. Useful if external orchestration isn’t available.

### Operational Flow (DAG Summary)
```
Ingest Raw Data
   │
   ├─► Validate / Curate
   │     └─► Update Manifest & QC Report
   │
   ├─► Train Model(s)
   │     └─► Evaluate / Stress Test
   │             ├─► Calibrate Thresholds
   │             └─► Generate Promotion Report
   │
   ├─► Promote Model? (gate)
   │     ├─► If pass: update live model registry
   │     └─► If fail: alert + rollback (no changes)
   │
   └─► Broker Sync (contracts, risk limits)
         └─► Persist Audit Artefacts & Notify
```

---

## Implementation Roadmap

To avoid brittle deployments, implement iteratively:

1. **Ingestion Service**
   - Build fetchers + raw lake integration.
   - Extend `DataIngestionService` for multi-asset QC, add CLI + scheduler hooks.
   - Unit + integration tests with synthetic APIs / fixtures.

2. **Model Promotion Pipeline**
   - Modularise training/validation; design promotion manifest.
   - Define automatic vs manual approval modes.
   - Implement rollback + model registry.

3. **Audit Layer**
   - Define audit log format and retention policy.
   - Integrate autopilot + promotion events into audit log.
   - Build report generators and CLI viewers.

4. **Broker Change Management**
   - Map asset policies to broker contracts + risk configs.
   - Implement reconciliation service with drift detection.
   - Connect to autopilot thresholds for automatic adjustments.

5. **Orchestration Integration**
   - Assemble DAG (cron or Airflow) with clear run-books.
   - Add monitoring/alerts for each step.

---

## Security & Compliance Considerations
- Rotate API and broker credentials regularly. Store secrets in environment managers or vaults, never in repo.
- Ensure all logs and artefacts include cryptographic hashes to detect tampering.
- Implement least-privilege IAM policies for services touching broker APIs.
- Provide kill switches: autopilot and live trading must abort safely if guardrails fail.
- Audit trail retention aligned with jurisdictional requirements (often ≥7 years).

---

## Next Steps
1. Review this plan with stakeholders (quant, compliance, operations).
2. Prioritise the iterative roadmap.
3. Stand up initial infrastructure (object storage, scheduler, secrets management).
4. Begin implementation starting with the data acquisition service, followed by the model promotion pipeline.

Once we agree on resource allocation and sequencing, we can start shipping these modules. Each milestone should deliver a deployable, well-tested component plus accompanying run-books so operators can monitor and intervene when necessary.
