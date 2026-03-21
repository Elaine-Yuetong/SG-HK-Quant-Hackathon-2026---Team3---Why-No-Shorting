# test_roostoo_connection.py
#!/usr/bin/env python3
"""
测试 Roostoo API 连接和余额查询
"""

import requests
import hmac
import hashlib
import time
import json

# 从 config 读取配置
ROOSTOO_BASE_URL = "https://mock-api.roostoo.com"  # 确认这个地址是否正确
ROOSTOO_API_KEY = "9q1LSYAYU5By23jB1mNOx8ZesXZN8I810iNZKLGKebAHVFGlxLLtvFOeFrPRwVAF"
ROOSTOO_SECRET_KEY = "4qSaoUaxTQu3bUs4XooWFLkUMdxYzzt6eVi4V5lOJx143ASxkrrS4yH1kGViEmA5"

def timestamp_ms():
    return str(int(time.time() * 1000))

def generate_signature(payload, secret_key):
    sorted_keys = sorted(payload.keys())
    total_params = "&".join(f"{k}={payload[k]}" for k in sorted_keys)
    signature = hmac.new(
        secret_key.encode('utf-8'),
        total_params.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return signature, total_params

def test_balance():
    """测试余额接口"""
    payload = {'timestamp': timestamp_ms()}
    signature, total_params = generate_signature(payload, ROOSTOO_SECRET_KEY)
    
    headers = {
        'RST-API-KEY': ROOSTOO_API_KEY,
        'MSG-SIGNATURE': signature
    }
    
    url = f"{ROOSTOO_BASE_URL}/v3/balance"
    
    print(f"🔍 Testing: {url}")
    print(f"📝 Headers: {headers}")
    print(f"📦 Payload: {payload}")
    
    try:
        response = requests.get(url, headers=headers, params=payload, timeout=10)
        print(f"📡 Status Code: {response.status_code}")
        print(f"📄 Response: {response.text}")
        
        if response.status_code == 200:
            data = response.json()
            if data.get('Success'):
                print(f"✅ Success! Balance: {data.get('Wallet', {}).get('USD', {})}")
                return data
            else:
                print(f"❌ API Error: {data.get('ErrMsg', 'Unknown')}")
        else:
            print(f"❌ HTTP Error: {response.status_code}")
            
    except Exception as e:
        print(f"❌ Exception: {e}")
    
    return None

def test_server_time():
    """测试公共接口"""
    url = f"{ROOSTOO_BASE_URL}/v3/serverTime"
    print(f"\n🔍 Testing server time: {url}")
    try:
        response = requests.get(url, timeout=5)
        print(f"📡 Response: {response.json()}")
    except Exception as e:
        print(f"❌ Failed: {e}")

if __name__ == "__main__":
    print("="*60)
    print("Roostoo API Connection Test")
    print("="*60)
    
    test_server_time()
    print("\n" + "="*60)
    test_balance()