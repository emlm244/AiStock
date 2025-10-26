# Supervised Autopilot Guide

## Overview

The **Supervised Autopilot** is a safe, human-in-the-loop automation system that runs the AIStock pipeline on a schedule while requiring explicit approval for critical actions like model promotion and risk limit changes.

This system addresses the safety gaps in full automation while still providing significant time savings and operational efficiency.

---

## What It Does

### Automated Tasks
- ✅ **Data ingestion** - Fetches and validates new market data
- ✅ **ML model training** - Retrains models on fresh data (configurable auto-approval)
- ✅ **Backtesting** - Validates models against historical data
- ✅ **Calibration** - Derives risk thresholds from backtest results
- ✅ **Health monitoring** - Checks for data staleness, risk breaches, position drift
- ✅ **Alert generation** - File-based alerts + optional webhooks (Slack, email)

### Human Approval Required (Configurable)
- ⏸️ **Model promotion** - Deploying new models to active registry
- ⏸️ **Risk limit changes** - Modifying position size or leverage limits
- ⏸️ **Universe changes** - Adding or removing trading symbols

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                    SCHEDULED AUTOPILOT                        │
│  Runs every N minutes (configurable, e.g., hourly or daily)  │
└────────────────────────┬─────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────────┐
│                  SUPERVISED AUTOPILOT                         │
│  • Wraps AutoPilot with approval gates                       │
│  • Emits alerts for all decisions                            │
│  • Manages pending approvals                                 │
└────────────────────────┬─────────────────────────────────────┘
                         │
           ┌─────────────┼─────────────┐
           │             │             │
           ▼             ▼             ▼
     ┌─────────┐   ┌──────────┐  ┌────────────┐
     │AutoPilot│   │  Health  │  │  Approval  │
     │Pipeline │   │ Monitor  │  │   Gate     │
     └─────────┘   └──────────┘  └────────────┘
           │             │             │
           │             │             │
     ┌─────▼─────┐  ┌────▼────┐  ┌────▼────────┐
     │ Audit Log │  │ Alerts  │  │ Pending     │
     │ (JSONL)   │  │ (JSON)  │  │ Approvals   │
     └───────────┘  └─────────┘  └─────────────┘
```

---

## Quick Start

### 1. Create Configuration

Copy the example configuration:
```bash
cp configs/supervised_autopilot_example.json configs/my_autopilot.json
```

Edit `configs/my_autopilot.json` and configure:
- **Data source** - Where to fetch market data
- **Training parameters** - ML model hyperparameters
- **Risk limits** - Position sizing and leverage limits
- **Supervision settings** - Approval gates and alerting

Key supervision settings:
```json
{
  "supervision": {
    "auto_approve_training": true,
    "auto_approve_promotion": false,  // RECOMMENDED: false
    "schedule_interval_minutes": 60,  // Run every hour
    "data_staleness_hours": 24,
    "alert_dir": "state/alerts"
  }
}
```

### 2. Run Once (Manual Mode)

Test the autopilot with a single manual run:
```bash
python scripts/supervised_autopilot.py configs/my_autopilot.json --run-once
```

This will:
1. Run data ingestion
2. Train ML model (auto-approved if configured)
3. Run backtest
4. Calibrate risk thresholds
5. Check model promotion (requires approval if `auto_approve_promotion: false`)
6. Emit health check and alerts

### 3. Review Pending Approvals

List pending approval requests:
```bash
python scripts/supervised_autopilot.py configs/my_autopilot.json --list-approvals
```

Output example:
```
================================================================================
PENDING APPROVALS: 1
================================================================================

Request ID: a1b2c3d4-e5f6-7890-abcd-ef1234567890
  Action:    model_promotion
  Timestamp: 2025-01-13T10:30:00Z
  Context:   {
    "model_id": "model_20250113T103000",
    "metrics": {
      "sharpe": 0.82,
      "max_drawdown": 0.12,
      "win_rate": 0.61
    }
  }

  To approve: python scripts/supervised_autopilot.py configs/my_autopilot.json --approve a1b2c3d4-e5f6-7890-abcd-ef1234567890
  To reject:  python scripts/supervised_autopilot.py configs/my_autopilot.json --reject a1b2c3d4-e5f6-7890-abcd-ef1234567890 --notes 'reason'
```

### 4. Approve or Reject

Approve a model promotion:
```bash
python scripts/supervised_autopilot.py configs/my_autopilot.json \
  --approve a1b2c3d4-e5f6-7890-abcd-ef1234567890 \
  --operator alice \
  --notes "Metrics look good, approved for deployment"
