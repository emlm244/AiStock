# Quick Integration Guide

## How to Integrate Production Improvements into main.py

### Step 1: Add Imports (Top of main.py, after line 78)

Add these imports after the existing imports:

```python
# --- Production Improvements ---
from utils.startup_helper import run_startup_checks
from utils.validation import ConfigValidator, ValidationError, InputValidator
from utils.data_quality import validate_market_data
from utils.emergency import EmergencyShutdownHandler, RecoveryManager
from utils.help_system import show_help
```

### Step 2: Add Startup Validation (line ~1360, inside `if __name__ == "__main__"`)

Replace the existing try block (starting around line 1362) with:

```python
    try:
        # --- RUN PRE-FLIGHT CHECKS ---
        # Determine if headless mode
        is_headless = args.headless if hasattr(args, 'headless') else False

        # Run comprehensive startup checks
        if not run_startup_checks(Settings(), headless=is_headless):
            print("\n❌ Startup checks failed. Please fix issues above.\n")
            sys.exit(1)

        # --- ORIGINAL CODE CONTINUES ---
        # Check if training mode requested
        if args.train:
            print("\nStarting ML Model Training...")
            # ... rest of existing code
```

### Step 3: Add Emergency Shutdown Handler to TradingBot (line ~96)

In `TradingBot.__init__()`, add after line 212:

```python
        # --- Emergency Shutdown Handler ---
        from utils.emergency import EmergencyShutdownHandler
        self.emergency_handler = EmergencyShutdownHandler(self.logger)
```

### Step 4: Add Data Quality Validation (line ~636, in finalize_historical_data)

In `TradingBot.finalize_historical_data()`, after line 678 (after hist_df cleaning), add:

```python
                    # --- Data Quality Validation ---
                    from utils.data_quality import validate_market_data
                    is_safe, dq_issues = validate_market_data(symbol, hist_df, self.settings, self.logger)

                    if not is_safe:
                        self.error_logger.error(f"Critical data quality issues detected for {symbol}")
                        # Log critical issues
                        critical_issues = [i for i in dq_issues if i.severity == "CRITICAL"]
                        for issue in critical_issues:
                            self.error_logger.error(f"  - {issue.message}")

                        # Optionally pause trading for this symbol
                        with self._lock:
                            self.symbol_trading_paused[symbol] = True

                        self.logger.warning(f"Trading paused for {symbol} due to data quality issues.")
```

### Step 5: Add Input Validation to User Prompts (line ~236, in prompt_user_config)

In `TradingBot.prompt_user_config()`, replace the instruments input section (around line 262):

```python
        elif not headless:
            # --- ORIGINAL CODE ---
            instr_prompt = f"Enter instruments (comma-separated, e.g., {','.join(default_instruments)}): "
            instr_input = input(instr_prompt).strip()

            if instr_input:
                # --- ADD VALIDATION ---
                from utils.validation import InputValidator
                raw_instruments = [inst.strip() for inst in instr_input.split(',') if inst.strip()]
                validated_instruments = []

                for inst in raw_instruments:
                    is_valid, cleaned_symbol, error_msg = InputValidator.validate_symbol_input(
                        inst, self.settings.TRADING_MODE
                    )

                    if is_valid:
                        validated_instruments.append(cleaned_symbol)
                    else:
                        print(f"  ⚠️  Skipping '{inst}': {error_msg}")

                if validated_instruments:
                    self.settings.TRADE_INSTRUMENTS = validated_instruments
                else:
                    print(f"  ℹ️  No valid instruments entered. Using defaults: {default_instruments}")
                    self.settings.TRADE_INSTRUMENTS = default_instruments
            else:
                self.settings.TRADE_INSTRUMENTS = default_instruments
```

### Step 6: Add Help Option to Menu (line ~1418, interactive menu)

In the interactive menu, replace:

```python
        print("\n" + "="*30 + "\n   AIStocker Options\n" + "="*30)
        print(" 1. Launch Trading Bot")
        print(" 2. Train ML Model")
        print(" 3. Exit")
        choice = input(" Enter your choice [1, 2, or 3]: ").strip()
```

With:

```python
        print("\n" + "="*30 + "\n   AIStocker Options\n" + "="*30)
        print(" 1. Launch Trading Bot")
        print(" 2. Train ML Model")
        print(" 3. Help & Documentation")  # NEW
        print(" 4. Exit")
        choice = input(" Enter your choice [1, 2, 3, or 4]: ").strip()
```

And add the handler:

```python
        elif choice == '3':  # NEW
            from utils.help_system import show_help
            show_help()

        elif choice == '4':  # WAS '3'
            print("Exiting.")
            startup_logger.info("User selected: Exit")
```

### Step 7: Use Emergency Shutdown in Critical Paths

In critical error handlers (e.g., line ~1072 in main_loop exception), replace `self.stop()` with:

```python
            except Exception as e:
                self.error_logger.critical(f"CRITICAL ERROR in main loop: {e}", exc_info=True)

                # Use emergency shutdown
                self.emergency_handler.execute_emergency_shutdown(
                    self,
                    reason=EmergencyShutdownHandler.REASON_CRITICAL_ERROR,
                    details=f"Critical error in main loop: {e}",
                    cancel_orders=True,
                    save_state=True
                )
                break
```

## Testing the Integration

1. **Run Diagnostics Only**:
   ```bash
   python -c "from utils.diagnostics import run_diagnostics; from config.settings import Settings; run_diagnostics(Settings())"
   ```

2. **Validate Configuration**:
   ```bash
   python -c "from utils.validation import ConfigValidator; from config.settings import Settings; errors = ConfigValidator.validate_settings(Settings()); print(f'Found {len(errors)} issues'); [print(e.format_message()) for e in errors]"
   ```

3. **Run Bot with Checks**:
   ```bash
   python main.py
   ```

## Minimal Integration (If You Want Simpler Start)

If you want to start with just the most critical improvements:

**Add only these 3 integrations:**
1. Step 2 (Startup validation) - Catches config issues before launch
2. Step 4 (Data quality) - Prevents trading on bad data
3. Step 7 (Emergency shutdown) - Safe shutdown on critical errors

The others can be added incrementally as you become comfortable.

## Verification

After integration, verify:

- ✅ Bot starts with diagnostic report
- ✅ Configuration is validated
- ✅ Invalid config shows helpful error messages
- ✅ Data quality is checked on historical data load
- ✅ Help menu is accessible
- ✅ Emergency shutdowns work properly

## Common Integration Issues

**Issue**: Import errors
**Fix**: Ensure all new files are in `utils/` directory

**Issue**: Validation too strict
**Fix**: Adjust thresholds in `ConfigValidator` class

**Issue**: Too many diagnostics
**Fix**: Set `headless=True` to skip interactive prompts

## Support

For issues, check:
- `IMPROVEMENTS.md` - Full documentation
- `CLAUDE.md` - Original system docs
- `logs/error_logs/errors.log` - Error details
