"""
AB_testing.py
Reads weather + traffic from MySQL
Trains Model A (weather only) vs Model B (weather + yesterday's traffic)
Exports results to MySQL for Tableau visualization
"""

import pandas as pd
import numpy as np
from sqlalchemy import create_engine
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error, r2_score


# ============================================================
# 1. CONNECT TO MYSQL & LOAD DATA
# ============================================================

engine = create_engine("mysql+pymysql://root:SillyOnion!#23@localhost/weather_project")

# Load weather data
df_weather = pd.read_sql("SELECT * FROM hourly_weather", con=engine)

# Load traffic data
df_traffic = pd.read_sql("SELECT * FROM traffic_information", con=engine)

print(f"Weather rows: {len(df_weather)}")
print(f"Traffic rows: {len(df_traffic)}")


# ============================================================
# 2. CLEAN & MERGE
# ============================================================

# Standardize timestamps
df_weather["datetime_full"] = pd.to_datetime(df_weather["datetime_full"])
df_traffic["traffic_hour"] = pd.to_datetime(df_traffic["traffic_hour"])

# Merge on hour
df = df_traffic.merge(
    df_weather,
    left_on="traffic_hour",
    right_on="datetime_full",
    how="inner"
)

print(f"Merged rows: {len(df)}")

# Calculate delay (baseline = 30 mph, delay = how much slower)
df["delay_minutes"] = (30 - df["speed"]) / 30 * 10
df["delay_minutes"] = df["delay_minutes"].clip(lower=0)

# Weather condition categories (FIXED: column is 'conditions' not 'weather_condition')
def classify_weather(condition):
    if pd.isna(condition):
        return "Clear"
    condition = str(condition).lower()
    if "rain" in condition:
        return "Rain"
    elif "snow" in condition:
        return "Snow"
    elif "fog" in condition or "mist" in condition:
        return "Fog"
    else:
        return "Clear"

df["weather_condition"] = df["conditions"].apply(classify_weather)


# ============================================================
# 3. DELAY DISTRIBUTION BY WEATHER CONDITION
# ============================================================

delay_by_weather = df.groupby("weather_condition").agg(
    avg_delay=("delay_minutes", "mean"),
    median_delay=("delay_minutes", "median"),
    max_delay=("delay_minutes", "max"),
    min_delay=("delay_minutes", "min"),
    record_count=("delay_minutes", "count")
).reset_index()

print("\n=== DELAY BY WEATHER CONDITION ===")
print(delay_by_weather)

delay_by_weather.to_sql("delay_by_weather", con=engine, if_exists="replace", index=False)
print("Saved to MySQL: delay_by_weather")


# ============================================================
# 4. DELAY DRIVERS BY BOROUGH
# ============================================================

borough_delay = df.groupby("borough").agg(
    avg_delay=("delay_minutes", "mean"),
    avg_speed=("speed", "mean"),
    record_count=("delay_minutes", "count")
).reset_index()

borough_delay["rain_impact"] = 0.0
borough_delay["volume_impact"] = 0.0
borough_delay["other_impact"] = 0.0

for i, row in borough_delay.iterrows():
    borough_data = df[df["borough"] == row["borough"]]
    
    rain_delay = borough_data[borough_data["weather_condition"] == "Rain"]["delay_minutes"].mean()
    clear_delay = borough_data[borough_data["weather_condition"] == "Clear"]["delay_minutes"].mean()
    
    if pd.notna(rain_delay) and pd.notna(clear_delay):
        borough_delay.at[i, "rain_impact"] = max(0, rain_delay - clear_delay)
    
    borough_data_hour = borough_data.copy()
    borough_data_hour["hour"] = borough_data_hour["traffic_hour"].dt.hour
    rush = borough_data_hour[borough_data_hour["hour"].isin([7,8,9,16,17,18,19])]["delay_minutes"].mean()
    non_rush = borough_data_hour[~borough_data_hour["hour"].isin([7,8,9,16,17,18,19])]["delay_minutes"].mean()
    
    if pd.notna(rush) and pd.notna(non_rush):
        borough_delay.at[i, "volume_impact"] = max(0, rush - non_rush)
    
    borough_delay.at[i, "other_impact"] = max(0, row["avg_delay"] - 
        borough_delay.at[i, "rain_impact"] - borough_delay.at[i, "volume_impact"])

