# Headless Autopilot - Fully Autonomous Mode

## ⚠️ WARNING

**This mode runs completely autonomously without human intervention.**

Only use headless mode after:
- ✅ **2+ weeks** of supervised mode operation
- ✅ **30+ days** of paper trading validation
- ✅ **Strict** promotion policy thresholds validated
- ✅ **External monitoring** configured
- ✅ **Kill switch** mechanism tested
- ✅ Starting with **small capital** (< 10% of portfolio)

---

## Overview

The **Headless Autopilot** is the final evolution of the automation system, removing all human approval gates while maintaining safety through:

1. **Multi-stage automated validation** (5+ checks before promotion)
2. **Hard-coded safety ceilings** (max position 30%, cannot be overridden)
3. **Adaptive risk management** (automatically tightens on poor performance)
4. **Automated error recovery** (handles failures gracefully)
5. **Remote kill switch** (instant emergency halt)
6. **External health reporting** (integrates with monitoring systems)

---

## Progression Path

```
Manual Mode → Supervised Mode → Headless Mode
(You are here)     (2-4 weeks)      (Production)
```

### Phase 1: Manual Mode (Week 1)
- Run `scripts/run_autopilot.py --run-once` daily
- Review all outputs manually
- No automation

### Phase 2: Supervised Mode (Weeks 2-4)
- Run `scripts/supervised_autopilot.py --schedule`
- Auto-approve training, manually approve promotions
- Build confidence in the system

### Phase 3: Headless Mode (Month 2+)
- Run `scripts/headless_autopilot.py --daemon`
- Fully autonomous operation
- Monitor alerts and health reports

**NEVER skip Phase 1 or Phase 2.**

---

## Safety Mechanisms

### 1. Multi-Stage Promotion Validation

Before auto-promoting a model, the system checks:

| Stage | Check | Threshold |
|-------|-------|-----------|
| 1 | Promotion policy gates | Sharpe ≥ 0.6, Drawdown ≤ 0.18 |
| 2 | Metric consistency | Win rate ≥ 0.5 OR Sharpe ≥ 0.8 |
| 3 | Overfitting detection | Test accuracy ≥ 85% of train accuracy |
| 4 | Return/drawdown ratio | Total return / max drawdown ≥ 2.0 |
| 5 | Minimum trade count | At least 30 trades (avoid lucky streaks) |

**All 5 stages must pass** for automatic promotion.

### 2. Hard-Coded Safety Ceilings

These limits are **hard-coded in `aistock/headless.py`** and cannot be overridden by configuration:

```python
HARD_CEILING_POSITION_FRACTION = 0.30  # Never allocate > 30% per position
HARD_CEILING_NOTIONAL_CAP = 500000     # Never > $500K per symbol
```

Even if the system proposes higher limits, these ceilings are enforced.

### 3. Adaptive Risk Management

The system automatically adjusts risk limits based on performance:

**Tightening Rules** (aggressive):
- Sharpe < 0.5 → Reduce position size by 20%
- Drawdown > 15% → Reduce position size by 20%
- Win rate < 45% → Reduce position size by 20%

**Expansion Rules** (conservative):
- Sharpe > 1.0 AND Drawdown < 10% AND Win rate > 55%
  → Increase position size by 3-5% (configurable: `max_risk_increase_pct`)

**Floor**: Never reduce below `min_risk_floor` (default: 10%)

### 4. Automated Error Recovery

| Failure Type | Recovery Strategy |
|--------------|-------------------|
| Data ingestion failure | Retry next cycle, alert |
| Training failure | Keep previous model, alert |
| Backtest failure | Skip promotion, alert |
| Max failures (3) | HALT automation, critical alert |

After 3 consecutive failures, the system halts and requires manual intervention.

### 5. Kill Switch

**File-based** (instant):
```bash
# Activate
touch state/KILL_SWITCH

# Or via CLI
python scripts/headless_autopilot.py config.json --kill
```

