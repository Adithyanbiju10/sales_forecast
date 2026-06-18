import os
import joblib
import pandas as pd
import numpy as np
from datetime import datetime
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder
from sklearn.pipeline import Pipeline
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
from data_generator import generate_retail_data

class DemandForecaster:
    def __init__(self, model_path="forecaster_model.joblib"):
        self.model_path = model_path
        self.model = None
        self.feature_cols = [
            "store_id", "product_id", "price", "is_promotion", 
            "weather_temp", "weather_precip", "is_holiday", 
            "dayofweek", "month", "is_weekend",
            "sales_lag_7", "sales_lag_14", "sales_roll_mean_7", "sales_roll_mean_14"
        ]
        self.categorical_cols = ["store_id", "product_id"]
        
    def create_features(self, df):
        """
        Creates time-series features: lags, rolling windows, and date parts.
        Assumes df is sorted by store_id, product_id, date.
        """
        df_feats = df.copy()
        
        # Ensure date type
        df_feats["date"] = pd.to_datetime(df_feats["date"])
        
        # Calendar features
        df_feats["dayofweek"] = df_feats["date"].dt.dayofweek
        df_feats["month"] = df_feats["date"].dt.month
        df_feats["year"] = df_feats["date"].dt.year
        df_feats["is_weekend"] = df_feats["dayofweek"].isin([5, 6]).astype(int)
        
        # Sort to ensure lag calculations are correct
        df_feats = df_feats.sort_values(by=["store_id", "product_id", "date"]).reset_index(drop=True)
        
        # Lag and Rolling features grouped by store & product
        # Lag sales
        df_feats["sales_lag_7"] = df_feats.groupby(["store_id", "product_id"])["sales"].shift(7)
        df_feats["sales_lag_14"] = df_feats.groupby(["store_id", "product_id"])["sales"].shift(14)
        
        # Rolling sales (shifted by 1 to prevent data leakage of the target)
        df_feats["sales_roll_mean_7"] = (
            df_feats.groupby(["store_id", "product_id"])["sales"]
            .shift(1)
            .rolling(window=7, min_periods=1)
            .mean()
        )
        df_feats["sales_roll_mean_14"] = (
            df_feats.groupby(["store_id", "product_id"])["sales"]
            .shift(1)
            .rolling(window=14, min_periods=1)
            .mean()
        )
        
        return df_feats

    def train_model(self, data_path="historical_sales.csv"):
        """
        Loads data, processes features, trains the pipeline, evaluates performance,
        and saves the serialized model and its metrics.
        """
        # Load or generate data
        if not os.path.exists(data_path):
            print(f"Data file {data_path} not found. Generating new synthetic sales data...")
            df, _, _ = generate_retail_data()
            df.to_csv(data_path, index=False)
        else:
            df = pd.read_csv(data_path)
            
        print("Preprocessing data and engineering features...")
        df_feats = self.create_features(df)
        
        # Drop rows where lag features are NaN (due to shifting at start of timeline)
        df_clean = df_feats.dropna().copy()
        
        X = df_clean[self.feature_cols]
        y = df_clean["sales"]
        
        # Time-based train-validation split (last 45 days for validation)
        max_date = df_clean["date"].max()
        split_date = max_date - pd.Timedelta(days=45)
        
        train_mask = df_clean["date"] <= split_date
        val_mask = df_clean["date"] > split_date
        
        X_train, y_train = X[train_mask], y[train_mask]
        X_val, y_val = X[val_mask], y[val_mask]
        
        print(f"Training set: {len(X_train)} records (up to {split_date.strftime('%Y-%m-%d')})")
        print(f"Validation set: {len(X_val)} records (after {split_date.strftime('%Y-%m-%d')})")
        
        # Build Preprocessing & Estimator Pipeline
        preprocessor = ColumnTransformer(
            transformers=[
                ("cat", OneHotEncoder(handle_unknown="ignore"), self.categorical_cols)
            ],
            remainder="passthrough"
        )
        
        # Use RandomForestRegressor - excellent accuracy and built-in feature importances
        model_pipeline = Pipeline(steps=[
            ("preprocessor", preprocessor),
            ("regressor", RandomForestRegressor(n_estimators=100, max_depth=12, random_state=42, n_jobs=-1))
        ])
        
        # Fit pipeline
        print("Fitting RandomForest model...")
        model_pipeline.fit(X_train, y_train)
        
        # Evaluate
        val_preds = model_pipeline.predict(X_val)
        
        rmse = np.sqrt(mean_squared_error(y_val, val_preds))
        mae = mean_absolute_error(y_val, val_preds)
        r2 = r2_score(y_val, val_preds)
        
        # MAPE: Mean Absolute Percentage Error (avoid division by zero)
        nonzero_mask = y_val > 0
        mape = float(np.mean(np.abs((y_val[nonzero_mask] - val_preds[nonzero_mask]) / y_val[nonzero_mask])) * 100)
        
        # Calculate baseline metrics (7-day seasonal lag baseline)
        baseline_preds = X_val["sales_lag_7"]
        b_rmse = np.sqrt(mean_squared_error(y_val, baseline_preds))
        b_mae = mean_absolute_error(y_val, baseline_preds)
        b_r2 = r2_score(y_val, baseline_preds)
        b_mape = float(np.mean(np.abs((y_val[nonzero_mask] - baseline_preds[nonzero_mask]) / y_val[nonzero_mask])) * 100)
        
        # Model improvement over baseline (as positive % means model is better)
        model_vs_baseline_pct = float(((b_rmse - rmse) / b_rmse) * 100) if b_rmse > 0 else 0.0
        
        metrics = {
            "val_rmse": float(rmse),
            "val_mae": float(mae),
            "val_r2": float(r2),
            "val_mape": mape,
            "baseline_rmse": float(b_rmse),
            "baseline_mae": float(b_mae),
            "baseline_r2": float(b_r2),
            "baseline_mape": b_mape,
            "model_vs_baseline_pct": model_vs_baseline_pct,
            "train_size": len(X_train),
            "val_size": len(X_val),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        print(f"Validation Metrics: RMSE={rmse:.2f}, MAE={mae:.2f}, R2={r2:.4f}")
        
        # Refit on ALL data for final model
        print("Refitting model on full dataset...")
        model_pipeline.fit(X, y)
        
        self.model = model_pipeline
        
        # Save model and metrics
        joblib.dump(model_pipeline, self.model_path)
        joblib.dump(metrics, self.model_path.replace(".joblib", "_metrics.joblib"))
        
        # Extract feature importances
        feature_names = self._get_feature_names(preprocessor)
        importances = model_pipeline.named_steps["regressor"].feature_importances_
        feat_imp_df = pd.DataFrame({"feature": feature_names, "importance": importances})
        feat_imp_df = feat_imp_df.sort_values(by="importance", ascending=False).reset_index(drop=True)
        feat_imp_df.to_csv(self.model_path.replace(".joblib", "_importances.csv"), index=False)
        
        print("Model and metrics saved successfully.")
        return metrics

    def _get_feature_names(self, preprocessor):
        """Helper to extract feature names from the column transformer."""
        # Get categorical feature names after one-hot encoding
        ohe = preprocessor.named_transformers_["cat"]
        cat_features = list(ohe.get_feature_names_out(self.categorical_cols))
        # Non-categorical columns
        num_features = [col for col in self.feature_cols if col not in self.categorical_cols]
        return cat_features + num_features

    def forecast(self, history_df, future_df):
        """
        Performs recursive forecasting over the future_df dates.
        - history_df: historical sales data for the given store/product (at least past 30 days)
        - future_df: features for the future forecast days (date, price, is_promotion, weather_temp, weather_precip, is_holiday)
        """
        if self.model is None:
            if os.path.exists(self.model_path):
                self.model = joblib.load(self.model_path)
            else:
                raise FileNotFoundError("Model not trained yet. Run train_model() first.")
                
        # Combine history and future
        combined = pd.concat([history_df, future_df], ignore_index=True)
        combined["date"] = pd.to_datetime(combined["date"])
        combined = combined.sort_values(by=["store_id", "product_id", "date"]).reset_index(drop=True)
        
        # Find index where forecast starts
        forecast_start_idx = len(history_df)
        
        # Run recursive generation day by day
        for idx in range(forecast_start_idx, len(combined)):
            # Update date features for this row
            row_date = combined.loc[idx, "date"]
            combined.loc[idx, "dayofweek"] = row_date.dayofweek
            combined.loc[idx, "month"] = row_date.month
            combined.loc[idx, "is_weekend"] = 1 if row_date.dayofweek in [5, 6] else 0
            
            # Recalculate lags and rolling averages using sales column
            # sales_lag_7: sales 7 days ago
            combined.loc[idx, "sales_lag_7"] = combined.loc[idx - 7, "sales"]
            # sales_lag_14: sales 14 days ago
            combined.loc[idx, "sales_lag_14"] = combined.loc[idx - 14, "sales"]
            
            # sales_roll_mean_7: mean of past 7 days (indexes idx-7 to idx-1)
            combined.loc[idx, "sales_roll_mean_7"] = combined.loc[idx - 7 : idx - 1, "sales"].mean()
            # sales_roll_mean_14: mean of past 14 days (indexes idx-14 to idx-1)
            combined.loc[idx, "sales_roll_mean_14"] = combined.loc[idx - 14 : idx - 1, "sales"].mean()
            
            # Extract features for prediction
            features = combined.loc[[idx], self.feature_cols]
            
            # Predict with individual estimator variance for confidence intervals
            pred_sales = self.model.predict(features)[0]
            
            # Compute per-tree predictions to get std deviation
            regressor = self.model.named_steps["regressor"]
            preprocessor = self.model.named_steps["preprocessor"]
            features_transformed = preprocessor.transform(features)
            tree_preds = np.array([tree.predict(features_transformed)[0] for tree in regressor.estimators_])
            pred_std = float(np.std(tree_preds))
            
            combined.loc[idx, "sales"] = max(0, round(pred_sales))
            combined.loc[idx, "confidence_lower"] = max(0, round(pred_sales - pred_std))
            combined.loc[idx, "confidence_upper"] = max(0, round(pred_sales + pred_std))
            
        # Return only the forecasted rows
        return combined.iloc[forecast_start_idx:].copy()

if __name__ == "__main__":
    forecaster = DemandForecaster()
    forecaster.train_model()
