import time
import hmac
import hashlib
import requests

ROOSTOO_BASE_URL = "https://mock-api.roostoo.com"
ROOSTOO_API_KEY = "9q1LSYAYU5By23jB1mNOx8ZesXZN8I810iNZKLGKebAHVFGlxLLtvFOeFrPRwVAF"
ROOSTOO_SECRET_KEY = "4qSaoUaxTQu3bUs4XooWFLkUMdxYzzt6eVi4V5lOJx143ASxkrrS4yH1kGViEmA5"

def place_test_order():
    payload = {
        'pair': 'BTC/USD',
        'side': 'BUY',
        'type': 'MARKET',
        'quantity': '0.001',
        'timestamp': str(int(time.time() * 1000))
    }
    
    sorted_keys = sorted(payload.keys())
    total_params = "&".join(f"{k}={payload[k]}" for k in sorted_keys)
    signature = hmac.new(
        ROOSTOO_SECRET_KEY.encode('utf-8'),
        total_params.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    headers = {
        'RST-API-KEY': ROOSTOO_API_KEY,
        'MSG-SIGNATURE': signature,
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    
    url = f"{ROOSTOO_BASE_URL}/v3/place_order"
    response = requests.post(url, headers=headers, data=total_params)
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")

if __name__ == "__main__":
    place_test_order()