```

Reject a model promotion:
```bash
python scripts/supervised_autopilot.py configs/my_autopilot.json \
  --reject a1b2c3d4-e5f6-7890-abcd-ef1234567890 \
  --operator bob \
  --notes "Sharpe ratio too low for live trading"
```

### 5. Run on Schedule (Daemon Mode)

Start the scheduled autopilot:
```bash
python scripts/supervised_autopilot.py configs/my_autopilot.json --schedule
```

This will:
- Run autopilot every `schedule_interval_minutes` (e.g., every 60 minutes)
- Continuously monitor health
- Emit alerts for issues (data staleness, risk breaches, etc.)
- Create pending approvals for critical actions

Press `Ctrl+C` to stop the scheduler.

**Production Tip:** Run this in a `screen` or `tmux` session, or use a process manager like `supervisord` or `systemd`.

---

## Health Monitoring

### Manual Health Check

Check system health at any time:
```bash
python scripts/supervised_autopilot.py configs/my_autopilot.json --health-check
```

Output example:
```json
{
  "timestamp": "2025-01-13T11:00:00Z",
  "healthy": false,
  "issues": [
    {
      "type": "data_staleness",
      "severity": "warning",
      "message": "No new data in 30.2 hours",
      "last_update": "2025-01-12T04:48:00Z"
    }
  ]
}
```

### Automatic Health Checks

When running in scheduled mode, health checks run automatically every `health_check_interval_seconds` (default: 300 seconds / 5 minutes).

Alerts are emitted to `state/alerts/` when issues are detected.

---

## Alert System

### File-Based Alerts

All alerts are written to `state/alerts/` organized by severity:

```
state/alerts/
├── info/
│   └── 20250113_103000_a1b2c3d4.json
├── warning/
│   ├── 20250113_110000_e5f6g7h8.json
│   └── 20250113_120000_i9j0k1l2.json
├── error/
│   └── 20250113_115000_m3n4o5p6.json
└── critical/
    └── 20250113_113000_q7r8s9t0.json
