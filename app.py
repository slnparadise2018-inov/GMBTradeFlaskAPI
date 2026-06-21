from flask import Flask, jsonify, request, send_file
import requests
from flask_cors import CORS
import hashlib
import time
from statsmodels.tsa.arima.model import ARIMA
import pandas as pd
import numpy as np
import json
import os
from dotenv import load_dotenv
import math

import certifi
from datetime import timedelta
import urllib3

from datetime import datetime, timedelta
from dateutil import parser

#from breeze_worker import start_worker, stop_worker, worker_status
from workers.breeze_ws_worker import start_worker, stop_worker, status

from flask_sock import Sock
import signal, sys, csv
from workers.breeze_ws_worker import start_worker, stop_worker, status, ws_clients

app = Flask(__name__)

# SSL certificate handling
CERT_FILE = "./corporate_proxy_cert.pem"
REQUEST_VERIFY = CERT_FILE if os.path.exists(CERT_FILE) else True

# load_dotenv()

sock = Sock(app)

from app_config import (
    BREEZE_API_KEY, BREEZE_API_SECRETE, BREEZE_API_SESSION, BREEZE_CLIENT_CODE
)

app = Flask(__name__)
CORS(app)  # Allow Angular calls

#Remove in prod
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

#BREEZE_API_KEY='95C%9965S615Z801Y227Nbkc7m292W5a'
#BREEZE_API_SECRETE='Hnt53359q69c39f94034_7U838ia7627'
#BREEZE_API_SESSION='54465786'
#BREEZE_CLIENT_CODE='MAHVW003'

# Select Stock (USE SYMBOL AS SHOWN ON NSE) eg: RELIANCE
STOCK = 'RELIANCE' 

NEWS_API_KEY = 'a7bf62abdfe7481fa87c9e46b3f866d3'
NEWS_API_URL = 'https://newsapi.org/v2/everything'

#NEWS_API_KEY = 'YOUR_NEWSAPI_KEY'
FILING_API_KEY = 'YOUR_STOCKINSIGHTS_API_KEY'

# Import Libraries
from breeze_connect import BreezeConnect

# Setup my API keys 
api = BreezeConnect(api_key=BREEZE_API_KEY)
print("Session Key : " + BREEZE_API_SESSION)
api.generate_session(api_secret=BREEZE_API_SECRETE,session_token=BREEZE_API_SESSION)


@app.route('/api/historical', methods=['GET', 'POST'])
def get_historical_data():
    #STOCK = api.get_names('NSE', STOCK)['isec_stock_code']
    #print(STOCK)
    if request.method == 'POST':
        data = request.get_json()
        symbol = data.get('symbol', 'ICIBANK')
        from_date = data.get('from_date', '2025-02-03T09:21:00.000Z')
        to_date = data.get('to_date', '2025-02-03T09:21:05.000Z')
        interval = data.get('interval', '5minute')
        exchange_code = data.get('exchange_code', 'NSE')
    else:  # GET
        symbol = request.args.get('symbol', 'ICIBANK')
        from_date = request.args.get('from_date', '2025-02-03T09:21:00.000Z')
        to_date = request.args.get('to_date', '2025-02-03T09:21:05.000Z')
        interval = request.args.get('interval', '5minute')
        exchange_code = request.args.get('exchange_code', 'NSE')

    print(symbol,from_date,to_date,interval,exchange_code)

    try:
        data = api.get_historical_data(interval=interval,
                        #from_date= "2025-02-03T09:21:00.000Z",
                        #to_date= "2025-02-03T09:21:05.000Z",
                        #stock_code="NIFTY",
                        from_date=from_date,
                        to_date=to_date,
                        stock_code=symbol,
                        exchange_code=exchange_code,
                        product_type="futures",
                        expiry_date="2025-02-27T07:00:00.000Z",
                        right="others",
                        strike_price="0")
                
        # Check if 'data' is present and is a list
        try:
            json_array = data.get("Success")

            if isinstance(json_array, list):
                print(f"The JSON array contains {len(json_array)} elements.")
            else:
                print("The 'Success' field is not a JSON array.", str(json_array))
                return jsonify({"success": False, "error": str(json_array)}), 500
        except Exception as ex:
            print("Error occurred while fetching historical data:", str(ex))            

        #print(data.count)
        

        
        output_path = os.path.join(os.path.dirname(__file__), 'historicalData.json')
        with open(output_path, 'w') as f:
            json.dump(data, f, indent=2, default=str)

        return jsonify(data)
    except Exception as e:
        print(e)
        return jsonify({"success": False, "error": str(e)}), 500
    

# Python Flask route
@app.route("/api/forecast_arima", methods=["POST"])
def forecast_arima():
    data = request.json["data"]
    # Fit ARIMA model
    model = ARIMA(data, order=(5, 1, 0))
    model_fit = model.fit()
    forecast = model_fit.forecast(steps=30)
    return jsonify(list(forecast))


def fetch_news_events(from_date, to_date):
    params = {
        'apiKey': NEWS_API_KEY,
        'from': from_date,
        'to': to_date,
        'language': 'en',
        'q': 'market OR politics OR economy'
    }
    r = requests.get('https://newsapi.org/v2/everything', params=params).json()
    return [{'date': art['publishedAt'][:10], 'event': art['title'], 'type': 'external'} 
            for art in r.get('articles', [])]

