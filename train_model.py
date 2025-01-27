# /train_model.py

import os
import pandas as pd
import numpy as np
from sklearn.linear_model import SGDClassifier
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.metrics import accuracy_score
from utils.logger import setup_logger
import joblib
from sklearn.model_selection import train_test_split

# Set up logger
logger = setup_logger('model_training_logger', 'logs/model_training.log')

def load_existing_model():
    model_path = 'models/trading_model.pkl'
    scaler_path = 'models/scaler.pkl'
    if os.path.exists(model_path) and os.path.exists(scaler_path):
        model = joblib.load(model_path)
        scaler = joblib.load(scaler_path)
        logger.info("Existing model and scaler loaded.")
    else:
        model = SGDClassifier(max_iter=1000, tol=1e-3, random_state=42)
        scaler = StandardScaler()
        logger.info("No existing model found. Created new model and scaler.")
    return model, scaler

def load_data():
    data_dir = 'data/historical_data'
    if not os.path.isdir(data_dir):
        logger.error("No historical data directory found.")
        return pd.DataFrame()

    all_files = os.listdir(data_dir)
    data_frames = []
    for file in all_files:
        if file.endswith('.csv'):
            df = pd.read_csv(os.path.join(data_dir, file))
            df['symbol'] = file.replace('.csv', '')
            data_frames.append(df)
    if data_frames:
        data = pd.concat(data_frames, ignore_index=True)
        return data
    else:
        logger.error("No historical data files found.")
        return pd.DataFrame()

def preprocess_data(data):
    # Ensure data is sorted by timestamp
    data.sort_values(by='timestamp', inplace=True)
    # Convert timestamp to datetime
    data['timestamp'] = pd.to_datetime(data['timestamp'])

    # Feature engineering
    data['return'] = data['close'].pct_change()
    data['volatility'] = data['return'].rolling(window=5).std()
    data['momentum'] = data['close'] / data['close'].shift(5) - 1
    data['sma'] = data['close'].rolling(window=10).mean()
    data['sma_ratio'] = data['close'] / data['sma']

    # Drop NaNs
    data = data.dropna().copy()

    # Define the target variable
    data['target'] = np.where(data['close'].shift(-1) > data['close'], 1, 0)

    # One-hot encode the symbol
    symbol_encoder = OneHotEncoder(sparse=False)
    symbol_encoded = symbol_encoder.fit_transform(data[['symbol']])
    symbol_feature_names = symbol_encoder.get_feature_names_out(['symbol'])
    symbol_df = pd.DataFrame(symbol_encoded, columns=symbol_feature_names)

    # Combine with other features
    features = ['volatility', 'momentum', 'sma_ratio']
    X = pd.concat([data[features].reset_index(drop=True), symbol_df.reset_index(drop=True)], axis=1)
    y = data['target'].reset_index(drop=True)

    return X, y

def train_model(X, y, model, scaler):
    # Split data into training and validation sets (e.g., 80% train, 20% validation)
    X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, shuffle=False)

    # Fit scaler on training data and transform both training and validation data
    scaler.partial_fit(X_train)
    X_train_scaled = scaler.transform(X_train)
    X_val_scaled = scaler.transform(X_val)

    # Incremental training
    model.partial_fit(X_train_scaled, y_train, classes=np.array([0, 1]))

    # Evaluate on validation set
    y_pred = model.predict(X_val_scaled)
    accuracy = accuracy_score(y_val, y_pred)
    logger.info(f"Validation accuracy: {accuracy:.4f}")

    # Implement early stopping based on validation accuracy
    if accuracy < 0.5:
        logger.warning("Validation accuracy is low. Consider retraining or adjusting parameters.")

    # Save the updated model and scaler
    os.makedirs('models', exist_ok=True)
    joblib.dump(model, model_path := 'models/trading_model.pkl')
    joblib.dump(scaler, scaler_path := 'models/scaler.pkl')
    logger.info(f"Model and scaler saved to {model_path} and {scaler_path}.")

def main():
    data = load_data()
    if data.empty:
        logger.error("No data available for training.")
        return

    X, y = preprocess_data(data)
    model, scaler = load_existing_model()
    train_model(X, y, model, scaler)

if __name__ == "__main__":
    main()
