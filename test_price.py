import requests
import time

ROOSTOO_BASE_URL = "https://mock-api.roostoo.com"

def test_ticker():
    payload = {'timestamp': str(int(time.time() * 1000))}
    response = requests.get(f"{ROOSTOO_BASE_URL}/v3/ticker", params=payload)
    data = response.json()
    
    print("Ticker response structure:")
    print(f"Success: {data.get('Success')}")
    
    if data.get('Data'):
        ticker_data = data['Data']
        print(f"\nAll ticker symbols ({len(ticker_data)} total):")
        for symbol in sorted(ticker_data.keys()):
            print(f"  {symbol}")
        
        # 检查你的币
        test_coins = ['XPLUS', 'PUMPFUN', 'STORY', 'VIRTUAL', 'TAO', 'PENGU', 'FLOKI', '1000CHEEMS']
        print("\n\nChecking your coins:")
        for coin in test_coins:
            if f"{coin}/USD" in ticker_data:
                print(f"✅ {coin}/USD exists")
            else:
                print(f"❌ {coin}/USD not found")

if __name__ == "__main__":
    test_ticker()