def fetch_company_filings(symbol, from_date, to_date):
    headers = {'Authorization': f'Bearer {FILING_API_KEY}'}
    params = {'ticker': symbol, 'document_type': 'earnings-transcript,annual-report,announcement'}
    r = requests.get('https://stockinsights-ai-main-95a26a0.zuplo.app/api/in/v0/documents', headers=headers, params=params).json()
    events = []
    for doc in r.get('data', []):
        date = doc.get('published_date', '')[:10]
        events.append({'date': date, 'event': f"{doc['company_name']} - {doc['type']}", 'type': 'internal'})
    return events

@app.route('/api/analyze_old', methods=['POST'])
def analyze_old():
    body = request.json
    dates = body.get('dates', [])
    prices = body.get('prices', [])
    symbol = body.get('symbol', '')

    if not (dates and prices and symbol):
        return jsonify({'error': 'missing parameters'}), 400

    df = pd.DataFrame({'date': pd.to_datetime(dates), 'price': prices})
    df.set_index('date', inplace=True)

    model = ARIMA(df['price'], order=(5, 1, 0))
    fit = model.fit()
    forecast_steps = 30
    forecast = fit.forecast(steps=forecast_steps)
    last = df.index[-1]
    fdates = pd.date_range(start=last + pd.Timedelta(days=1), periods=forecast_steps)
    fc = [{'date': d.strftime('%Y-%m-%d'), 'price': round(p, 2)} for d, p in zip(fdates, forecast)]

    ev_hist = fetch_news_events(dates[0], dates[-1])
    ev_hist += fetch_company_filings(symbol, dates[0], dates[-1])
    ev_future = fetch_news_events(fdates[0].strftime('%Y-%m-%d'), fdates[-1].strftime('%Y-%m-%d'))

    return jsonify({
        'forecast': fc,
        'events_historical': ev_hist,
        'events_future': ev_future
    })

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

def fetch_gdelt_events(from_date: str, to_date: str):
    params = {
        "query": "market OR stock OR economy OR inflation OR interest rates",
        "mode": "artlist",
        "maxrecords": 100,
        "format": "json",
        "startdatetime": from_date.replace("-", "") + "000000",
        "enddatetime": to_date.replace("-", "") + "235959"
    }
    r = requests.get(GDELT_URL, params=params)
    events = []
    if r.ok:
        articles = r.json().get("articles", [])
        for art in articles:
            events.append({
                "date": art.get("seendate", "")[:10],
                "event": art.get("title", ""),
                "url": art.get("url", ""),
                "type": "external"
            })
    return events

def nearest_event(date_str, events):
    date = pd.to_datetime(date_str)
    if not events:
        return None
    events_df = pd.DataFrame(events)
    events_df["date"] = pd.to_datetime(events_df["date"])
    events_df["delta"] = (events_df["date"] - date).abs()
    nearest = events_df.sort_values("delta").iloc[0]
    return {
        "date": nearest["date"].strftime('%Y-%m-%d'),
        "event": nearest["event"],
        "type": nearest["type"],
        "url": nearest["url"]
    }

def find_best_buy_sell(df):
    min_price = float('inf')
    max_profit = 0
    buy_date = sell_date = None

    for i in range(len(df)):
        if df['price'].iloc[i] < min_price:
            min_price = df['price'].iloc[i]
            min_index = i
        profit = df['price'].iloc[i] - min_price
        if profit > max_profit:
            max_profit = profit
            buy_date = df.index[min_index]
            sell_date = df.index[i]

    return {
        "buy_date": buy_date.strftime('%Y-%m-%d'),
        "buy_price": round(df.loc[buy_date]['price'], 2),
        "sell_date": sell_date.strftime('%Y-%m-%d'),
        "sell_price": round(df.loc[sell_date]['price'], 2),
        "profit": round(max_profit, 2)
    }

def get_gdelt_events1(start_date, end_date):
    query = f"SELECT DATE, EventCode, Actor1Name, Actor2Name FROM gdeltv2 WHERE DATE BETWEEN '{start_date}' AND '{end_date}'"
    response = requests.get(f'https://api.gdeltproject.org/api/v2/doc/doc?query={query}&format=json',
                            verify=REQUEST_VERIFY)
    data = response.json()

    events = []
    for item in data.get('articles', []):
        events.append({
            'date': item.get('seendate', '')[:10],
            'event': item.get('title', '')
        })

    return events

def remove_nan_objects(data_list):
    clean_list = []
    for obj in data_list:
        if all(
            v is not None and
            not (isinstance(v, float) and (math.isnan(v) or not math.isfinite(v)))
            for v in obj.values()
        ):
            clean_list.append(obj)
    return clean_list

def get_gdelt_events2(start_date, end_date):
    query = f"india"  # NOTE: GDELT does not support SQL-like `SELECT` directly in `query`
    url = f'https://api.gdeltproject.org/api/v2/doc/doc?query={query}&mode=artlist&maxrecords=250&format=json'

    try:
        response = requests.get(url, verify=REQUEST_VERIFY, timeout=10)
        print("🔗 GDELT API status:", response.status_code)

        print("🔎 Response preview:", response.text[:300])

        data = response.json()
    except requests.exceptions.SSLError as e:
        print("❌ SSL error:", e)
        return []
    except requests.exceptions.RequestException as e:
        print("❌ Request error:", e)
        return []
    except Exception as e:
        print("❌ JSON parse or unknown error:", e)
        return []

    events = []
    for item in data.get('articles', []):
        seendate = item.get('seendate', '')[:10]
        if start_date <= seendate <= end_date:
            events.append({
                'date': seendate,
                'event': item.get('title', '')
            })

    print(f"📄 Fetched {len(events)} GDELT events between {start_date} and {end_date}")
    return events