print("\n=== DELAY DRIVERS BY BOROUGH ===")
print(borough_delay[["borough", "avg_delay", "rain_impact", "volume_impact", "other_impact"]])

borough_delay.to_sql("delay_drivers_borough", con=engine, if_exists="replace", index=False)
print("Saved to MySQL: delay_drivers_borough")


# ============================================================
# 5. A/B MODEL COMPARISON
# ============================================================

df["is_rush_hour"] = df["traffic_hour"].dt.hour.isin([7,8,9,16,17,18,19]).astype(int)

features_a = ["precip", "temp", "humidity", "is_rush_hour"]

df = df.sort_values(["borough", "traffic_hour"])
df["yesterday_delay"] = df.groupby("borough")["delay_minutes"].shift(24)
df["yesterday_delay"] = df["yesterday_delay"].fillna(df["delay_minutes"].median())

features_b = ["precip", "temp", "humidity", "is_rush_hour", "yesterday_delay"]

df_model = df.dropna(subset=features_a + features_b + ["delay_minutes"])

print(f"\nRows for modeling: {len(df_model)}")

# Prepare data
X_a = df_model[features_a]
X_b = df_model[features_b]
y = df_model["delay_minutes"]

# Split data (same split for both models for fair comparison)
X_train_a, X_test_a, X_train_b, X_test_b, y_train, y_test = train_test_split(
    X_a, X_b, y, test_size=0.2, random_state=42
)

# Model A
model_a = LinearRegression()
model_a.fit(X_train_a, y_train)
y_pred_a = model_a.predict(X_test_a)
rmse_a = np.sqrt(mean_squared_error(y_test, y_pred_a))
r2_a = r2_score(y_test, y_pred_a)

# Model B
model_b = LinearRegression()
model_b.fit(X_train_b, y_train)
y_pred_b = model_b.predict(X_test_b)
rmse_b = np.sqrt(mean_squared_error(y_test, y_pred_b))
r2_b = r2_score(y_test, y_pred_b)

improvement = ((rmse_a - rmse_b) / rmse_a) * 100

print("\n=== A/B MODEL COMPARISON ===")
print(f"Model A (Weather Only):     RMSE = {rmse_a:.2f} min, R² = {r2_a:.3f}")
print(f"Model B (Weather + History): RMSE = {rmse_b:.2f} min, R² = {r2_b:.3f}")
print(f"Improvement: {improvement:.1f}%")

ab_results = pd.DataFrame([
    {"model": "Model A (Weather Only)", "rmse": round(rmse_a, 2), "r2": round(r2_a, 3)},
    {"model": "Model B (Weather + Yesterday)", "rmse": round(rmse_b, 2), "r2": round(r2_b, 3)},
    {"model": "Improvement", "rmse": round(improvement, 1), "r2": 0}
])

ab_results.to_sql("ab_model_results", con=engine, if_exists="replace", index=False)
print("Saved to MySQL: ab_model_results")


# ============================================================
# 6. EXPORT PREDICTIONS FOR TABLEAU
# ============================================================

df_predictions = df_model[["traffic_hour", "borough", "precip", "delay_minutes"]].copy()
df_predictions["predicted_delay_a"] = model_a.predict(df_model[features_a])
df_predictions["predicted_delay_b"] = model_b.predict(df_model[features_b])
df_predictions["model_a_error"] = abs(df_predictions["delay_minutes"] - df_predictions["predicted_delay_a"])
df_predictions["model_b_error"] = abs(df_predictions["delay_minutes"] - df_predictions["predicted_delay_b"])

df_predictions.to_sql("model_predictions", con=engine, if_exists="replace", index=False)
print("Saved to MySQL: model_predictions")