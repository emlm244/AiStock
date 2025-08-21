# train_model.py

import os
import pandas as pd
import numpy as np
from sklearn.linear_model import SGDClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, classification_report
import joblib
from sklearn.model_selection import train_test_split
from datetime import datetime
import argparse # Use argparse for potential command-line control
import sys # <--- ADDED IMPORT

# Ensure correct import paths
try:
    from config.settings import Settings # Import settings if needed for parameters
    from utils.logger import setup_logger
    from indicators.oscillators import calculate_rsi, calculate_macd
    from indicators.moving_averages import calculate_sma
    from indicators.volatility import calculate_atr # Example: If adding ATR feature
except ImportError as e:
    print(f"Error importing modules in train_model.py: {e}")
    print("Ensure paths are correct and required packages are installed.")
    # Fallback logging if setup_logger fails
    import logging
    logger = logging.getLogger('model_training_logger_fallback')
    error_logger = logging.getLogger('model_training_error_fallback')
    # Cannot proceed without core indicator functions if they fail import
    raise

# --- Configuration ---
MODEL_DIR = 'models'
MODEL_BASE_NAME = 'trading_model'
SCALER_BASE_NAME = 'scaler'
MODEL_VERSION = "1.2" # Increment version

# Setup loggers (reads settings implicitly via Settings import)
# Use consistent logger names with main application if possible
logger = setup_logger('MLTraining', 'logs/model_training.log', level='INFO') # Use setting from Settings()
error_logger = setup_logger('MLTrainingError', 'logs/error_logs/errors.log', level='ERROR')

# Feature Engineering Parameters (MUST MATCH ml_strategy.py and settings.py defaults)
# Read from Settings to ensure consistency
settings = Settings()
VOLATILITY_WINDOW = 5 # Fixed window for this example feature
MOMENTUM_WINDOW = settings.MOMENTUM_PRICE_CHANGE_PERIOD
SMA_WINDOW = settings.MOVING_AVERAGE_PERIODS.get('short_term', 10) # Example: use short MA
RSI_PERIOD = settings.RSI_PERIOD
MACD_FAST = settings.MACD_SETTINGS['fast_period']
MACD_SLOW = settings.MACD_SETTINGS['slow_period']
MACD_SIGNAL = settings.MACD_SETTINGS['signal_period']

FEATURES = [
    'volatility', 'momentum', 'sma_ratio', 'rsi', 'macd', 'macd_signal', 'macd_hist'
    # Add/remove features here, ensuring ml_strategy.py matches EXACTLY
]
TARGET_SHIFT = -1 # Predict next bar's direction (-1)
TARGET_CLASSES = [0, 1] # 0 for down/flat, 1 for up