####
def fetch_gdelt_events_for_date(date_str):
    """
    Fetch GDELT events for a specific date using GDELT 2.0 API.
    """
    try:
        print(f"📅 Processing GDELT events for {date_str}")
        query = "stock OR finance OR market OR economy"
        startdatetime = date_str.replace("-", "") + "000000"
        enddatetime = date_str.replace("-", "") + "235959"

        url = (
            f"https://api.gdeltproject.org/api/v2/events/search?"
            f"query={query}&mode=artlist&format=json&maxrecords=250"
            f"&startdatetime={startdatetime}&enddatetime={enddatetime}"
        )
        #print(f"🔗 URL: {url}")

        response = requests.get(url, verify=REQUEST_VERIFY, timeout=10)
        
        if response.status_code == 404:
            print(f"ℹ️ No GDELT events found for {date_str}")
            return []

        response.raise_for_status()
        data = response.json()
        events = []

        for item in data.get('articles', []):
            seendate_raw = item.get('seendate', '')
            try:
                seendate_dt = datetime.strptime(seendate_raw, "%Y%m%dT%H%M%SZ")
                formatted_date = seendate_dt.strftime("%Y-%m-%d")
            except Exception as ex:
                print(f"❌ Failed to parse seendate: {seendate_raw} – {ex}")
                continue

            events.append({
                'date': formatted_date,
                'datetime': seendate_dt.isoformat(),
                'title': item.get('title', ''),
                'url': item.get('url', ''),
                'image': item.get('socialimage', ''),
                'domain': item.get('domain', ''),
                'language': item.get('language', ''),
                'source_country': item.get('sourcecountry', '')
            })

        return events

    except Exception as e:
        print(f"⚠️ Failed to fetch GDELT events for {date_str}: {e}")
        return []