```

Each alert file contains:
```json
{
  "timestamp": "2025-01-13T11:00:00Z",
  "level": "warning",
  "message": "Data staleness detected",
  "context": {
    "hours_since_update": 30.2
  }
}
```

### Webhook Notifications (Optional)

Configure webhooks to receive alerts via Slack, email, or custom services:

```json
{
  "supervision": {
    "notification_webhooks": {
      "slack": "https://hooks.slack.com/services/YOUR/WEBHOOK/URL",
      "custom": "https://your-alerting-service.com/webhook"
    }
  }
}
```

Webhooks are called for **WARNING, ERROR, and CRITICAL** alerts (not INFO).

**Note:** Webhook HTTP POST requires the `requests` library, which is not included in the stdlib-only baseline. For now, webhooks are logged but not sent. To enable, install `requests` and uncomment the webhook code in `aistock/supervision.py`.

---

## Approval Workflow

### Approval Actions

The system supports approval gates for:

1. **Model Promotion** (`model_promotion`)
   - Triggered when a trained model passes policy gates
   - Context includes model ID, metrics (Sharpe, drawdown, win rate)
   - Default: Requires approval (`auto_approve_promotion: false`)

2. **Risk Limit Changes** (`risk_limit_change`)
   - Triggered when adaptive agent proposes risk tightening
   - Context includes old/new limits
   - Default: Requires approval (`auto_approve_risk_changes: false`)

3. **Universe Changes** (`universe_change`)
   - Triggered when symbols are added or removed
   - Context includes old/new symbol lists
   - Default: Requires approval (`auto_approve_universe_changes: false`)

4. **Strategy Parameter Changes** (`strategy_parameter_change`)
   - Triggered when adaptive agent proposes strategy updates
   - Context includes old/new parameters
   - Default: Requires approval (not currently implemented in AutoPilot)

### Approval Persistence

Approval requests are stored in `state/alerts/pending_approvals.json`:

```json
[
  {
    "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "action": "model_promotion",
    "timestamp": "2025-01-13T10:30:00Z",
    "context": {
      "model_id": "model_20250113T103000",
      "metrics": {"sharpe": 0.82, "max_drawdown": 0.12}
    },
    "status": "pending",
    "decided_at": null,
    "decided_by": null,
    "notes": null
  }
]
```

After approval/rejection:
```json
[
  {
    "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "action": "model_promotion",
    "timestamp": "2025-01-13T10:30:00Z",
    "context": {...},
    "status": "approved",
    "decided_at": "2025-01-13T10:35:00Z",
    "decided_by": "alice",
    "notes": "Metrics look good, approved for deployment"
  }
]
```

### Audit Trail

All approval decisions are logged to the audit log (`state/audit/log.jsonl`):

```json
{"timestamp": "2025-01-13T10:35:00Z", "action": "approval_granted", "actor": "alice", "details": {"request_id": "a1b2c3d4", "action": "model_promotion"}, "prev_hash": "abc123", "hash": "def456"}
```

---

## Configuration Reference

### Supervision Config Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `auto_approve_training` | bool | `false` | Auto-approve ML training without human review |
| `auto_approve_promotion` | bool | `false` | Auto-approve model promotion (⚠️ KEEP FALSE for production) |
| `auto_approve_risk_changes` | bool | `false` | Auto-approve risk limit adjustments |
| `auto_approve_universe_changes` | bool | `false` | Auto-approve symbol additions/removals |
| `alert_dir` | string | `"state/alerts"` | Directory for file-based alerts |
| `pending_approvals_path` | string | `"state/alerts/pending_approvals.json"` | JSON file for pending approvals |
| `schedule_interval_minutes` | int\|null | `null` | Run autopilot every N minutes (null = manual only) |
| `health_check_interval_seconds` | int | `300` | Health monitor check frequency (seconds) |
| `data_staleness_hours` | int | `24` | Alert if no new data in X hours |
| `position_reconciliation_tolerance_pct` | float | `1.0` | Alert if position drift > X% |
| `notification_webhooks` | dict | `{}` | Webhook URLs for external alerting |

### Recommended Settings

**Conservative (Manual Approval for Everything):**
```json
{
  "supervision": {
    "auto_approve_training": false,
    "auto_approve_promotion": false,
    "auto_approve_risk_changes": false,
    "auto_approve_universe_changes": false,
    "schedule_interval_minutes": null
  }
}
```

**Semi-Automated (Training Auto-Approved, Promotion Requires Approval):**
```json
{
  "supervision": {
    "auto_approve_training": true,
    "auto_approve_promotion": false,
    "auto_approve_risk_changes": false,
    "schedule_interval_minutes": 60
  }
}
```

**Aggressive (Auto-Approve All - NOT RECOMMENDED FOR PRODUCTION):**
```json
{
  "supervision": {
    "auto_approve_training": true,
    "auto_approve_promotion": true,
    "auto_approve_risk_changes": true,
    "schedule_interval_minutes": 60
  }
}
```

---

## Operational Best Practices

### 1. Start Conservative, Escalate Gradually

- **Week 1:** Run manually (`--run-once`), review all outputs, approve promotions carefully
- **Week 2-4:** Enable scheduled mode with `auto_approve_training: true`, but keep `auto_approve_promotion: false`
- **Month 2+:** Consider auto-approving promotions **only if** you have:
  - Robust promotion policy gates (strict Sharpe/drawdown thresholds)
  - Walk-forward validation
  - Live paper trading validation
  - Rollback procedures tested

### 2. Monitor Alerts Daily

Check `state/alerts/warning/`, `error/`, and `critical/` directories daily:

```bash
ls -lht state/alerts/warning/ | head -10
cat state/alerts/warning/20250113_110000_*.json
```

Integrate with your monitoring stack (Grafana, Datadog, etc.) or set up cron jobs to email you on critical alerts.

### 3. Review Audit Logs Weekly

```bash
tail -100 state/audit/log.jsonl | jq .
```

Verify:
- ✅ All promotions were approved by humans (if `auto_approve_promotion: false`)
- ✅ No unauthorized risk limit changes
- ✅ No unexpected universe changes

### 4. Test Rollback Procedures

Before enabling auto-promotion:

```bash
# Promote a model
python scripts/supervised_autopilot.py configs/my_autopilot.json --approve <request_id>

# Verify active model
cat models/active/model.json