def load_data(data_dir='data/historical_data', symbol_filter=None):
    """
    Loads historical data from CSV files. Expects UTC timestamps in 'timestamp' column.
    Args:
        data_dir (str): Directory containing historical data CSVs.
        symbol_filter (list, optional): List of symbols (filenames without .csv) to load. Loads all if None.
    """
    if not os.path.isdir(data_dir):
        error_logger.error(f"Historical data directory not found: {data_dir}")
        return pd.DataFrame()

    all_files = [f for f in os.listdir(data_dir) if f.endswith('.csv')]
    if symbol_filter:
        # Normalize filenames (e.g., ETH_USD.csv from ETH/USD)
        symbol_files = {f"{s.replace('/', '_')}.csv" for s in symbol_filter}
        files_to_load = [f for f in all_files if f in symbol_files]
        if not files_to_load:
             logger.warning(f"No matching historical files found for filter: {symbol_filter} in {data_dir}")
             return pd.DataFrame()
    else:
        files_to_load = all_files

    if not files_to_load:
        logger.warning(f"No historical CSV files found in {data_dir}")
        return pd.DataFrame()

    data_frames = []
    logger.info(f"Loading data from: {files_to_load}")
    for file in files_to_load:
        try:
            filepath = os.path.join(data_dir, file)
            df = pd.read_csv(filepath)
            # --- Timestamp Handling ---
            if 'timestamp' not in df.columns:
                 logger.warning(f"Skipping file {file}: Missing required 'timestamp' column.")
                 continue
            try:
                 # Assume timestamp is already UTC or parse accordingly
                 df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
                 df = df.set_index('timestamp') # Set index for easier time-series operations
            except Exception as time_e:
                 logger.warning(f"Could not parse timestamp in {file}: {time_e}. Skipping file.")
                 continue

            if not all(col in df.columns for col in ['open', 'high', 'low', 'close', 'volume']):
                 logger.warning(f"Skipping file {file}: Missing required OHLCV columns.")
                 continue

            # Convert OHLCV to numeric early
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            df.dropna(subset=['open', 'high', 'low', 'close'], inplace=True) # Drop rows with NaN OHLC

            # Add symbol identifier
            symbol = file.replace('.csv', '').replace('_', '/') # Convert filename back
            df['symbol'] = symbol
            logger.debug(f"Loaded {len(df)} rows from {file} for symbol {symbol}")
            data_frames.append(df.reset_index()) # Reset index before concat if needed
        except Exception as e:
            error_logger.error(f"Failed to load or process file {file}: {e}", exc_info=True)

    if not data_frames:
        error_logger.error("No valid data could be loaded.")
        return pd.DataFrame()

    # Combine and sort globally
    data = pd.concat(data_frames, ignore_index=True)
    try:
        # Ensure final sort order
        data = data.sort_values(by=['symbol', 'timestamp']).reset_index(drop=True)
        logger.info(f"Total historical data loaded: {len(data)} rows from {len(data_frames)} files.")
    except Exception as e:
         error_logger.error(f"Error sorting concatenated data: {e}", exc_info=True)
         return pd.DataFrame()

    return data

def engineer_features(data):
    """
    Engineers features for the ML model. Must match ml_strategy.py features.
    Uses parameters defined globally in this script (read from Settings).
    """
    logger.info("Starting feature engineering...")
    if data.empty:
        logger.warning("Cannot engineer features: Input data is empty.")
        return pd.DataFrame(), pd.Series()

    required_cols = ['timestamp', 'symbol', 'open', 'high', 'low', 'close', 'volume']
    if not all(col in data.columns for col in required_cols):
        logger.error(f"Input data missing required columns for feature engineering: Need {required_cols}")
        return pd.DataFrame(), pd.Series()

    # Sort data globally first
    data = data.sort_values(by=['symbol', 'timestamp']).set_index('timestamp')

    all_features_df = []

    # Process each symbol independently
    for symbol, group in data.groupby('symbol', group_keys=False): # group_keys=False optional
        df = group.copy()
        logger.debug(f"Processing features for {symbol} ({len(df)} rows)")

        # Calculate features using imported functions
        try:
            # Simple return/volatility
            df['return'] = df['close'].pct_change()
            df['volatility'] = df['return'].rolling(window=VOLATILITY_WINDOW).std()
            # Momentum (Price Change over N periods)
            df['momentum'] = df['close'].pct_change(periods=MOMENTUM_WINDOW)
            # SMA Ratio (Close / SMA)
            sma = calculate_sma(df, SMA_WINDOW)
            df['sma_ratio'] = (df['close'] / sma) # Handle potential division by zero later
            # RSI
            df['rsi'] = calculate_rsi(df, period=RSI_PERIOD)
            # MACD
            macd_line, macd_signal_line, macd_hist = calculate_macd(
                df, fast_period=MACD_FAST, slow_period=MACD_SLOW, signal_period=MACD_SIGNAL
            )
            df['macd'] = macd_line
            df['macd_signal'] = macd_signal_line
            df['macd_hist'] = macd_hist

            # Define Target Variable
            df['target'] = np.where(df['close'].shift(TARGET_SHIFT) > df['close'], 1, 0)

            all_features_df.append(df)

        except Exception as e:
            error_logger.error(f"Error engineering features for symbol {symbol}: {e}", exc_info=True)
            continue # Skip this symbol if features fail

    if not all_features_df:
        logger.error("Feature engineering yielded no results (perhaps errors for all symbols?).")
        return pd.DataFrame(), pd.Series()

    # Combine results from all symbols
    processed_data = pd.concat(all_features_df)

    # --- Data Cleaning Post-Feature Engineering ---
    initial_rows = len(processed_data)
    # Handle infinities resulting from division by zero (e.g., sma_ratio)
    processed_data.replace([np.inf, -np.inf], np.nan, inplace=True)
    # Drop rows with NaN in features OR target (important!)
    processed_data.dropna(subset=FEATURES + ['target'], inplace=True)
    final_rows = len(processed_data)
    logger.info(f"Feature engineering complete. Rows dropped due to NaNs/Infs: {initial_rows - final_rows}. Remaining: {final_rows}")

    if final_rows == 0:
        logger.error("No data remaining after feature engineering and NaN removal.")
        return pd.DataFrame(), pd.Series()

    # Separate features (X) and target (y)
    X = processed_data[FEATURES]
    y = processed_data['target']
    return X, y