def get_gdelt_events(start_date, end_date):
    # Convert to GDELT datetime format: YYYYMMDDHHMMSS
    try:
        start_date_obj = parser.parse(start_date)
        end_date_obj = parser.parse(end_date)

        start_str = start_date_obj.strftime("%Y%m%d%H%M%S")
        end_str = end_date_obj.strftime("%Y%m%d%H%M%S")

        print(f"Date converted {start_str} {end_str}")

        #start_str = datetime.strptime(start_date, "%Y-%m-%d").strftime("%Y%m%d%H%M%S")
        #end_str = datetime.strptime(end_date, "%Y-%m-%d").strftime("%Y%m%d%H%M%S")

        query = "india"
        url = (
            f"https://api.gdeltproject.org/api/v2/doc/doc?"
            f"query={query}&mode=artlist&format=json&maxrecords=250"
            f"&startdatetime={start_str}&enddatetime={end_str}"
        )

        print(f"url: {url}")
    
        response = requests.get(url, verify=REQUEST_VERIFY, timeout=10)
        print("🔗 GDELT API status:", response.status_code)
        #print("🔎 Response preview:", response.text[:300])
        data = response.json()

        # ✅ Write full response to file
        with open("gdelt_response.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except requests.exceptions.SSLError as e:
        print("❌ SSL error:", e)
        return []
    except requests.exceptions.RequestException as e:
        print("❌ Request error:", e)
        return []
    except Exception as e:
        print("❌ JSON parse or unknown error:", e)
        return []

    #events = []
    
    events = []
    for item in data.get('articles', []):
        seendate_raw = item.get('seendate', '')
        try:
            seendate_dt = datetime.strptime(seendate_raw, "%Y%m%dT%H%M%SZ")
            formatted_date = seendate_dt.strftime("%Y-%m-%d")
        except Exception as ex:
            print(f"❌ Failed to parse seendate: {seendate_raw} – {ex}")
            continue

        # Add full article metadata to each event
        events.append({
            'date': formatted_date,
            'datetime': seendate_dt.isoformat(),
            'title': item.get('title', ''),
            'url': item.get('url', ''),
            'image': item.get('socialimage', ''),
            'domain': item.get('domain', ''),
            'language': item.get('language', ''),
            'source_country': item.get('sourcecountry', '')
        })

    print(f"📄 Fetched {len(events)} GDELT events between {start_date} and {end_date}")
    return events

@app.route('/api/analyze11', methods=['POST'])
def analyze22():
    print("📩 Received analyze API request")
    data = request.json
    symbol = data.get("symbol")
    prices = data.get("prices")
    dates = data.get("dates")
    freq = data.get("freq")

    if not (symbol and prices and dates):
        return jsonify({"error": "Missing symbol, prices, or dates"}), 400

    # Create DataFrame
    df = pd.DataFrame({"date": pd.to_datetime(dates), "price": prices})
    df.set_index("date", inplace=True)

    if df.index.duplicated().any():
        print("⛔ Duplicate timestamps found, dropping them...")
        df = df[~df.index.duplicated(keep='first')]

    # Try to infer and apply frequency
    # inferred_freq = pd.infer_freq(df.index)
    # if inferred_freq:
    #     try:
    #         df = df.asfreq(inferred_freq)
    #         print(f"✅ Applied inferred frequency: {inferred_freq}")
    #     except Exception as e:
    #         print(f"⚠️ Failed to apply frequency '{inferred_freq}': {e}")
    # else:
    #     print("⚠️ Could not infer frequency")

    # Force to minutely to avoid ARIMA warning
    #df = df.asfreq('min')
    df = df.asfreq(freq)

    # ARIMA forecast
    try:
        print("📈 Starting ARIMA")
        model = ARIMA(df['price'], order=(5, 1, 0))
        fit = model.fit()
        forecast = fit.forecast(steps=10)
    except Exception as e:
        return jsonify({"error": f"ARIMA model failed: {e}"}), 500

    fdates = pd.date_range(start=df.index[-1] + timedelta(minutes=1), periods=10, freq='min')
    fc = [{'date': d.strftime('%Y-%m-%d %H:%M'), 'price': round(p, 2)} for d, p in zip(fdates, forecast)]

    # Buy/Sell detection
    min_price = df['price'].min()
    max_price = df['price'].max()
    buy_date = df['price'].idxmin().strftime('%Y-%m-%d')
    sell_date = df['price'].idxmax().strftime('%Y-%m-%d')

    print("📡 Fetching GDELT Events...")
    events = get_gdelt_events(dates[0], fdates[-1].strftime('%Y-%m-%d'))

    # Match events close to buy/sell dates
    matched_events = []
    for e in events:
        try:
            event_date = pd.to_datetime(e.get('date'))
            if abs((event_date - pd.to_datetime(buy_date)).days) <= 1 or \
            abs((event_date - pd.to_datetime(sell_date)).days) <= 1:
                matched_events.append(e)
        except:
            continue

    print("✅ Match complete. Returning response.")

    return jsonify({
        'forecast': fc,
        'history': df.reset_index().to_dict(orient='records'),
        'buy_sell': {
            'buy': {'date': buy_date, 'price': round(min_price, 2)},
            'sell': {'date': sell_date, 'price': round(max_price, 2)}
        },
        'events': matched_events
    })


@app.route('/api/analyze', methods=['POST'])
def analyze():
    print("📩 Received analyze API request")
    data = request.json
    symbol = data.get("symbol")
    prices = data.get("prices")
    dates = data.get("dates")
    freq = data.get("freq", 'min')  # Default to 'min' if not provided

    if not (symbol and prices and dates):
        return jsonify({"error": "Missing symbol, prices, or dates"}), 400

    # Create DataFrame
    df = pd.DataFrame({"date": pd.to_datetime(dates), "price": prices})
    df.set_index("date", inplace=True)

    # Drop duplicates
    if df.index.duplicated().any():
        print("⛔ Duplicate timestamps found, dropping them...")
        df = df[~df.index.duplicated(keep='first')]

    # Replace NaNs or infs in price
    #df['price'] = pd.to_numeric(df['price'], errors='coerce')  # Ensure numeric
    #df['price'] = df['price'].replace([np.nan, np.inf, -np.inf], method='ffill')
    #df['price'] = df['price'].fillna(method='bfill')  # Fallback if any NaNs remain
    
    df['price'] = pd.to_numeric(df['price'], errors='coerce')
    df = df[np.isfinite(df['price'])]  # drop NaN, inf

    try:
        df = df.asfreq(freq)
    except Exception as e:
        print(f"⚠️ Failed to apply frequency '{freq}': {e}")
        return jsonify({"error": f"Invalid frequency '{freq}'"}), 400

    # ARIMA forecast
    try:
        print("📈 Starting ARIMA")
        model = ARIMA(df['price'], order=(5, 1, 0))
        fit = model.fit()
        forecast = fit.forecast(steps=10)
    except Exception as e:
        return jsonify({"error": f"ARIMA model failed: {e}"}), 500

    # Forecast dates
    fdates = pd.date_range(start=df.index[-1] + pd.tseries.frequencies.to_offset(freq), periods=10, freq=freq)
    
    # Ensure forecast is clean JSON
    fc = []
    for d, p in zip(fdates, forecast):
        try:
            p = float(p)
            if not math.isnan(p) and math.isfinite(p):
                fc.append({
                    'date': d.strftime('%Y-%m-%d %H:%M'),
                    'price': round(p, 2)
                })
        except:
            continue



    # Buy/Sell detection
    min_price = df['price'].min()
    max_price = df['price'].max()
    buy_date = df['price'].idxmin().strftime('%Y-%m-%d')
    sell_date = df['price'].idxmax().strftime('%Y-%m-%d')

    print("📡 Fetching GDELT Events...")
    try:
        events = get_gdelt_events(dates[0], fdates[-1].strftime('%Y-%m-%d'))
    except Exception as e:
        print(f"⚠️ Failed to fetch GDELT events: {e}")
        events = []

    # Match events close to buy/sell dates
    matched_events = []
    for e in events:
        try:
            print(f"{e}")
            raw_datetime = e.get('datetime')
            #print(f"match - Raw: {raw_datetime}, buydate: {buy_date} and selldate:{sell_date}")
            if not raw_datetime:
                print(f"❌ Missing 'datetime' in event: {json.dumps(e, indent=2)}")
                continue

            # ✅ Parse GDELT datetime format
            try:
                event_date = datetime.fromisoformat(raw_datetime)
            except Exception as ex:
                print(f"❌ Error parsing datetime '{raw_datetime}': {ex}")
                continue

            #print(f"Checking for match - eventdate: {event_date}, buydate: {pd.to_datetime(buy_date)} and selldate:{pd.to_datetime(sell_date)}")
            if abs((event_date - pd.to_datetime(buy_date)).days) <= 1 or \
            abs((event_date - pd.to_datetime(sell_date)).days) <= 1:
                matched_events.append(e)
        except:
            continue

    print("✅ Match complete. Returning response.")


    fc_clean = remove_nan_objects(fc)
    history_clean = remove_nan_objects(df.reset_index().to_dict(orient='records'))
    events_clean = remove_nan_objects(matched_events)  # if needed

    result = {
        'forecast': fc_clean,
        'history': history_clean,
        'buy_sell': {
            'buy': {'date': buy_date, 'price': round(min_price, 2)},
            'sell': {'date': sell_date, 'price': round(max_price, 2)}
        },
        'events': events_clean
    }

    # Print to console for debugging
    #import json
    print("=== Returning JSON result ===")
    #print(json.dumps(result, indent=2, default=str))  # default=str handles datetime objects

    # Write to file in the same directory
    output_path = os.path.join(os.path.dirname(__file__), 'last_analysis_output.json')
    with open(output_path, 'w') as f:
        json.dump(result, f, indent=2, default=str)

    # Return as JSON
    return jsonify(result)

@app.route("/api/analyzeforday", methods=["POST"])
def analyze_for_day():
    data = request.get_json()
    candledata = data.get("candledata", [])
    print(len(candledata))
    freq = data.get("freq", 'min')
    
    result = analyze_candles_by_day_with_events(candledata,freq)
    #print(len(result))
    return result


def analyze_candles_by_day_with_events1(candledata,freq, forecast_steps=5):
    
    print("Start")

    df = pd.DataFrame(candledata)
    df["datetime"] = pd.to_datetime(df["date"])
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df.sort_values("datetime", inplace=True)
    print(len(df))

    print("Columns in received DataFrame:", df.columns.tolist())

    results = []

    try:
        df.set_index("datetime", inplace=True)
        df = df.asfreq(freq)  # Try applying frequency now on index
        df.reset_index(inplace=True)
    except Exception as e:
        print(f"⚠️ Failed to apply frequency '{freq}': {e}")
        #return jsonify({"error": f"Invalid frequency '{freq}'"}), 400
    
    print("Next ")
    print(df.head(20)) 
    for date, group in df.groupby("date"):
        print("Inside loop")
        group.set_index("datetime", inplace=True)
        group.sort_index(inplace=True)

        close_series = group["close"]

        if len(close_series) < 10:
            continue

        
        print("Trying ARIMA")
        try:
            model = ARIMA(close_series, order=(2, 1, 2),freq='infer')
            fitted = model.fit()
            print(f"Arima model execution for {date} complete")
        except Exception as e:
            print(f"❌ ARIMA failed for {date}: {e}")
            continue

        interval = group.index[1] - group.index[0]
        last_time = group.index[-1]
        forecast = fitted.forecast(steps=forecast_steps)

        forecast_points = [
            {
                "datetime": (last_time + (i + 1) * interval).isoformat(),
                "predicted_price": float(value)
            }
            for i, value in enumerate(forecast)
        ]

        max_profit = 0
        buy_time = sell_time = None
        for i in range(len(close_series)):
            for j in range(i + 1, len(close_series)):
                buy_price = close_series.iloc[i]
                sell_price = close_series.iloc[j]
                profit = sell_price - buy_price
                if profit > max_profit:
                    max_profit = profit
                    buy_time = close_series.index[i]
                    sell_time = close_series.index[j]

        # 📡 Fetch GDELT events for this day
        #gdelt_events = fetch_gdelt_events_for_date(str(date))

        print("📡 Fetching GDELT Events...")
        try:
            gdelt_events = fetch_gdelt_events_for_date(str(date))
        except Exception as e:
            print(f"⚠️ Failed to fetch GDELT events: {e}")
            gdelt_events = []

        # 🎯 Attach nearest events to buy/sell
        buy_event = find_nearest_event(gdelt_events, buy_time) if buy_time else None
        sell_event = find_nearest_event(gdelt_events, sell_time) if sell_time else None

        results.append({
            "date": date.isoformat(),
            "best_trade": {
                "buy_time": buy_time.isoformat() if buy_time else None,
                "buy_price": float(close_series.loc[buy_time]) if buy_time else None,
                "sell_time": sell_time.isoformat() if sell_time else None,
                "sell_price": float(close_series.loc[sell_time]) if sell_time else None,
                "profit": float(max_profit),
                "buy_event": buy_event,
                "sell_event": sell_event
            },
            "forecast": forecast_points
        })

        print(f"Returning {len(results)} records... ")

    return results


def analyze_candles_by_day_with_events_working_6thAug_2025(candledata, freq='5min', forecast_steps=5):
    print("📊 Start analyzing candle data by day...")

    
    df = pd.DataFrame(candledata)

    if 'date' not in df.columns or 'close' not in df.columns:
        print("❌ Required columns missing in data!")
        return jsonify({"error": "Missing required fields in input data"}), 400

    df["datetime"] = pd.to_datetime(df["date"])
    df["date"] = df["datetime"].dt.date
    df.sort_values("datetime", inplace=True)

    if df.index.duplicated().any():
        print("⛔ Duplicate timestamps found, dropping them...")
        df = df[~df.index.duplicated(keep='first')]

    # Replace NaNs or infs in price
    #df['price'] = pd.to_numeric(df['price'], errors='coerce')  # Ensure numeric
    #df['price'] = df['price'].replace([np.nan, np.inf, -np.inf], method='ffill')
    #df['price'] = df['price'].fillna(method='bfill')  # Fallback if any NaNs remain
    

    print(f"✅ Received {len(df)} records")
    print("Columns:", df.columns.tolist())

    results = []

# Set datetime as index to apply frequency
    try:
        df = df.drop_duplicates(subset='datetime')
        df.set_index("datetime", inplace=True)

        #df = df.asfreq(freq)
        print(freq)
        if freq != 'day' and freq != 'D' and 1==2:
                try:
                    df = df.asfreq(freq)
                    df["close"] = df["close"].interpolate(method='time').bfill().ffill()
                    print(f"🕒 Applied frequency: {freq}")
                except Exception as e:
                    print(f"⚠️ Failed to apply frequency '{freq}': {e}")
                    return jsonify({"error": f"Invalid frequency '{freq}'"}), 400
        else:
            print("🗓️ Skipping asfreq for 'day' frequency, using original datetime series")
        
        df.reset_index(inplace=True)
        print(f"🕒 Index reset")
    except Exception as e:
        print(f"⚠️ Failed to apply frequency '{freq}': {e}")
        return jsonify({"error": f"Invalid frequency '{freq}'"}), 400

    # Group by each day and process
    grouped = df.groupby("date")
    for date, group in grouped:
        print(f"📅 Analyzing date: {date}")
        
        group = group.set_index("datetime").sort_index()

        # Ensure even frequency and fill missing values
        group = group.asfreq(freq)
        group["close"] = group["close"].interpolate(method='time')  # or 'linear'
        #group["close"] = group["close"].fillna(method='bfill').fillna(method='ffill')
        group["close"] = group["close"].bfill().ffill()

        close_series = group["close"]

        if len(close_series) < 10:
            print(f"⏭️ Skipping {date}, not enough data points ({len(close_series)})")
            continue
        print(f"ARIMA model call... {date}")
        try:
            if freq != 'day' and freq != 'D' and 1==2:
                model = ARIMA(close_series, order=(2, 1, 2), freq=freq)
            else:
                model = ARIMA(close_series, order=(2, 1, 2))  # Let it infer freq from index

            fitted = model.fit()
            print(f"✅ ARIMA model fitted for {date}")
        except Exception as e:
            print(f"❌ ARIMA failed for {date}: {e}")
            continue

        interval = group.index[1] - group.index[0]
        last_time = group.index[-1]
        forecast = fitted.forecast(steps=forecast_steps)

        forecast_points = [
            {
                "datetime": (last_time + (i + 1) * interval).isoformat(),
                "predicted_price": float(value)
            }
            for i, value in enumerate(forecast)
        ]

        # Find best buy/sell for the day
        max_profit = 0
        buy_time = sell_time = None
        for i in range(len(close_series)):
            for j in range(i + 1, len(close_series)):
                buy_price = close_series.iloc[i]
                sell_price = close_series.iloc[j]
                profit = sell_price - buy_price
                if profit > max_profit:
                    max_profit = profit
                    buy_time = close_series.index[i]
                    sell_time = close_series.index[j]

        # Fetch events from GDELT
        print("📡 Fetching GDELT Events...")
        try:
            gdelt_events = fetch_gdelt_events_for_date(str(date))
        except Exception as e:
            print(f"⚠️ Failed to fetch GDELT events: {e}")
            gdelt_events = []

        buy_event = find_nearest_event(gdelt_events, buy_time) if buy_time else None
        sell_event = find_nearest_event(gdelt_events, sell_time) if sell_time else None

        results.append({
            "date": str(date),
            "best_trade": {
                "buy_time": buy_time.isoformat() if buy_time else None,
                "buy_price": float(close_series.loc[buy_time]) if buy_time else None,
                "sell_time": sell_time.isoformat() if sell_time else None,
                "sell_price": float(close_series.loc[sell_time]) if sell_time else None,
                "profit": float(max_profit),
                "buy_event": buy_event,
                "sell_event": sell_event
            },
            "forecast": forecast_points
        })

    print(f"✅ Completed processing. Returning {len(results)} daily results.")
    print("=== Returning JSON result ===")
    #print(json.dumps(result, indent=2, default=str))  # default=str handles datetime objects

    # Write to file in the same directory
    output_path = os.path.join(os.path.dirname(__file__), 'last_analysis_output_day.json')
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)

    # Return as JSON
    print(len(results))
    return jsonify(results)