# Rollback (manual process - see RUNBOOK.md)
# Copy previous model from models/archive/<previous_model_id>/model.json to models/active/
```

### 5. Set Up Kill Switches

Ensure your `RiskEngine` kill switches are configured:

```json
{
  "engine": {
    "risk": {
      "max_daily_loss_pct": 0.05,  // Halt if lose > 5% in a day
      "max_drawdown_pct": 0.15,    // Halt if drawdown > 15%
      "max_position_fraction": 0.25  // Never allocate > 25% to one position
    }
  }
}
```

Supervised autopilot respects these kill switches and will halt trading if breached.

---

## Troubleshooting

### "No new data ingested, skipping training"

**Cause:** No new bars added since last run.

**Solution:**
- Check data source is accessible
- Verify ingestion manifest: `cat state/ingestion/manifest.json`
- Run health check: `--health-check`
- Manually trigger data ingestion: `python scripts/run_autopilot.py configs/my_autopilot.json` (old script)

### "Model promotion rejected: sharpe_below_threshold"

**Cause:** Backtest Sharpe ratio < promotion policy threshold.

**Solution:**
- Review backtest results in autopilot state: `cat state/autopilot/state.json`
- Adjust promotion policy if thresholds are too strict
- Improve strategy parameters or ML features
- Run scenario analysis to understand model behavior

### "Health check failed: data_staleness"

**Cause:** No new data in > `data_staleness_hours`.

**Solution:**
- Check data provider is operational
- Verify data source configuration
- Review ingestion logs
- Adjust `data_staleness_hours` if this is expected (e.g., weekends, holidays)

### "ERROR: schedule_interval_minutes not configured"

**Cause:** Trying to run `--schedule` mode without setting `schedule_interval_minutes`.

**Solution:**
- Add `"schedule_interval_minutes": 60` to `supervision` section in config
- Or use `--run-once` for manual execution

---

## Integration with Existing Systems

### Cron (Alternative to Built-in Scheduler)

Instead of using `--schedule`, you can run via cron:

```bash
# Run every hour
0 * * * * cd /path/to/AiStock && python scripts/supervised_autopilot.py configs/my_autopilot.json --run-once >> logs/autopilot.log 2>&1
```

### Airflow / Prefect / Dagster

Create a DAG that calls the supervised autopilot CLI:

```python
from airflow import DAG
from airflow.operators.bash import BashOperator
from datetime import datetime, timedelta

dag = DAG(
    'aistock_autopilot',
    default_args={'retries': 1},
    schedule_interval=timedelta(hours=1),
    start_date=datetime(2025, 1, 13),
)

run_autopilot = BashOperator(
    task_id='run_supervised_autopilot',
    bash_command='cd /path/to/AiStock && python scripts/supervised_autopilot.py configs/my_autopilot.json --run-once',
    dag=dag,
)
```

### Monitoring Dashboards

Parse alert files and ingest into your monitoring system:

```bash
# Example: Send critical alerts to Slack via webhook
for alert in state/alerts/critical/*.json; do
  curl -X POST -H 'Content-Type: application/json' \
    -d @"$alert" \
    https://hooks.slack.com/services/YOUR/WEBHOOK/URL
done
```

---

## Security & Compliance

### Credential Management

Supervised autopilot inherits credential management from the base autopilot:

- **IBKR credentials:** Set via environment variables (`IBKR_ACCOUNT`, `IBKR_HOST`, `IBKR_PORT`)
- **Webhook URLs:** Stored in config file (ensure config is not committed to public repos)
- **Audit logs:** Hash-chained for tamper detection

### Approval Audit Trail

All approval decisions are recorded in:
1. **Pending approvals file** (`state/alerts/pending_approvals.json`)
2. **Audit log** (`state/audit/log.jsonl`)
3. **Promotion manifest** (`state/promotion/manifest.json`)

This triple redundancy ensures regulatory compliance and incident forensics.

### Access Control

Recommended access control:

- **Autopilot scheduler:** Read-only access to data, write access to `state/`
- **Human operators:** Read/write access to approval files, read-only audit logs
- **Production systems:** No write access to audit logs (append-only)

---

## Roadmap: What's Next

The current supervised autopilot provides Phase 1-2 automation. Future enhancements:

### Phase 3: Broker Automation (Paper Mode)
- Automatic broker contract sync (IBKR)
- Position reconciliation with auto-correction (after approval)
- Paper trading validation before live deployment

### Phase 4: Advanced Alerting
- Email/SMS notifications (via Twilio, SendGrid)
- PagerDuty integration for critical alerts
- Custom alert routing rules

### Phase 5: Multi-Asset Support
- Forex and crypto data feeds
- Per-asset-class approval gates
- Cross-asset risk management

### Phase 6: Walk-Forward Validation
- Archival datastore for model versioning
- Automated walk-forward backtests
- Feature/label provenance tracking

---

## Support & Troubleshooting

For issues or questions:
1. Check logs: `state/audit/log.jsonl`, `state/alerts/`
2. Run health check: `--health-check`
3. Review configuration: `cat configs/my_autopilot.json`
4. Consult RUNBOOK.md for operational procedures
5. Report issues at: https://github.com/anthropics/aistock/issues (if applicable)

---

## Summary

The Supervised Autopilot provides a **safe, incremental path to automation** by:

✅ Automating low-risk tasks (data ingestion, training, backtesting)
✅ Requiring human approval for high-risk tasks (model promotion, risk changes)
✅ Providing full audit trails and tamper-evident logs
✅ Emitting file-based alerts for monitoring
✅ Supporting scheduled execution with health monitoring

**Start conservatively** with manual approval for everything, then gradually enable auto-approval for tasks you're comfortable with.

**Never enable `auto_approve_promotion: true` in production without extensive testing in paper mode first.**