def train_model(X, y):
    """
    Trains or retrains the SGDClassifier model. Creates new model/scaler each time.
    """
    logger.info(f"Starting model training with {len(X)} samples.")
    if len(X) < 50: # Add a minimum sample check
        logger.error(f"Training aborted: Insufficient data samples ({len(X)}). Need at least 50.")
        return None, None, 0.0

    # Split data (chronological split is better for time series)
    split_index = int(len(X) * 0.8)
    X_train, X_val = X[:split_index], X[split_index:]
    y_train, y_val = y[:split_index], y[split_index:]

    if len(X_train) == 0 or len(X_val) == 0:
        logger.error("Training aborted: Train or Validation set is empty after split.")
        return None, None, 0.0
    logger.info(f"Train size: {len(X_train)}, Validation size: {len(X_val)}")

    # --- Scaler ---
    # Always fit a new scaler on the current training data
    logger.info("Creating and fitting a new StandardScaler.")
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train) # Fit and transform train
    X_val_scaled = scaler.transform(X_val)     # Transform validation

    # --- Model Training ---
    # Reinitialize model each time for a full retrain from scratch
    logger.info("Creating a new SGDClassifier model for training.")
    model = SGDClassifier(
        loss='log_loss',        # Logistic regression
        penalty='l2',           # Regularization
        max_iter=2500,          # Increased iterations
        tol=1e-4,               # Convergence tolerance
        random_state=42,        # Reproducibility
        shuffle=True,           # Shuffle data each epoch
        early_stopping=True,    # Stop if validation score doesn't improve
        n_iter_no_change=20,    # Patience for early stopping (increased)
        validation_fraction=0.15, # Use portion of training data for early stopping validation
        class_weight='balanced' # Adjust weights for imbalanced classes
    )

    try:
        model.fit(X_train_scaled, y_train)
        logger.info("Model training complete.")
    except Exception as e:
        error_logger.critical(f"Exception during model.fit: {e}", exc_info=True)
        return None, None, 0.0 # Indicate failure

    # --- Evaluation ---
    try:
        y_pred_val = model.predict(X_val_scaled)
        val_accuracy = accuracy_score(y_val, y_pred_val)
        logger.info(f"Validation Accuracy: {val_accuracy:.4f}")
        # Print and log classification report
        report = classification_report(y_val, y_pred_val, target_names=['Down/Flat (0)', 'Up (1)'], zero_division=0)
        print("\n--- Validation Classification Report ---")
        print(report)
        print("--------------------------------------\n")
        logger.info("Validation Classification Report:\n" + report)
    except Exception as e:
        error_logger.error(f"Exception during model evaluation: {e}", exc_info=True)
        val_accuracy = 0.0 # Set accuracy to 0 on evaluation error

    # --- Save Model and Scaler ---
    try:
        os.makedirs(MODEL_DIR, exist_ok=True)
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        # Include version and accuracy in filename for tracking
        ver_acc_str = f"v{MODEL_VERSION}_acc{val_accuracy:.3f}".replace('.', 'p') # Replace . for safe filename
        model_filename = f"{MODEL_BASE_NAME}_{ver_acc_str}_{timestamp_str}.pkl"
        scaler_filename = f"{SCALER_BASE_NAME}_{ver_acc_str}_{timestamp_str}.pkl"
        model_path = os.path.join(MODEL_DIR, model_filename)
        scaler_path = os.path.join(MODEL_DIR, scaler_filename)

        joblib.dump(model, model_path)
        joblib.dump(scaler, scaler_path)
        logger.info(f"Model saved to: {model_path}")
        logger.info(f"Scaler saved to: {scaler_path}")

        # Overwrite/Create 'latest' symlinks/files for the bot to load easily
        latest_model_path = os.path.join(MODEL_DIR, f"{MODEL_BASE_NAME}.pkl")
        latest_scaler_path = os.path.join(MODEL_DIR, f"{SCALER_BASE_NAME}.pkl")
        # Use joblib again for atomicity if possible
        joblib.dump(model, latest_model_path)
        joblib.dump(scaler, latest_scaler_path)
        logger.info(f"Updated 'latest' model/scaler files: {MODEL_BASE_NAME}.pkl, {SCALER_BASE_NAME}.pkl")

    except Exception as e:
        error_logger.critical(f"Failed to save model or scaler: {e}", exc_info=True)
        return None, None, val_accuracy # Return accuracy even if saving failed

    return model, scaler, val_accuracy