###
def analyze_candles_by_day_with_events(candledata, freq='5min', forecast_steps=10):
    print("📊 Start analyzing candle data...")

    df = pd.DataFrame(candledata)

    if 'date' not in df.columns or 'close' not in df.columns:
        print("❌ Required columns missing in data!")
        return jsonify({"error": "Missing required fields in input data"}), 400

    df["datetime"] = pd.to_datetime(df["date"])
    df["date"] = df["datetime"].dt.date
    df.sort_values("datetime", inplace=True)

    if df.index.duplicated().any():
        print("⛔ Duplicate timestamps found, dropping them...")
        df = df[~df.index.duplicated(keep='first')]

    df = df.drop_duplicates(subset='datetime')
    df.set_index("datetime", inplace=True)

    print(f"✅ Received {len(df)} records")
    
    # Interpolate missing data
    df = df.asfreq(freq)
    df["close"] = df["close"].interpolate(method='time').bfill().ffill()

    # ✅ Global ARIMA Forecast (10 steps ahead from last point)
    try:
        model = ARIMA(df["close"], order=(2, 1, 2))
        fitted = model.fit()
        interval = df.index[1] - df.index[0]
        last_date = df.index[-1].date()
        future_dates = [last_date + timedelta(days=i + 1) for i in range(forecast_steps)]

        forecast = fitted.forecast(steps=forecast_steps)
        forecast_points = [
            {
                "datetime": future_dates[i].isoformat(),  # Only date part (daily)
                "predicted_price": float(value)
            }
            for i, value in enumerate(forecast)
        ]
        print("✅ Global forecast complete")
    except Exception as e:
        print(f"❌ ARIMA model failed: {e}")
        forecast_points = []

    # ✅ Per-day analysis for best trade and events
    df.reset_index(inplace=True)
    grouped = df.groupby("date")
    daily_results = []

    for date, group in grouped:
        print(f"📅 Analyzing date: {date}")
        group = group.set_index("datetime").sort_index()

        if len(group) < 10:
            print(f"⏭️ Skipping {date}, not enough data points")
            continue

        close_series = group["close"]

        # Best trade logic
        max_profit = 0
        buy_time = sell_time = None
        for i in range(len(close_series)):
            for j in range(i + 1, len(close_series)):
                profit = close_series.iloc[j] - close_series.iloc[i]
                if profit > max_profit:
                    max_profit = profit
                    buy_time = close_series.index[i]
                    sell_time = close_series.index[j]

        print("📡 Fetching GDELT Events...")
        try:
            gdelt_events = fetch_gdelt_events_for_date(str(date))
        except Exception as e:
            print(f"⚠️ Failed to fetch GDELT events: {e}")
            gdelt_events = []

        buy_event = find_nearest_event(gdelt_events, buy_time) if buy_time else None
        sell_event = find_nearest_event(gdelt_events, sell_time) if sell_time else None

        daily_results.append({
            "date": str(date),
            "best_trade": {
                "buy_time": buy_time.isoformat() if buy_time else None,
                "buy_price": float(close_series.loc[buy_time]) if buy_time else None,
                "sell_time": sell_time.isoformat() if sell_time else None,
                "sell_price": float(close_series.loc[sell_time]) if sell_time else None,
                "profit": float(max_profit),
                "buy_event": buy_event,
                "sell_event": sell_event
            }
        })

    result = {
        "forecast_next_10_periods": forecast_points,
        "daily_best_trades": daily_results
    }

    # Save output
    output_path = os.path.join(os.path.dirname(__file__), 'last_analysis_output_forecast.json')
    with open(output_path, 'w') as f:
        json.dump(result, f, indent=2, default=str)

    print(f"✅ Completed. {len(daily_results)} days analyzed.")
    return jsonify(result)

