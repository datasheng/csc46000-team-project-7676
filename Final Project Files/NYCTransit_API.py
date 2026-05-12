#########################
# 1- Libraries Required #
#########################
import pandas as pd
import requests
from sqlalchemy import create_engine
from datetime import date, timedelta
import time

################################################
# 2- Settings for both API call and SQL Upload #
################################################

START_DATE = date(2026, 1, 1)
END_DATE = date(2026, 3, 31)

# NYC Open Data Socrata endpoint for DOT Traffic Speeds
API_URL = "https://data.cityofnewyork.us/resource/i4gi-tjb9.json"

# MySQL connection
engine = create_engine(
    "mysql+pymysql://root:SillyOnion!#23@localhost/weather_project"
)

TABLE_NAME = "traffic_information"

##################################
# 2- Actual API request          #
##################################

all_rows = []

current_date = START_DATE

while current_date <= END_DATE:
    next_date = current_date + timedelta(days=1)

    where_clause = (
        f"data_as_of >= '{current_date}T00:00:00' "
        f"AND data_as_of < '{next_date}T00:00:00'"
    )

    params = {
        "$limit": 50000,
        "$where": where_clause,
        "$order": "data_as_of ASC"
    }

    print(f"Requesting traffic data for {current_date}...")

    response = requests.get(API_URL, params=params)

    print("Status code:", response.status_code)

    if response.status_code != 200:
        print("Response preview:")
        print(response.text[:1000])
        response.raise_for_status()

    rows = response.json()
    print(f"Rows received: {len(rows)}")

    all_rows.extend(rows)

    current_date = next_date

    # Small pause to be polite to the API
    time.sleep(0.5)

df_traffic = pd.DataFrame(all_rows)

print("Total rows collected:", len(df_traffic))

if df_traffic.empty:
    print("No traffic data found for this date range.")
else:
    print("Columns received:")
    print(df_traffic.columns.tolist())

    print("Preview before cleaning:")
    print(df_traffic.head())



#########################
# 3- Data Cleaning      #
#########################
    # Convert traffic timestamp
    df_traffic["data_as_of"] = pd.to_datetime(
        df_traffic["data_as_of"],
        errors="coerce"
    )

    # Round/floor each traffic timestamp down to the hour.
    df_traffic["traffic_hour"] = df_traffic["data_as_of"].dt.floor("h")

    # Create date-only helper field
    df_traffic["traffic_date"] = df_traffic["data_as_of"].dt.date

    # Convert numeric fields
    numeric_cols = [
        "speed",
        "travel_time",
        "link_id",
        "transcom_id"
    ]

    for col in numeric_cols:
        if col in df_traffic.columns:
            df_traffic[col] = pd.to_numeric(df_traffic[col], errors="coerce")

    # Remove bad rows
    df_traffic = df_traffic[
        df_traffic["data_as_of"].notna()
        & df_traffic["traffic_hour"].notna()
    ]

    if "speed" in df_traffic.columns:
        df_traffic = df_traffic[
            df_traffic["speed"].notna()
            & (df_traffic["speed"] > 0)
            & (df_traffic["speed"] <= 80)
        ]

    print("Preview after cleaning:")
    print(df_traffic.head())

    print("Final shape:", df_traffic.shape)

#########################
# 4- My SQL Upload      #
#########################

    df_traffic.to_sql(
        TABLE_NAME,
        con=engine,
        if_exists="append",
        index=False
    )

    print(f"Uploaded to MySQL table: {TABLE_NAME}")