**Remote URL** (optional):
```json
{
  "headless": {
    "kill_switch_check_url": "https://your-service.com/kill_switch",
    "kill_switch_check_interval_seconds": 60
  }
}
```

The daemon checks every 60 seconds and halts immediately if kill switch is active.

### 6. External Health Reporting

Send health reports to external monitoring:

```json
{
  "headless": {
    "external_health_report_url": "https://your-monitoring.com/health",
    "health_report_interval_seconds": 300
  }
}
```

Reports include:
- System health (data staleness, risk breaches)
- Bars added, trades executed
- Model promotions, risk adjustments
- Kill switch status

---

## Configuration

### Minimal Headless Config

```json
{
  "headless": {
    "enable_auto_promotion": true,
    "enable_auto_risk_adjustment": true,
    "enable_auto_recovery": true,
    "promotion_validation_stages": 5,
    "max_risk_increase_pct": 0.03,
    "min_risk_floor": 0.10,
    "max_consecutive_failures": 3
  }
}
```

### Conservative Settings (Recommended for Production)

```json
{
  "headless": {
    "enable_auto_promotion": true,
    "enable_auto_risk_adjustment": true,
    "enable_auto_recovery": true,
    "promotion_validation_stages": 5,
    "max_risk_increase_pct": 0.01,      // 1% max increase per cycle
    "min_risk_floor": 0.15,             // Never below 15%
    "max_consecutive_failures": 2,       // Halt after 2 failures
    "auto_rollback_on_degradation": true,
    "degradation_threshold_pct": 0.05   // Rollback if 5% degradation
  }
}
```

### Aggressive Settings (Use at Your Own Risk)

```json
{
  "headless": {
    "enable_auto_promotion": true,
    "enable_auto_risk_adjustment": true,
    "enable_auto_recovery": true,
    "promotion_validation_stages": 3,
    "max_risk_increase_pct": 0.10,      // 10% max increase per cycle
    "min_risk_floor": 0.05,             // Allow 5% minimum
    "max_consecutive_failures": 5        // More tolerance for failures
  }
}
```

---

## Usage

### 1. Test Run (Single Execution)

```bash
python scripts/headless_autopilot.py configs/headless_autopilot_example.json --run-once
```

This will:
- ✅ Run full autopilot cycle
- ✅ Auto-promote models that pass validation
- ✅ Auto-adjust risk limits within ceilings
- ✅ Report all decisions to alerts

**Review the output carefully** before enabling daemon mode.

### 2. Daemon Mode (Fully Autonomous)

```bash
python scripts/headless_autopilot.py configs/headless_autopilot_example.json \
  --daemon \
  --interval-minutes 60
```

This runs every 60 minutes (or your configured interval), completely autonomously.

**Run in a process manager** (systemd, supervisord) or screen/tmux session:

```bash
# Using screen
screen -S headless
python scripts/headless_autopilot.py configs/headless_autopilot_example.json --daemon --interval-minutes 60
# Detach: Ctrl+A, D
```

### 3. Emergency Stop

```bash
# Activate kill switch
python scripts/headless_autopilot.py configs/headless_autopilot_example.json --kill

# Or manually
touch state/KILL_SWITCH
```

Daemon will halt on next cycle (within 60 seconds by default).

### 4. Resume After Kill

```bash
python scripts/headless_autopilot.py configs/headless_autopilot_example.json --unkill
```

---

## Monitoring

### File-Based Alerts

Check alerts regularly (or set up automated monitoring):

```bash
# Check critical alerts
ls -lht state/alerts/critical/

# Review latest critical alert
cat state/alerts/critical/$(ls -t state/alerts/critical/ | head -1)

# Check warnings
ls -lht state/alerts/warning/ | head -10
```

### External Monitoring Integration

#### Grafana Dashboard

Parse alert files and send metrics to Grafana:

```bash
#!/bin/bash
# Monitor critical alerts
CRITICAL_COUNT=$(ls state/alerts/critical/*.json 2>/dev/null | wc -l)
curl -X POST "http://grafana:9090/api/metrics" \
  -d "aistock_critical_alerts{instance=\"prod\"} $CRITICAL_COUNT"
```

#### Slack/PagerDuty Integration

Configure webhooks in config:

```json
{
  "supervision": {
    "notification_webhooks": {
      "slack": "https://hooks.slack.com/services/YOUR/WEBHOOK/URL",
      "pagerduty": "https://events.pagerduty.com/v2/enqueue"
    }
  }
}
```

Webhooks are called for **WARNING, ERROR, and CRITICAL** alerts automatically.

### Health Report API

If you set `external_health_report_url`, the system POSTs health reports every 5 minutes:

```json
{
  "timestamp": "2025-01-13T12:00:00Z",
  "healthy": true,
  "issues": [],
  "bars_added": 1440,
  "promotions": 1,
  "risk_adjustments": 0
}
```

Integrate this with your monitoring stack (Datadog, New Relic, etc.).

---

## Operational Runbook

### Daily Operations

**Morning (9:00 AM)**:
1. Check critical alerts: `ls state/alerts/critical/`
2. Review health reports (if external monitoring enabled)
3. Verify daemon is running: `ps aux | grep headless_autopilot`

**Mid-Day (12:00 PM)**:
1. Check if any promotions occurred: `cat state/promotion/manifest.json | tail -5`
2. Review risk adjustments in logs

**Evening (6:00 PM)**:
1. Review day's performance
2. Check for any warning alerts
3. Verify data ingestion completed

### Weekly Review

**Every Monday**:
1. Review audit log: `tail -500 state/audit/log.jsonl | jq .`
2. Analyze promotion history: `cat state/promotion/manifest.json | jq '.[] | select(.status=="approved")'`
3. Check risk limit trends
4. Verify external monitoring is operational

### Monthly Review

**First Monday of Each Month**:
1. Full backtest of active model
2. Review all promotions and rejections
3. Analyze risk adjustments (are limits drifting up or down?)
4. Test kill switch mechanism
5. Review failure recovery logs
6. Validate external health reports accuracy

---

## Incident Response

### Scenario 1: Kill Switch Triggered

**Symptoms**: Daemon logs "kill_switch_activated"

**Response**:
1. Investigate why kill switch was triggered
2. Check state/KILL_SWITCH file or remote kill switch logs
3. Review recent alerts (state/alerts/critical/)
4. Fix underlying issue
5. Deactivate kill switch: `python scripts/headless_autopilot.py config.json --unkill`
6. Resume daemon

### Scenario 2: Max Consecutive Failures

**Symptoms**: Daemon halts with "max_failures_reached"

**Response**:
1. Check error logs: `tail -100 state/audit/log.jsonl | jq 'select(.action=="autopilot_failed")'`
2. Identify failure type (data ingestion, training, backtest)
3. Fix underlying issue (data source, model corruption, etc.)
4. Test with `--run-once` before resuming daemon
5. Reset failure counter by successful run

### Scenario 3: Performance Degradation

**Symptoms**: Alert "auto_rollback_on_degradation"

**Response**:
1. Review rolled-back model: `cat models/active/model.json`
2. Analyze why live performance degraded
3. Check if market regime changed
4. Investigate if model was overfitted
5. Consider retraining with more recent data

### Scenario 4: Unauthorized Risk Increase

**Symptoms**: Position sizes larger than expected

**Response**:
1. Check risk adjustment logs: `grep "risk_limits_adjusted" state/audit/log.jsonl`
2. Verify limits are within hard ceilings (30% max)
3. If limits exceeded ceiling → **CRITICAL BUG, halt immediately**
4. If within ceiling but undesired → Tighten `max_risk_increase_pct`
5. Manually revert risk limits in next config update

---

## Comparison: Supervised vs. Headless