###New output
def analyze_candles_by_day_with_events_new(candledata, freq='5min', forecast_days=10):
    print("📊 Start analyzing candle data...")

    df = pd.DataFrame(candledata)

    if 'date' not in df.columns or 'close' not in df.columns:
        print("❌ Required columns missing in data!")
        return jsonify({"error": "Missing required fields in input data"}), 400

    df["datetime"] = pd.to_datetime(df["date"])
    df["date"] = df["datetime"].dt.date
    df.sort_values("datetime", inplace=True)

    if df.index.duplicated().any():
        print("⛔ Duplicate timestamps found, dropping them...")
        df = df[~df.index.duplicated(keep='first')]

    df = df.drop_duplicates(subset='datetime')
    df.set_index("datetime", inplace=True)

    print(f"✅ Received {len(df)} records")
    
    # Interpolate missing data
    df = df.asfreq(freq)
    df["close"] = df["close"].interpolate(method='time').bfill().ffill()

    # === 📈 Forecasting future 10 trading days every 5 minutes ===
    forecast_results_by_day = []

    try:
        interval = pd.Timedelta(freq)
        steps_per_day = int(timedelta(hours=6.5) / interval)  # Typically 78 steps per trading day
        total_steps = steps_per_day * forecast_days

        model = ARIMA(df["close"], order=(2, 1, 2))
        fitted = model.fit()

        start_datetime = df.index[-1] + interval
        forecast_datetimes = [start_datetime + i * interval for i in range(total_steps)]

        forecast = fitted.forecast(steps=total_steps)

        forecast_df = pd.DataFrame({
            "datetime": forecast_datetimes,
            "predicted_price": forecast
        })
        forecast_df["date"] = forecast_df["datetime"].dt.date

        for forecast_date, group in forecast_df.groupby("date"):
            prices = group["predicted_price"].values
            times = group["datetime"].values

            # Best trade logic (max profit window)
            max_profit = 0
            buy_index = sell_index = None
            for i in range(len(prices)):
                for j in range(i + 1, len(prices)):
                    profit = prices[j] - prices[i]
                    if profit > max_profit:
                        max_profit = profit
                        buy_index = i
                        sell_index = j

            forecast_results_by_day.append({
                "date": str(forecast_date),
                "forecast": [
                    {
                        "datetime": group["datetime"].iloc[k].isoformat(),
                        "predicted_price": float(prices[k])
                    }
                    for k in range(len(prices))
                ],
                "best_forecast_trade": {
                    "buy_time": times[buy_index].isoformat() if buy_index is not None else None,
                    "buy_price": float(prices[buy_index]) if buy_index is not None else None,
                    "sell_time": times[sell_index].isoformat() if sell_index is not None else None,
                    "sell_price": float(prices[sell_index]) if sell_index is not None else None,
                    "profit": float(max_profit)
                }
            })

        print("✅ Forecast with intraday best trade per day complete")

    except Exception as e:
        print(f"❌ ARIMA model failed: {e}")
        forecast_results_by_day = []

    # === 🔍 Historical per-day analysis for best trade + events ===
    df.reset_index(inplace=True)
    grouped = df.groupby("date")
    daily_results = []

    for date, group in grouped:
        print(f"📅 Analyzing date: {date}")
        group = group.set_index("datetime").sort_index()

        if len(group) < 10:
            print(f"⏭️ Skipping {date}, not enough data points")
            continue

        close_series = group["close"]

        # Best trade logic
        max_profit = 0
        buy_time = sell_time = None
        for i in range(len(close_series)):
            for j in range(i + 1, len(close_series)):
                profit = close_series.iloc[j] - close_series.iloc[i]
                if profit > max_profit:
                    max_profit = profit
                    buy_time = close_series.index[i]
                    sell_time = close_series.index[j]

        print("📡 Fetching GDELT Events...")
        try:
            gdelt_events = fetch_gdelt_events_for_date(str(date))
        except Exception as e:
            print(f"⚠️ Failed to fetch GDELT events: {e}")
            gdelt_events = []

        buy_event = find_nearest_event(gdelt_events, buy_time) if buy_time else None
        sell_event = find_nearest_event(gdelt_events, sell_time) if sell_time else None

        daily_results.append({
            "date": str(date),
            "best_trade": {
                "buy_time": buy_time.isoformat() if buy_time else None,
                "buy_price": float(close_series.loc[buy_time]) if buy_time else None,
                "sell_time": sell_time.isoformat() if sell_time else None,
                "sell_price": float(close_series.loc[sell_time]) if sell_time else None,
                "profit": float(max_profit),
                "buy_event": buy_event,
                "sell_event": sell_event
            }
        })

    # === ✅ Final Result ===
    result = {
        "forecast_next_10_days": forecast_results_by_day,
        "daily_best_trades": daily_results
    }

    # Save to JSON for inspection
    output_path = os.path.join(os.path.dirname(__file__), 'last_analysis_output_forecast.json')
    with open(output_path, 'w') as f:
        json.dump(result, f, indent=2, default=str)

    print(f"✅ Completed. {len(daily_results)} days analyzed.")
    return jsonify(result)


