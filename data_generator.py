import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def generate_retail_data(start_date="2024-01-01", end_date="2026-06-01", seed=42):
    """
    Generates realistic historical daily sales data for 3 stores and 4 products.
    
    Factors modeled:
    - Weekly seasonality (higher sales on weekends)
    - Yearly seasonality (product specific: e.g., soft drinks in summer, umbrellas in rain)
    - Price elasticity (higher price reduces demand)
    - Promotions (increases demand, decreases price)
    - Holidays (significant demand spike on Thanksgiving/Black Friday/Christmas)
    - Weather effects (temperature and precipitation)
    - Store and Product specific baseline demand and trends.
    """
    np.random.seed(seed)
    
    # Define stores and products with their attributes
    stores = {
        "Store_1": {"name": "Downtown flagship", "base_multiplier": 1.5, "trend": 0.05},
        "Store_2": {"name": "Suburban Hypermarket", "base_multiplier": 1.2, "trend": 0.02},
        "Store_3": {"name": "Express City", "base_multiplier": 0.7, "trend": -0.01}
    }
    
    products = {
        "Prod_1": {
            "name": "Organic Milk 1L", 
            "base_price": 3.5, 
            "base_demand": 120, 
            "elasticity": -0.8,
            "seasonal_type": "perishable_constant",
            "promo_effect": 1.25
        },
        "Prod_2": {
            "name": "Summer Cola 500ml", 
            "base_price": 1.8, 
            "base_demand": 80, 
            "elasticity": -1.8,
            "seasonal_type": "summer_peak",
            "promo_effect": 1.6
        },
        "Prod_3": {
            "name": "Compact Umbrella", 
            "base_price": 12.0, 
            "base_demand": 10, 
            "elasticity": -1.2,
            "seasonal_type": "weather_dependent",
            "promo_effect": 1.15
        },
        "Prod_4": {
            "name": "Premium Coffee Beans 250g", 
            "base_price": 8.5, 
            "base_demand": 45, 
            "elasticity": -2.2,
            "seasonal_type": "winter_peak",
            "promo_effect": 1.8
        }
    }
    
    # Generate Date Range
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    delta = end - start
    date_list = [start + timedelta(days=i) for i in range(delta.days + 1)]
    
    records = []
    
    # Pre-generate weather & holiday conditions for dates
    dates_df = pd.DataFrame({"date": date_list})
    dates_df["day_of_year"] = dates_df["date"].dt.dayofyear
    dates_df["month"] = dates_df["date"].dt.month
    dates_df["day_of_week"] = dates_df["date"].dt.dayofweek
    
    # Weather simulation: temperature peaks in July (month 7), precipitation is higher in spring/autumn
    # Temperature (normal-ish distribution centered around 15C in winter, 28C in summer)
    dates_df["weather_temp"] = 20 + 10 * np.sin(2 * np.pi * (dates_df["day_of_year"] - 105) / 365) + np.random.normal(0, 3, len(dates_df))
    # Precipitation: probability of rain is higher in winter/spring. Represent index 0 (dry) to 1 (heavy rain)
    dates_df["weather_precip"] = np.clip(
        0.2 + 0.3 * np.cos(2 * np.pi * (dates_df["day_of_year"] - 45) / 365) + np.random.normal(0, 0.25, len(dates_df)),
        0, 1
    )
    # Holidays: Thanksgiving (late Nov), Christmas (Dec 25), Black Friday, and random sales events
    dates_df["is_holiday"] = 0
    # Add holiday markers
    for idx, row in dates_df.iterrows():
        dt = row["date"]
        # Christmas period (Dec 20-24)
        if dt.month == 12 and 20 <= dt.day <= 24:
            dates_df.at[idx, "is_holiday"] = 1
        # Black Friday (approx late November - 4th Friday)
        elif dt.month == 11 and dt.dayofweek == 4 and 23 <= dt.day <= 29:
            dates_df.at[idx, "is_holiday"] = 1
        # New Year's Eve (Dec 31)
        elif dt.month == 12 and dt.day == 31:
            dates_df.at[idx, "is_holiday"] = 1
            
    # Generate promotions: specific random intervals
    dates_df["promo_event"] = 0
    np.random.seed(seed + 1)
    # Generate 15-day promotional blocks scattered randomly (about 12% probability of a promo block on any day)
    promo_active = np.zeros(len(dates_df))
    i = 0
    while i < len(dates_df) - 14:
        if np.random.rand() < 0.03: # chance to start a promo block
            promo_active[i:i+10] = 1 # 10 days duration
            i += 15
        else:
            i += 1
    dates_df["promo_event"] = promo_active
    
    # Build complete store/product/date panel
    for store_id, store_info in stores.items():
        for prod_id, prod_info in products.items():
            # Copy dates dataframe and customize
            df = dates_df.copy()
            df["store_id"] = store_id
            df["product_id"] = prod_id
            
            # Base price
            base_price = prod_info["base_price"]
            
            # Pricing details: price drops during promotion
            df["is_promotion"] = df["promo_event"].values
            # Randomize promotion status slightly per store/product (e.g. only 80% stores run the promo at same time)
            mask = df["is_promotion"] == 1
            rand_mask = np.random.rand(len(df)) < 0.8
            df["is_promotion"] = (mask & rand_mask).astype(int)
            
            # Price is lower by 15-30% during promotion, or has small random weekly changes
            df["price"] = base_price
            df.loc[df["is_promotion"] == 1, "price"] = base_price * (1.0 - np.random.uniform(0.15, 0.30, sum(df["is_promotion"] == 1)))
            # Add small random price drift/adjustments (e.g. inflation or random pricing policies)
            df["price"] += np.random.normal(0, base_price * 0.02, len(df))
            df["price"] = df["price"].round(2)
            
            # Core demand formula
            base_demand = prod_info["base_demand"] * store_info["base_multiplier"]
            
            # Trend calculation
            days_since_start = np.arange(len(df))
            trend_factor = 1.0 + (store_info["trend"] / 365.0) * days_since_start
            
            # Weekly seasonality (higher sales on Fri, Sat, Sun)
            # Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6
            weekly_multipliers = {0: 0.85, 1: 0.82, 2: 0.85, 3: 0.95, 4: 1.25, 5: 1.45, 6: 1.15}
            weekly_factor = df["day_of_week"].map(weekly_multipliers).values
            
            # Yearly seasonality based on product type
            yearly_factor = np.ones(len(df))
            if prod_info["seasonal_type"] == "summer_peak":
                # Peak in July (day 180-210)
                yearly_factor = 1.0 + 0.6 * np.sin(2 * np.pi * (df["day_of_year"] - 100) / 365).values
            elif prod_info["seasonal_type"] == "winter_peak":
                # Peak in December/January (day 355/15)
                yearly_factor = 1.0 + 0.4 * np.cos(2 * np.pi * (df["day_of_year"] - 15) / 365).values
            elif prod_info["seasonal_type"] == "perishable_constant":
                # Flat seasonality, very slight weather effects
                yearly_factor = 1.0 + 0.05 * np.sin(2 * np.pi * df["day_of_year"] / 365).values
            elif prod_info["seasonal_type"] == "weather_dependent":
                # Very low base, spikes purely with precipitation
                yearly_factor = 0.5 + 0.1 * np.cos(2 * np.pi * df["day_of_year"] / 365).values
                
            # Weather factors
            weather_factor = np.ones(len(df))
            if prod_info["seasonal_type"] == "summer_peak":
                # Soft drinks sell more in hot weather (temp > 22C)
                weather_factor = np.clip(1.0 + 0.04 * (df["weather_temp"].values - 22), 0.7, 1.8)
            elif prod_info["seasonal_type"] == "weather_dependent":
                # Umbrellas sell heavily in rain
                weather_factor = np.clip(1.0 + 8.0 * df["weather_precip"].values, 1.0, 10.0)
            elif prod_info["seasonal_type"] == "winter_peak":
                # Coffee beans sell more in cold weather
                weather_factor = np.clip(1.0 + 0.03 * (18 - df["weather_temp"].values), 0.8, 1.5)
                
            # Price Elasticity: Q = Q0 * (P/P0) ^ Elasticity
            price_elasticity = prod_info["elasticity"]
            price_ratio = df["price"].values / base_price
            price_factor = np.power(price_ratio, price_elasticity)
            
            # Promotion effect (extra branding boost beyond just price elasticity)
            promo_factor = 1.0 + df["is_promotion"].values * (prod_info["promo_effect"] - 1.0)
            
            # Holiday multiplier
            holiday_multiplier = 1.0 + df["is_holiday"].values * np.random.uniform(0.6, 1.5, len(df))
            
            # Calculate final expected sales
            expected_sales = (
                base_demand * 
                trend_factor * 
                weekly_factor * 
                yearly_factor * 
                weather_factor * 
                price_factor * 
                promo_factor * 
                holiday_multiplier
            )
            
            # Add random noise (Poisson-like distribution variation or Normal scaled by demand)
            noise = np.random.normal(0, np.sqrt(expected_sales) * 1.5, len(df))
            
            # Final sales column, integer format, minimum 0
            df["sales"] = np.clip(np.round(expected_sales + noise), 0, None).astype(int)
            
            # Drop unnecessary columns
            df = df.drop(columns=["day_of_year", "month", "day_of_week", "promo_event"])
            records.append(df)
            
    # Combine all store-product dataframes
    full_df = pd.concat(records, ignore_index=True)
    full_df = full_df.sort_values(by=["store_id", "product_id", "date"]).reset_index(drop=True)
    
    return full_df, stores, products

if __name__ == "__main__":
    df, stores, products = generate_retail_data()
    df.to_csv("historical_sales.csv", index=False)
    print(f"Generated {len(df)} records of sales data.")
    print("Stores:", list(stores.keys()))
    print("Products:", list(products.keys()))
    print(df.head())
