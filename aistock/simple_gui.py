"""
Simple beginner-friendly GUI for AIStock Robot.

This interface is designed for users who:
- Are new to stock trading
- Want to use FSD (Full Self-Driving) mode
- Don't want to see complex configuration options
- Just want to "turn on the robot and relax"
"""

from __future__ import annotations

import threading
import tkinter as tk
import tkinter.font as tkfont
from contextlib import suppress
from datetime import timezone
from decimal import Decimal
from pathlib import Path
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING, Callable, Literal, Protocol, TypedDict, cast

from .config import (
    BacktestConfig,
    BrokerConfig,
    ContractSpec,
    DataSource,
    EngineConfig,
    ExecutionConfig,
    StrategyConfig,
)
from .factories import SessionFactory
from .fsd import FSDConfig
from .interfaces.decision import SupportsGuiLogCallback
from .logging import configure_logger
from .runtime_settings import load_runtime_settings

if TYPE_CHECKING:
    from .session.coordinator import TradingCoordinator

# from .setup import FirstTimeSetupWizard  # Module doesn't exist - disable for now


VolatilityBias = Literal['high', 'low', 'balanced']


class GuiRiskConfig(TypedDict):
    max_capital_pct: float
    time_limit: int
    learning_rate: float
    exploration_rate: float
    confidence_threshold: float
    min_liquidity_volume: int
    confidence_decay: float
    decay_start_minutes: int
    max_concurrent_positions: int
    max_capital_per_position_pct: float
    max_stocks: int
    timeframes: list[str]
    volatility_bias: VolatilityBias
    max_loss_per_trade_pct: float


class TradeSnapshot(TypedDict, total=False):
    timestamp: object
    symbol: object
    quantity: object
    price: object
    realised_pnl: object


class SessionSnapshot(TypedDict, total=False):
    equity: object
    cash: object
    trades: list[TradeSnapshot]
    fsd: object


class _KeyEvent(Protocol):
    keysym: str


class _MouseWheelEvent(Protocol):
    delta: int


class _ConfigureEvent(Protocol):
    width: int


class StopControllerProtocol(Protocol):
    def request_stop(self, reason: str) -> None:
        ...


class CapitalManagerProtocol(Protocol):
    def get_stats(self) -> dict[str, object]:
        ...


class RiskConfigProtocol(Protocol):
    max_daily_loss_pct: float
    max_drawdown_pct: float


class RiskProtocol(Protocol):
    config: RiskConfigProtocol


class SessionProtocol(Protocol):
    risk: RiskProtocol
    decision_engine: object
    stop_controller: StopControllerProtocol | None
    capital_manager: CapitalManagerProtocol | None

    def start(self) -> None:
        ...

    def stop(self) -> None:
        ...

    def snapshot(self) -> dict[str, object]:
        ...