def find_nearest_event(events, target_time):
    """
    Find the nearest event on or before the target_time.
    """
    nearest = None
    min_diff = timedelta.max

    for event in events:
        event_time = pd.to_datetime(event["datetime"])
        if event_time <= target_time:
            diff = target_time - event_time
            if diff < min_diff:
                min_diff = diff
                nearest = event

    return nearest



# ---------- REST ----------
@app.route("/worker/start_1", methods=["POST"])
def startNew():
    # Initialize SDK
    #breeze = BreezeConnect(api_key=BREEZE_API_KEY)

    # Generate Session
    #breeze.generate_session(api_secret=BREEZE_API_SECRETE, session_token=BREEZE_API_SESSION)

    # Connect to Websocket
    api.ws_connect()

    # Callback to handle incoming data
    def on_ticks(ticks):
        print("Ticks: {}".format(ticks))

    # Assign callback
    api.on_ticks = on_ticks

    # Subscribe to OHLC (1 second interval)
    api.subscribe_feeds(exchange_code= "NSE", 
                stock_code="NIFTY", 
                expiry_date="31-Jan-2026", 
                #right="call", 
                product_type="cash", 
                get_market_depth=False ,
                get_exchange_quotes=True,
                interval="1second")
    
    print("📡 Subscribed to NIFTY cash 1second")
    return jsonify({"success" : "OK"})
    #return jsonify({"success": ok, "message": msg})