def main(symbol_filter=None):
    """ Main function to run the training process. Returns True on success, False on failure. """
    logger.info(f"--- Starting ML Model Training (Version: {MODEL_VERSION}) ---")

    # 1. Load Data
    # Potentially load specific symbols if provided via command line
    data = load_data(symbol_filter=symbol_filter)
    if data.empty:
        error_logger.critical("Training aborted: No data loaded.")
        print("Training aborted: No data loaded.")
        return False # Indicate failure

    # 2. Feature Engineering
    X, y = engineer_features(data)
    if X.empty or y.empty:
        error_logger.critical("Training aborted: Feature engineering resulted in no data.")
        print("Training aborted: Feature engineering resulted in no data.")
        return False

    # 3. Train Model
    try:
        # Train a new model from scratch each time
        model, scaler, accuracy = train_model(X, y)
        if model is None or scaler is None:
             error_logger.error("Training failed: Model or scaler was not returned.")
             print("Training failed: Model or scaler generation failed.")
             return False

        logger.info(f"--- ML Model Training Finished (Validation Accuracy: {accuracy:.4f}) ---")
        print(f"--- ML Model Training Finished (Validation Accuracy: {accuracy:.4f}) ---")
        return True # Indicate success

    except Exception as e:
        error_logger.critical(f"An unexpected error occurred during model training: {e}", exc_info=True)
        print(f"An unexpected error occurred during model training: {e}")
        logger.info("--- ML Model Training Failed ---")
        return False # Indicate failure


if __name__ == "__main__":
    # --- Command Line Argument Parsing ---
    parser = argparse.ArgumentParser(description='Train the ML trading model.')
    parser.add_argument(
        '--symbols',
        type=str,
        help='Comma-separated list of symbols (e.g., AAPL,MSFT or ETH/USD,BTC/USD) to train on. Trains on all found CSVs if omitted.'
    )
    args = parser.parse_args()

    symbols_to_train = None
    if args.symbols:
        # Split and sanitize symbols
        symbols_to_train = [s.strip().upper() for s in args.symbols.split(',') if s.strip()]
        logger.info(f"Training requested for specific symbols: {symbols_to_train}")
    else:
        logger.info("Training on all available historical data files.")

    # --- Execute Main Training Function ---
    training_success = main(symbol_filter=symbols_to_train)

    # Exit with appropriate code based on success
    sys.exit(0 if training_success else 1)