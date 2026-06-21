from flask import Flask, request, jsonify
import pandas as pd
from statsmodels.tsa.arima.model import ARIMA
import requests

app = Flask(__name__)

NEWS_API_KEY = 'YOUR_NEWSAPI_KEY'
FILING_API_KEY = 'YOUR_STOCKINSIGHTS_API_KEY'

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

@app.route('/api/analyze', methods=['POST'])
def analyze():
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

if __name__ == '__main__':
    app.run(debug=True)
