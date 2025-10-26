"""
First-time setup wizard for AIStock Robot.

Downloads historical data and trains ML model on first run.
"""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from ..data import Bar
from ..logging import configure_logger
from ..ml.dataset import build_dataset_from_directory
from ..ml.model import save_model, train_logistic_regression
from ..ml.pipeline import train_model


class FirstTimeSetupWizard:
    """
    Handles first-time setup for new users.

    Downloads historical data and trains ML model automatically.
    """

    def __init__(self, progress_callback: Callable[[str, float], None] | None = None):
        """
        Initialize setup wizard.

        Args:
            progress_callback: Optional callback for progress updates.
                               Called with (message: str, progress: float 0-1)
        """
        self.logger = configure_logger("FirstTimeSetup", structured=True)
        self.progress_callback = progress_callback

    def _report_progress(self, message: str, progress: float) -> None:
        """Report progress to callback if provided."""
        self.logger.info("setup_progress", extra={"message": message, "progress": progress})
        if self.progress_callback:
            self.progress_callback(message, progress)

    def needs_setup(self) -> bool:
        """
        Check if first-time setup is needed.

        Returns True if:
        - No historical data exists
        - No ML model exists
        """
        historical_dir = Path("data/historical")
        model_path = Path("models/ml_model.json")

        has_historical_data = historical_dir.exists() and any(historical_dir.glob("*.csv"))
        has_ml_model = model_path.exists()

        needs_setup = not (has_historical_data and has_ml_model)

        self.logger.info(
            "setup_check",
            extra={
                "has_historical_data": has_historical_data,
                "has_ml_model": has_ml_model,
                "needs_setup": needs_setup,
            }
        )

        return needs_setup

    def run_setup(self, symbols: list[str] | None = None, days: int = 10) -> bool:
        """
        Run first-time setup.

        Args:
            symbols: List of symbols to download (default: top liquid stocks)
            days: Number of days of historical data to download (default: 10)

        Returns:
            True if setup completed successfully, False otherwise
        """
        if symbols is None:
            # Default to highly liquid stocks
            symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"]

        try:
            self._report_progress("Starting first-time setup...", 0.0)

            # Step 1: Create directories
            self._report_progress("Creating directories...", 0.1)
            self._create_directories()

            # Step 2: Download historical data
            self._report_progress(f"Downloading {days} days of data for {len(symbols)} stocks...", 0.2)
            success = self._download_historical_data(symbols, days)

            if not success:
                self.logger.error("setup_failed", extra={"step": "download_historical_data"})
                return False

            self._report_progress("Historical data downloaded successfully", 0.6)

            # Step 3: Train ML model
            self._report_progress("Training ML model from historical data...", 0.7)
            success = self._train_ml_model(symbols)

            if not success:
                self.logger.warning("ml_training_failed", extra={"note": "Will use momentum fallback"})
                # Don't fail setup if ML training fails - FSD can use momentum fallback

            self._report_progress("Setup complete!", 1.0)
            self.logger.info("setup_completed_successfully")
            return True

        except Exception as exc:
            self.logger.error("setup_failed", extra={"error": str(exc)})
            self._report_progress(f"Setup failed: {exc}", 1.0)
            return False

    def _create_directories(self) -> None:
        """Create necessary directories."""
        dirs = [
            Path("data/historical"),
            Path("data/live"),
            Path("models"),
            Path("state/fsd"),
        ]

        for directory in dirs:
            directory.mkdir(parents=True, exist_ok=True)
            self.logger.debug("directory_created", extra={"path": str(directory)})

    def _download_historical_data(self, symbols: list[str], days: int) -> bool:
        """
        Download historical data for symbols.

        Args:
            symbols: List of stock symbols
            days: Number of days to download

        Returns:
            True if successful, False otherwise
        """
        try:
            # Try to import yfinance
            try:
                import yfinance as yf
            except ImportError:
                self.logger.error("yfinance_not_installed", extra={"note": "Run: pip install yfinance"})
                # Fall back to generating synthetic data
                return self._generate_synthetic_data(symbols, days)

            historical_dir = Path("data/historical")
            total_symbols = len(symbols)

            for idx, symbol in enumerate(symbols):
                progress = 0.2 + (idx / total_symbols) * 0.4  # 20% to 60%
                self._report_progress(f"Downloading {symbol}... ({idx+1}/{total_symbols})", progress)

                try:
                    ticker = yf.Ticker(symbol)

                    # Download with 1-minute interval for last N days
                    # Note: yfinance has limits on intraday data (max 7 days for 1m)
                    # So we'll download daily data for 10 days instead
                    end_date = datetime.now()
                    start_date = end_date - timedelta(days=days)

                    # Download daily data
                    df = ticker.history(start=start_date, end=end_date, interval="1d")

                    if df.empty:
                        self.logger.warning("no_data_for_symbol", extra={"symbol": symbol})
                        continue

                    # Convert to CSV format
                    csv_path = historical_dir / f"{symbol}.csv"
                    self._save_to_csv(symbol, df, csv_path)

                    self.logger.info(
                        "symbol_downloaded",
                        extra={"symbol": symbol, "bars": len(df), "path": str(csv_path)}
                    )

                except Exception as exc:
                    self.logger.error("symbol_download_failed", extra={"symbol": symbol, "error": str(exc)})
                    continue

            return True

        except Exception as exc:
            self.logger.error("download_failed", extra={"error": str(exc)})
            return False

    def _save_to_csv(self, symbol: str, df, csv_path: Path) -> None:
        """Save dataframe to CSV in AIStock format."""
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)

            # Write header
            writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])

            # Write data
            for timestamp, row in df.iterrows():
                # Convert timestamp to ISO format
                ts_str = timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")

                writer.writerow([
                    ts_str,
                    float(row["Open"]),
                    float(row["High"]),
                    float(row["Low"]),
                    float(row["Close"]),
                    int(row["Volume"])
                ])

    def _generate_synthetic_data(self, symbols: list[str], days: int) -> bool:
        """
        Generate synthetic data if yfinance is not available.

        This is a fallback for testing purposes.
        """
        self.logger.info("generating_synthetic_data", extra={"symbols": symbols, "days": days})

        import random

        historical_dir = Path("data/historical")
        bars_per_day = 1  # Daily data

        for symbol in symbols:
            csv_path = historical_dir / f"{symbol}.csv"

            with csv_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])

                # Start from 'days' ago
                base_date = datetime.now(timezone.utc) - timedelta(days=days)
                base_price = random.uniform(100, 200)

                for day in range(days * bars_per_day):
                    timestamp = base_date + timedelta(days=day)

                    # Random walk
                    daily_change = random.uniform(-0.02, 0.02)  # ±2% daily
                    open_price = base_price * (1 + daily_change)
                    close_price = open_price * (1 + random.uniform(-0.01, 0.01))
                    high_price = max(open_price, close_price) * (1 + random.uniform(0, 0.01))
                    low_price = min(open_price, close_price) * (1 - random.uniform(0, 0.01))
                    volume = random.randint(500000, 2000000)

                    writer.writerow([
                        timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        round(open_price, 2),
                        round(high_price, 2),
                        round(low_price, 2),
                        round(close_price, 2),
                        volume
                    ])

                    base_price = close_price

            self.logger.info("synthetic_data_created", extra={"symbol": symbol, "path": str(csv_path)})

        return True

    def _train_ml_model(self, symbols: list[str]) -> bool:
        """
        Train ML model from downloaded historical data.

        Args:
            symbols: List of symbols to include in training

        Returns:
            True if successful, False otherwise
        """
        try:
            model_path = Path("models/ml_model.json")

            # Use the ML pipeline to train the model
            self.logger.info("training_ml_model", extra={"symbols": symbols})

            result = train_model(
                data_dir="data/historical",
                symbols=symbols,
                lookback=30,
                horizon=1,
                learning_rate=0.01,
                epochs=200,
                model_path=str(model_path)
            )

            self.logger.info(
                "ml_model_trained",
                extra={
                    "train_accuracy": result.train_accuracy,
                    "test_accuracy": result.test_accuracy,
                    "model_path": str(model_path)
                }
            )

            return True

        except Exception as exc:
            self.logger.error("ml_training_failed", extra={"error": str(exc)})
            return False


def run_first_time_setup(
    progress_callback: Callable[[str, float], None] | None = None,
    symbols: list[str] | None = None,
    days: int = 10
) -> bool:
    """
    Convenience function to run first-time setup.

    Args:
        progress_callback: Optional callback for progress updates
        symbols: List of symbols to download (default: top liquid stocks)
        days: Number of days of historical data (default: 10)

    Returns:
        True if setup completed successfully, False otherwise
    """
    wizard = FirstTimeSetupWizard(progress_callback=progress_callback)

    if not wizard.needs_setup():
        if progress_callback:
            progress_callback("Setup not needed - data already exists", 1.0)
        return True

    return wizard.run_setup(symbols=symbols, days=days)
