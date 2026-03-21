import requests
import time

ROOSTOO_BASE_URL = "https://mock-api.roostoo.com"

def test_exchange_info():
    payload = {'timestamp': str(int(time.time() * 1000))}
    response = requests.get(f"{ROOSTOO_BASE_URL}/v3/exchangeInfo", params=payload)
    data = response.json()
    
    print("All coins with precision:")
    for pair, info in data['TradePairs'].items():
        if info.get('CanTrade'):
            print(f"{pair}: AmountPrecision={info['AmountPrecision']}, MiniOrder={info['MiniOrder']}")

if __name__ == "__main__":
    test_exchange_info()