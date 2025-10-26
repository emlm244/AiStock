from __future__ import annotations

import itertools
import json
import tkinter as tk
import tkinter.font as tkfont
from datetime import timezone
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
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
from .engine import BacktestRunner
from .fsd import FSDConfig
from .logging import configure_logger
from .ml.pipeline import train_model
from .scenario import GapScenario, MissingDataScenario, ScenarioRunner, VolatilitySpikeScenario
from .session import LiveTradingSession


class TradingGUI:
    """
    Rich desktop interface for the AIStock Robot.

    The application guides new users through each capability:
      1. Welcome dashboard explaining the trading workflow.
      2. Backtesting studio with strategy controls (including ML toggle).
      3. Scenario lab for stress testing.
      4. ML lab for training / loading models.
      5. Live trading console (paper or IBKR).
      6. Risk console and diagnostics.
    """

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("AIStock Robot – Control Center")
        self.root.geometry("1280x820")
        self.root.configure(bg="#f5f7fb")

        self.logger = configure_logger("GUI", level="INFO", structured=False)

        self._init_fonts()
        self._configure_style()
        self._init_variables()
        self._build_layout()

        self.root.after(1000, self._update_live_views)

    # ------------------------------------------------------------------
    # Initialisation helpers
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
        font_spec = f"{{{self.font_family}}} 10" if " " in self.font_family else f"{self.font_family} 10"
        self.root.option_add("*Font", font_spec)
        style = ttk.Style()
        # Use clam to get ttk themed widgets that respect custom colours.
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Heading.TLabel", font=self._font(16, weight="bold"))
        style.configure("Subheading.TLabel", font=self._font(13, weight="bold"))
        style.configure("Card.TFrame", padding=12)
        style.configure("Status.TLabel", font=self._font(10), foreground="#1a4d2e")
        style.configure("Feature.TLabel", font=self._font(11))
        style.configure("Info.TLabel", font=self._font(11), wraplength=760, justify="left")
        style.configure("Context.TFrame", background="#f5f7fb")
        style.configure("ContextTitle.TLabel", font=self._font(14, weight="bold"))
        style.configure("ContextBody.TLabel", font=self._font(11), wraplength=1120, justify="left")
        style.configure("Accent.TButton", font=self._font(11, weight="bold"))
        style.configure("Nav.TNotebook.Tab", font=self._font(11, weight="bold"))
        style.map("Accent.TButton", background=[("!disabled", "#1a73e8"), ("pressed", "#135cb3")], foreground=[("!disabled", "white")])
        style.configure("Secondary.TButton", font=self._font(10, weight="bold"))
        style.map(
            "Secondary.TButton",
            background=[("!disabled", "#e2ebff"), ("pressed", "#c5d7ff")],
            foreground=[("!disabled", "#1a3c7c")],
        )

    def _init_variables(self) -> None:
        # Backtest tab inputs
        self.backtest_data_var = tk.StringVar(value="data/historical")
        self.backtest_symbols_var = tk.StringVar(value="AAPL")
        self.backtest_equity_var = tk.StringVar(value="100000")
        self.backtest_short_var = tk.StringVar(value="8")
        self.backtest_long_var = tk.StringVar(value="21")
        self.backtest_warmup_var = tk.StringVar(value="20")
        self.backtest_enable_ml_var = tk.BooleanVar(value=False)
        self.backtest_ml_model_path_var = tk.StringVar(value="models/ml_model.json")
        self.backtest_output: tk.Text | None = None

        # Scenario tab
        self.scenario_tree: ttk.Treeview | None = None

        # ML lab inputs
        self.ml_data_var = tk.StringVar(value="data/historical")
        self.ml_symbols_var = tk.StringVar(value="AAPL")
        self.ml_model_path_var = tk.StringVar(value="models/ml_model.json")
        self.ml_lookback_var = tk.StringVar(value="30")
        self.ml_horizon_var = tk.StringVar(value="1")
        self.ml_epochs_var = tk.StringVar(value="200")
        self.ml_lr_var = tk.StringVar(value="0.01")
        self.ml_output: tk.Text | None = None

        # Live trading inputs
        self.live_backend_var = tk.StringVar(value="paper")
        self.live_mode_var = tk.StringVar(value="bot")  # "bot", "headless", or "fsd"
        self.live_data_var = tk.StringVar(value="data/live")
        self.live_symbols_var = tk.StringVar(value="AAPL")
        self.live_equity_var = tk.StringVar(value="50000")
        self.live_warmup_var = tk.StringVar(value="50")
        self.live_delay_var = tk.StringVar(value="250")
        self.live_slippage_var = tk.StringVar(value="5")
        self.live_enable_ml_var = tk.BooleanVar(value=True)
        self.live_ml_model_path_var = tk.StringVar(value="models/ml_model.json")

        # FSD mode configuration
        self.fsd_max_capital_var = tk.StringVar(value="10000")
        self.fsd_time_limit_var = tk.StringVar(value="5")
        self.fsd_learning_rate_var = tk.StringVar(value="0.001")
        self.fsd_exploration_rate_var = tk.StringVar(value="0.20")
        self.fsd_state_path_var = tk.StringVar(value="state/fsd/ai_state.json")

        # IBKR configuration
        self.ib_host_var = tk.StringVar(value="127.0.0.1")
        self.ib_port_var = tk.StringVar(value="7497")
        self.ib_client_var = tk.StringVar(value="1001")
        self.ib_account_var = tk.StringVar(value="")
        self.ib_sec_type_var = tk.StringVar(value="STK")
        self.ib_exchange_var = tk.StringVar(value="SMART")
        self.ib_currency_var = tk.StringVar(value="USD")

        # Widgets populated later
        self.positions_tree: ttk.Treeview | None = None
        self.trades_tree: ttk.Treeview | None = None
        self.risk_labels: Dict[str, tk.Label] = {}
        self.fsd_labels: Dict[str, tk.Label] = {}
        self.log_text: tk.Text | None = None

        # Session state
        self.session: LiveTradingSession | None = None
        self.simulated_bars: List[Bar] = []
        self.sim_index = 0
        self.sim_running = False
        self.live_show_advanced_var = tk.BooleanVar(value=False)

        # Status bar
        self.status_var = tk.StringVar(value="Ready")

        # Context + navigation helpers
        self.context_title_var = tk.StringVar(value="Control Center Overview")
        self.context_body_var = tk.StringVar(
            value="Select any tab to see what it does, why it matters, and how to get started."
        )
        self.tab_details: Dict[tk.Widget, dict[str, object]] = {}
        self.tabs: Dict[str, tk.Widget] = {}
        self.tour_steps: List[dict[str, object]] = []
        self.tour_index = 0

    # ------------------------------------------------------------------
    def _build_layout(self) -> None:
        hero = tk.Frame(self.root, bg="#102a43", padx=24, pady=18)
        hero.pack(fill=tk.X)

        hero_header = tk.Frame(hero, bg="#102a43")
        hero_header.pack(fill=tk.X)

        tk.Label(
            hero_header,
            text="AIStock Robot Control Center",
            font=self._font(20, weight="bold"),
            fg="white",
            bg="#102a43",
        ).pack(side=tk.LEFT)

        ttk.Button(
            hero_header,
            text="🎯 Switch to Simple Mode",
            command=self._switch_to_simple_mode,
        ).pack(side=tk.RIGHT, padx=(10, 0))

        tk.Label(
            hero,
            text="A guided workspace that explains each trading capability while you explore backtests, stress tests, machine learning, and live execution.",
            font=self._font(12),
            fg="#c8d6ff",
            bg="#102a43",
            wraplength=1080,
            justify="left",
        ).pack(anchor="w", pady=(6, 0))

        context_frame = ttk.Frame(self.root, style="Context.TFrame", padding=(20, 14))
        context_frame.pack(fill=tk.X)
        context_header = ttk.Frame(context_frame, style="Context.TFrame")
        context_header.pack(fill=tk.X)
        context_header.columnconfigure(0, weight=1)

        ttk.Label(context_header, textvariable=self.context_title_var, style="ContextTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Button(
            context_header,
            text="Start Guided Tour",
            style="Accent.TButton",
            command=self._start_guided_tour,
        ).grid(row=0, column=1, sticky="e", padx=(12, 0))

        ttk.Label(context_frame, textvariable=self.context_body_var, style="ContextBody.TLabel").pack(
            anchor="w", pady=(8, 0)
        )

        quick_links = ttk.Frame(context_frame, style="Context.TFrame")
        quick_links.pack(fill=tk.X, pady=(12, 0))
        ttk.Label(quick_links, text="Jump to a workspace:", style="Feature.TLabel").pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(quick_links, text="Backtesting Studio", style="Secondary.TButton", command=lambda: self._focus_tab("backtesting")).pack(side=tk.LEFT, padx=4)
        ttk.Button(quick_links, text="Scenario Lab", style="Secondary.TButton", command=lambda: self._focus_tab("scenario")).pack(side=tk.LEFT, padx=4)
        ttk.Button(quick_links, text="ML Lab", style="Secondary.TButton", command=lambda: self._focus_tab("ml")).pack(side=tk.LEFT, padx=4)
        ttk.Button(quick_links, text="Live Console", style="Secondary.TButton", command=lambda: self._focus_tab("live")).pack(side=tk.LEFT, padx=4)
        ttk.Button(quick_links, text="Risk Dashboard", style="Secondary.TButton", command=lambda: self._focus_tab("risk")).pack(side=tk.LEFT, padx=4)
        ttk.Button(quick_links, text="Logs & Diagnostics", style="Secondary.TButton", command=lambda: self._focus_tab("logs")).pack(side=tk.LEFT, padx=4)

        container = ttk.Frame(self.root, padding=(10, 14, 10, 10))
        container.pack(fill=tk.BOTH, expand=True)

        self.notebook = ttk.Notebook(container, style="Nav.TNotebook")
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self._build_welcome_tab()
        self._build_backtest_tab()
        self._build_scenario_tab()
        self._build_ml_tab()
        self._build_live_tab()
        self._build_risk_tab()
        self._build_logs_tab()

        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        self._set_initial_context()

        status_frame = ttk.Frame(self.root, padding=(12, 4))
        status_frame.pack(fill=tk.X, side=tk.BOTTOM)
        ttk.Label(status_frame, textvariable=self.status_var, style="Status.TLabel").pack(anchor="w")

    def _register_tab(
        self,
        slug: str,
        tab: tk.Widget,
        context_title: str,
        summary: str,
        key_points: List[str] | None = None,
        tour_message: str | None = None,
    ) -> None:
        self.tabs[slug] = tab
        self.tab_details[tab] = {
            "title": context_title,
            "summary": summary,
            "key_points": key_points or [],
        }
        if tour_message:
            self.tour_steps.append({"tab": tab, "title": context_title, "message": tour_message})

    def _set_initial_context(self) -> None:
        current = self.notebook.select()
        if current:
            tab_widget = self.notebook.nametowidget(current)
            self._update_context_panel(tab_widget)

    def _on_tab_changed(self, _event: tk.Event) -> None:  # type: ignore[override]
        tab_id = self.notebook.select()
        if not tab_id:
            return
        tab_widget = self.notebook.nametowidget(tab_id)
        self._update_context_panel(tab_widget)

    def _update_context_panel(self, tab_widget: tk.Widget) -> None:
        details = self.tab_details.get(tab_widget)
        if not details:
            self.context_title_var.set("Control Center Overview")
            self.context_body_var.set("Select any tab to see detailed guidance.")
            return
        self.context_title_var.set(str(details["title"]))
        summary = str(details["summary"])
        key_points = details.get("key_points", [])
        if key_points:
            bullet_list = "\n- " + "\n- ".join(str(point) for point in key_points)
            body = f"{summary}\n\nKey actions:{bullet_list}"
        else:
            body = summary
        self.context_body_var.set(body)

    def _focus_tab(self, slug: str) -> None:
        tab = self.tabs.get(slug)
        if tab is not None:
            self.notebook.select(tab)
        else:
            self._set_status(f"Tab '{slug}' not found. Please use the notebook tabs above.")

    def _start_guided_tour(self) -> None:
        if not self.tour_steps:
            messagebox.showinfo("Guided Tour", "No tour steps registered yet. Try again after the interface loads.")
            return
        self.tour_index = 0
        self._advance_tour()

    def _advance_tour(self) -> None:
        if self.tour_index >= len(self.tour_steps):
            messagebox.showinfo(
                "Guided Tour",
                "Tour complete! You now know where to backtest, stress test, train models, and monitor risk.",
            )
            return
        step = self.tour_steps[self.tour_index]
        tab = step["tab"]
        title = str(step["title"])
        message = str(step["message"])
        self.notebook.select(tab)
        proceed = messagebox.askyesno(title, f"{message}\n\nContinue to the next stop?")
        if proceed:
            self.tour_index += 1
            self.root.after(120, self._advance_tour)
        else:
            messagebox.showinfo("Guided Tour", "Tour paused. Use the header button when you're ready to continue.")

    # ------------------------------------------------------------------
    # Welcome tab
    def _build_welcome_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=20)
        self.notebook.add(tab, text="Welcome")

        ttk.Label(tab, text="Welcome to AIStock Robot", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(
            tab,
            text=(
                "This control center walks you through the complete lifecycle of an algorithmic trading system. "
                "Use the steps below to explore data, train models, and deploy paper or IBKR live sessions. "
                "Hover over sections and read the inline guidance before launching a session."
            ),
            style="Info.TLabel",
        ).pack(anchor="w", pady=(8, 18))

        steps = [
            (
                "1. Understand the Workflow",
                "Read this overview, review the feature map, and skim the Risk Dashboard tab so you know what data is tracked.",
            ),
            (
                "2. Backtest Strategies",
                "Pick historical data, tweak classical indicators, and optionally layer in the machine-learning model.",
            ),
            (
                "3. Stress Test with Scenarios",
                "Run gap/missing/volatility scenarios to see how strategies behave under unusual market conditions.",
            ),
            (
                "4. Train or Refresh ML Models",
                "Use the ML Lab to build logistic-regression classifiers on your datasets. Results feed directly into Backtest/Live tabs.",
            ),
            (
                "5. Launch Live Sessions",
                "Start paper or IBKR connections from the Live tab. Monitor risk metrics and trade logs in real time.",
            ),
        ]

        for title, description in steps:
            card = ttk.Frame(tab, style="Card.TFrame")
            card.pack(fill=tk.X, pady=6)
            ttk.Label(card, text=title, style="Subheading.TLabel").pack(anchor="w")
            ttk.Label(card, text=description, style="Info.TLabel").pack(anchor="w", pady=(2, 0))

        feature_frame = ttk.LabelFrame(tab, text="Feature Map", padding=14)
        feature_frame.pack(fill=tk.BOTH, expand=True, pady=(14, 0))
        features = [
            "Backtesting Studio – run deterministic simulations, toggle ML signals, and review results locally.",
            "Scenario Lab – apply designed shocks (gaps, data loss, volatility spikes) before trusting results.",
            "ML Lab – train deterministic logistic-regression models with built-in feature engineering.",
            "Live Control – orchestrate paper or IBKR sessions with unified risk controls and sizing logic.",
            "Risk Console – inspect equity, cash, drawdowns, and halt reasons sourced from the live session.",
            "Logs & Diagnostics – tail structured logs and inspect activity without leaving the GUI.",
        ]
        for feature in features:
            ttk.Label(feature_frame, text=f"• {feature}", style="Feature.TLabel").pack(anchor="w", pady=2)

        concepts_frame = ttk.LabelFrame(tab, text="Trading 101", padding=14)
        concepts_frame.pack(fill=tk.BOTH, expand=True, pady=(14, 0))
        concepts = [
            (
                "Market Data (Bars)",
                "Every row in your CSV is a bar: a timestamped record of open/high/low/close/volume. The warmup bars prime indicators before live signals fire.",
            ),
            (
                "Signals & Strategies",
                "Strategies transform historical bars into target positions. Out of the box you have moving-average crossover plus RSI-style reversion, with optional ML overlays.",
            ),
            (
                "Risk Guardrails",
                "RiskEngine watches drawdowns, daily loss, leverage, and symbol caps. When limits trip, trading halts until you resolve the issue and restart the session.",
            ),
            (
                "Execution & Brokers",
                "Backtests replay data locally, paper mode simulates fills, and IBKR mode connects to TWS/Gateway. The execution layer normalises trades across all modes.",
            ),
        ]
        for title, description in concepts:
            card = ttk.Frame(concepts_frame, style="Card.TFrame")
            card.pack(fill=tk.X, pady=4)
            ttk.Label(card, text=title, style="Subheading.TLabel").pack(anchor="w")
            ttk.Label(card, text=description, style="Info.TLabel").pack(anchor="w", pady=(2, 0))

        system_frame = ttk.LabelFrame(tab, text="How the Pieces Fit Together", padding=14)
        system_frame.pack(fill=tk.BOTH, expand=True, pady=(14, 0))
        flow = [
            ("Step 1 – Load Data", "Point to a folder of OHLCV CSVs. The loader validates schema, timestamps, and ordering."),
            ("Step 2 – Generate Signals", "Strategies produce target weights using classical indicators plus optional ML probabilities."),
            ("Step 3 – Size & Risk Check", "Sizing converts weights to share counts; RiskEngine enforces exposure, loss, and drawdown limits."),
            ("Step 4 – Execute Trades", "Fills are simulated (paper) or routed (IBKR). Every trade lands in the portfolio and log panels."),
            ("Step 5 – Review Insights", "Use dashboards to inspect positions, trades, and risk metrics before promoting to live sessions."),
        ]
        for prefix, detail in flow:
            ttk.Label(system_frame, text=f"{prefix}: {detail}", style="Feature.TLabel").pack(anchor="w", pady=2)

        path_frame = ttk.LabelFrame(tab, text="Guided Path", padding=14)
        path_frame.pack(fill=tk.X, pady=(14, 0))
        ttk.Label(
            path_frame,
            text="Follow these shortcuts if you prefer a structured walkthrough.",
            style="Info.TLabel",
        ).pack(anchor="w", pady=(0, 6))
        actions = [
            ("1. Run a backtest", lambda: self._focus_tab("backtesting")),
            ("2. Stress test the results", lambda: self._focus_tab("scenario")),
            ("3. Train an ML signal", lambda: self._focus_tab("ml")),
            ("4. Start a paper session", lambda: self._focus_tab("live")),
            ("5. Monitor risk live", lambda: self._focus_tab("risk")),
        ]
        buttons = ttk.Frame(path_frame)
        buttons.pack(anchor="w")
        for text, callback in actions:
            ttk.Button(buttons, text=text, style="Secondary.TButton", command=callback).pack(side=tk.LEFT, padx=4, pady=4)

        self._register_tab(
            slug="welcome",
            tab=tab,
            context_title="Welcome – Understand the Trading Loop",
            summary=(
                "Start here to see the entire lifecycle: from clean data and signal generation through risk controls and execution. "
                "Use the Guided Path buttons to jump straight into each workspace once you're ready."
            ),
            key_points=[
                "Read the workflow overview before running your first backtest.",
                "Skim Trading 101 cards to learn how strategies, brokers, and risk fit together.",
                "Use Guided Path shortcuts if you prefer a step-by-step experience.",
            ],
            tour_message=(
                "This Welcome tab orients you around the full trading workflow. Read the workflow, skim Trading 101, "
                "and use the shortcuts when you're ready to explore the other tabs."
            ),
        )

    # ------------------------------------------------------------------
    # Backtest tab
    def _build_backtest_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=16)
        self.notebook.add(tab, text="Backtesting")

        ttk.Label(tab, text="Backtesting Studio", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(
            tab,
            text=(
                "Choose historical data, configure the strategy, and run a backtest. "
                "The ML toggle loads the latest trained model if available."
            ),
            style="Info.TLabel",
        ).pack(anchor="w", pady=(6, 12))

        form = ttk.Frame(tab)
        form.pack(fill=tk.X, pady=(0, 12))

        dataset_box = ttk.LabelFrame(form, text="Dataset", padding=10)
        dataset_box.grid(row=0, column=0, sticky="nsew", padx=(0, 12))

        ttk.Label(dataset_box, text="Data folder").grid(row=0, column=0, sticky="w")
        ttk.Entry(dataset_box, textvariable=self.backtest_data_var, width=40).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(dataset_box, text="Browse…", command=self._browse_backtest_data).grid(row=0, column=2, padx=4)

        ttk.Label(dataset_box, text="Symbols (comma)").grid(row=1, column=0, sticky="w")
        ttk.Entry(dataset_box, textvariable=self.backtest_symbols_var).grid(row=1, column=1, sticky="ew", padx=4)

        ttk.Label(dataset_box, text="Warmup bars").grid(row=2, column=0, sticky="w")
        ttk.Entry(dataset_box, textvariable=self.backtest_warmup_var, width=10).grid(row=2, column=1, sticky="w", padx=4)

        strategy_box = ttk.LabelFrame(form, text="Strategy", padding=10)
        strategy_box.grid(row=0, column=1, sticky="nsew")

        ttk.Label(strategy_box, text="Initial equity").grid(row=0, column=0, sticky="w")
        ttk.Entry(strategy_box, textvariable=self.backtest_equity_var, width=12).grid(row=0, column=1, sticky="w", padx=4)

        ttk.Label(strategy_box, text="Short MA window").grid(row=1, column=0, sticky="w")
        ttk.Entry(strategy_box, textvariable=self.backtest_short_var, width=12).grid(row=1, column=1, sticky="w", padx=4)

        ttk.Label(strategy_box, text="Long MA window").grid(row=2, column=0, sticky="w")
        ttk.Entry(strategy_box, textvariable=self.backtest_long_var, width=12).grid(row=2, column=1, sticky="w", padx=4)

        ttk.Checkbutton(strategy_box, text="Enable ML strategy", variable=self.backtest_enable_ml_var).grid(row=3, column=0, sticky="w", pady=(6, 0))
        ttk.Label(strategy_box, text="ML model path").grid(row=4, column=0, sticky="w")
        ttk.Entry(strategy_box, textvariable=self.backtest_ml_model_path_var, width=30).grid(row=4, column=1, sticky="ew", padx=4)

        button_row = ttk.Frame(tab)
        button_row.pack(fill=tk.X, pady=(0, 10))
        ttk.Button(button_row, text="Run Backtest", style="Accent.TButton", command=self._run_backtest).pack(side=tk.LEFT)
        ttk.Button(button_row, text="Clear Output", command=self._clear_backtest_output).pack(side=tk.LEFT, padx=8)

        tips_frame = ttk.LabelFrame(tab, text="How to read the results", padding=10)
        tips_frame.pack(fill=tk.X, pady=(0, 10))
        tips = [
            "Total return compares ending equity with your starting capital.",
            "Max drawdown shows the largest peak-to-trough drop—watch this before going live.",
            "Trades include entry/exit timestamps, quantity, and PnL for each position.",
            "Sharpe/Sortino metrics help gauge risk-adjusted performance; higher is generally better.",
        ]
        for tip in tips:
            ttk.Label(tips_frame, text=f"- {tip}", style="Feature.TLabel").pack(anchor="w", pady=1)

        self.backtest_output = tk.Text(tab, height=18, state=tk.DISABLED, wrap=tk.WORD)
        self.backtest_output.pack(fill=tk.BOTH, expand=True)

        self._register_tab(
            slug="backtesting",
            tab=tab,
            context_title="Backtesting – Prove Ideas Before Real Money",
            summary=(
                "Pick historical data, tune strategy knobs, and compare results before touching live markets. "
                "The output panel streams equity, drawdowns, and trade-by-trade analytics."
            ),
            key_points=[
                "Use data folders with ISO-8601 CSV bars and list symbols with commas.",
                "Toggle the ML option to blend machine learning probabilities into decisions.",
                "Review drawdown and trade logs in the output panel to judge robustness.",
            ],
            tour_message=(
                "Backtesting lets you experiment risk-free. Choose your dataset, adjust windows, optionally enable ML, "
                "and run the simulation to see returns, drawdowns, and trade-by-trade stats."
            ),
        )

    # ------------------------------------------------------------------
    # Scenario tab
    def _build_scenario_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=16)
        self.notebook.add(tab, text="Scenario Lab")

        ttk.Label(tab, text="Scenario Lab", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(
            tab,
            text=(
                "Stress test your strategies with predefined shocks. "
                "Gap scenarios apply opening jumps, Missing drops random bars, and Volatility spikes widen highs/lows."
            ),
            style="Info.TLabel",
        ).pack(anchor="w", pady=(6, 12))

        ttk.Button(tab, text="Run Scenario Suite", style="Accent.TButton", command=self._run_scenarios).pack(anchor="w")

        columns = ("scenario", "trades", "total_return", "max_dd")
        tree = ttk.Treeview(tab, columns=columns, show="headings", height=18)
        headings = {
            "scenario": ("Scenario", 180),
            "trades": ("Trades", 100),
            "total_return": ("Total Return", 140),
            "max_dd": ("Max Drawdown", 140),
        }
        for col in columns:
            text, width = headings[col]
            tree.heading(col, text=text)
            tree.column(col, width=width, anchor=tk.CENTER)
        tree.pack(fill=tk.BOTH, expand=True, pady=(12, 0))
        self.scenario_tree = tree

        guidance = ttk.LabelFrame(tab, text="Why scenarios matter", padding=10)
        guidance.pack(fill=tk.X, pady=(12, 0))
        notes = [
            "Gap tests simulate overnight shocks so you can verify stop handling.",
            "Missing data ensures your strategy tolerates incomplete feeds without crashing.",
            "Volatility spikes widen highs/lows to expose fragile sizing or risk settings.",
            "Compare total return and max drawdown across rows to understand resilience.",
        ]
        for note in notes:
            ttk.Label(guidance, text=f"- {note}", style="Feature.TLabel").pack(anchor="w", pady=1)

        self._register_tab(
            slug="scenario",
            tab=tab,
            context_title="Scenario Lab – Stress Test Before Live Deployment",
            summary=(
                "Apply curated shocks (gaps, missing bars, volatility spikes) to see how your strategy behaves when markets misbehave."
                " Each run populates the table with trades, total return, and drawdown deltas."
            ),
            key_points=[
                "Run the full suite after every major strategy or data change.",
                "Use the drawdown column to spot scenarios that violate your risk appetite.",
                "Investigate high trade counts under stress—they often signal over-trading during chaos.",
            ],
            tour_message=(
                "Scenario Lab lets you inject gaps, missing data, and volatility spikes. Run the suite and compare the results "
                "to catch fragile behaviour before promoting strategies to live sessions."
            ),
        )

    # ------------------------------------------------------------------
    # ML tab
    def _build_ml_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=16)
        self.notebook.add(tab, text="ML Lab")

        ttk.Label(tab, text="Machine Learning Lab", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(
            tab,
            text=(
                "Train or refresh the logistic-regression model that augments the rule-based strategies. "
                "Models are deterministic and stored as JSON for easy review."
            ),
            style="Info.TLabel",
        ).pack(anchor="w", pady=(6, 12))

        config_frame = ttk.LabelFrame(tab, text="Training Configuration", padding=10)
        config_frame.pack(fill=tk.X)

        ttk.Label(config_frame, text="Data folder").grid(row=0, column=0, sticky="w")
        ttk.Entry(config_frame, textvariable=self.ml_data_var, width=40).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(config_frame, text="Browse…", command=self._browse_ml_data).grid(row=0, column=2, padx=4)

        ttk.Label(config_frame, text="Symbols (comma)").grid(row=1, column=0, sticky="w")
        ttk.Entry(config_frame, textvariable=self.ml_symbols_var).grid(row=1, column=1, sticky="ew", padx=4)

        ttk.Label(config_frame, text="Feature lookback").grid(row=2, column=0, sticky="w")
        ttk.Entry(config_frame, textvariable=self.ml_lookback_var, width=12).grid(row=2, column=1, sticky="w", padx=4)

        ttk.Label(config_frame, text="Prediction horizon").grid(row=3, column=0, sticky="w")
        ttk.Entry(config_frame, textvariable=self.ml_horizon_var, width=12).grid(row=3, column=1, sticky="w", padx=4)

        ttk.Label(config_frame, text="Epochs").grid(row=4, column=0, sticky="w")
        ttk.Entry(config_frame, textvariable=self.ml_epochs_var, width=12).grid(row=4, column=1, sticky="w", padx=4)

        ttk.Label(config_frame, text="Learning rate").grid(row=5, column=0, sticky="w")
        ttk.Entry(config_frame, textvariable=self.ml_lr_var, width=12).grid(row=5, column=1, sticky="w", padx=4)

        ttk.Label(config_frame, text="Model output").grid(row=6, column=0, sticky="w")
        ttk.Entry(config_frame, textvariable=self.ml_model_path_var, width=40).grid(row=6, column=1, sticky="ew", padx=4)

        button_row = ttk.Frame(tab, padding=(0, 10))
        button_row.pack(fill=tk.X)
        ttk.Button(button_row, text="Train Model", style="Accent.TButton", command=self._train_model_gui).pack(side=tk.LEFT)
        ttk.Button(button_row, text="Load Model into Sessions", command=self._load_model_into_sessions).pack(side=tk.LEFT, padx=8)

        info_frame = ttk.LabelFrame(tab, text="Training tips", padding=10)
        info_frame.pack(fill=tk.X, pady=(0, 10))
        advice = [
            "Feature lookback controls how many past bars feed each training example.",
            "Prediction horizon is the number of bars ahead you want the ML signal to forecast.",
            "Keep an eye on accuracy/precision metrics printed in the output pane after training.",
            "Store model files in version control or a dedicated models/ directory so sessions can reload them later.",
        ]
        for item in advice:
            ttk.Label(info_frame, text=f"- {item}", style="Feature.TLabel").pack(anchor="w", pady=1)

        self.ml_output = tk.Text(tab, height=18, state=tk.DISABLED, wrap=tk.WORD)
        self.ml_output.pack(fill=tk.BOTH, expand=True)

        self._register_tab(
            slug="ml",
            tab=tab,
            context_title="ML Lab – Enhance Signals with Deterministic Models",
            summary=(
                "Train logistic models on your datasets without leaving the platform. The output highlights metrics so you know "
                "when a model is good enough to load into backtests or live sessions."
            ),
            key_points=[
                "Use the same data directories as backtests to keep features aligned.",
                "Tune lookback and horizon to balance responsiveness and stability.",
                "Click 'Load Model into Sessions' to push the saved path into Backtesting and Live tabs automatically.",
            ],
            tour_message=(
                "The ML Lab trains deterministic logistic models. Configure lookback, horizon, and optimisation settings, "
                "train the model, then load the resulting JSON path into the other tabs."
            ),
        )

    # ------------------------------------------------------------------
    # Live tab
    def _build_live_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=16)
        self.notebook.add(tab, text="Live Control")

        ttk.Label(tab, text="Live Trading Console", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(
            tab,
            text="Kick off a session in three steps. Advanced knobs stay a toggle away when you want them.",
            style="Info.TLabel",
        ).pack(anchor="w", pady=(6, 12))

        quick_start = ttk.LabelFrame(tab, text="Quick Start (3 simple steps)", padding=12)
        quick_start.pack(fill=tk.X, pady=(0, 12))

        ttk.Label(quick_start, text="1. Choose a driving mode", style="Subheading.TLabel").grid(row=0, column=0, sticky="w")
        mode_frame = ttk.Frame(quick_start)
        mode_frame.grid(row=1, column=0, sticky="w", pady=(2, 8))
        ttk.Radiobutton(mode_frame, text="BOT – Strategy Autopilot", variable=self.live_mode_var, value="bot").pack(anchor="w")
        ttk.Radiobutton(mode_frame, text="FSD – Full Self-Driving AI", variable=self.live_mode_var, value="fsd").pack(anchor="w")

        ttk.Label(quick_start, text="2. Point to data & broker", style="Subheading.TLabel").grid(row=2, column=0, sticky="w")
        step2 = ttk.Frame(quick_start)
        step2.grid(row=3, column=0, sticky="ew", pady=(2, 8))
        step2.columnconfigure(1, weight=1)
        ttk.Label(step2, text="Backend").grid(row=0, column=0, sticky="w")
        ttk.Combobox(step2, textvariable=self.live_backend_var, values=["paper", "ibkr"], state="readonly", width=12).grid(row=0, column=1, sticky="w", padx=4)
        ttk.Label(step2, text="Data folder").grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(step2, textvariable=self.live_data_var).grid(row=1, column=1, sticky="ew", padx=4)
        ttk.Button(step2, text="Browse…", command=self._browse_live_data).grid(row=1, column=2, padx=4)
        ttk.Label(step2, text="Symbols").grid(row=2, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(step2, textvariable=self.live_symbols_var).grid(row=2, column=1, sticky="ew", padx=4)

        ttk.Label(quick_start, text="3. Launch & monitor", style="Subheading.TLabel").grid(row=4, column=0, sticky="w")
        step3 = ttk.Frame(quick_start)
        step3.grid(row=5, column=0, sticky="w", pady=(2, 0))
        ttk.Button(step3, text="Start Session", style="Accent.TButton", command=self._start_live_session).pack(side=tk.LEFT)
        ttk.Button(step3, text="Stop Session", command=self._stop_live_session).pack(side=tk.LEFT, padx=8)
        ttk.Button(step3, text="Snapshot", command=self._snapshot_live_session).pack(side=tk.LEFT, padx=8)
        ttk.Label(step3, text="Keep the Risk console open when capital is live.", style="Feature.TLabel").pack(side=tk.LEFT, padx=12)

        toggle_row = ttk.Frame(tab)
        toggle_row.pack(fill=tk.X, pady=(0, 8))
        ttk.Checkbutton(
            toggle_row,
            text="Show advanced configuration",
            variable=self.live_show_advanced_var,
            command=self._toggle_live_advanced,
        ).pack(anchor="w")

        self.live_advanced_container = ttk.Frame(tab)

        config_wrapper = ttk.Frame(self.live_advanced_container)
        config_wrapper.pack(fill=tk.X)
        config_wrapper.columnconfigure(0, weight=1)
        config_wrapper.columnconfigure(1, weight=1)
        config_wrapper.columnconfigure(2, weight=1)

        session_box = ttk.LabelFrame(config_wrapper, text="Session tuning", padding=10)
        session_box.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        ttk.Label(session_box, text="Initial equity").grid(row=0, column=0, sticky="w")
        ttk.Entry(session_box, textvariable=self.live_equity_var, width=12).grid(row=0, column=1, sticky="w", padx=4)
        ttk.Label(session_box, text="Warmup bars").grid(row=1, column=0, sticky="w")
        ttk.Entry(session_box, textvariable=self.live_warmup_var, width=12).grid(row=1, column=1, sticky="w", padx=4)
        ttk.Label(session_box, text="Slippage (bps)").grid(row=2, column=0, sticky="w")
        ttk.Entry(session_box, textvariable=self.live_slippage_var, width=12).grid(row=2, column=1, sticky="w", padx=4)
        ttk.Label(session_box, text="Playback delay (ms)").grid(row=3, column=0, sticky="w")
        ttk.Entry(session_box, textvariable=self.live_delay_var, width=12).grid(row=3, column=1, sticky="w", padx=4)
        ttk.Checkbutton(session_box, text="Enable ML strategy", variable=self.live_enable_ml_var).grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Label(session_box, text="ML model path").grid(row=5, column=0, sticky="w")
        ttk.Entry(session_box, textvariable=self.live_ml_model_path_var).grid(row=5, column=1, sticky="ew", padx=4)
        ttk.Button(session_box, text="Browse model", command=self._browse_live_model).grid(row=5, column=2, padx=4)

        fsd_box = ttk.LabelFrame(config_wrapper, text="FSD AI guardrails", padding=10)
        fsd_box.grid(row=0, column=1, sticky="nsew", padx=(0, 12))
        ttk.Label(fsd_box, text="Max Capital (USD)").grid(row=0, column=0, sticky="w")
        ttk.Entry(fsd_box, textvariable=self.fsd_max_capital_var, width=12).grid(row=0, column=1, sticky="w", padx=4)
        ttk.Label(fsd_box, text="Time Limit (minutes)").grid(row=1, column=0, sticky="w")
        ttk.Entry(fsd_box, textvariable=self.fsd_time_limit_var, width=12).grid(row=1, column=1, sticky="w", padx=4)
        ttk.Label(fsd_box, text="Learning Rate").grid(row=2, column=0, sticky="w")
        ttk.Entry(fsd_box, textvariable=self.fsd_learning_rate_var, width=12).grid(row=2, column=1, sticky="w", padx=4)
        ttk.Label(fsd_box, text="Exploration Rate").grid(row=3, column=0, sticky="w")
        ttk.Entry(fsd_box, textvariable=self.fsd_exploration_rate_var, width=12).grid(row=3, column=1, sticky="w", padx=4)
        ttk.Label(fsd_box, text="AI State Path").grid(row=4, column=0, sticky="w")
        ttk.Entry(fsd_box, textvariable=self.fsd_state_path_var, width=30).grid(row=4, column=1, sticky="ew", padx=4)
        ttk.Button(fsd_box, text="Browse…", command=self._browse_fsd_state).grid(row=4, column=2, padx=4)

        ib_box = ttk.LabelFrame(config_wrapper, text="Connectivity", padding=10)
        ib_box.grid(row=0, column=2, sticky="nsew")
        ttk.Label(ib_box, text="Host").grid(row=0, column=0, sticky="w")
        ttk.Entry(ib_box, textvariable=self.ib_host_var, width=18).grid(row=0, column=1, sticky="w", padx=4)
        ttk.Label(ib_box, text="Port").grid(row=0, column=2, sticky="w")
        ttk.Entry(ib_box, textvariable=self.ib_port_var, width=8).grid(row=0, column=3, sticky="w", padx=4)
        ttk.Label(ib_box, text="Client ID").grid(row=0, column=4, sticky="w")
        ttk.Entry(ib_box, textvariable=self.ib_client_var, width=8).grid(row=0, column=5, sticky="w", padx=4)
        ttk.Label(ib_box, text="Account").grid(row=1, column=0, sticky="w")
        ttk.Entry(ib_box, textvariable=self.ib_account_var, width=18).grid(row=1, column=1, sticky="w", padx=4)
        ttk.Label(ib_box, text="Sec Type").grid(row=1, column=2, sticky="w")
        ttk.Entry(ib_box, textvariable=self.ib_sec_type_var, width=8).grid(row=1, column=3, sticky="w", padx=4)
        ttk.Label(ib_box, text="Exchange").grid(row=2, column=0, sticky="w")
        ttk.Entry(ib_box, textvariable=self.ib_exchange_var, width=8).grid(row=2, column=1, sticky="w", padx=4)
        ttk.Label(ib_box, text="Currency").grid(row=2, column=2, sticky="w")
        ttk.Entry(ib_box, textvariable=self.ib_currency_var, width=8).grid(row=2, column=3, sticky="w", padx=4)

        action_row = ttk.Frame(self.live_advanced_container, padding=(0, 6))
        action_row.pack(fill=tk.X)
        ttk.Button(action_row, text="Save Config", command=self._save_live_config).pack(side=tk.RIGHT)

        self.live_advanced_container.pack_forget()

        self.live_views = ttk.PanedWindow(tab, orient=tk.HORIZONTAL)
        self.live_views.pack(fill=tk.BOTH, expand=True)

        positions_frame = ttk.LabelFrame(self.live_views, text="Open Positions", padding=8)
        trades_frame = ttk.LabelFrame(self.live_views, text="Recent Trades", padding=8)
        self.live_views.add(positions_frame, weight=1)
        self.live_views.add(trades_frame, weight=1)

        self.positions_tree = ttk.Treeview(positions_frame, columns=("symbol", "qty", "avg_price"), show="headings", height=12)
        for col in ("symbol", "qty", "avg_price"):
            self.positions_tree.heading(col, text=col.title())
            self.positions_tree.column(col, width=120, anchor=tk.CENTER)
        self.positions_tree.pack(fill=tk.BOTH, expand=True)

        self.trades_tree = ttk.Treeview(trades_frame, columns=("timestamp", "symbol", "qty", "price", "pnl"), show="headings", height=12)
        for col, width in zip(("timestamp", "symbol", "qty", "price", "pnl"), (170, 90, 90, 90, 90)):
            self.trades_tree.heading(col, text=col.title())
            self.trades_tree.column(col, width=width, anchor=tk.CENTER)
        self.trades_tree.pack(fill=tk.BOTH, expand=True)

        playbook_frame = ttk.LabelFrame(tab, text="Session checklist", padding=10)
        playbook_frame.pack(fill=tk.X, pady=(12, 0))
        checklist = [
            "Paper mode replays historical CSVs; IBKR mode streams from your brokerage connection.",
            "Need more tuning? Tick 'Show advanced configuration' to reveal every knob.",
            "RiskEngine halts trading when limits trip. Watch the Risk Console tab for halt reasons.",
            "Use Stop Session for a graceful shutdown before changing configuration or switching datasets.",
        ]
        for item in checklist:
            ttk.Label(playbook_frame, text=f"- {item}", style="Feature.TLabel").pack(anchor="w", pady=1)

        self._register_tab(
            slug="live",
            tab=tab,
            context_title="Live Control – Operate Paper or IBKR Sessions",
            summary=(
                "Configure backend, data feeds, and risk-aware sizing before going live. Positions and trades stream into the panels "
                "below so you can supervise fills without touching the command line."
            ),
            key_points=[
                "Start in paper mode to rehearse the full workflow before touching IBKR.",
                "Confirm risk limits in the Risk Console tab before enabling real capital.",
                "Use Stop Session prior to changing symbols or credentials.",
            ],
            tour_message=(
                "The Live tab is where paper and IBKR sessions run. Configure data, warmup, delays, and risk settings, then start the session "
                "to watch positions and trades update in real time."
            ),
        )

    # ------------------------------------------------------------------
    # Risk tab
    def _build_risk_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=16)
        self.notebook.add(tab, text="Risk Console")

        ttk.Label(tab, text="Risk Console", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(
            tab,
            text=(
                "Real-time snapshot of equity, cash, daily PnL, drawdowns, and halt status. "
                "This panel updates automatically when a live session is running."
            ),
            style="Info.TLabel",
        ).pack(anchor="w", pady=(6, 12))

        grid = ttk.Frame(tab, padding=10)
        grid.pack(fill=tk.X)
        labels = [
            ("Equity", "equity"),
            ("Cash", "cash"),
            ("Daily PnL", "daily_pnl"),
            ("Peak Equity", "peak_equity"),
            ("Risk Halted", "halted"),
            ("Halt Reason", "halt_reason"),
        ]
        for row, (title, key) in enumerate(labels):
            ttk.Label(grid, text=f"{title}:", style="Subheading.TLabel").grid(row=row, column=0, sticky="w", pady=4)
            value_label = ttk.Label(grid, text="-", style="Feature.TLabel")
            value_label.grid(row=row, column=1, sticky="w", pady=4)
            self.risk_labels[key] = value_label

        # FSD AI Stats (only shown when FSD mode is active)
        fsd_stats_frame = ttk.LabelFrame(tab, text="FSD AI Learning Stats", padding=10)
        fsd_stats_frame.pack(fill=tk.X, pady=(12, 0))
        fsd_stats = [
            ("Trading Mode", "mode"),
            ("Total Trades (Learning)", "total_trades"),
            ("Q-Values Learned", "q_values_learned"),
            ("Exploration Rate", "exploration_rate"),
            ("Win Rate", "win_rate"),
            ("Average PnL per Trade", "avg_pnl"),
            ("Experience Buffer Size", "experience_buffer"),
            ("Last Trade (UTC)", "last_trade_time"),
        ]
        for row, (title, key) in enumerate(fsd_stats):
            ttk.Label(fsd_stats_frame, text=f"{title}:", style="Subheading.TLabel").grid(row=row, column=0, sticky="w", pady=4)
            value_label = ttk.Label(fsd_stats_frame, text="-", style="Feature.TLabel")
            value_label.grid(row=row, column=1, sticky="w", pady=4)
            self.fsd_labels[key] = value_label

        helper = ttk.LabelFrame(tab, text="Interpreting the dashboard", padding=10)
        helper.pack(fill=tk.X, pady=(12, 0))
        guidance = [
            "Equity is total account value; Cash reflects immediately available capital.",
            "Daily PnL resets automatically with each new session start.",
            "Peak equity tracks the highest value seen this session to measure drawdowns.",
            "If Risk Halted is True, review Halt Reason, stop the session, and address the root cause before restarting.",
        ]
        for line in guidance:
            ttk.Label(helper, text=f"- {line}", style="Feature.TLabel").pack(anchor="w", pady=1)

        self._register_tab(
            slug="risk",
            tab=tab,
            context_title="Risk Console – Stay Within Guardrails",
            summary=(
                "Live sessions stream equity, cash, drawdowns, and halt reasons here. "
                "Use it as your heartbeat monitor—if something breaks, this tab tells you why."
            ),
            key_points=[
                "Watch Daily PnL and drawdowns when experimenting with new strategies.",
                "Resolve any halt reason before resuming a session.",
                "Keep this tab open alongside Live Control during trading hours.",
            ],
            tour_message=(
                "Risk Console mirrors the RiskEngine state. Monitor equity, cash, and halt reasons while your session runs "
                "so you can intervene before losses escalate."
            ),
        )

    # ------------------------------------------------------------------
    # Logs tab
    def _build_logs_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=16)
        self.notebook.add(tab, text="Logs & Diagnostics")

        ttk.Label(tab, text="Diagnostics Console", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(
            tab,
            text=(
                "This rolling log shows key events (orders, fills, scenario runs, model training). "
                "Use it to triage issues or capture audit trails."
            ),
            style="Info.TLabel",
        ).pack(anchor="w", pady=(6, 12))

        self.log_text = tk.Text(tab, height=22, state=tk.DISABLED, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        helper = ttk.LabelFrame(tab, text="Troubleshooting checklist", padding=10)
        helper.pack(fill=tk.X, pady=(12, 0))
        steps = [
            "Look for risk violations or broker errors if sessions halt unexpectedly.",
            "Search for Scenario or ML log records to trace parameter changes.",
            "Copy relevant entries when filing incident reviews or sharing results.",
        ]
        for step in steps:
            ttk.Label(helper, text=f"- {step}", style="Feature.TLabel").pack(anchor="w", pady=1)

        self._register_tab(
            slug="logs",
            tab=tab,
            context_title="Logs & Diagnostics – Understand What Happened",
            summary=(
                "Tail structured events from backtests, scenarios, model training, and live sessions without leaving the app. "
                "Use the console whenever you need to troubleshoot or create an audit trail."
            ),
            key_points=[
                "Scan for ERROR entries or risk violations after a halted session.",
                "Capture key log lines when documenting research runs.",
                "Use alongside the Risk Console for a full operational picture.",
            ],
            tour_message=(
                "Logs & Diagnostics centralises structured events. Keep an eye here for errors, fills, and training updates so you can debug quickly."
            ),
        )

    # ------------------------------------------------------------------
    # Actions & callbacks
    def _browse_backtest_data(self) -> None:
        path = filedialog.askdirectory()
        if path:
            self.backtest_data_var.set(path)

    def _browse_live_data(self) -> None:
        path = filedialog.askdirectory()
        if path:
            self.live_data_var.set(path)

    def _browse_live_model(self) -> None:
        path = filedialog.askopenfilename(title="Select ML model", filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")])
        if path:
            self.live_ml_model_path_var.set(path)

    def _browse_fsd_state(self) -> None:
        path = filedialog.askopenfilename(title="Select FSD state file", filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")])
        if path:
            self.fsd_state_path_var.set(path)

    def _browse_ml_data(self) -> None:
        path = filedialog.askdirectory()
        if path:
            self.ml_data_var.set(path)

    def _save_live_config(self) -> None:
        try:
            config = self._build_live_config()
            config.validate()
        except Exception as exc:
            self._display_error("Save Config Error", f"Unable to build configuration: {exc}")
            return

        suggested = Path(self.live_data_var.get() or "config").with_suffix(".json")
        path = filedialog.asksaveasfilename(
            title="Save Live Configuration",
            defaultextension=".json",
            initialfile=suggested.name,
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
        )
        if not path:
            return

        try:
            payload = asdict(config)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, default=str)
            self._append_log(f"Live configuration saved to '{path}'.")
            self._set_status("Live configuration saved.")
        except Exception as exc:
            self._display_error("Save Config Error", str(exc))

    def _run_backtest(self) -> None:
        try:
            config = self._build_backtest_config()
            result = BacktestRunner(config).run()
            output = (
                "Backtest complete\n"
                f"Trades executed  : {len(result.trades)}\n"
                f"Total return     : {float(result.total_return):.4%}\n"
                f"Max drawdown     : {float(result.max_drawdown):.4%}\n"
                f"Win rate         : {result.win_rate:.2%}\n"
                f"Sharpe Ratio     : {result.metrics.get('sharpe', 0.0):.2f}\n"
                f"Sortino Ratio    : {result.metrics.get('sortino', 0.0):.2f}\n"
                f"Expectancy       : {result.metrics.get('expectancy', 0.0):.2f}\n"
            )
            self._write_backtest_output(output)
            self._append_log("Backtest finished successfully.")
            self._set_status("Backtest complete.")
        except Exception as exc:
            self._display_error("Backtest Error", str(exc))

    def _clear_backtest_output(self) -> None:
        if self.backtest_output:
            self.backtest_output.configure(state=tk.NORMAL)
            self.backtest_output.delete("1.0", tk.END)
            self.backtest_output.configure(state=tk.DISABLED)
        self._set_status("Backtest output cleared.")

    def _run_scenarios(self) -> None:
        try:
            config = self._build_backtest_config()
            base_data = load_csv_directory(config.data, config.engine.data_quality)
            runner = ScenarioRunner(
                [
                    GapScenario(name="Gap +5%", gap_percentage=5, bars_to_skip=1),
                    VolatilitySpikeScenario(name="Volatility Spike", multiplier=1.5),
                    MissingDataScenario(name="Missing Bars 30%", probability=0.3),
                ]
            )
            scenario_views = runner.run(base_data)
            if self.scenario_tree:
                self.scenario_tree.delete(*self.scenario_tree.get_children())
            for scen_name, data_view in scenario_views.items():
                scen_config = config
                result = BacktestRunner(scen_config).run(override_data=data_view)
                if self.scenario_tree:
                    self.scenario_tree.insert(
                        "", tk.END, values=(scen_name, len(result.trades), f"{float(result.total_return):.4%}", f"{float(result.max_drawdown):.4%}")
                    )
            self._append_log("Scenario run completed.")
            self._set_status("Scenario run complete.")
        except Exception as exc:
            self._display_error("Scenario Error", str(exc))

    def _train_model_gui(self) -> None:
        try:
            symbols = self._parse_symbols(self.ml_symbols_var.get())
            result = train_model(
                data_dir=self.ml_data_var.get(),
                symbols=symbols,
                lookback=int(self.ml_lookback_var.get()),
                horizon=int(self.ml_horizon_var.get()),
                learning_rate=float(self.ml_lr_var.get()),
                epochs=int(self.ml_epochs_var.get()),
                model_path=self.ml_model_path_var.get(),
            )
            output = (
                "Model training complete\n"
                f"Samples       : {result.samples}\n"
                f"Train Accuracy: {result.train_accuracy:.4f}\n"
                f"Test Accuracy : {result.test_accuracy:.4f}\n"
                f"Model stored  : {result.model_path}\n"
            )
            self._write_ml_output(output)
            # sync model paths with other tabs
            self.backtest_ml_model_path_var.set(result.model_path)
            self.live_ml_model_path_var.set(result.model_path)
            self._append_log("ML model trained successfully.")
            self._set_status("ML training complete.")
        except Exception as exc:
            self._display_error("ML Training Error", str(exc))

    def _load_model_into_sessions(self) -> None:
        path = self.ml_model_path_var.get()
        if not Path(path).exists():
            self._display_error("Model Not Found", f"No model file found at '{path}'. Train a model first.")
            return
        self.backtest_ml_model_path_var.set(path)
        self.live_ml_model_path_var.set(path)
        self.backtest_enable_ml_var.set(True)
        self.live_enable_ml_var.set(True)
        self._append_log(f"Model path '{path}' loaded into Backtest and Live configurations.")
        self._set_status("Model path applied across tabs.")

    def _start_live_session(self) -> None:
        if self.session is not None:
            self._display_error("Session Active", "A live session is already running. Stop it before starting a new one.")
            return
        try:
            config = self._build_live_config()
            mode = self.live_mode_var.get()

            # Build FSD config if in FSD mode
            fsd_config = None
            if mode == "fsd":
                fsd_config = FSDConfig(
                    max_capital=float(self.fsd_max_capital_var.get()),
                    time_limit_minutes=int(self.fsd_time_limit_var.get()),
                    learning_rate=float(self.fsd_learning_rate_var.get()),
                    exploration_rate=float(self.fsd_exploration_rate_var.get()),
                    state_save_path=self.fsd_state_path_var.get(),
                )

            self.session = LiveTradingSession(config, mode=mode, fsd_config=fsd_config)
            self.session.start()
            backend = self.live_backend_var.get()
            if backend == "paper":
                data_map = load_csv_directory(config.data, config.engine.data_quality)
                self.simulated_bars = self._merge_bars(data_map)
                self.sim_index = 0
                self.sim_running = True
                self.root.after(100, self._step_simulation)
                self._append_log(f"Paper simulation started in {mode.upper()} mode.")
            else:
                self._append_log(f"IBKR session started in {mode.upper()} mode. Awaiting market data…")
            self._set_status(f"Live session started ({mode.upper()} mode).")
        except Exception as exc:
            if self.session:
                self.session.stop()
            self.session = None
            self._display_error("Live Session Error", str(exc))

    def _stop_live_session(self) -> None:
        if self.session:
            self.session.stop()
            self.session = None
        self.sim_running = False
        self.simulated_bars.clear()
        self._append_log("Live session stopped.")
        self._set_status("Session stopped.")

    def _snapshot_live_session(self) -> None:
        if not self.session:
            self._display_error("No Active Session", "Start a live session before capturing a snapshot.")
            return
        try:
            snapshot = self.session.snapshot()
            equity = float(snapshot.get("equity", 0.0))
            cash = float(snapshot.get("cash", 0.0))
            positions = len(snapshot.get("positions", []))
            trades = len(snapshot.get("trades", []))
            self._append_log(
                f"Snapshot captured – equity: {equity:,.2f}, cash: {cash:,.2f}, positions: {positions}, trades: {trades}"
            )
            self._set_status("Snapshot captured.")
        except Exception as exc:
            self._display_error("Snapshot Error", str(exc))

    def _step_simulation(self) -> None:
        if not self.sim_running or self.session is None:
            return
        if self.sim_index >= len(self.simulated_bars):
            self._append_log("Simulation reached end of dataset.")
            self.sim_running = False
            return
        bar = self.simulated_bars[self.sim_index]
        self.sim_index += 1
        self.session.process_bar(bar)
        delay = max(50, int(float(self.live_delay_var.get() or 200)))
        self.root.after(delay, self._step_simulation)

    def _toggle_live_advanced(self) -> None:
        if self.live_show_advanced_var.get():
            self.live_advanced_container.pack(fill=tk.X, pady=(0, 12), before=self.live_views)
        else:
            self.live_advanced_container.pack_forget()

    # ------------------------------------------------------------------
    # Periodic updates
    def _update_live_views(self) -> None:
        if self.session and self.positions_tree and self.trades_tree:
            snapshot = self.session.snapshot()
            self._refresh_positions(snapshot.get("positions", []))
            self._refresh_trades(snapshot.get("trades", []))
            self._update_risk_labels(snapshot)
            self._set_status("Live snapshot updated.")
        else:
            self._update_risk_labels(None)
        self.root.after(1000, self._update_live_views)

    def _refresh_positions(self, positions: List[dict]) -> None:
        if not self.positions_tree:
            return
        self.positions_tree.delete(*self.positions_tree.get_children())
        for pos in positions:
            self.positions_tree.insert(
                "", tk.END, values=(pos["symbol"], f"{pos['quantity']:.4f}", f"{pos['avg_price']:.4f}")
            )

    def _refresh_trades(self, trades: List[dict]) -> None:
        if not self.trades_tree:
            return
        self.trades_tree.delete(*self.trades_tree.get_children())
        for trade in trades[-100:]:
            ts = trade["timestamp"].strftime("%Y-%m-%d %H:%M:%S") if trade.get("timestamp") else "-"
            self.trades_tree.insert(
                "",
                tk.END,
                values=(ts, trade["symbol"], f"{trade['quantity']:.4f}", f"{trade['price']:.4f}", f"{trade['realised_pnl']:.2f}"),
            )

    def _update_risk_labels(self, snapshot: dict | None) -> None:
        if not self.risk_labels:
            return
        if not snapshot:
            for label in self.risk_labels.values():
                label.config(text="-")
            for label in self.fsd_labels.values():
                label.config(text="-")
            return

        # Update risk labels
        risk = snapshot.get("risk", {})
        values = {
            "equity": f"{snapshot.get('equity', 0.0):,.2f}",
            "cash": f"{snapshot.get('cash', 0.0):,.2f}",
            "daily_pnl": f"{risk.get('daily_pnl', 0.0):,.2f}",
            "peak_equity": f"{risk.get('peak_equity', 0.0):,.2f}",
            "halted": str(risk.get("halted", False)),
            "halt_reason": risk.get("halt_reason") or "-",
        }
        for key, label in self.risk_labels.items():
            label.config(text=values.get(key, "-"))

        # Update FSD labels
        fsd = snapshot.get("fsd", {})
        fsd_values = {
            "mode": fsd.get("mode", "bot").upper(),
            "total_trades": str(fsd.get("total_trades", "-")),
            "q_values_learned": str(fsd.get("q_values_learned", "-")),
            "exploration_rate": f"{fsd.get('exploration_rate', 0.0):.4f}" if isinstance(fsd.get('exploration_rate'), (int, float)) else "-",
            "win_rate": f"{fsd.get('win_rate', 0.0):.2%}" if isinstance(fsd.get('win_rate'), (int, float)) else "-",
            "avg_pnl": f"${fsd.get('avg_pnl', 0.0):,.2f}" if isinstance(fsd.get('avg_pnl'), (int, float)) else "-",
            "experience_buffer": str(fsd.get("experience_buffer", "-")),
            "last_trade_time": fsd.get("last_trade_time") or "-",
        }
        for key, label in self.fsd_labels.items():
            label.config(text=fsd_values.get(key, "-"))

    # ------------------------------------------------------------------
    # Configuration builders
    def _build_backtest_config(self) -> BacktestConfig:
        symbols = self._parse_symbols(self.backtest_symbols_var.get())
        data_source = DataSource(
            path=self.backtest_data_var.get(),
            timezone=timezone.utc,
            symbols=symbols,
            warmup_bars=int(self.backtest_warmup_var.get()),
        )
        strategy_cfg = StrategyConfig(
            short_window=int(self.backtest_short_var.get()),
            long_window=int(self.backtest_long_var.get()),
            ml_enabled=self.backtest_enable_ml_var.get(),
            ml_model_path=self.backtest_ml_model_path_var.get(),
            ml_feature_lookback=int(self.ml_lookback_var.get()),
        )
        engine = EngineConfig(
            strategy=strategy_cfg,
            initial_equity=float(self.backtest_equity_var.get()),
            commission_per_trade=0.0,
            slippage_bps=0.0,
        )
        return BacktestConfig(data=data_source, engine=engine, execution=ExecutionConfig())

    def _build_live_config(self) -> BacktestConfig:
        symbols = self._parse_symbols(self.live_symbols_var.get())
        data_source = DataSource(
            path=self.live_data_var.get(),
            timezone=timezone.utc,
            symbols=symbols,
            warmup_bars=int(self.live_warmup_var.get()),
        )
        strategy_cfg = StrategyConfig(
            short_window=int(self.backtest_short_var.get()),
            long_window=int(self.backtest_long_var.get()),
            ml_enabled=self.live_enable_ml_var.get(),
            ml_model_path=self.live_ml_model_path_var.get(),
            ml_feature_lookback=int(self.ml_lookback_var.get()),
        )
        engine = EngineConfig(
            strategy=strategy_cfg,
            initial_equity=float(self.live_equity_var.get()),
            commission_per_trade=0.0,
            slippage_bps=float(self.live_slippage_var.get()),
        )
        contracts = {
            symbol: ContractSpec(
                symbol=symbol,
                sec_type=self.ib_sec_type_var.get(),
                exchange=self.ib_exchange_var.get(),
                currency=self.ib_currency_var.get(),
            )
            for symbol in symbols
        }
        broker = BrokerConfig(
            backend=self.live_backend_var.get(),
            ib_host=self.ib_host_var.get(),
            ib_port=int(self.ib_port_var.get()),
            ib_client_id=int(self.ib_client_var.get()),
            ib_account=self.ib_account_var.get() or None,
            contracts=contracts,
        )
        execution = ExecutionConfig(slip_bps_limit=float(self.live_slippage_var.get()))
        return BacktestConfig(data=data_source, engine=engine, execution=execution, broker=broker)

    # ------------------------------------------------------------------
    # Utility helpers
    @staticmethod
    def _merge_bars(data: Dict[str, List[Bar]]) -> List[Bar]:
        bars = list(itertools.chain.from_iterable(data.values()))
        bars.sort(key=lambda bar: bar.timestamp)
        return bars

    @staticmethod
    def _parse_symbols(raw: str) -> List[str]:
        symbols = [sym.strip() for sym in raw.split(",") if sym.strip()]
        if not symbols:
            raise ValueError("At least one symbol must be provided.")
        return symbols

    def _write_backtest_output(self, text: str) -> None:
        if not self.backtest_output:
            return
        self.backtest_output.configure(state=tk.NORMAL)
        self.backtest_output.insert(tk.END, text + "\n")
        self.backtest_output.see(tk.END)
        self.backtest_output.configure(state=tk.DISABLED)

    def _write_ml_output(self, text: str) -> None:
        if not self.ml_output:
            return
        self.ml_output.configure(state=tk.NORMAL)
        self.ml_output.insert(tk.END, text + "\n")
        self.ml_output.see(tk.END)
        self.ml_output.configure(state=tk.DISABLED)

    def _append_log(self, message: str) -> None:
        self.logger.info(message)
        if not self.log_text:
            return
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _display_error(self, title: str, message: str) -> None:
        messagebox.showerror(title, message)
        self._append_log(f"{title}: {message}")
        self._set_status(f"{title} – see logs.")

    def _set_status(self, text: str) -> None:
        self.status_var.set(text)

    def _switch_to_simple_mode(self) -> None:
        """Switch to the beginner-friendly Simple Mode interface."""
        response = messagebox.askyesno(
            "Switch to Simple Mode",
            "Switch to Simple Mode?\n\n"
            "Simple Mode is perfect for beginners who want to:\n"
            "• Use FSD (Full Self-Driving) AI trading\n"
            "• See only essential options (capital and risk level)\n"
            "• Just click START and let the robot do everything\n\n"
            "You can always switch back to Advanced Mode later.\n\n"
            "Continue?"
        )

        if response:
            self.root.destroy()
            from .simple_gui import SimpleGUI
            SimpleGUI().run()

    # ------------------------------------------------------------------
    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    TradingGUI().run()


if __name__ == "__main__":
    main()