# ---------- REST ----------
@app.route("/worker/start", methods=["POST"])
def start():
    d = request.json
    ok, msg = start_worker(
        d["symbol"],
        d.get("interval", "1second"),
        d.get("qty", 1),
        d.get("trading_mode", "LIVE"),
        d.get("order_mode", "SIMULATION"),
        d.get("strategy", "ema_strategy")
    )
    return jsonify({"success": ok, "message": msg})

@app.route("/worker/stop", methods=["POST"])
def stop():
    ok, msg = stop_worker(request.json["symbol"])
    return jsonify({"success": ok, "message": msg})

@app.route("/worker/status")
def stat():
    return jsonify(status())

# ---------- Trade journal export ----------
@app.route("/export/trades")
def export_trades():
    from db import get_db
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM orders ORDER BY ts")
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]

    file = "trade_journal.csv"
    with open(file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(cols)
        writer.writerows(rows)

    return send_file(file, as_attachment=True)

# ---------- WebSocket (Angular) ----------
@sock.route("/ws")
def ws(ws):
    ws_clients.add(ws)
    while True:
        msg = ws.receive()
        if msg is None:
            break
    ws_clients.remove(ws)

# ---------- Graceful shutdown ----------
def shutdown_handler(signum, frame):
    print("\n[APP] Shutting down → killing all workers")
    from workers.breeze_ws_worker import workers
    for w in workers.values():
        w.stop()
        print(f"Worker stopped - {w} " )
    sys.exit(0)

signal.signal(signal.SIGINT, shutdown_handler)
signal.signal(signal.SIGTERM, shutdown_handler)


@app.route("/health")
def health():
    return jsonify({"status": "ok"})

if __name__ == '__main__':
    app.run(debug=True, port=5000)
