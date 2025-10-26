"""
Simple beginner-friendly GUI for AIStock Robot.

This interface is designed for users who:
- Are new to stock trading
- Want to use FSD (Full Self-Driving) mode
- Don't want to see complex configuration options
- Just want to "turn on the robot and relax"
"""

from __future__ import annotations

import json
import tkinter as tk
import tkinter.font as tkfont
from datetime import timezone
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Dict, List

from dataclasses import asdict

from .config import (
    BacktestConfig,
    BrokerConfig,
    ContractSpec,
    DataSource,
    EngineConfig,
    ExecutionConfig,
    StrategyConfig,
)
from .data import Bar, load_csv_directory
from .fsd import FSDConfig
from .logging import configure_logger
from .session import LiveTradingSession
from .setup import FirstTimeSetupWizard


class SimpleGUI:
    """
    Beginner-friendly interface with just 3 questions:
    1. How much money?
    2. Risk level?
    3. Click START!
    """

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("AIStock Robot - FSD Mode")
        self.root.geometry("900x700")
        self.root.configure(bg="#f5f7fb")

        self.logger = configure_logger("SimpleGUI", level="INFO", structured=False)

        self._init_fonts()
        self._configure_style()
        self._init_variables()

        # Check if first-time setup is needed
        self._run_first_time_setup_if_needed()

        self._build_layout()

        self.root.after(1000, self._update_dashboard)

    def _init_fonts(self) -> None:
        try:
            available = {name.lower() for name in tkfont.families(self.root)}
        except tk.TclError:
            available = set()

        default_family = tkfont.nametofont("TkDefaultFont").actual("family")
        if "segoe ui" in available:
            self.font_family = "Segoe UI"
        else:
            self.font_family = default_family

    def _font(self, size: int, *, weight: str = "normal") -> tuple[str, int] | tuple[str, int, str]:
        if weight == "normal":
            return (self.font_family, size)
        return (self.font_family, size, weight)

    def _configure_style(self) -> None:
        font_spec = f"{{{self.font_family}}} 11" if " " in self.font_family else f"{self.font_family} 11"
        self.root.option_add("*Font", font_spec)
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        # Large button for START
        style.configure("Start.TButton", font=self._font(18, weight="bold"), padding=20)
        style.map(
            "Start.TButton",
            background=[("!disabled", "#00c853"), ("pressed", "#00a043")],
            foreground=[("!disabled", "white")]
        )

        # Stop button
        style.configure("Stop.TButton", font=self._font(14, weight="bold"), padding=12)
        style.map(
            "Stop.TButton",
            background=[("!disabled", "#ff1744"), ("pressed", "#d50000")],
            foreground=[("!disabled", "white")]
        )

        # Advanced button
        style.configure("Advanced.TButton", font=self._font(10), padding=8)
        style.map(
            "Advanced.TButton",
            background=[("!disabled", "#e0e0e0"), ("pressed", "#bdbdbd")],
            foreground=[("!disabled", "#424242")]
        )

    def _init_variables(self) -> None:
        # Simple user inputs
        self.capital_var = tk.StringVar(value="200")
        self.risk_level_var = tk.StringVar(value="conservative")
        self.investment_goal_var = tk.StringVar(value="steady_growth")
        self.max_loss_per_trade_var = tk.StringVar(value="5")  # percentage
        self.trade_deadline_enabled_var = tk.BooleanVar(value=False)
        self.trade_deadline_minutes_var = tk.StringVar(value="60")  # minutes

        # Default configurations (hidden from user)
        self.data_folder = "data/historical"  # Use historical data for warmup
        # FSD Auto-Discovery: Scan ALL available stocks, let AI choose best ones
        self.symbols = self._discover_available_symbols()

        # Session state
        self.session: LiveTradingSession | None = None
        self.simulated_bars: List[Bar] = []
        self.sim_index = 0
        self.sim_running = False

        # Dashboard metrics
        self.balance_var = tk.StringVar(value="$0.00")
        self.profit_var = tk.StringVar(value="$0.00")
        self.status_var = tk.StringVar(value="🤖 Ready to start")
        self.activity_text: tk.Text | None = None

    def _discover_available_symbols(self) -> list[str]:
        """
        FSD Auto-Discovery: Scan data directory for all available stocks.

        The AI will autonomously choose which ones to trade based on:
        - User's risk preferences (Conservative/Moderate/Aggressive)
        - Liquidity (volume)
        - Price range
        - Volatility characteristics

        Returns:
            List of all available stock symbols (e.g., ['AAPL', 'MSFT', ...])
        """
        data_dir = Path(self.data_folder)

        if not data_dir.exists():
            self.logger.warning("data_directory_not_found", extra={"path": str(data_dir)})
            # Fallback to default symbols if directory doesn't exist
            return ["AAPL", "MSFT", "GOOGL"]

        # Scan for all CSV files in data directory
        csv_files = list(data_dir.glob("*.csv"))

        if not csv_files:
            self.logger.warning("no_csv_files_found", extra={"path": str(data_dir)})
            return ["AAPL", "MSFT", "GOOGL"]

        # Extract symbol names from filenames (e.g., "AAPL.csv" -> "AAPL")
        symbols = [f.stem for f in csv_files if f.stem != ".gitkeep"]

        self.logger.info(
            "fsd_auto_discovery_complete",
            extra={
                "symbols_found": len(symbols),
                "symbols": symbols[:10],  # Log first 10 for brevity
                "total_available": len(symbols)
            }
        )

        return symbols

    def _run_first_time_setup_if_needed(self) -> None:
        """Run first-time setup wizard if needed."""
        wizard = FirstTimeSetupWizard()

        if not wizard.needs_setup():
            self.logger.info("first_time_setup_not_needed")
            return

        # Show progress dialog
        setup_dialog = tk.Toplevel(self.root)
        setup_dialog.title("First-Time Setup")
        setup_dialog.geometry("500x300")
        setup_dialog.transient(self.root)
        setup_dialog.grab_set()

        # Center the dialog
        setup_dialog.update_idletasks()
        x = (setup_dialog.winfo_screenwidth() // 2) - (500 // 2)
        y = (setup_dialog.winfo_screenheight() // 2) - (300 // 2)
        setup_dialog.geometry(f"500x300+{x}+{y}")

        # Setup dialog content
        header = tk.Label(
            setup_dialog,
            text="🎯 Welcome to AIStock Robot!",
            font=self._font(16, weight="bold"),
            pady=20
        )
        header.pack()

        message = tk.Label(
            setup_dialog,
            text="This is your first time running FSD mode.\nLet me set everything up for you...",
            font=self._font(11),
            justify=tk.CENTER
        )
        message.pack(pady=10)

        progress_label = tk.Label(
            setup_dialog,
            text="Initializing...",
            font=self._font(10)
        )
        progress_label.pack(pady=10)

        progress_bar = ttk.Progressbar(
            setup_dialog,
            length=400,
            mode='determinate'
        )
        progress_bar.pack(pady=10)

        def update_progress(msg: str, progress: float) -> None:
            """Update progress callback."""
            progress_label.config(text=msg)
            progress_bar['value'] = progress * 100
            setup_dialog.update()

        # Run setup in background
        def run_setup() -> None:
            try:
                success = wizard.run_setup(
                    progress_callback=update_progress,
                    symbols=self.symbols,
                    days=10
                )

                if success:
                    update_progress("✅ Setup complete! Starting AIStock...", 1.0)
                    self.root.after(1000, setup_dialog.destroy)
                else:
                    update_progress("⚠️ Setup failed - will use fallback mode", 1.0)
                    self.root.after(2000, setup_dialog.destroy)

            except Exception as exc:
                self.logger.error(f"Setup failed: {exc}")
                update_progress(f"❌ Error: {exc}", 1.0)
                self.root.after(2000, setup_dialog.destroy)

        # Start setup after a brief delay
        self.root.after(500, run_setup)

    def _build_layout(self) -> None:
        # Header
        header = tk.Frame(self.root, bg="#1a237e", padx=24, pady=20)
        header.pack(fill=tk.X)
        tk.Label(
            header,
            text="🤖 AIStock Robot - Full Self-Driving",
            font=self._font(24, weight="bold"),
            fg="white",
            bg="#1a237e",
        ).pack()
        tk.Label(
            header,
            text="Turn on AI trading and let the robot do everything!",
            font=self._font(13),
            fg="#c5cae9",
            bg="#1a237e",
        ).pack(pady=(6, 0))

        # Main container
        main = ttk.Frame(self.root, padding=30)
        main.pack(fill=tk.BOTH, expand=True)

        # Question 1: How much money?
        q1_frame = ttk.LabelFrame(main, text="💰 How much money do you want to start with?", padding=20)
        q1_frame.pack(fill=tk.X, pady=(0, 20))

        money_frame = tk.Frame(q1_frame)
        money_frame.pack()
        tk.Label(money_frame, text="$", font=self._font(20, weight="bold")).pack(side=tk.LEFT, padx=(0, 5))
        money_entry = ttk.Entry(money_frame, textvariable=self.capital_var, font=self._font(20), width=12, justify=tk.CENTER)
        money_entry.pack(side=tk.LEFT)
        tk.Label(money_frame, text="dollars", font=self._font(14)).pack(side=tk.LEFT, padx=(10, 0))

        # Question 2: Risk level
        q2_frame = ttk.LabelFrame(main, text="📊 How much risk are you comfortable with?", padding=20)
        q2_frame.pack(fill=tk.X, pady=(0, 20))

        risk_options = [
            ("conservative", "🛡️ Conservative", "Safe & slow gains. Uses max 30% capital, tight stops."),
            ("moderate", "⚖️ Moderate", "Balanced approach. Uses max 50% capital, balanced risk."),
            ("aggressive", "🚀 Aggressive", "Risky & fast gains. Uses max 70% capital, loose stops."),
        ]

        for value, label, description in risk_options:
            radio_frame = tk.Frame(q2_frame, bg="white", relief=tk.RIDGE, borderwidth=1)
            radio_frame.pack(fill=tk.X, pady=5)

            rb = ttk.Radiobutton(
                radio_frame,
                text=label,
                variable=self.risk_level_var,
                value=value
            )
            rb.pack(anchor="w", padx=10, pady=5)

            tk.Label(
                radio_frame,
                text=description,
                font=self._font(9),
                fg="#666666",
                bg="white"
            ).pack(anchor="w", padx=30, pady=(0, 5))

        # Question 3: Investment goal
        q3_frame = ttk.LabelFrame(main, text="🎯 What's your investment goal?", padding=20)
        q3_frame.pack(fill=tk.X, pady=(0, 20))

        goal_options = [
            ("quick_gains", "⚡ Quick Gains", "Day trading style. AI trades frequently, exits quickly."),
            ("steady_growth", "📈 Steady Growth", "Swing trading style. AI holds positions longer for bigger moves."),
        ]

        for value, label, description in goal_options:
            radio_frame = tk.Frame(q3_frame, bg="white", relief=tk.RIDGE, borderwidth=1)
            radio_frame.pack(fill=tk.X, pady=5)

            rb = ttk.Radiobutton(
                radio_frame,
                text=label,
                variable=self.investment_goal_var,
                value=value
            )
            rb.pack(anchor="w", padx=10, pady=5)

            tk.Label(
                radio_frame,
                text=description,
                font=self._font(9),
                fg="#666666",
                bg="white"
            ).pack(anchor="w", padx=30, pady=(0, 5))

        # Question 4: Max loss per trade
        q4_frame = ttk.LabelFrame(main, text="🛑 Maximum loss you're okay with PER TRADE?", padding=20)
        q4_frame.pack(fill=tk.X, pady=(0, 20))

        loss_info = tk.Frame(q4_frame)
        loss_info.pack(fill=tk.X)

        tk.Label(
            loss_info,
            text="If a trade goes bad, stop it when I've lost:",
            font=self._font(11)
        ).pack(side=tk.LEFT, padx=(0, 10))

        loss_entry = ttk.Entry(loss_info, textvariable=self.max_loss_per_trade_var, font=self._font(14), width=6, justify=tk.CENTER)
        loss_entry.pack(side=tk.LEFT)

        tk.Label(loss_info, text="% of that trade", font=self._font(11)).pack(side=tk.LEFT, padx=(5, 0))

        tk.Label(
            q4_frame,
            text="💡 Example: With $200 capital, Conservative = $60 max deployed. If you trade $30 and set 5%, max loss = $1.50 per trade.",
            font=self._font(9),
            fg="#666666",
            wraplength=800,
            justify="left"
        ).pack(anchor="w", pady=(10, 0))

        # Question 5: Trade Deadline (Urgency Mode)
        q5_frame = ttk.LabelFrame(main, text="⏰ Do you need money within a specific time? (Optional)", padding=20)
        q5_frame.pack(fill=tk.X, pady=(0, 20))

        deadline_option1 = tk.Frame(q5_frame, bg="white", relief=tk.RIDGE, borderwidth=1)
        deadline_option1.pack(fill=tk.X, pady=5)

        no_rush_rb = ttk.Radiobutton(
            deadline_option1,
            text="⚪ No rush - Trade when opportunities are good",
            variable=self.trade_deadline_enabled_var,
            value=False,
            command=self._toggle_deadline_entry
        )
        no_rush_rb.pack(anchor="w", padx=10, pady=5)

        tk.Label(
            deadline_option1,
            text="FSD trades normally, no deadline pressure. May not trade if no good opportunities.",
            font=self._font(9),
            fg="#666666",
            bg="white"
        ).pack(anchor="w", padx=30, pady=(0, 5))

        deadline_option2 = tk.Frame(q5_frame, bg="white", relief=tk.RIDGE, borderwidth=1)
        deadline_option2.pack(fill=tk.X, pady=5)

        yes_deadline_rb = ttk.Radiobutton(
            deadline_option2,
            text="⚪ Yes - I need to make a trade within:",
            variable=self.trade_deadline_enabled_var,
            value=True,
            command=self._toggle_deadline_entry
        )
        yes_deadline_rb.pack(anchor="w", padx=10, pady=5)

        deadline_entry_frame = tk.Frame(deadline_option2, bg="white")
        deadline_entry_frame.pack(anchor="w", padx=30, pady=(5, 5))

        self.deadline_entry = ttk.Entry(deadline_entry_frame, textvariable=self.trade_deadline_minutes_var, font=self._font(14), width=8, justify=tk.CENTER, state=tk.DISABLED)
        self.deadline_entry.pack(side=tk.LEFT)

        tk.Label(deadline_entry_frame, text=" minutes", font=self._font(11), bg="white").pack(side=tk.LEFT, padx=(5, 0))

        tk.Label(
            deadline_option2,
            text="💡 FSD will try to trade normally, but if no opportunities appear, it becomes "
                 "more aggressive as the deadline approaches. Ensures you don't wait forever!",
            font=self._font(9),
            fg="#666666",
            bg="white",
            wraplength=750,
            justify="left"
        ).pack(anchor="w", padx=30, pady=(0, 5))

        # Start button
        button_frame = tk.Frame(main)
        button_frame.pack(pady=20)

        self.start_btn = ttk.Button(
            button_frame,
            text="🚀 START ROBOT (FSD Mode)",
            style="Start.TButton",
            command=self._start_robot
        )
        self.start_btn.pack()

        self.stop_btn = ttk.Button(
            button_frame,
            text="⏹️ STOP ROBOT",
            style="Stop.TButton",
            command=self._stop_robot
        )
        # Stop button is hidden initially

        # Advanced options button (small, at bottom)
        advanced_frame = tk.Frame(main)
        advanced_frame.pack(pady=10)
        ttk.Button(
            advanced_frame,
            text="⚙️ Advanced Options",
            style="Advanced.TButton",
            command=self._open_advanced
        ).pack()

        tk.Label(
            advanced_frame,
            text="(For power users who want full control)",
            font=self._font(9),
            fg="#666666"
        ).pack(pady=(5, 0))

        # Dashboard
        dashboard = ttk.LabelFrame(main, text="📊 Dashboard", padding=15)
        dashboard.pack(fill=tk.BOTH, expand=True, pady=(20, 0))

        metrics_frame = tk.Frame(dashboard)
        metrics_frame.pack(fill=tk.X, pady=(0, 15))

        # Balance
        balance_card = tk.Frame(metrics_frame, bg="#e3f2fd", relief=tk.RAISED, borderwidth=2)
        balance_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)
        tk.Label(balance_card, text="💵 Balance", font=self._font(11, weight="bold"), bg="#e3f2fd").pack(pady=(10, 0))
        tk.Label(balance_card, textvariable=self.balance_var, font=self._font(20, weight="bold"), bg="#e3f2fd", fg="#1565c0").pack(pady=(0, 10))

        # Profit
        profit_card = tk.Frame(metrics_frame, bg="#e8f5e9", relief=tk.RAISED, borderwidth=2)
        profit_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)
        tk.Label(profit_card, text="📈 Profit/Loss", font=self._font(11, weight="bold"), bg="#e8f5e9").pack(pady=(10, 0))
        self.profit_label = tk.Label(profit_card, textvariable=self.profit_var, font=self._font(20, weight="bold"), bg="#e8f5e9", fg="#2e7d32")
        self.profit_label.pack(pady=(0, 10))

        # Status
        status_card = tk.Frame(metrics_frame, bg="#fff3e0", relief=tk.RAISED, borderwidth=2)
        status_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)
        tk.Label(status_card, text="🤖 AI Status", font=self._font(11, weight="bold"), bg="#fff3e0").pack(pady=(10, 0))
        tk.Label(status_card, textvariable=self.status_var, font=self._font(12, weight="bold"), bg="#fff3e0", fg="#e65100", wraplength=200).pack(pady=(0, 10))

        # Activity log
        tk.Label(dashboard, text="Recent Activity:", font=self._font(11, weight="bold")).pack(anchor="w", pady=(10, 5))
        self.activity_text = tk.Text(dashboard, height=8, state=tk.DISABLED, wrap=tk.WORD, font=self._font(10))
        self.activity_text.pack(fill=tk.BOTH, expand=True)

        self._log_activity("🤖 Robot initialized and ready to trade")
        self._log_activity("💡 Select your starting capital and risk level, then click START!")

    def _get_risk_config(self, risk_level: str, investment_goal: str, max_loss_pct: float) -> dict:
        """
        Returns FSD configuration based on user preferences.

        Parameters are now TAILORED to user's exact preferences:
        - risk_level: How much capital to deploy
        - investment_goal: Trading frequency and hold time
        - max_loss_pct: Per-trade stop-loss
        """
        # Base configs by risk level
        base_configs = {
            "conservative": {
                "max_capital_pct": 0.30,  # Use max 30% of capital
                "time_limit": 60,  # 60 minutes max per session
                "learning_rate": 0.0005,
                "exploration_rate": 0.10,  # Less exploration = more conservative
                "confidence_threshold": 0.70,  # Higher threshold = more selective
                "min_liquidity_volume": 500000,  # High liquidity required
            },
            "moderate": {
                "max_capital_pct": 0.50,  # Use max 50% of capital
                "time_limit": 120,  # 2 hours
                "learning_rate": 0.001,
                "exploration_rate": 0.20,
                "confidence_threshold": 0.60,
                "min_liquidity_volume": 200000,
            },
            "aggressive": {
                "max_capital_pct": 0.70,  # Use max 70% of capital
                "time_limit": 180,  # 3 hours
                "learning_rate": 0.002,
                "exploration_rate": 0.35,  # More exploration = more aggressive
                "confidence_threshold": 0.50,  # Lower threshold = more trades
                "min_liquidity_volume": 100000,  # Accept lower liquidity
            },
        }

        config = base_configs.get(risk_level, base_configs["moderate"]).copy()

        # Adjust based on investment goal
        if investment_goal == "quick_gains":
            # Day trading style: shorter holds, more trades
            config["time_limit"] = int(config["time_limit"] * 0.5)  # Half the time
            config["confidence_threshold"] *= 0.9  # 10% lower threshold = more trades
            config["exploration_rate"] *= 1.2  # 20% more exploration
        else:  # steady_growth
            # Swing trading style: longer holds, fewer trades
            config["time_limit"] = int(config["time_limit"] * 1.5)  # 50% more time
            config["confidence_threshold"] *= 1.1  # 10% higher threshold = more selective
            config["exploration_rate"] *= 0.8  # 20% less exploration

        # Add per-trade stop-loss
        config["max_loss_per_trade_pct"] = max_loss_pct

        return config

    def _start_robot(self) -> None:
        if self.session is not None:
            messagebox.showwarning("Already Running", "The robot is already running! Stop it first before starting again.")
            return

        try:
            # Parse user inputs
            capital = float(self.capital_var.get())
            if capital <= 0:
                raise ValueError("Capital must be positive")

            risk_level = self.risk_level_var.get()
            investment_goal = self.investment_goal_var.get()
            max_loss_pct = float(self.max_loss_per_trade_var.get())
            trade_deadline_enabled = self.trade_deadline_enabled_var.get()
            trade_deadline_minutes = int(self.trade_deadline_minutes_var.get()) if trade_deadline_enabled else None

            risk_config = self._get_risk_config(risk_level, investment_goal, max_loss_pct)

            # Calculate max capital based on risk level
            max_capital = capital * risk_config["max_capital_pct"]

            self._log_activity(f"🚀 Starting FSD Robot with ${capital:.2f} capital")
            self._log_activity(f"📊 Risk Level: {risk_level.upper()}")
            self._log_activity(f"🎯 Goal: {'QUICK GAINS (day trading)' if investment_goal == 'quick_gains' else 'STEADY GROWTH (swing trading)'}")
            self._log_activity(f"🛡️ AI will use up to ${max_capital:.2f} (max {risk_config['max_capital_pct']*100:.0f}%)")
            self._log_activity(f"🛑 Max loss per trade: {max_loss_pct}%")

            if trade_deadline_enabled and trade_deadline_minutes:
                self._log_activity(f"⏰ Trade Deadline: MUST make a trade within {trade_deadline_minutes} minutes")
                self._log_activity(f"💪 FSD will get more aggressive as deadline approaches if no trades made")

            # Build configuration
            data_source = DataSource(
                path=self.data_folder,
                timezone=timezone.utc,
                symbols=self.symbols,
                warmup_bars=50,
            )

            strategy_cfg = StrategyConfig(
                short_window=8,
                long_window=21,
                ml_enabled=True,
                ml_model_path="models/ml_model.json",
                ml_feature_lookback=30,
            )

            engine = EngineConfig(
                strategy=strategy_cfg,
                initial_equity=capital,
                commission_per_trade=0.0,
                slippage_bps=5.0,
            )

            contracts = {
                symbol: ContractSpec(
                    symbol=symbol,
                    sec_type="STK",
                    exchange="SMART",
                    currency="USD",
                )
                for symbol in self.symbols
            }

            broker = BrokerConfig(
                backend="paper",  # Always use paper mode for beginners
                ib_host="127.0.0.1",
                ib_port=7497,
                ib_client_id=1001,
                ib_account=None,
                contracts=contracts,
            )

            execution = ExecutionConfig(slip_bps_limit=5.0)
            config = BacktestConfig(data=data_source, engine=engine, execution=execution, broker=broker)

            # Build FSD config with ALL user preferences
            fsd_config = FSDConfig(
                max_capital=max_capital,
                time_limit_minutes=risk_config["time_limit"],
                learning_rate=risk_config["learning_rate"],
                exploration_rate=risk_config["exploration_rate"],
                initial_confidence_threshold=risk_config["confidence_threshold"],
                min_liquidity_volume=risk_config["min_liquidity_volume"],
                state_save_path=f"state/fsd/simple_gui_{risk_level}_{investment_goal}.json",
                ml_model_path="models/ml_model.json",  # Use trained ML model if available
                trade_deadline_minutes=trade_deadline_minutes,  # Trade deadline (urgency mode)
                trade_deadline_stress_enabled=True,  # Enable stress threshold lowering
            )

            self._log_activity(f"⚙️ AI Config: Confidence={risk_config['confidence_threshold']:.0%}, Exploration={risk_config['exploration_rate']:.0%}")
            self._log_activity(f"📊 Min Liquidity: {risk_config['min_liquidity_volume']:,} volume required")

            # Create session
            self.session = LiveTradingSession(config, mode="fsd", fsd_config=fsd_config)

            # Load historical data for warmup
            self._log_activity("📚 Loading historical data for FSD warmup...")
            data_map = load_csv_directory(config.data, config.engine.data_quality)

            # FSD Warmup Phase: Learn from historical data BEFORE live trading
            self._log_activity("🧠 FSD Warmup Phase: Learning from historical patterns...")
            self.status_var.set("🧠 Warming up...")

            try:
                warmup_report = self.session.fsd_engine.warmup_from_historical(
                    historical_bars=data_map,
                    observation_fraction=0.5  # 50% observation, 50% simulation
                )

                self._log_activity(f"✅ Warmup Complete!")
                self._log_activity(f"  📊 Processed {warmup_report['total_bars_processed']} bars")
                self._log_activity(f"  🎯 Simulated {warmup_report['simulated_trades']} trades")
                self._log_activity(f"  🧠 Learned {warmup_report['q_values_learned']} Q-values")
                self._log_activity(f"  📈 Simulated win rate: {warmup_report['simulated_win_rate']*100:.1f}%")

            except Exception as exc:
                self.logger.warning(f"Warmup failed: {exc}")
                self._log_activity(f"⚠️ Warmup skipped - will learn on-the-fly: {exc}")

            # Start live session
            self.session.start()

            # Start simulation
            self.simulated_bars = self._merge_bars(data_map)
            self.sim_index = 0
            self.sim_running = True
            self.root.after(250, self._step_simulation)

            self._log_activity("✅ Robot started successfully!")
            self._log_activity(f"🧠 AI is now ready with pre-trained knowledge!")
            self._log_activity(f"⏱️ Session will run for max {risk_config['time_limit']} minutes")

            self.status_var.set("🟢 TRADING")

            # Swap buttons
            self.start_btn.pack_forget()
            self.stop_btn.pack()

        except ValueError as e:
            messagebox.showerror("Invalid Input", f"Please enter a valid amount: {e}")
        except Exception as e:
            messagebox.showerror("Error Starting Robot", f"Failed to start: {e}")
            self._log_activity(f"❌ Error: {e}")
            if self.session:
                self.session.stop()
                self.session = None

    def _stop_robot(self) -> None:
        if self.session:
            self.session.stop()
            self.session = None

        self.sim_running = False
        self.simulated_bars.clear()

        self._log_activity("⏹️ Robot stopped")
        self.status_var.set("🔴 Stopped")

        # Swap buttons
        self.stop_btn.pack_forget()
        self.start_btn.pack()

    def _step_simulation(self) -> None:
        if not self.sim_running or self.session is None:
            return

        if self.sim_index >= len(self.simulated_bars):
            self._log_activity("✅ Simulation complete - reached end of data")
            self.sim_running = False
            self.status_var.set("✅ Complete")
            return

        bar = self.simulated_bars[self.sim_index]
        self.sim_index += 1
        self.session.process_bar(bar)

        self.root.after(250, self._step_simulation)

    def _update_dashboard(self) -> None:
        if self.session:
            try:
                snapshot = self.session.snapshot()

                # Update metrics
                equity = float(snapshot.get("equity", 0.0))
                initial_equity = float(self.capital_var.get() or 0.0)
                profit = equity - initial_equity

                self.balance_var.set(f"${equity:,.2f}")
                self.profit_var.set(f"${profit:+,.2f}")

                # Color profit label
                if profit > 0:
                    self.profit_label.config(fg="#2e7d32")  # Green
                elif profit < 0:
                    self.profit_label.config(fg="#c62828")  # Red
                else:
                    self.profit_label.config(fg="#616161")  # Gray

                # Check for trades
                trades = snapshot.get("trades", [])
                if trades:
                    latest_trade = trades[-1]
                    if latest_trade not in getattr(self, '_logged_trades', set()):
                        trade_pnl = latest_trade.get("realised_pnl", 0.0)
                        symbol = latest_trade["symbol"]
                        qty = latest_trade["quantity"]
                        price = latest_trade["price"]

                        emoji = "📈" if trade_pnl > 0 else "📉" if trade_pnl < 0 else "➡️"
                        self._log_activity(f"{emoji} AI traded: {qty:.2f} {symbol} @ ${price:.2f} | PnL: ${trade_pnl:+,.2f}")

                        if not hasattr(self, '_logged_trades'):
                            self._logged_trades = set()
                        self._logged_trades.add(latest_trade)

                # Update status with learning stats
                fsd = snapshot.get("fsd", {})
                total_trades = fsd.get("total_trades", 0)
                if total_trades > 0:
                    self.status_var.set(f"🟢 TRADING\n🧠 {total_trades} decisions made")

            except Exception as e:
                self.logger.error(f"Error updating dashboard: {e}")
        else:
            # Reset dashboard when not running
            capital = self.capital_var.get() or "0"
            try:
                self.balance_var.set(f"${float(capital):,.2f}")
            except ValueError:
                self.balance_var.set("$0.00")

            self.profit_var.set("$0.00")
            if self.status_var.get() not in ["🔴 Stopped", "✅ Complete"]:
                self.status_var.set("🤖 Ready to start")

        self.root.after(1000, self._update_dashboard)

    def _toggle_deadline_entry(self) -> None:
        """Enable/disable the deadline entry field based on selection."""
        if self.trade_deadline_enabled_var.get():
            self.deadline_entry.config(state=tk.NORMAL)
        else:
            self.deadline_entry.config(state=tk.DISABLED)

    def _log_activity(self, message: str) -> None:
        if not self.activity_text:
            return

        self.activity_text.configure(state=tk.NORMAL)
        self.activity_text.insert(tk.END, f"• {message}\n")
        self.activity_text.see(tk.END)
        self.activity_text.configure(state=tk.DISABLED)

    def _open_advanced(self) -> None:
        """Open the full advanced GUI."""
        response = messagebox.askyesno(
            "Advanced Mode",
            "Switch to Advanced Mode?\n\n"
            "This will close the simple interface and open the full control center "
            "with all configuration options, backtesting, ML training, and more.\n\n"
            "Are you sure you want to continue?"
        )

        if response:
            self.root.destroy()
            # Import and launch the full GUI
            from .gui import TradingGUI
            TradingGUI().run()

    @staticmethod
    def _merge_bars(data: Dict[str, List[Bar]]) -> List[Bar]:
        import itertools
        bars = list(itertools.chain.from_iterable(data.values()))
        bars.sort(key=lambda bar: bar.timestamp)
        return bars

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    SimpleGUI().run()


if __name__ == "__main__":
    main()