class SimpleGUI:
    """
    Beginner-friendly interface with just 3 questions:
    1. How much money?
    2. Risk level?
    3. Click START!
    """

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title('AIStock Robot - FSD Mode')
        self.root.geometry('1000x900')  # Larger default size
        self.root.resizable(True, True)  # Allow window resizing
        self.root.configure(bg='#f5f7fb')

        # Set minimum window size
        self.root.minsize(900, 700)

        self.runtime_settings = load_runtime_settings()
        self.logger = configure_logger('SimpleGUI', level=self.runtime_settings.log_level, structured=False)

        self._init_fonts()
        self._configure_style()
        self._init_variables()

        # Check if first-time setup is needed
        self._run_first_time_setup_if_needed()

        self._build_layout()

        self.root.after(1000, self._update_dashboard)

    def _init_fonts(self) -> None:
        try:
            families = tkfont.families(self.root)
            available: set[str] = {name.lower() for name in families}
        except tk.TclError:
            available = set()

        default_family = tkfont.nametofont('TkDefaultFont').actual('family')
        if 'segoe ui' in available:
            self.font_family = 'Segoe UI'
        else:
            self.font_family = default_family

    def _font(self, size: int, *, weight: str = 'normal') -> tuple[str, int] | tuple[str, int, str]:
        if weight == 'normal':
            return (self.font_family, size)
        return (self.font_family, size, weight)

    def _configure_style(self) -> None:
        font_spec = f'{{{self.font_family}}} 11' if ' ' in self.font_family else f'{self.font_family} 11'
        option_add = cast(Callable[[str, str], None], self.root.option_add)
        option_add('*Font', font_spec)
        style = ttk.Style()
        with suppress(tk.TclError):
            style.theme_use('clam')

        # Large button for START
        style.configure('Start.TButton', font=self._font(18, weight='bold'), padding=20)
        style.map(
            'Start.TButton',
            background=[('!disabled', '#00c853'), ('pressed', '#00a043')],
            foreground=[('!disabled', 'white')],
        )

        # Stop button
        style.configure('Stop.TButton', font=self._font(14, weight='bold'), padding=12)
        style.map(
            'Stop.TButton',
            background=[('!disabled', '#ff1744'), ('pressed', '#d50000')],
            foreground=[('!disabled', 'white')],
        )

        # Emergency stop button (more prominent red)
        style.configure('Emergency.TButton', font=self._font(12, weight='bold'), padding=10)
        style.map(
            'Emergency.TButton',
            background=[('!disabled', '#b71c1c'), ('pressed', '#7f0000')],
            foreground=[('!disabled', 'white')],
        )

    def _init_variables(self) -> None:
        # Simple user inputs
        self.capital_var = tk.StringVar(value='200')
        self.risk_level_var = tk.StringVar(value='conservative')
        self.investment_goal_var = tk.StringVar(value='steady_growth')
        self.max_loss_per_trade_var = tk.StringVar(value='5')  # percentage

        # Trading mode selection (2 modes: ibkr_paper, ibkr_live)
        self.trading_mode_var = tk.StringVar(value='ibkr_paper')  # Default: IBKR paper (safe)
        self.allow_extended_hours_var = tk.BooleanVar(value=False)  # Default: regular market hours only

        # IBKR runtime settings
        self.ibkr_settings = self.runtime_settings.ibkr
        self.ibkr_account = self.ibkr_settings.account_id
        self.ibkr_client_id = self.ibkr_settings.client_id
        self.ibkr_host = self.ibkr_settings.host
        self.ibkr_paper_port = self.ibkr_settings.paper_port
        self.ibkr_live_port = self.ibkr_settings.live_port
        self._ibkr_account_display = self.ibkr_account or 'Not configured (set IBKR_ACCOUNT_ID in .env)'
        self.user_timezone = self.runtime_settings.timezone

        # Default configurations (hidden from user)
        self.data_folder = 'data/historical/stocks'  # FSD mode: stocks only
        # Symbols are discovered at session start so the IBKR scanner uses the currently selected mode (paper vs live).
        self.symbols: list[str] = []

        # Session state
        self.session: TradingCoordinator | None = None  # TradingCoordinator from new modular architecture
        self._stop_in_progress = False
        self._logged_trade_ids: set[str] = set()
        self._session_stop_after_id: str | None = None

        self.trade_tempo_var = tk.StringVar(value='balanced')

        # Safety limits (hard caps the AI must respect)
        self.max_daily_loss_pct_var = tk.StringVar(value='5')
        self.max_drawdown_pct_var = tk.StringVar(value='15')
        self.max_trades_per_hour_var = tk.StringVar(value='20')
        self.max_trades_per_day_var = tk.StringVar(value='100')
        self.chase_threshold_pct_var = tk.StringVar(value='5')
        self.news_volume_multiplier_var = tk.StringVar(value='5')
        self.end_of_day_minutes_var = tk.StringVar(value='30')

        # Dashboard metrics
        self.balance_var = tk.StringVar(value='$0.00')
        self.profit_var = tk.StringVar(value='$0.00')
        self.status_var = tk.StringVar(value='🤖 Ready to start')
        self.activity_text: tk.Text | None = None

        # Session time limit (user editable)
        self.session_time_limit_var = tk.StringVar(value='240')  # 4 hours default

        # Minimum balance protection (new feature)
        self.minimum_balance_var = tk.StringVar(value='100')  # Default: Don't go below $100
        self.minimum_balance_enabled_var = tk.BooleanVar(value=True)  # Enabled by default

        # Capital management (profit withdrawal)
        self.enable_withdrawal_var = tk.BooleanVar(value=False)  # Disabled by default
        self.target_capital_var = tk.StringVar(value='200')  # Will be set to initial capital
        self.withdrawal_threshold_var = tk.StringVar(value='5000')  # Default: $5k threshold
        self.withdrawal_frequency_var = tk.StringVar(value='Daily')  # Daily, Weekly, Monthly

        # Stop controls
        self.enable_eod_flatten_var = tk.BooleanVar(value=False)  # Disabled by default
        self.eod_flatten_time_var = tk.StringVar(value='15:45')  # 3:45 PM ET (15 min before close)
        self.auto_liquidate_on_stop_var = tk.BooleanVar(value=False)  # Disabled by default

        # Withdrawal stats (updated during trading)
        self.total_withdrawn_var = tk.StringVar(value='$0.00')
        self.last_withdrawal_var = tk.StringVar(value='Never')

    def _discover_available_symbols(self) -> list[str]:
        """
        FSD Market-Wide Stock Discovery.

        Discovery modes:
        1. IBKR Market Scanner (when connected): Scan ENTIRE stock market
           - Uses IBKR's market scanner API
           - Filters by liquidity, price range, volume
           - Can discover ANY tradeable stock
           - ✅ NOW IMPLEMENTED!

        2. Local Data Directory (fallback): Scan data/historical/stocks/
           - Used for backtesting and when IBKR not connected
           - Scans all CSV files in directory

        The AI will autonomously choose which discovered stocks to trade based on:
        - User's risk preferences (Conservative/Moderate/Aggressive)
        - Liquidity (volume)
        - Price range
        - Volatility characteristics
        - Technical indicator signals

        Returns:
            List of all available/discovered stock symbols (e.g., ['AAPL', 'MSFT', ...])
        """
        # Try IBKR market scanner first (if available)
        scanner_symbols = self._try_ibkr_scanner()
        if scanner_symbols:
            self.logger.info(
                'fsd_ibkr_scanner_success', extra={'symbols_found': len(scanner_symbols), 'source': 'ibkr_live_scanner'}
            )
            return scanner_symbols

        # Fallback to local data directory discovery
        data_dir = Path(self.data_folder)

        if not data_dir.exists():
            self.logger.warning('data_directory_not_found', extra={'path': str(data_dir)})
            # Fallback to default symbols if directory doesn't exist
            return ['AAPL', 'MSFT', 'GOOGL']

        # Scan for all CSV files in data directory
        csv_files = list(data_dir.glob('*.csv'))

        if not csv_files:
            self.logger.warning('no_csv_files_found', extra={'path': str(data_dir)})
            return ['AAPL', 'MSFT', 'GOOGL']

        # Extract symbol names from filenames (e.g., "AAPL.csv" -> "AAPL")
        symbols = [f.stem for f in csv_files if f.stem != '.gitkeep']

        self.logger.info(
            'fsd_auto_discovery_complete',
            extra={
                'symbols_found': len(symbols),
                'symbols': symbols[:10],  # Log first 10 for brevity
                'total_available': len(symbols),
            },
        )

        return symbols

    def _try_ibkr_scanner(self) -> list[str]:
        """
        Try to use IBKR market scanner for live stock discovery.

        Returns:
            List of symbols from scanner, or empty list if scanner unavailable/fails
        """
        try:
            # Check if scanner is available
            from .scanner import IBAPI_AVAILABLE, scan_for_fsd

            if not IBAPI_AVAILABLE:
                self.logger.info('scanner_unavailable_no_ibapi')
                return []

            # Try to scan with FSD-optimized defaults
            # Uses conservative filters to ensure quality stocks
            self.logger.info('scanner_attempting_live_scan')

            if self.ibkr_client_id is None:
                self.logger.info('scanner_skipped_missing_client_id')
                return []

            trading_mode = self.trading_mode_var.get()
            port = self.ibkr_paper_port if trading_mode == 'ibkr_paper' else self.ibkr_live_port
            scanner_client_id = self.ibkr_client_id + 1

            symbols = scan_for_fsd(
                min_price=1.0,
                max_price=10000.0,
                min_volume=100000,  # 100K shares/day minimum
                max_results=100,  # Top 100 stocks
                host=self.ibkr_host,
                port=port,
                client_id=scanner_client_id,
            )

            if symbols:
                self.logger.info('scanner_success', extra={'symbols_discovered': len(symbols), 'sample': symbols[:10]})
                return symbols
            else:
                self.logger.info('scanner_no_results')
                return []

        except TimeoutError:
            self.logger.warning('scanner_timeout', extra={'hint': 'IBKR may not be running'})
            return []
        except ConnectionRefusedError:
            self.logger.warning('scanner_connection_refused', extra={'hint': 'Start IBKR Gateway/TWS first'})
            return []
        except Exception as e:
            self.logger.warning('scanner_failed', extra={'error': str(e), 'type': type(e).__name__})
            return []

    def _run_first_time_setup_if_needed(self) -> None:
        """Run first-time setup wizard if needed."""
        # First-time setup wizard module doesn't exist - system works without it
        # Users configure settings directly via the GUI (capital, risk, mode, etc.)
        state_dir = Path('state')
        state_dir.mkdir(parents=True, exist_ok=True)
        self.logger.info('first_time_setup_skipped', extra={'reason': 'wizard_module_not_implemented'})
        # System continues normally - all configuration via GUI

    def _build_layout(self) -> None:
        # Header with mode switching
        header = tk.Frame(self.root, bg='#1a237e', padx=24, pady=20)
        header.pack(fill=tk.X)

        # Title and subtitle
        title_frame = tk.Frame(header, bg='#1a237e')
        title_frame.pack()

        tk.Label(
            title_frame,
            text='🤖 AIStock Robot - Full Self-Driving',
            font=self._font(24, weight='bold'),
            fg='white',
            bg='#1a237e',
        ).pack()
        tk.Label(
            title_frame,
            text='Turn on AI trading and let the robot do everything!',
            font=self._font(13),
            fg='#c5cae9',
            bg='#1a237e',
        ).pack(pady=(6, 0))

        # Mode switching buttons
        mode_frame = tk.Frame(header, bg='#1a237e')
        mode_frame.pack(pady=(15, 0))

        tk.Label(mode_frame, text='Trading Mode:', font=self._font(11, weight='bold'), fg='white', bg='#1a237e').pack(
            side=tk.LEFT, padx=(0, 10)
        )

        # FSD button (current mode - highlighted)
        fsd_btn = tk.Button(
            mode_frame,
            text='🤖 FSD (Current)',
            font=self._font(11, weight='bold'),
            bg='#00c853',
            fg='white',
            activebackground='#00a043',
            activeforeground='white',
            relief=tk.RAISED,
            borderwidth=3,
            padx=15,
            pady=8,
            cursor='arrow',
            state=tk.DISABLED,
        )
        fsd_btn.pack(side=tk.LEFT, padx=5)

        # Note: Other modes (Headless, BOT) have been removed in v2.0
        # FSD (Full Self-Driving) is now the only mode available

        # Create scrollable main container
        # Container for canvas and scrollbar
        container = tk.Frame(self.root, bg='#f5f7fb')
        container.pack(fill=tk.BOTH, expand=True)

        # Canvas for scrolling
        canvas = tk.Canvas(container, bg='#f5f7fb', highlightthickness=0)
        canvas_yview = cast(Callable[..., tuple[float, float] | None], canvas.yview)
        scrollbar = ttk.Scrollbar(container, orient='vertical', command=canvas_yview)

        # Scrollable frame inside canvas
        scrollable_frame = ttk.Frame(canvas, padding=30)

        # Configure canvas scrolling
        def on_frame_configure(event: object) -> None:
            canvas.configure(scrollregion=canvas.bbox('all'))

        scrollable_frame.bind('<Configure>', on_frame_configure)

        canvas_frame = canvas.create_window((0, 0), window=scrollable_frame, anchor='nw')

        # Update scroll region when window is resized
        def on_canvas_configure(event: object) -> None:
            configure_event = cast(_ConfigureEvent, event)
            canvas.itemconfig(canvas_frame, width=configure_event.width)

        canvas.bind('<Configure>', on_canvas_configure)
        canvas.configure(yscrollcommand=scrollbar.set)

        # Pack canvas and scrollbar
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Enable mouse wheel scrolling
        def on_mousewheel(event: object) -> None:
            wheel_event = cast(_MouseWheelEvent, event)
            canvas.yview_scroll(int(-1 * (wheel_event.delta / 120)), 'units')

        canvas.bind_all('<MouseWheel>', on_mousewheel)

        # Enable keyboard scrolling
        def on_keypress(event: object) -> None:
            key_event = cast(_KeyEvent, event)
            if key_event.keysym == 'Prior':  # Page Up
                canvas.yview_scroll(-1, 'pages')
            elif key_event.keysym == 'Next':  # Page Down
                canvas.yview_scroll(1, 'pages')
            elif key_event.keysym == 'Home':
                canvas.yview_moveto(0)
            elif key_event.keysym == 'End':
                canvas.yview_moveto(1)
            elif key_event.keysym == 'Up':
                canvas.yview_scroll(-1, 'units')
            elif key_event.keysym == 'Down':
                canvas.yview_scroll(1, 'units')

        self.root.bind('<Prior>', on_keypress)  # Page Up
        self.root.bind('<Next>', on_keypress)  # Page Down
        self.root.bind('<Home>', on_keypress)
        self.root.bind('<End>', on_keypress)
        self.root.bind('<Up>', on_keypress)
        self.root.bind('<Down>', on_keypress)

        # Store canvas reference for later use
        self.main_canvas = canvas

        # Main container (now inside scrollable frame)
        main = scrollable_frame

        # Question 1: How much money?
        q1_frame = ttk.LabelFrame(main, text='💰 How much money do you want to start with?', padding=20)
        q1_frame.pack(fill=tk.X, pady=(0, 20))

        money_frame = tk.Frame(q1_frame)
        money_frame.pack()
        tk.Label(money_frame, text='$', font=self._font(20, weight='bold')).pack(side=tk.LEFT, padx=(0, 5))
        money_entry = tk.Entry(
            money_frame,
            textvariable=self.capital_var,
            font=self._font(20),
            width=12,
            justify=tk.CENTER,
            bg='white',
            relief=tk.SUNKEN,
            borderwidth=2,
        )
        money_entry.pack(side=tk.LEFT)
        money_entry.focus_set()  # Set initial focus so it's clearly editable
        money_entry.config(state=tk.NORMAL)  # Ensure it's editable
        tk.Label(money_frame, text='dollars', font=self._font(14)).pack(side=tk.LEFT, padx=(10, 0))

        # Question 2: Risk level
        q2_frame = ttk.LabelFrame(main, text='📊 How much risk are you comfortable with?', padding=20)
        q2_frame.pack(fill=tk.X, pady=(0, 20))

        risk_options = [
            ('conservative', '🛡️ Conservative', 'Safe & slow gains. Uses max 30% capital, tight stops.'),
            ('moderate', '⚖️ Moderate', 'Balanced approach. Uses max 50% capital, balanced risk.'),
            ('aggressive', '🚀 Aggressive', 'Risky & fast gains. Uses max 70% capital, loose stops.'),
        ]

        for value, label, description in risk_options:
            radio_frame = tk.Frame(q2_frame, bg='white', relief=tk.RIDGE, borderwidth=1)
            radio_frame.pack(fill=tk.X, pady=5)

            rb = ttk.Radiobutton(radio_frame, text=label, variable=self.risk_level_var, value=value)
            rb.pack(anchor='w', padx=10, pady=5)

            tk.Label(radio_frame, text=description, font=self._font(9), fg='#666666', bg='white').pack(
                anchor='w', padx=30, pady=(0, 5)
            )

        # Question 3: Investment goal
        q3_frame = ttk.LabelFrame(main, text="🎯 What's your investment goal?", padding=20)
        q3_frame.pack(fill=tk.X, pady=(0, 20))

        goal_options = [
            ('quick_gains', '⚡ Quick Gains', 'Day trading style. AI trades frequently, exits quickly.'),
            ('steady_growth', '📈 Steady Growth', 'Swing trading style. AI holds positions longer for bigger moves.'),
        ]

        for value, label, description in goal_options:
            radio_frame = tk.Frame(q3_frame, bg='white', relief=tk.RIDGE, borderwidth=1)
            radio_frame.pack(fill=tk.X, pady=5)

            rb = ttk.Radiobutton(radio_frame, text=label, variable=self.investment_goal_var, value=value)
            rb.pack(anchor='w', padx=10, pady=5)

            tk.Label(radio_frame, text=description, font=self._font(9), fg='#666666', bg='white').pack(
                anchor='w', padx=30, pady=(0, 5)
            )

        # Question 4: Session time limit
        q4_frame = ttk.LabelFrame(main, text='⏱️ How long should the robot run?', padding=20)
        q4_frame.pack(fill=tk.X, pady=(0, 20))

        time_frame = tk.Frame(q4_frame)
        time_frame.pack()

        tk.Label(time_frame, text='Run the robot for up to:', font=self._font(11)).pack(side=tk.LEFT, padx=(0, 10))

        time_entry = tk.Entry(
            time_frame,
            textvariable=self.session_time_limit_var,
            font=self._font(14),
            width=8,
            justify=tk.CENTER,
            bg='white',
            relief=tk.SUNKEN,
            borderwidth=2,
        )
        time_entry.pack(side=tk.LEFT)
        time_entry.config(state=tk.NORMAL)  # Ensure it's editable

        tk.Label(time_frame, text='minutes', font=self._font(11)).pack(side=tk.LEFT, padx=(5, 0))

        tk.Label(
            q4_frame,
            text='💡 Examples: 60 min (1 hour), 240 min (4 hours), 480 min (full trading day). Robot stops automatically after this time.',
            font=self._font(9),
            fg='#666666',
            wraplength=800,
            justify='left',
        ).pack(anchor='w', pady=(10, 0))

        # Question 5: Max loss per trade
        q5_frame = ttk.LabelFrame(main, text="🛑 Maximum loss you're okay with PER TRADE?", padding=20)
        q5_frame.pack(fill=tk.X, pady=(0, 20))

        loss_info = tk.Frame(q5_frame)
        loss_info.pack(fill=tk.X)

        tk.Label(loss_info, text="If a trade goes bad, stop it when I've lost:", font=self._font(11)).pack(
            side=tk.LEFT, padx=(0, 10)
        )

        loss_entry = tk.Entry(
            loss_info,
            textvariable=self.max_loss_per_trade_var,
            font=self._font(14),
            width=6,
            justify=tk.CENTER,
            bg='white',
            relief=tk.SUNKEN,
            borderwidth=2,
        )
        loss_entry.pack(side=tk.LEFT)
        loss_entry.config(state=tk.NORMAL)  # Ensure it's editable

        tk.Label(loss_info, text='% of that trade', font=self._font(11)).pack(side=tk.LEFT, padx=(5, 0))

        tk.Label(
            q5_frame,
            text='💡 Example: With $200 capital, Conservative = $60 max deployed. If you trade $30 and set 5%, max loss = $1.50 per trade.',
            font=self._font(9),
            fg='#666666',
            wraplength=800,
            justify='left',
        ).pack(anchor='w', pady=(10, 0))

        # Question 6: Trade tempo / volatility preference
        q6_frame = ttk.LabelFrame(main, text='⚡ How fast do you want results?', padding=20)
        q6_frame.pack(fill=tk.X, pady=(0, 20))

        tempo_options = [
            ('steady', '🛡️ Steady & Low Volatility', 'Prefers calmer stocks, fewer trades, tighter risk.'),
            ('balanced', '⚖️ Balanced (Default)', 'Blend of stability and opportunity.'),
            ('fast', '🚀 Fast Lane', 'Targets high-volatility tickers for rapid moves and more trades.'),
        ]

        for value, label, description in tempo_options:
            tempo_row = tk.Frame(q6_frame, bg='white', relief=tk.RIDGE, borderwidth=1)
            tempo_row.pack(fill=tk.X, pady=5)

            rb = ttk.Radiobutton(tempo_row, text=label, variable=self.trade_tempo_var, value=value)
            rb.pack(anchor='w', padx=10, pady=5)

            tk.Label(tempo_row, text=description, font=self._font(9), fg='#666666', bg='white').pack(
                anchor='w', padx=30, pady=(0, 5)
            )

        # NEW: Question 5.5: Minimum Balance Protection
        q5_5_frame = ttk.LabelFrame(main, text='🛡️ Minimum Balance Protection (Safety Feature)', padding=20)
        q5_5_frame.pack(fill=tk.X, pady=(0, 20))

        # Option 1: Protection enabled
        protection_enabled_frame = tk.Frame(q5_5_frame, bg='#e8f5e9', relief=tk.RIDGE, borderwidth=2, padx=15, pady=10)
        protection_enabled_frame.pack(fill=tk.X, pady=5)

        protection_enabled_rb = ttk.Radiobutton(
            protection_enabled_frame,
            text='✅ ENABLED - Stop trading if balance would drop below minimum (RECOMMENDED)',
            variable=self.minimum_balance_enabled_var,
            value=True,
        )
        protection_enabled_rb.pack(anchor='w')

        min_balance_entry_frame = tk.Frame(protection_enabled_frame, bg='#e8f5e9')
        min_balance_entry_frame.pack(anchor='w', padx=(25, 0), pady=(10, 5))

        tk.Label(
            min_balance_entry_frame, text='Never let my balance go below: $', font=self._font(11), bg='#e8f5e9'
        ).pack(side=tk.LEFT, padx=(0, 5))

        self.min_balance_entry = tk.Entry(
            min_balance_entry_frame,
            textvariable=self.minimum_balance_var,
            font=self._font(14),
            width=10,
            justify=tk.CENTER,
            bg='white',
            relief=tk.SUNKEN,
            borderwidth=2,
        )
        self.min_balance_entry.pack(side=tk.LEFT)
        self.min_balance_entry.config(state=tk.NORMAL)

        tk.Label(
            protection_enabled_frame,
            text='💡 The bot will refuse to trade if any trade would bring your balance below this amount.\n'
            '   Protects you from losing everything. Also keeps $500+ for IBKR market data requirements.',
            font=self._font(9),
            fg='#2e7d32',
            bg='#e8f5e9',
            wraplength=750,
            justify='left',
        ).pack(anchor='w', padx=(25, 0), pady=(0, 5))

        # Option 2: Protection disabled
        protection_disabled_frame = tk.Frame(q5_5_frame, bg='#fff3e0', relief=tk.RIDGE, borderwidth=1, padx=15, pady=10)
        protection_disabled_frame.pack(fill=tk.X, pady=5)

        protection_disabled_rb = ttk.Radiobutton(
            protection_disabled_frame,
            text='⚠️ DISABLED - Allow trading down to $0 (NOT RECOMMENDED)',
            variable=self.minimum_balance_enabled_var,
            value=False,
        )
        protection_disabled_rb.pack(anchor='w')

        tk.Label(
            protection_disabled_frame,
            text="⚠️ WARNING: Bot can trade until your balance reaches $0. Only disable if you know what you're doing!",
            font=self._font(9),
            fg='#d84315',
            bg='#fff3e0',
            justify='left',
            wraplength=750,
        ).pack(anchor='w', padx=(25, 0), pady=(5, 0))

        # Safety limits (hard caps)
        safety_frame = ttk.LabelFrame(main, text='🧱 Safety Limits (Hard Caps)', padding=20)
        safety_frame.pack(fill=tk.X, pady=(0, 20))

        safety_row1 = tk.Frame(safety_frame)
        safety_row1.pack(fill=tk.X, pady=5)
        tk.Label(safety_row1, text='Max daily loss halt (%):', font=self._font(11)).pack(side=tk.LEFT)
        tk.Entry(
            safety_row1,
            textvariable=self.max_daily_loss_pct_var,
            font=self._font(12),
            width=6,
            justify=tk.CENTER,
            bg='white',
            relief=tk.SUNKEN,
            borderwidth=2,
        ).pack(side=tk.LEFT, padx=(10, 20))
        tk.Label(safety_row1, text='Max drawdown halt (%):', font=self._font(11)).pack(side=tk.LEFT)
        tk.Entry(
            safety_row1,
            textvariable=self.max_drawdown_pct_var,
            font=self._font(12),
            width=6,
            justify=tk.CENTER,
            bg='white',
            relief=tk.SUNKEN,
            borderwidth=2,
        ).pack(side=tk.LEFT, padx=(10, 0))

        safety_row2 = tk.Frame(safety_frame)
        safety_row2.pack(fill=tk.X, pady=5)
        tk.Label(safety_row2, text='Max trades per hour:', font=self._font(11)).pack(side=tk.LEFT)
        tk.Entry(
            safety_row2,
            textvariable=self.max_trades_per_hour_var,
            font=self._font(12),
            width=6,
            justify=tk.CENTER,
            bg='white',
            relief=tk.SUNKEN,
            borderwidth=2,
        ).pack(side=tk.LEFT, padx=(10, 20))
        tk.Label(safety_row2, text='Max trades per day:', font=self._font(11)).pack(side=tk.LEFT)
        tk.Entry(
            safety_row2,
            textvariable=self.max_trades_per_day_var,
            font=self._font(12),
            width=6,
            justify=tk.CENTER,
            bg='white',
            relief=tk.SUNKEN,
            borderwidth=2,
        ).pack(side=tk.LEFT, padx=(10, 0))

        safety_row3 = tk.Frame(safety_frame)
        safety_row3.pack(fill=tk.X, pady=5)
        tk.Label(safety_row3, text='Chase threshold (% move):', font=self._font(11)).pack(side=tk.LEFT)
        tk.Entry(
            safety_row3,
            textvariable=self.chase_threshold_pct_var,
            font=self._font(12),
            width=6,
            justify=tk.CENTER,
            bg='white',
            relief=tk.SUNKEN,
            borderwidth=2,
        ).pack(side=tk.LEFT, padx=(10, 20))
        tk.Label(safety_row3, text='News volume multiplier:', font=self._font(11)).pack(side=tk.LEFT)
        tk.Entry(
            safety_row3,
            textvariable=self.news_volume_multiplier_var,
            font=self._font(12),
            width=6,
            justify=tk.CENTER,
            bg='white',
            relief=tk.SUNKEN,
            borderwidth=2,
        ).pack(side=tk.LEFT, padx=(10, 20))
        tk.Label(safety_row3, text='Stop new trades before close (min):', font=self._font(11)).pack(side=tk.LEFT)
        tk.Entry(
            safety_row3,
            textvariable=self.end_of_day_minutes_var,
            font=self._font(12),
            width=6,
            justify=tk.CENTER,
            bg='white',
            relief=tk.SUNKEN,
            borderwidth=2,
        ).pack(side=tk.LEFT, padx=(10, 0))

        tk.Label(
            safety_frame,
            text='These limits are hard guardrails. The AI will refuse trades that violate them.',
            font=self._font(9),
            fg='#666666',
            wraplength=780,
            justify='left',
        ).pack(anchor='w', pady=(10, 0))

        # Trading Mode Selection (CRITICAL SETTING) - 2 MODES (removed backtest)
        mode_frame = ttk.LabelFrame(main, text='⚡ IBKR Trading Mode (Choose Carefully!)', padding=20)
        mode_frame.pack(fill=tk.X, pady=(0, 20))

        # Mode 1: IBKR Paper Trading (recommended for testing)
        ibkr_paper_frame = tk.Frame(mode_frame, bg='#e3f2fd', relief=tk.RIDGE, borderwidth=2, padx=15, pady=10)
        ibkr_paper_frame.pack(fill=tk.X, pady=5)

        ibkr_paper_rb = ttk.Radiobutton(
            ibkr_paper_frame,
            text="🔵 IBKR PAPER MODE - Practice with IBKR's fake money (RECOMMENDED)",
            variable=self.trading_mode_var,
            value='ibkr_paper',
        )
        ibkr_paper_rb.pack(anchor='w')

        tk.Label(
            ibkr_paper_frame,
            text=f'• Connects to IBKR Paper Trading (Host {self.ibkr_host}, Port {self.ibkr_paper_port})\n'
            "• Uses IBKR's simulated $1.1M fake money\n"
            '• Gets REAL-TIME multi-timeframe market data\n'
            '• No historical warmup — learns as it trades (paper recommended)\n'
            '• Tests IBKR connection without risking real money\n'
            f'⚠️ Requires: IBKR Gateway/TWS + market data subscription ($500 live balance) on port {self.ibkr_paper_port}',
            font=self._font(9),
            fg='#1565c0',
            bg='#e3f2fd',
            justify='left',
        ).pack(anchor='w', padx=(25, 0))

        # Mode 2: IBKR Live Trading (expert - real money!)
        ibkr_live_frame = tk.Frame(mode_frame, bg='#ffebee', relief=tk.RIDGE, borderwidth=3, padx=15, pady=10)
        ibkr_live_frame.pack(fill=tk.X, pady=5)

        ibkr_live_rb = ttk.Radiobutton(
            ibkr_live_frame,
            text='🔴 IBKR LIVE MODE - REAL MONEY TRADING (EXPERT ONLY)',
            variable=self.trading_mode_var,
            value='ibkr_live',
        )
        ibkr_live_rb.pack(anchor='w')

        tk.Label(
            ibkr_live_frame,
            text=f'• Connects to IBKR LIVE Trading account (Port {self.ibkr_live_port})\n'
            f'• Uses REAL MONEY from account: {self._ibkr_account_display}\n'
            f'• Gets REAL-TIME multi-timeframe market data\n'
            f'• No historical warmup — learns as it trades (paper recommended first)\n'
            f'• Requires $500+ account balance for market data\n'
            f'• Requires IBKR Gateway/TWS running on port {self.ibkr_live_port}\n'
            f'🚨 WARNING: REAL MONEY AT RISK - LOSSES ARE PERMANENT!',
            font=self._font(9),
            fg='#c62828',
            bg='#ffebee',
            justify='left',
            wraplength=750,
        ).pack(anchor='w', padx=(25, 0))

        allow_extended_hours_check = ttk.Checkbutton(
            mode_frame,
            text='🕒 Allow extended hours (pre-market + after-hours)',
            variable=self.allow_extended_hours_var,
        )
        allow_extended_hours_check.pack(anchor='w', pady=(10, 0))

        tk.Label(
            mode_frame,
            text='Default is regular market hours only. Extended hours trading has wider spreads and thinner liquidity.',
            font=self._font(9),
            fg='#666666',
            justify='left',
            wraplength=780,
        ).pack(anchor='w', padx=(25, 0))

        # Capital Management (Profit Withdrawal)
        capital_frame = ttk.LabelFrame(main, text='💰 Capital Management (Optional)', padding=20)
        capital_frame.pack(fill=tk.X, pady=(0, 20))

        enable_withdrawal_check = ttk.Checkbutton(
            capital_frame,
            text='✅ Enable Automatic Profit Withdrawal (Fixed Capital Mode)',
            variable=self.enable_withdrawal_var,
        )
        enable_withdrawal_check.pack(anchor='w', pady=(0, 10))

        tk.Label(
            capital_frame,
            text='Maintains fixed trading capital by withdrawing excess profits automatically.\n'
            'Prevents position sizes from growing indefinitely and locks in gains.',
            font=self._font(9),
            fg='#666666',
            justify='left',
        ).pack(anchor='w', padx=(25, 0), pady=(0, 10))

        # Capital settings row
        capital_settings_row = tk.Frame(capital_frame)
        capital_settings_row.pack(fill=tk.X, padx=(25, 0), pady=5)

        tk.Label(capital_settings_row, text='Target Capital:', font=self._font(11)).pack(side=tk.LEFT)
        tk.Label(capital_settings_row, text='$', font=self._font(11)).pack(side=tk.LEFT, padx=(10, 0))
        tk.Entry(
            capital_settings_row,
            textvariable=self.target_capital_var,
            font=self._font(12),
            width=10,
            justify=tk.CENTER,
            bg='white',
            relief=tk.SUNKEN,
            borderwidth=2,
        ).pack(side=tk.LEFT)

        tk.Label(capital_settings_row, text='Withdrawal Threshold:', font=self._font(11)).pack(
            side=tk.LEFT, padx=(20, 0)
        )
        tk.Label(capital_settings_row, text='$', font=self._font(11)).pack(side=tk.LEFT, padx=(10, 0))
        tk.Entry(
            capital_settings_row,
            textvariable=self.withdrawal_threshold_var,
            font=self._font(12),
            width=10,
            justify=tk.CENTER,
            bg='white',
            relief=tk.SUNKEN,
            borderwidth=2,
        ).pack(side=tk.LEFT)

        tk.Label(capital_settings_row, text='Frequency:', font=self._font(11)).pack(side=tk.LEFT, padx=(20, 0))
        frequency_dropdown = ttk.Combobox(
            capital_settings_row,
            textvariable=self.withdrawal_frequency_var,
            values=['Daily', 'Weekly', 'Monthly'],
            state='readonly',
            width=10,
            font=self._font(11),
        )
        frequency_dropdown.pack(side=tk.LEFT, padx=(10, 0))

        tk.Label(
            capital_frame,
            text='💡 Example: Target=$100k, Threshold=$5k → When equity reaches $105k, withdraw $5k',
            font=self._font(9),
            fg='#2e7d32',
            justify='left',
        ).pack(anchor='w', padx=(25, 0), pady=(10, 0))

        # Stop Controls
        stop_frame = ttk.LabelFrame(main, text='🛑 Stop Controls (Safety)', padding=20)
        stop_frame.pack(fill=tk.X, pady=(0, 20))

        auto_liquidate_check = ttk.Checkbutton(
            stop_frame,
            text='🧯 Auto-liquidate positions when pressing STOP ROBOT',
            variable=self.auto_liquidate_on_stop_var,
        )
        auto_liquidate_check.pack(anchor='w', pady=(0, 10))

        tk.Label(
            stop_frame,
            text='If enabled, STOP ROBOT will request a graceful shutdown (cancel orders + close positions).',
            font=self._font(9),
            fg='#666666',
            justify='left',
        ).pack(anchor='w', padx=(25, 0), pady=(0, 10))

        enable_eod_check = ttk.Checkbutton(
            stop_frame,
            text='✅ Enable End-of-Day Auto-Flatten (closes all positions before market close)',
            variable=self.enable_eod_flatten_var,
        )
        enable_eod_check.pack(anchor='w', pady=(0, 10))

        tk.Label(
            stop_frame,
            text='Automatically closes all positions at specified time before market close.\n'
            'Handles both regular closes (4 PM ET) and early closes (1 PM ET) correctly.',
            font=self._font(9),
            fg='#666666',
            justify='left',
        ).pack(anchor='w', padx=(25, 0), pady=(0, 10))

        eod_time_row = tk.Frame(stop_frame)
        eod_time_row.pack(fill=tk.X, padx=(25, 0), pady=5)

        tk.Label(eod_time_row, text='Flatten Time (ET):', font=self._font(11)).pack(side=tk.LEFT)
        tk.Entry(
            eod_time_row,
            textvariable=self.eod_flatten_time_var,
            font=self._font(12),
            width=8,
            justify=tk.CENTER,
            bg='white',
            relief=tk.SUNKEN,
            borderwidth=2,
        ).pack(side=tk.LEFT, padx=(10, 0))
        tk.Label(eod_time_row, text='(Format: HH:MM, e.g., 15:45 for 3:45 PM)', font=self._font(9), fg='#666666').pack(
            side=tk.LEFT, padx=(10, 0)
        )

        tk.Label(
            stop_frame,
            text='💡 Default 15:45 = 15 minutes before regular close. Adjusts for early closes automatically.',
            font=self._font(9),
            fg='#2e7d32',
            justify='left',
        ).pack(anchor='w', padx=(25, 0), pady=(10, 0))

        # Start button
        button_frame = tk.Frame(main)
        button_frame.pack(pady=20)

        self.start_btn = ttk.Button(
            button_frame, text='🚀 START ROBOT (FSD Mode)', style='Start.TButton', command=self._start_robot
        )
        self.start_btn.pack(side=tk.LEFT, padx=10)

        self.stop_btn = ttk.Button(button_frame, text='⏹️ STOP ROBOT', style='Stop.TButton', command=self._stop_robot)
        # Stop button is hidden initially

        self.emergency_stop_btn = ttk.Button(
            button_frame, text='🛑 EMERGENCY STOP', style='Emergency.TButton', command=self._emergency_stop
        )
        self.emergency_stop_btn.pack(side=tk.LEFT, padx=10)
        self.emergency_stop_btn.config(state=tk.DISABLED)  # Disabled until session starts

        # Dashboard
        dashboard = ttk.LabelFrame(main, text='📊 Dashboard', padding=15)
        dashboard.pack(fill=tk.BOTH, expand=True, pady=(20, 0))

        metrics_frame = tk.Frame(dashboard)
        metrics_frame.pack(fill=tk.X, pady=(0, 15))

        # Balance
        balance_card = tk.Frame(metrics_frame, bg='#e3f2fd', relief=tk.RAISED, borderwidth=2)
        balance_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)
        tk.Label(balance_card, text='💵 Balance', font=self._font(11, weight='bold'), bg='#e3f2fd').pack(pady=(10, 0))
        tk.Label(
            balance_card, textvariable=self.balance_var, font=self._font(20, weight='bold'), bg='#e3f2fd', fg='#1565c0'
        ).pack(pady=(0, 10))

        # Profit
        profit_card = tk.Frame(metrics_frame, bg='#e8f5e9', relief=tk.RAISED, borderwidth=2)
        profit_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)
        tk.Label(profit_card, text='📈 Profit/Loss', font=self._font(11, weight='bold'), bg='#e8f5e9').pack(
            pady=(10, 0)
        )
        self.profit_label = tk.Label(
            profit_card, textvariable=self.profit_var, font=self._font(20, weight='bold'), bg='#e8f5e9', fg='#2e7d32'
        )
        self.profit_label.pack(pady=(0, 10))

        # Status
        status_card = tk.Frame(metrics_frame, bg='#fff3e0', relief=tk.RAISED, borderwidth=2)
        status_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)
        tk.Label(status_card, text='🤖 AI Status', font=self._font(11, weight='bold'), bg='#fff3e0').pack(pady=(10, 0))
        tk.Label(
            status_card,
            textvariable=self.status_var,
            font=self._font(12, weight='bold'),
            bg='#fff3e0',
            fg='#e65100',
            wraplength=200,
        ).pack(pady=(0, 10))

        # NEW: Minimum Balance Protection Card
        self.min_balance_display_var = tk.StringVar(value='$0.00')
        self.min_balance_card = tk.Frame(metrics_frame, bg='#e8f5e9', relief=tk.RAISED, borderwidth=2)
        self.min_balance_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)
        tk.Label(self.min_balance_card, text='🛡️ Min Balance', font=self._font(11, weight='bold'), bg='#e8f5e9').pack(
            pady=(10, 0)
        )
        self.min_balance_display_label = tk.Label(
            self.min_balance_card,
            textvariable=self.min_balance_display_var,
            font=self._font(16, weight='bold'),
            bg='#e8f5e9',
            fg='#2e7d32',
        )
        self.min_balance_display_label.pack(pady=(0, 10))

        # Withdrawal Statistics (Second Row)
        withdrawal_frame = tk.Frame(dashboard)
        withdrawal_frame.pack(fill=tk.X, pady=(10, 15))

        # Total Withdrawn
        withdrawn_card = tk.Frame(withdrawal_frame, bg='#f3e5f5', relief=tk.RAISED, borderwidth=2)
        withdrawn_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)
        tk.Label(withdrawn_card, text='💰 Total Withdrawn', font=self._font(11, weight='bold'), bg='#f3e5f5').pack(
            pady=(10, 0)
        )
        tk.Label(
            withdrawn_card,
            textvariable=self.total_withdrawn_var,
            font=self._font(16, weight='bold'),
            bg='#f3e5f5',
            fg='#6a1b9a',
        ).pack(pady=(0, 10))

        # Last Withdrawal
        last_withdrawal_card = tk.Frame(withdrawal_frame, bg='#fce4ec', relief=tk.RAISED, borderwidth=2)
        last_withdrawal_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)
        tk.Label(
            last_withdrawal_card, text='📅 Last Withdrawal', font=self._font(11, weight='bold'), bg='#fce4ec'
        ).pack(pady=(10, 0))
        tk.Label(
            last_withdrawal_card,
            textvariable=self.last_withdrawal_var,
            font=self._font(12, weight='bold'),
            bg='#fce4ec',
            fg='#ad1457',
        ).pack(pady=(0, 10))

        # Activity log with scrollbar
        tk.Label(dashboard, text='Recent Activity:', font=self._font(11, weight='bold')).pack(anchor='w', pady=(10, 5))

        # Create frame for text and scrollbar
        log_frame = tk.Frame(dashboard)
        log_frame.pack(fill=tk.BOTH, expand=True)

        # Scrollbar
        log_scrollbar = ttk.Scrollbar(log_frame)
        log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Text widget with scrollbar
        self.activity_text = tk.Text(
            log_frame, height=8, state=tk.DISABLED, wrap=tk.WORD, font=self._font(10), yscrollcommand=log_scrollbar.set
        )
        self.activity_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Configure scrollbar
        text_yview = cast(Callable[..., tuple[float, float] | None], self.activity_text.yview)
        log_scrollbar.config(command=text_yview)

        self._log_activity('🤖 Robot initialized and ready to trade')
        self._log_activity('💡 Select your starting capital and risk level, then click START!')

    def _get_risk_config(
        self, risk_level: str, investment_goal: str, trade_tempo: str, max_loss_pct: float
    ) -> GuiRiskConfig:
        """
        Returns FSD configuration based on user preferences.

        Parameters are now TAILORED to user's exact preferences:
        - risk_level: How much capital to deploy
        - investment_goal: Trading frequency and hold time
        - trade_tempo: Desired speed/volatility preference
        - max_loss_pct: Per-trade stop-loss
        """
        # Base configs by risk level
        base_configs: dict[str, GuiRiskConfig] = {
            'conservative': {
                'max_capital_pct': 0.30,  # Use max 30% of capital
                'time_limit': 60,  # 60 minutes max per session
                'learning_rate': 0.0005,
                'exploration_rate': 0.10,  # Less exploration = more conservative
                'confidence_threshold': 0.60,  # FIXED: Was 70%, now 60% (more realistic)
                'min_liquidity_volume': 30000,  # FIXED: Realistic for daily data (was 500K)
                'confidence_decay': 0.10,  # Max decay over session (if no trades)
                'decay_start_minutes': 30,  # Start adapting after 30 min
                'max_concurrent_positions': 3,
                'max_capital_per_position_pct': 15.0,
                'max_stocks': 8,
                'timeframes': ['1m', '5m', '15m'],
                'volatility_bias': 'balanced',
                'max_loss_per_trade_pct': 0.0,
            },
            'moderate': {
                'max_capital_pct': 0.50,  # Use max 50% of capital
                'time_limit': 120,  # 2 hours
                'learning_rate': 0.001,
                'exploration_rate': 0.20,
                'confidence_threshold': 0.55,  # FIXED: Was 60%, now 55% (more trades)
                'min_liquidity_volume': 25000,  # FIXED: Realistic (was 200K)
                'confidence_decay': 0.15,  # Max decay over session
                'decay_start_minutes': 30,
                'max_concurrent_positions': 5,
                'max_capital_per_position_pct': 25.0,
                'max_stocks': 12,
                'timeframes': ['1m', '5m', '15m'],
                'volatility_bias': 'balanced',
                'max_loss_per_trade_pct': 0.0,
            },
            'aggressive': {
                'max_capital_pct': 0.70,  # Use max 70% of capital
                'time_limit': 180,  # 3 hours
                'learning_rate': 0.002,
                'exploration_rate': 0.35,  # More exploration = more aggressive
                'confidence_threshold': 0.45,  # FIXED: Was 50%, now 45% (many more trades)
                'min_liquidity_volume': 10000,  # FIXED: Realistic (was 100K)
                'confidence_decay': 0.20,  # Max decay over session
                'decay_start_minutes': 20,  # More aggressive = faster adaptation
                'max_concurrent_positions': 7,
                'max_capital_per_position_pct': 35.0,
                'max_stocks': 16,
                'timeframes': ['1m', '5m', '15m'],
                'volatility_bias': 'balanced',
                'max_loss_per_trade_pct': 0.0,
            },
        }

        config = base_configs.get(risk_level, base_configs['moderate']).copy()

        # Adjust based on investment goal
        if investment_goal == 'quick_gains':
            # Day trading style: shorter holds, more trades
            config['time_limit'] = int(config['time_limit'] * 0.5)  # Half the time
            config['confidence_threshold'] *= 0.9  # 10% lower threshold = more trades
            config['exploration_rate'] *= 1.2  # 20% more exploration
        else:  # steady_growth
            # Swing trading style: longer holds, fewer trades
            config['time_limit'] = int(config['time_limit'] * 1.5)  # 50% more time
            config['confidence_threshold'] *= 1.1  # 10% higher threshold = more selective
            config['exploration_rate'] *= 0.8  # 20% less exploration

        # Tempo adjustments (volatility preference)
        if trade_tempo == 'fast':
            config['confidence_threshold'] *= 0.85
            config['exploration_rate'] *= 1.3
            config['min_liquidity_volume'] = max(5000, int(config['min_liquidity_volume'] * 0.75))
            config['volatility_bias'] = 'high'
        elif trade_tempo == 'steady':
            config['confidence_threshold'] *= 1.15
            config['exploration_rate'] *= 0.7
            config['min_liquidity_volume'] = int(config['min_liquidity_volume'] * 1.2)
            config['volatility_bias'] = 'low'
        else:
            config['volatility_bias'] = 'balanced'

        # Keep exploration within sensible bounds
        config['exploration_rate'] = max(0.02, min(0.8, config['exploration_rate']))
        config['confidence_threshold'] = max(0.35, min(0.9, config['confidence_threshold']))

        # Add per-trade stop-loss
        config['max_loss_per_trade_pct'] = max_loss_pct

        return config

    def _start_robot(self) -> None:
        if self.session is not None:
            messagebox.showwarning(
                'Already Running', 'The robot is already running! Stop it first before starting again.'
            )
            return

        try:
            # Parse user inputs
            capital = float(self.capital_var.get())
            if capital <= 0:
                raise ValueError('Capital must be positive')

            risk_level = self.risk_level_var.get()
            investment_goal = self.investment_goal_var.get()
            max_loss_pct = float(self.max_loss_per_trade_var.get())
            session_time_limit = int(self.session_time_limit_var.get())

            # NEW: Parse minimum balance protection settings
            minimum_balance_enabled = self.minimum_balance_enabled_var.get()
            minimum_balance = float(self.minimum_balance_var.get()) if minimum_balance_enabled else 0.0

            if session_time_limit <= 0:
                raise ValueError('Session time limit must be positive')

            # Validate minimum balance
            if minimum_balance_enabled and minimum_balance >= capital:
                raise ValueError(
                    f'Minimum balance (${minimum_balance:.2f}) must be less than starting capital (${capital:.2f})'
                )

            trade_tempo = self.trade_tempo_var.get()
            risk_config = self._get_risk_config(risk_level, investment_goal, trade_tempo, max_loss_pct)

            # Parse safety limits (hard caps)
            try:
                max_daily_loss_pct = float(self.max_daily_loss_pct_var.get())
            except ValueError as err:
                raise ValueError('Max daily loss must be a number') from err
            if not 0 < max_daily_loss_pct < 100:
                raise ValueError('Max daily loss must be between 0 and 100 percent')

            try:
                max_drawdown_pct = float(self.max_drawdown_pct_var.get())
            except ValueError as err:
                raise ValueError('Max drawdown must be a number') from err
            if not 0 < max_drawdown_pct < 100:
                raise ValueError('Max drawdown must be between 0 and 100 percent')

            try:
                max_trades_per_hour = int(self.max_trades_per_hour_var.get())
                max_trades_per_day = int(self.max_trades_per_day_var.get())
            except ValueError as err:
                raise ValueError('Trade limits must be integers') from err
            if max_trades_per_hour <= 0:
                raise ValueError('Max trades per hour must be at least 1')
            if max_trades_per_day <= 0:
                raise ValueError('Max trades per day must be at least 1')
            if max_trades_per_day < max_trades_per_hour:
                raise ValueError('Max trades per day must be greater than or equal to trades per hour limit')

            try:
                chase_threshold_pct = float(self.chase_threshold_pct_var.get())
            except ValueError as err:
                raise ValueError('Chase threshold must be a number') from err
            if chase_threshold_pct <= 0:
                raise ValueError('Chase threshold must be positive')

            try:
                news_volume_multiplier = float(self.news_volume_multiplier_var.get())
            except ValueError as err:
                raise ValueError('News volume multiplier must be a number') from err
            if news_volume_multiplier <= 0:
                raise ValueError('News volume multiplier must be positive')

            try:
                end_of_day_minutes = int(self.end_of_day_minutes_var.get())
            except ValueError as err:
                raise ValueError('End-of-day cutoff must be an integer') from err
            if end_of_day_minutes < 0:
                raise ValueError('End-of-day cutoff cannot be negative')

            safeguard_config = {
                'max_trades_per_hour': max_trades_per_hour,
                'max_trades_per_day': max_trades_per_day,
                'chase_threshold_pct': chase_threshold_pct,
                'news_volume_multiplier': news_volume_multiplier,
                'end_of_day_minutes': end_of_day_minutes,
            }

            risk_limit_overrides = {
                'max_daily_loss_pct': max_daily_loss_pct / 100.0,
                'max_drawdown_pct': max_drawdown_pct / 100.0,
            }

            max_parallel_trades = int(risk_config.get('max_concurrent_positions', 5))
            max_capital_per_position_pct = float(risk_config.get('max_capital_per_position_pct', 20.0))
            max_capital_fraction = min(max_capital_per_position_pct / 100.0, risk_config['max_capital_pct'])

            timeframes = list(risk_config.get('timeframes', ['1m', '5m', '15m']))
            if not timeframes:
                timeframes = ['1m', '5m', '15m']

            max_stocks = int(risk_config.get('max_stocks', 10))
            if max_stocks <= 0:
                max_stocks = 10

            # Refresh symbol discovery using the currently selected trading mode (paper vs live affects scanner host/port).
            self.symbols = self._discover_available_symbols()

            # Limit symbols before wiring into backend
            original_symbol_count = len(self.symbols)
            if original_symbol_count == 0:
                raise ValueError('No symbols discovered. Add CSV data or connect to IBKR scanner.')

            if original_symbol_count > max_stocks:
                self._log_activity(f'📊 Found {original_symbol_count} symbols, limiting to top {max_stocks}')
            self.symbols = self.symbols[:max_stocks]

            # Calculate max capital based on risk level
            max_capital = capital * risk_config['max_capital_pct']

            tempo_labels = {
                'steady': 'STEADY (low-volatility preference)',
                'balanced': 'BALANCED (default)',
                'fast': 'FAST LANE (high-volatility, faster trades)',
            }

            self._logged_trade_ids = set()
            self._log_activity(f'🚀 Starting FSD Robot with ${capital:.2f} capital')
            self._log_activity(f'📊 Risk Level: {risk_level.upper()}')
            self._log_activity(
                f'🎯 Goal: {"QUICK GAINS (day trading)" if investment_goal == "quick_gains" else "STEADY GROWTH (swing trading)"}'
            )
            self._log_activity(f'⚡ Trade tempo: {tempo_labels.get(trade_tempo, trade_tempo)}')
            self._log_activity(
                f'🛡️ AI will use up to ${max_capital:.2f} (max {risk_config["max_capital_pct"] * 100:.0f}%)'
            )
            self._log_activity(f'🛑 Max loss per trade: {max_loss_pct}%')
            self._log_activity(f'⏱️ Session will run for max {session_time_limit} minutes')
            self._log_activity(
                f'🧱 Safety: Halt if daily loss hits {max_daily_loss_pct:.1f}% or drawdown hits {max_drawdown_pct:.1f}%'
            )
            self._log_activity(
                f'   Trades limit: {max_trades_per_hour}/hour, {max_trades_per_day}/day | Chase>{chase_threshold_pct:.1f}% flagged'
            )
            self._log_activity(
                f'   News volume x{news_volume_multiplier:.1f}; stop new trades {end_of_day_minutes} min before close'
            )

            # NEW: Log minimum balance protection
            if minimum_balance_enabled:
                self._log_activity(f'🛡️ Minimum Balance Protection: ENABLED at ${minimum_balance:.2f}')
                self._log_activity(f'   Bot will REFUSE trades that would drop balance below ${minimum_balance:.2f}')
                tradeable_capital = capital - minimum_balance
                self._log_activity(f'   Tradeable capital: ${tradeable_capital:.2f} (${minimum_balance:.2f} protected)')
            else:
                self._log_activity('⚠️  Minimum Balance Protection: DISABLED (not recommended)')

            # Build configuration
            data_source = DataSource(
                path=self.data_folder,
                timezone=self.user_timezone,
                symbols=tuple(self.symbols),
                warmup_bars=50,
                enforce_trading_hours=True,
                allow_extended_hours=self.allow_extended_hours_var.get(),
            )

            hours_desc = (
                'regular + extended (pre-market and after-hours)'
                if data_source.allow_extended_hours
                else 'regular market hours only'
            )
            self._log_activity(f'🕒 Trading hours: {hours_desc}')

            # StrategyConfig is now a placeholder (FSD doesn't use rule-based strategies)
            strategy_cfg = StrategyConfig()

            engine = EngineConfig(
                strategy=strategy_cfg,
                initial_equity=capital,
                commission_per_trade=0.0,
                slippage_bps=5.0,
            )
            engine.risk.per_trade_risk_pct = max_loss_pct / 100.0
            engine.risk.max_position_fraction = min(engine.risk.max_position_fraction, max_capital_fraction)
            engine.risk.max_daily_loss_pct = risk_limit_overrides['max_daily_loss_pct']
            engine.risk.max_drawdown_pct = risk_limit_overrides['max_drawdown_pct']

            contracts = {
                symbol: ContractSpec(
                    symbol=symbol,
                    sec_type='STK',
                    exchange='SMART',
                    currency='USD',
                )
                for symbol in self.symbols
            }

            # Determine backend based on trading mode selection (2 IBKR modes only)
            trading_mode = self.trading_mode_var.get()

            if trading_mode == 'ibkr_paper':
                # MODE 2: IBKR PAPER - Connects to IBKR's paper trading account
                # Check if market is open (weekend warning)
                from datetime import datetime

                from .calendar import is_trading_day

                today = datetime.now(timezone.utc).date()
                if not is_trading_day(today):
                    day_name = today.strftime('%A')
                    response = messagebox.askyesno(
                        'Market Closed',
                        f'⚠️ NOTICE: Market is CLOSED today ({day_name})\n\n'
                        f'IBKR Paper Trading works even when market is closed,\n'
                        f"but you won't get live data until market opens.\n\n"
                        f'Continue anyway?',
                    )
                    if not response:
                        raise ValueError('IBKR Paper mode cancelled')

                account_id, client_id = self.ibkr_settings.require_credentials()

                broker = BrokerConfig(
                    backend='ibkr',
                    ib_host=self.ibkr_host,
                    ib_port=self.ibkr_paper_port,
                    ib_client_id=client_id,
                    ib_account=account_id,
                    contracts=contracts,
                )
                self._log_activity('🔵 IBKR PAPER MODE - IBKR simulated account')
                self._log_activity(f'  📡 Connecting to IBKR Paper Trading @ {self.ibkr_host}:{self.ibkr_paper_port}')
                self._log_activity("  🎭 Using IBKR's fake $1.1M account (no real money)")
                self._log_activity(f'  📊 Timeframes: {", ".join(timeframes)} (multi-timeframe analysis)')
                self._log_activity(f'  📈 Max stocks: {max_stocks} (parallel monitoring)')
                self._log_activity('  🧠 No historical warmup - AI learns as it trades (paper recommended)')
                self._log_activity(
                    f'  ⚠️ IMPORTANT: Requires IBKR Gateway/TWS running on {self.ibkr_host}:{self.ibkr_paper_port}'
                )

            elif trading_mode == 'ibkr_live':
                # MODE 3: IBKR LIVE - Real money trading
                # Check if market is open (weekend warning)
                from datetime import datetime

                from .calendar import is_trading_day

                today = datetime.now(timezone.utc).date()
                if not is_trading_day(today):
                    day_name = today.strftime('%A')
                    response = messagebox.askyesno(
                        'Market Closed',
                        f'🚨 WARNING: Market is CLOSED today ({day_name})\n\n'
                        f'REAL MONEY live trading should only be done when market is open!\n\n'
                        f'Continue anyway? (NOT recommended)',
                    )
                    if not response:
                        raise ValueError('Live trading cancelled - market is closed')

                account_id, client_id = self.ibkr_settings.require_credentials()

                # Final confirmation for real money
                confirm = messagebox.askyesno(
                    '🚨 FINAL WARNING - REAL MONEY',
                    f'You are about to trade with REAL MONEY!\n\n'
                    f'Account: {account_id}\n'
                    f'Capital: ${capital:.2f}\n'
                    f'Endpoint: {self.ibkr_host}:{self.ibkr_live_port} (LIVE TRADING)\n\n'
                    f'Losses will be REAL and PERMANENT!\n\n'
                    f'Are you absolutely sure?',
                )
                if not confirm:
                    raise ValueError('Live trading cancelled by user')

                broker = BrokerConfig(
                    backend='ibkr',
                    ib_host=self.ibkr_host,
                    ib_port=self.ibkr_live_port,
                    ib_client_id=client_id,
                    ib_account=account_id,
                    contracts=contracts,
                )
                self._log_activity('🔴 IBKR LIVE MODE - REAL MONEY TRADING!')
                self._log_activity(f'  📡 Connecting to IBKR LIVE account: {account_id}')
                self._log_activity(f'  🔌 Endpoint: {self.ibkr_host}:{self.ibkr_live_port} (LIVE TRADING)')
                self._log_activity(f'  📊 Timeframes: {", ".join(timeframes)} (multi-timeframe analysis)')
                self._log_activity(f'  📈 Max stocks: {max_stocks} (parallel monitoring)')
                self._log_activity('  🧠 No historical warmup - AI learns as it trades (paper recommended first)')
                self._log_activity('  💰 REAL MONEY AT RISK - monitor closely!')
                self._log_activity('  ⚠️ Requires: $500+ balance + market data subscription')
            else:
                raise ValueError(f'Unknown trading mode: {trading_mode}. Must be "ibkr_paper" or "ibkr_live"')

            execution = ExecutionConfig(slip_bps_limit=5.0)

            # Create capital management config from UI
            from .capital_management import CapitalManagementConfig

            # Sync target capital with main capital if still at default
            if self.target_capital_var.get() == '200':  # Default value, never changed by user
                self.target_capital_var.set(self.capital_var.get())
                self._log_activity(
                    f'📊 Auto-set target capital to ${self.capital_var.get()} (matches starting capital)'
                )

            capital_mgmt_config = None
            if self.enable_withdrawal_var.get():
                try:
                    capital_mgmt_config = CapitalManagementConfig(
                        target_capital=Decimal(str(self.target_capital_var.get())),
                        withdrawal_threshold=Decimal(str(self.withdrawal_threshold_var.get())),
                        withdrawal_frequency=self.withdrawal_frequency_var.get().lower(),
                        enabled=True,
                    )
                    self._log_activity(
                        f'💰 Profit Withdrawal Enabled: target=${capital_mgmt_config.target_capital}, '
                        f'threshold=${capital_mgmt_config.withdrawal_threshold}, '
                        f'frequency={capital_mgmt_config.withdrawal_frequency}'
                    )
                except Exception as e:
                    self._log_activity(f'⚠️ Invalid capital management config: {e}')
                    capital_mgmt_config = None

            # Create stop control config from UI
            from datetime import time

            from .stop_control import StopConfig

            try:
                # Parse EOD time (HH:MM format)
                eod_time_str = self.eod_flatten_time_var.get()
                hour, minute = map(int, eod_time_str.split(':'))
                eod_time = time(hour, minute)
            except Exception as e:
                self._log_activity(f'⚠️ Invalid EOD time format, using default 15:45: {e}')
                eod_time = time(15, 45)

            stop_config = StopConfig(
                enable_manual_stop=True,  # Always enabled for emergency button
                enable_eod_flatten=self.enable_eod_flatten_var.get(),
                eod_flatten_time=eod_time,
                emergency_liquidation_timeout=30.0,
            )

            if stop_config.enable_eod_flatten:
                self._log_activity(f'🛑 EOD Auto-Flatten Enabled: will flatten at {eod_time} ET')

            config = BacktestConfig(
                data=data_source,
                engine=engine,
                execution=execution,
                broker=broker,
                capital_management=capital_mgmt_config,
                stop_control=stop_config,
            )

            self._log_activity(
                f'  📈 Will trade up to {len(self.symbols)} stocks: {", ".join(self.symbols[:5])}{"..." if len(self.symbols) > 5 else ""}'
            )

            # Build FSD config with user preferences (ENHANCED with professional features)
            fsd_config = FSDConfig(
                max_capital=max_capital,
                max_timeframe_seconds=session_time_limit * 60,  # Convert minutes to seconds
                learning_rate=risk_config['learning_rate'],
                exploration_rate=risk_config['exploration_rate'],
                min_confidence_threshold=risk_config['confidence_threshold'],
                risk_penalty_factor=risk_config.get('risk_penalty', 0.1),
                transaction_cost_factor=0.001,
                # Advanced features
                max_concurrent_positions=max_parallel_trades,  # Trade up to N stocks simultaneously
                max_capital_per_position=max_capital_fraction,  # Max capital per position
                max_loss_per_trade_pct=max_loss_pct,
                enable_per_symbol_params=True,  # Learn which symbols are profitable
                adaptive_confidence=True,  # Adjust confidence per symbol
                # Session-based confidence adaptation (replaces hard deadlines)
                enable_session_adaptation=True,
                max_confidence_decay=float(risk_config.get('confidence_decay', 0.15)),
                confidence_decay_start_minutes=int(risk_config.get('decay_start_minutes', 30)),
                volatility_bias=risk_config.get('volatility_bias', 'balanced'),
            )

            self._log_activity('⚙️ AI Config:')
            self._log_activity(
                f'   🎯 Confidence threshold: {risk_config["confidence_threshold"]:.0%} (higher = more selective)'
            )
            self._log_activity(
                f'   🔍 Exploration rate: {risk_config["exploration_rate"]:.0%} (how often AI experiments)'
            )
            self._log_activity(f'   📊 Volume filter: >{risk_config["min_liquidity_volume"]:,} shares/day minimum')
            self._log_activity(
                f'   💡 Stocks below {risk_config["min_liquidity_volume"]:,} volume are filtered out for safety'
            )
            self._log_activity(f'   🤝 Max parallel trades: {fsd_config.max_concurrent_positions}')
            self._log_activity(f'   💵 Max capital per position: {fsd_config.max_capital_per_position:.0%}')
            self._log_activity(f'   🌪️ Volatility bias: {fsd_config.volatility_bias}')

            # Create session using new modular SessionFactory
            factory = SessionFactory(
                config,
                fsd_config=fsd_config,
                enable_professional_features=True,
            )
            session = factory.create_trading_session(
                symbols=list(data_source.symbols) if data_source.symbols else [],
                checkpoint_dir='state',
                minimum_balance=minimum_balance,
                minimum_balance_enabled=minimum_balance_enabled,
                timeframes=timeframes,
                safeguard_config=safeguard_config,
            )
            self.session = session

            # Apply risk limit overrides if provided
            if risk_limit_overrides:
                for key, value in risk_limit_overrides.items():
                    if key == 'max_daily_loss_pct':
                        session.risk.config.max_daily_loss_pct = max(0.0001, min(float(value), 1.0))
                    elif key == 'max_drawdown_pct':
                        session.risk.config.max_drawdown_pct = max(0.0001, min(float(value), 1.0))

            # Attach logging callback so FSD decisions appear in GUI (if supported).
            if isinstance(session.decision_engine, SupportsGuiLogCallback):
                session.decision_engine.gui_log_callback = self._log_activity

            self._log_activity('🔌 Starting session...')
            self.status_var.set('🔌 Connecting...')

            # Start IBKR connection and subscribe to multi-timeframe bars
            session.start()
            self._schedule_session_timeout(session_time_limit)

            # IBKR modes: subscribe to real-time bars
            if trading_mode == 'ibkr_paper':
                self._log_activity('🔵 IBKR Paper mode - Initializing...')
                self._log_activity(f'  📡 Connected to {self.ibkr_host}:{self.ibkr_paper_port} (IBKR Paper Trading)')
                self._log_activity("  🎭 Using IBKR's $1.1M simulated account")
            else:  # ibkr_live
                self._log_activity('🔴 IBKR Live mode - Initializing...')
                self._log_activity(f'  📡 Connected to {self.ibkr_host}:{self.ibkr_live_port} (IBKR LIVE TRADING)')
                self._log_activity(f'  💰 Using REAL MONEY from account: {self._ibkr_account_display}')
                self._log_activity('  🚨 REMINDER: Real money at risk!')

            self._log_activity('📡 Subscribing to REAL-TIME multi-timeframe bars...')
            self._log_activity(f'   ⏱️ Active timeframes: {", ".join(timeframes)}')
            self._log_activity('   🔄 Bot will analyze cross-timeframe correlations')
            self._log_activity('   🎯 If 1m drops, bot expects 5m to drop too (professional logic)')
            # Note: Multi-timeframe subscription happens in session for each symbol

            self._log_activity('✅ Robot started successfully!')
            self._log_activity('🧠 No historical warmup - AI learns as it trades (paper recommended first)')
            self._log_activity('📊 Watch for evaluation messages below as bars are processed...')

            self.status_var.set('🟢 TRADING')

            # Swap buttons - show stop and enable emergency stop
            self.start_btn.pack_forget()
            self.stop_btn.pack(side=tk.LEFT, padx=10)
            self.emergency_stop_btn.config(state=tk.NORMAL)  # Enable emergency stop

        except ValueError as e:
            messagebox.showerror('Invalid Input', str(e))
            self._log_activity(f'❌ Validation error: {e}')
            # Clean up state
            if self.session:
                with suppress(Exception):
                    self.session.stop()
                self.session = None
        except Exception as e:
            messagebox.showerror('Error Starting Robot', f'Failed to start: {e}')
            self._log_activity(f'❌ Error: {e}')
            # Clean up state
            if self.session:
                with suppress(Exception):
                    self.session.stop()
                self.session = None

    def _stop_robot(self) -> None:
        if not self.session or self._stop_in_progress:
            return

        auto_liquidate = self.auto_liquidate_on_stop_var.get()
        if auto_liquidate:
            stop_controller = getattr(self.session, 'stop_controller', None)
            if stop_controller is not None:
                cast(StopControllerProtocol, stop_controller).request_stop('user_manual_stop')
                self._log_activity('🛑 STOP requested - cancelling orders and liquidating (auto-liquidate enabled)')
            else:
                self._log_activity('⚠️ Stop controller not available - stopping session without liquidation')
        else:
            self._log_activity('⏹️ STOP requested - stopping session (no liquidation)')

        self.status_var.set('⏹️ Stopping...')
        self._stop_session_async()

    def _emergency_stop(self) -> None:
        """Execute emergency stop with confirmation dialog."""
        if not self.session or self._stop_in_progress:
            return

        # Show confirmation dialog
        response = messagebox.askyesno(
            'Emergency Stop',
            'This will immediately:\n'
            '• Cancel all pending orders\n'
            '• Close all open positions (market orders)\n'
            '• Stop trading\n\n'
            'Are you sure?',
            icon='warning',
        )

        if not response:
            return

        self._log_activity('🛑 EMERGENCY STOP initiated by user')
        self.status_var.set('🛑 Emergency Stop - Cancelling orders and closing positions...')

        stop_controller = getattr(self.session, 'stop_controller', None)
        if stop_controller is not None:
            cast(StopControllerProtocol, stop_controller).request_stop('user_emergency_stop')
            self._log_activity('⚠️ Cancelling orders and liquidating positions...')
        else:
            self._log_activity('⚠️ Stop controller not available - stopping session without liquidation')

        self._stop_session_async()

    def _stop_session_async(self) -> None:
        if not self.session or self._stop_in_progress:
            return

        session = self.session
        self._stop_in_progress = True
        self.stop_btn.config(state=tk.DISABLED)
        self.emergency_stop_btn.config(state=tk.DISABLED)

        def stop_worker() -> None:
            error: Exception | None = None
            try:
                session.stop()
            except Exception as exc:
                error = exc
            self.root.after(0, self._finish_stop, session, error)

        threading.Thread(target=stop_worker, daemon=True, name='GUIStop').start()

    def _finish_stop(self, session: TradingCoordinator, error: Exception | None) -> None:
        if self.session is session:
            self.session = None

        self._cancel_session_timeout()
        self._logged_trade_ids.clear()

        if error is not None:
            self._log_activity(f'⚠️ Error while stopping: {error}')

        self._log_activity('⏹️ Robot stopped')
        self.status_var.set('🔴 Stopped')

        # Swap buttons and disable emergency stop
        self.stop_btn.pack_forget()
        self.stop_btn.config(state=tk.NORMAL)
        self.start_btn.pack(side=tk.LEFT, padx=10)
        self.emergency_stop_btn.config(state=tk.DISABLED)
        self._stop_in_progress = False

    def _schedule_session_timeout(self, minutes: int) -> None:
        self._cancel_session_timeout()
        if minutes <= 0:
            return
        delay_ms = int(minutes * 60 * 1000)
        self._session_stop_after_id = self.root.after(delay_ms, self._handle_session_timeout)

    def _cancel_session_timeout(self) -> None:
        if self._session_stop_after_id is None:
            return
        try:
            self.root.after_cancel(self._session_stop_after_id)
        except tk.TclError:
            pass
        self._session_stop_after_id = None

    def _handle_session_timeout(self) -> None:
        self._session_stop_after_id = None
        if not self.session or self._stop_in_progress:
            return
        self._log_activity('⏱️ Session time limit reached - stopping robot.')
        self._stop_robot()

    def _update_dashboard(self) -> None:
        session = self.session
        if session is not None:
            try:
                snapshot = cast(SessionSnapshot, session.snapshot())

                # Update metrics
                equity_value = snapshot.get('equity', 0.0)
                equity = float(equity_value) if isinstance(equity_value, (int, float, Decimal)) else 0.0
                initial_equity = float(self.capital_var.get() or 0.0)
                profit = equity - initial_equity

                self.balance_var.set(f'${equity:,.2f}')
                self.profit_var.set(f'${profit:+,.2f}')

                # Color profit label
                if profit > 0:
                    self.profit_label.config(fg='#2e7d32')  # Green
                elif profit < 0:
                    self.profit_label.config(fg='#c62828')  # Red
                else:
                    self.profit_label.config(fg='#616161')  # Gray

                # Check for trades
                trades = snapshot.get('trades', [])
                if trades:
                    latest_trade = trades[-1]
                    trade_id = '|'.join(
                        [
                            str(latest_trade.get('timestamp')),
                            str(latest_trade.get('symbol', '')),
                            str(latest_trade.get('quantity')),
                            str(latest_trade.get('price')),
                        ]
                    )
                    logged_ids = self._logged_trade_ids
                    if trade_id not in logged_ids:
                        trade_pnl_value = latest_trade.get('realised_pnl', 0.0)
                        trade_pnl = (
                            float(trade_pnl_value) if isinstance(trade_pnl_value, (int, float, Decimal)) else 0.0
                        )
                        symbol = str(latest_trade.get('symbol', ''))
                        qty_value = latest_trade.get('quantity', 0.0)
                        qty = float(qty_value) if isinstance(qty_value, (int, float, Decimal)) else 0.0
                        price_value = latest_trade.get('price', 0.0)
                        price = float(price_value) if isinstance(price_value, (int, float, Decimal)) else 0.0

                        emoji = '📈' if trade_pnl > 0 else '📉' if trade_pnl < 0 else '➡️'
                        self._log_activity(
                            f'{emoji} AI traded: {qty:.2f} {symbol} @ ${price:.2f} | PnL: ${trade_pnl:+,.2f}'
                        )

                        self._logged_trade_ids.add(trade_id)

                # Update status with learning stats
                fsd_value = snapshot.get('fsd', {})
                fsd = cast(dict[str, object], fsd_value) if isinstance(fsd_value, dict) else {}
                total_trades_value = fsd.get('total_trades', 0)
                total_trades = int(total_trades_value) if isinstance(total_trades_value, (int, float)) else 0
                if total_trades > 0:
                    self.status_var.set(f'🟢 TRADING\n🧠 {total_trades} decisions made')

                # NEW: Update minimum balance display with visual warnings
                min_balance_enabled = self.minimum_balance_enabled_var.get()
                if min_balance_enabled:
                    try:
                        min_balance = float(self.minimum_balance_var.get() or 0.0)
                        self.min_balance_display_var.set(f'${min_balance:,.2f}')

                        # Visual warning system based on proximity to minimum
                        cash_value = snapshot.get('cash', 0.0)
                        cash = float(cash_value) if isinstance(cash_value, (int, float, Decimal)) else 0.0
                        margin = cash - min_balance
                        margin_pct = (margin / cash * 100) if cash > 0 else 0

                        if margin < 0:
                            # CRITICAL: Below minimum (should never happen due to protection)
                            self.min_balance_card.config(bg='#ffebee')
                            self.min_balance_display_label.config(bg='#ffebee', fg='#c62828')
                            self._log_activity(f'🚨 CRITICAL: Cash ${cash:.2f} is BELOW minimum ${min_balance:.2f}!')
                        elif margin_pct < 10:
                            # DANGER: Within 10% of minimum
                            self.min_balance_card.config(bg='#fff3e0')
                            self.min_balance_display_label.config(bg='#fff3e0', fg='#d84315')
                            if not hasattr(self, '_danger_warning_shown'):
                                self._log_activity(f'⚠️  WARNING: Only ${margin:.2f} above minimum balance!')
                                self._danger_warning_shown = True
                        elif margin_pct < 25:
                            # CAUTION: Within 25% of minimum
                            self.min_balance_card.config(bg='#fffde7')
                            self.min_balance_display_label.config(bg='#fffde7', fg='#f57c00')
                        else:
                            # SAFE: Well above minimum
                            self.min_balance_card.config(bg='#e8f5e9')
                            self.min_balance_display_label.config(bg='#e8f5e9', fg='#2e7d32')
                            if hasattr(self, '_danger_warning_shown'):
                                delattr(self, '_danger_warning_shown')
                    except ValueError:
                        self.min_balance_display_var.set('$0.00')
                else:
                    # Protection disabled
                    self.min_balance_display_var.set('DISABLED')
                    self.min_balance_card.config(bg='#f5f5f5')
                    self.min_balance_display_label.config(bg='#f5f5f5', fg='#9e9e9e')

                # Update withdrawal statistics
                try:
                    stats = cast(dict[str, object], session.capital_manager.get_stats())
                    total_withdrawn_value = stats.get('total_withdrawn')
                    total_withdrawn = 0.0
                    if isinstance(total_withdrawn_value, (int, float, Decimal)):
                        total_withdrawn = float(total_withdrawn_value)
                    elif isinstance(total_withdrawn_value, str):
                        try:
                            total_withdrawn = float(total_withdrawn_value)
                        except ValueError:
                            total_withdrawn = 0.0

                    self.total_withdrawn_var.set(f'${total_withdrawn:,.2f}')

                    last_withdrawal = stats.get('last_withdrawal')  # ISO string or None
                    if isinstance(last_withdrawal, str):
                        # Parse ISO string back to datetime for formatting
                        from datetime import datetime

                        try:
                            last_withdrawal_dt = datetime.fromisoformat(last_withdrawal)
                        except ValueError:
                            self.last_withdrawal_var.set('Never')
                        else:
                            last_withdrawal_str = last_withdrawal_dt.strftime('%Y-%m-%d %H:%M')
                            self.last_withdrawal_var.set(last_withdrawal_str)
                    else:
                        self.last_withdrawal_var.set('Never')
                except Exception as e:
                    self.logger.debug(f'Could not update withdrawal stats: {e}')

            except Exception as e:
                self.logger.error(f'Error updating dashboard: {e}')
        else:
            # Reset dashboard when not running
            capital = self.capital_var.get() or '0'
            try:
                self.balance_var.set(f'${float(capital):,.2f}')
            except ValueError:
                self.balance_var.set('$0.00')

            self.profit_var.set('$0.00')

            # Reset withdrawal stats when not running
            self.total_withdrawn_var.set('$0.00')
            self.last_withdrawal_var.set('Never')

            # Show minimum balance threshold even when not running
            min_balance_enabled = self.minimum_balance_enabled_var.get()
            if min_balance_enabled:
                try:
                    min_balance = float(self.minimum_balance_var.get() or 0.0)
                    self.min_balance_display_var.set(f'${min_balance:,.2f}')
                    self.min_balance_card.config(bg='#e8f5e9')
                    self.min_balance_display_label.config(bg='#e8f5e9', fg='#2e7d32')
                except ValueError:
                    self.min_balance_display_var.set('$0.00')
            else:
                self.min_balance_display_var.set('DISABLED')
                self.min_balance_card.config(bg='#f5f5f5')
                self.min_balance_display_label.config(bg='#f5f5f5', fg='#9e9e9e')

            if self.status_var.get() not in ['🔴 Stopped', '✅ Complete']:
                self.status_var.set('🤖 Ready to start')

        self.root.after(1000, self._update_dashboard)

    def _log_activity(self, message: str) -> None:
        if not self.activity_text:
            return

        self.activity_text.configure(state=tk.NORMAL)
        self.activity_text.insert(tk.END, f'• {message}\n')
        self.activity_text.see(tk.END)
        self.activity_text.configure(state=tk.DISABLED)

    # Mode switching methods removed - FSD is the only mode in v2.0

    def _open_advanced(self) -> None:
        """Advanced features note - removed in v2.0."""
        messagebox.showinfo(
            'FSD Mode Only',
            'AIStock v2.0 is now FSD-only mode!\n\n'
            'All advanced features have been removed to focus on\n'
            'the Full Self-Driving RL trading agent.\n\n'
            'FSD mode provides everything you need:\n'
            '• AI-powered trading decisions\n'
            '• Automatic learning and adaptation\n'
            '• Risk management\n'
            '• Real-time monitoring\n\n'
            'No need for complex configurations!',
        )

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    SimpleGUI().run()


if __name__ == '__main__':
    main()