| Feature | Supervised Mode | Headless Mode |
|---------|-----------------|---------------|
| **Model Promotion** | Requires human approval | Automatic (5-stage validation) |
| **Risk Adjustment** | Requires human approval | Automatic (within ceilings) |
| **Error Recovery** | Manual intervention | Automatic (up to 3 failures) |
| **Data Ingestion** | Automatic | Automatic |
| **Training** | Auto or manual (configurable) | Automatic |
| **Kill Switch** | Manual | File-based + Remote URL |
| **Monitoring** | File alerts | File alerts + External API |
| **Recommended For** | Testing, validation | Production (after validation) |

---

## Safety Checklist Before Enabling

- [ ] Supervised mode tested for **2+ weeks**
- [ ] Paper trading validation for **30+ days**
- [ ] Promotion policy thresholds **validated** (Sharpe ≥ 0.80, Drawdown ≤ 0.15)
- [ ] Hard-coded ceilings **reviewed** (max 30% position, max $500K notional)
- [ ] External monitoring **configured** (webhooks or health report API)
- [ ] Kill switch mechanism **tested** (both file and remote)
- [ ] Rollback procedures **tested**
- [ ] Starting with **< 10% of total portfolio capital**
- [ ] Operator available for **emergency response** (within 1 hour)
- [ ] Audit logs **retained** for compliance (7+ years)

---

## Troubleshooting

### "auto_promotion_rejected: stage3_failed_overfitting_suspected"

**Cause**: Test accuracy < 85% of train accuracy (overfitting indicator).

**Solution**:
- Increase training data size
- Add regularization (L1/L2)
- Simplify model (reduce features)
- Use cross-validation

### "risk_limits_adjusted: tightened_on_poor_performance"

**Cause**: Sharpe < 0.5 or drawdown > 15% or win rate < 45%.

**Solution**:
- Review recent trades for patterns
- Check if market regime changed
- Consider retraining model
- This is **expected behavior** (system is protecting you)

### "max_failures_reached: halted_automation"

**Cause**: 3 consecutive autopilot failures.

**Solution**:
1. Check logs for failure types
2. Fix underlying issues (data source, model, etc.)
3. Test with `--run-once`
4. Restart daemon once validated

### "kill_switch_check_failed: remote URL unreachable"

**Cause**: External kill switch URL is down.

**Solution**:
- Verify URL is correct
- Check network connectivity
- Fallback to file-based kill switch: `touch state/KILL_SWITCH`

---

## Limitations

Headless mode **does not** currently support:

❌ **Live broker feeds** (still CSV-based)
❌ **Multi-venue data** (forex/crypto API feeds)
❌ **Walk-forward ML validation** (requires model registry)
❌ **Partial fill handling** (assumes full fills)
❌ **Complex order types** (bracket, OCO, etc.)
❌ **Cross-asset risk management** (equities only)

These features are planned for Phase 4+ (see `docs/FULL_AUTOMATION_PLAN.md`).

---

## Summary

The Headless Autopilot provides **fully autonomous operation** while maintaining safety through:

✅ **Multi-stage validation** before promotion
✅ **Hard-coded safety ceilings** (cannot be overridden)
✅ **Adaptive risk management** (tightens aggressively, expands conservatively)
✅ **Automated error recovery** (up to 3 failures)
✅ **Remote kill switch** (instant emergency halt)
✅ **External monitoring** (integrates with your stack)

**Start small** (< 10% capital), **monitor closely** (daily alerts), and **scale gradually** (after 30+ days validation).

**Never enable headless mode without completing Phase 1 (Manual) and Phase 2 (Supervised) first.**

---

## Support

For issues or questions:
1. Check logs: `state/audit/log.jsonl`, `state/alerts/`
2. Activate kill switch: `python scripts/headless_autopilot.py config.json --kill`
3. Consult `docs/SUPERVISED_AUTOPILOT.md` for comparison
4. Review `docs/RUNBOOK.md` for operational procedures
