#########################
# 1- Libraries Required #
#########################
import json
import pandas as pd
import requests
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.engine import URL


##################################
# 2- API Key and Request of Data #
##################################
ApiK = "FYBKXYPHYXR525KQGM5W4UJWY"
Place = "New York,NY"

HourlyInitial = date(2026, 1, 1)
HourlyEnd = date(2026, 1, 31)

url = f"https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline/{Place}/{HourlyInitial}/{HourlyEnd}"

params = {
    "unitGroup": "us",
    "include": "hours",
    "key": ApiK,
    "contentType": "json"
}

response = requests.get(url, params=params)

print("Status code:", response.status_code)
print("Response preview:")
print(response.text[:500])

response.raise_for_status()

data = response.json()

hourly_rows = []


################################################
# 3- Setting the extracted data in a Dataframe #
################################################

for day in data["days"]:
    day_date = day["datetime"]

    for hour in day.get("hours", []):
        row = hour.copy()
        row["weather_date"] = day_date
        row["datetime_full"] = f"{day_date} {hour['datetime']}"
        hourly_rows.append(row)



##################################################################
# 4- Transforming the dataframe to be properly stored into MySQL #
##################################################################

#adjusting the time to match the hourly system.
df_hourly_weather = pd.DataFrame(hourly_rows)
df_hourly_weather["datetime_full"] = pd.to_datetime(
    df_hourly_weather["datetime_full"],
    errors="coerce"
)

df_hourly_weather["weather_date"] = pd.to_datetime(
    df_hourly_weather["weather_date"],
    errors="coerce"
).dt.date

# Convert list/dict values into strings so MySQL accepts them
for col in df_hourly_weather.columns:
    df_hourly_weather[col] = df_hourly_weather[col].apply(
        lambda x: json.dumps(x) if isinstance(x, (list, dict)) else x
    )

#preview for the visual guidance during program run
print("Preview:")
print(df_hourly_weather.head())

print("Rows:", len(df_hourly_weather))
print("Columns:", df_hourly_weather.columns.tolist())



#######################################
# 5- Uploading the Dataframe to MySQL #
#######################################

connection_url = URL.create(
    drivername="mysql+pymysql",
    username="root",
    password="SillyOnion!#23",
    host="localhost",
    database="weather_project",
)

engine = create_engine(connection_url)

if "tzoffset" in df_hourly_weather.columns: #removing time zone offset column, not used and conflicts with other months
    df_hourly_weather = df_hourly_weather.drop(columns=["tzoffset"]) 

df_hourly_weather.to_sql(
    "hourly_weather",
    con=engine,
    if_exists="append",
    index=False
)

print("Uploaded to MySQL table: hourly_weather")