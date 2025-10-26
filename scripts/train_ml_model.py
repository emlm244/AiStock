#!/usr/bin/env python3
"""
Train ML Model for FSD Mode

This script trains a machine learning model using historical stock data.
The trained model will be used by FSD (Full Self-Driving) mode for
enhanced confidence scoring.

Usage:
    python -m scripts.train_ml_model

Or from project root:
    python scripts/train_ml_model.py

The model will be saved to: models/ml_model.json
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from aistock.ml.pipeline import train_model


def main() -> None:
    print("=" * 70)
    print(" [AI] Training ML Model for FSD Mode")
    print("=" * 70)
    print()

    # Get all available symbols from data/historical/stocks/
    data_dir = Path("data/historical/stocks")

    if not data_dir.exists():
        print("[ERROR] data/historical/stocks/ directory not found!")
        print("        Please run: python scripts/generate_synthetic_dataset.py first")
        return

    csv_files = list(data_dir.glob("*.csv"))
    if not csv_files:
        print("[ERROR] No CSV files found in data/historical/stocks/")
        print("        Please run: python scripts/generate_synthetic_dataset.py first")
        return

    symbols = [f.stem for f in csv_files if f.stem != ".gitkeep"]
    print(f"[DATA] Found {len(symbols)} stocks for training:")
    print(f"       {', '.join(symbols[:10])}...")
    print()

    print("[CONFIG] Training Configuration:")
    print(f"         - Data Directory: {data_dir}")
    print(f"         - Symbols: {len(symbols)} stocks")
    print(f"         - Lookback: 30 bars")
    print(f"         - Horizon: 1 bar (predict next bar)")
    print(f"         - Learning Rate: 0.01")
    print(f"         - Epochs: 200")
    print(f"         - Model Path: models/ml_model.json")
    print()

    print("[TRAIN] Training model (this may take a few minutes)...")
    print()

    try:
        from datetime import timedelta

        result = train_model(
            data_dir=str(data_dir),
            symbols=symbols,
            lookback=30,
            horizon=1,
            learning_rate=0.01,
            epochs=200,
            model_path="models/ml_model.json",
            bar_interval=timedelta(days=1),  # Daily data
        )

        print("=" * 70)
        print(" [SUCCESS] Training Complete!")
        print("=" * 70)
        print()
        print(f"[RESULTS]")
        print(f"         - Model saved to: {result.model_path}")
        print(f"         - Training samples: {result.samples}")
        print(f"         - Train accuracy: {result.train_accuracy:.2%}")
        print(f"         - Test accuracy: {result.test_accuracy:.2%}")
        print()

        if result.test_accuracy >= 0.52:
            print("[OK] Model shows predictive power (accuracy > 52%)")
            print("     FSD mode will use this model for confidence scoring")
        else:
            print("[WARN] Model accuracy is low (< 52%)")
            print("       FSD will still use it, but with reduced weight")
        print()

        print("[NEXT STEPS]")
        print("     1. Launch FSD mode: python launch_gui.py")
        print("     2. FSD will automatically load and use this trained model")
        print("     3. The model enhances confidence scoring for better trades")
        print()

    except Exception as e:
        print(f"[ERROR] Training failed: {e}")
        import traceback
        traceback.print_exc()
        return


if __name__ == "__main__":
    main()
