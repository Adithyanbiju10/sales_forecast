import os
import uvicorn
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from data_generator import generate_retail_data
from pipeline import DemandForecaster

app = FastAPI(title="Retail Demand Forecasting API", version="1.0.0")

# Setup paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE_DIR, "historical_sales.csv")
MODEL_PATH = os.path.join(BASE_DIR, "forecaster_model.joblib")
STATIC_DIR = os.path.join(BASE_DIR, "static")

# Instantiate forecaster
forecaster = DemandForecaster(model_path=MODEL_PATH)

# Global variables to cache metadata
stores_info = {}
products_info = {}
is_training = False

def init_data_and_model():
    global stores_info, products_info
    # Generate data if not exists
    if not os.path.exists(DATA_PATH):
        print("Initial launch: Generating historical sales data...")
        df, stores, products = generate_retail_data()
        df.to_csv(DATA_PATH, index=False)
        stores_info = stores
        products_info = products
    else:
        # Load metadata by generating template or read unique keys
        _, stores, products = generate_retail_data()
        stores_info = stores
        products_info = products
        
    # Train model if not exists
    if not os.path.exists(MODEL_PATH):
        print("Initial launch: Training the forecast model...")
        forecaster.train_model(DATA_PATH)
    else:
        # Load the model
        try:
            import joblib
            forecaster.model = joblib.load(MODEL_PATH)
        except Exception as e:
            print(f"Error loading model: {e}. Retraining...")
            forecaster.train_model(DATA_PATH)

# Run initialization
init_data_and_model()

# Request Models
class SimulateRequest(BaseModel):
    store_id: str
    product_id: str
    price_adjust: float  # e.g., -0.10 for 10% discount, +0.10 for 10% increase
    is_promotion: int    # 0 or 1
    weather_temp: float  # Custom temperature override
    weather_precip: float # Custom precipitation override
    is_holiday: int      # 0 or 1

# API Endpoints
@app.get("/api/metadata")
def get_metadata():
    """Returns information about the retail stores and products available."""
    # Convert keys to list of dictionaries for easier select binding on frontend
    stores_list = [{"id": k, **v} for k, v in stores_info.items()]
    products_list = [{"id": k, **v} for k, v in products_info.items()]
    
    # Load model metrics if they exist
    metrics = {}
    metrics_path = MODEL_PATH.replace(".joblib", "_metrics.joblib")
    if os.path.exists(metrics_path):
        import joblib
        metrics = joblib.load(metrics_path)
        
    return {
        "stores": stores_list,
        "products": products_list,
        "metrics": metrics
    }

@app.get("/api/historical")
def get_historical(store_id: str, product_id: str, days: int = 90):
    """Retrieves the last N days of historical sales for a store and product."""
    if not os.path.exists(DATA_PATH):
        raise HTTPException(status_code=404, detail="Sales data not found.")
        
    df = pd.read_csv(DATA_PATH)
    filtered = df[(df["store_id"] == store_id) & (df["product_id"] == product_id)].copy()
    
    if filtered.empty:
        raise HTTPException(status_code=404, detail="Store or Product not found in database.")
        
    filtered["date"] = pd.to_datetime(filtered["date"])
    filtered = filtered.sort_values(by="date")
    
    # Take the last N records
    subset = filtered.tail(days)
    
    # Convert date to string for JSON serialization
    subset["date"] = subset["date"].dt.strftime("%Y-%m-%d")
    
    return subset.to_dict(orient="records")

@app.get("/api/forecast")
def get_forecast(store_id: str, product_id: str):
    """
    Generates a 14-day future demand forecast for the given store and product,
    based on historical sales.
    """
    if not os.path.exists(DATA_PATH):
        raise HTTPException(status_code=404, detail="Sales data not found.")
        
    df = pd.read_csv(DATA_PATH)
    
    # Get historical records for this store/product
    history_all = df[(df["store_id"] == store_id) & (df["product_id"] == product_id)].copy()
    if history_all.empty:
        raise HTTPException(status_code=404, detail="Store or Product not found.")
        
    history_all = history_all.sort_values(by="date").reset_index(drop=True)
    last_row = history_all.iloc[-1]
    last_date = datetime.strptime(last_row["date"], "%Y-%m-%d")
    
    # Needs at least 30 days history to compute rolling averages and lag features
    history_subset = history_all.tail(30).copy()
    
    # Generate future 14-day template
    future_rows = []
    base_price = products_info[product_id]["base_price"]
    
    for i in range(1, 15):
        forecast_date = last_date + timedelta(days=i)
        day_of_year = forecast_date.timetuple().tm_yday
        
        # Calculate standard temperature & precip profiles
        temp = 20 + 10 * np.sin(2 * np.pi * (day_of_year - 105) / 365)
        precip = max(0, 0.2 + 0.3 * np.cos(2 * np.pi * (day_of_year - 45) / 365))
        
        # Default holiday rules
        is_holiday = 0
        if forecast_date.month == 12 and 20 <= forecast_date.day <= 24:
            is_holiday = 1
        elif forecast_date.month == 11 and forecast_date.weekday() == 4 and 23 <= forecast_date.day <= 29:
            is_holiday = 1
        elif forecast_date.month == 12 and forecast_date.day == 31:
            is_holiday = 1
            
        future_rows.append({
            "date": forecast_date.strftime("%Y-%m-%d"),
            "store_id": store_id,
            "product_id": product_id,
            "price": float(base_price),
            "is_promotion": 0,
            "weather_temp": float(temp),
            "weather_precip": float(precip),
            "is_holiday": is_holiday,
            "sales": 0,
            "confidence_lower": 0,
            "confidence_upper": 0
        })
        
    future_df = pd.DataFrame(future_rows)
    
    try:
        # Run recursive forecast
        forecast_result = forecaster.forecast(history_subset, future_df)
        forecast_list = forecast_result.to_dict(orient="records")
        return {
            "forecast": forecast_list,
            "history_last_30": history_subset.to_dict(orient="records")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Forecasting error: {str(e)}")

@app.post("/api/simulate")
def simulate_scenario(req: SimulateRequest):
    """
    Simulates a 14-day demand response by modifying price, promotions, weather, 
    or holiday settings.
    """
    if not os.path.exists(DATA_PATH):
        raise HTTPException(status_code=404, detail="Sales data not found.")
        
    df = pd.read_csv(DATA_PATH)
    history_all = df[(df["store_id"] == req.store_id) & (df["product_id"] == req.product_id)].copy()
    if history_all.empty:
        raise HTTPException(status_code=404, detail="Store or Product not found.")
        
    history_all = history_all.sort_values(by="date").reset_index(drop=True)
    last_row = history_all.iloc[-1]
    last_date = datetime.strptime(last_row["date"], "%Y-%m-%d")
    
    history_subset = history_all.tail(30).copy()
    
    # Calculate price based on override adjustment
    base_price = products_info[req.product_id]["base_price"]
    adjusted_price = max(0.5, round(base_price * (1.0 + req.price_adjust), 2))
    
    future_rows = []
    for i in range(1, 15):
        forecast_date = last_date + timedelta(days=i)
        future_rows.append({
            "date": forecast_date.strftime("%Y-%m-%d"),
            "store_id": req.store_id,
            "product_id": req.product_id,
            "price": adjusted_price,
            "is_promotion": req.is_promotion,
            "weather_temp": req.weather_temp,
            "weather_precip": req.weather_precip,
            "is_holiday": req.is_holiday,
            "sales": 0,
            "confidence_lower": 0,
            "confidence_upper": 0
        })
        
    future_df = pd.DataFrame(future_rows)
    
    try:
        # Perform recursive forecast under simulation parameters
        simulation_result = forecaster.forecast(history_subset, future_df)
        return {
            "simulation": simulation_result.to_dict(orient="records"),
            "adjusted_price": adjusted_price
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Simulation error: {str(e)}")

def train_model_task():
    global is_training
    try:
        forecaster.train_model(DATA_PATH)
    except Exception as e:
        print(f"Error training model: {e}")
    finally:
        is_training = False

@app.post("/api/train")
def train_model(background_tasks: BackgroundTasks):
    """Triggers an asynchronous model retraining job."""
    global is_training
    if is_training:
        return {"status": "already_training", "message": "Model training is already in progress."}
        
    is_training = True
    background_tasks.add_task(train_model_task)
    return {"status": "started", "message": "Model training started in background."}

@app.get("/api/train/status")
def get_train_status():
    """Returns the training status and model metrics if available."""
    metrics = {}
    metrics_path = MODEL_PATH.replace(".joblib", "_metrics.joblib")
    if os.path.exists(metrics_path):
        import joblib
        metrics = joblib.load(metrics_path)
        
    # Get feature importances if they exist
    importances = []
    imp_path = MODEL_PATH.replace(".joblib", "_importances.csv")
    if os.path.exists(imp_path):
        imp_df = pd.read_csv(imp_path)
        importances = imp_df.to_dict(orient="records")
        
    return {
        "is_training": is_training,
        "metrics": metrics,
        "importances": importances
    }

# Serve static files
if os.path.exists(STATIC_DIR):
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
else:
    # If the static dir doesn't exist yet, we serve a temporary endpoint
    @app.get("/")
    def index_placeholder():
        return {"message": "Retail Demand Forecasting backend is running. Frontend static directory is missing or empty."}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
