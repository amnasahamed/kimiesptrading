#!/usr/bin/env python3
"""
Automated Kite Access Token Fetcher
Uses Selenium to login and extract access token daily.

Run via cron before market open:
0 8 * * 1-5 /path/to/python /path/to/get_token.py
"""

import os
import sys
import json
import time
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Selenium imports
try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
except ImportError:
    print("Installing selenium...")
    os.system("pip install selenium")
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service


# Configuration
KITE_API_KEY = os.getenv("KITE_API_KEY", "your_api_key")
KITE_USER_ID = os.getenv("KITE_USER_ID", "your_user_id")
KITE_PASSWORD = os.getenv("KITE_PASSWORD", "your_password")
KITE_TOTP_SECRET = os.getenv("KITE_TOTP_SECRET", "your_totp_secret")

CONFIG_FILE = Path(__file__).parent.parent / "config.json"


def generate_totp(secret: str) -> str:
    """Generate TOTP for 2FA."""
    try:
        import pyotp
        totp = pyotp.TOTP(secret)
        return totp.now()
    except ImportError:
        print("Installing pyotp...")
        os.system("pip install pyotp")
        import pyotp
        totp = pyotp.TOTP(secret)
        return totp.now()


def get_access_token() -> str:
    """
    Login to Kite and extract access token.
    """
    # Setup Chrome options
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    
    # Initialize driver
    driver = webdriver.Chrome(options=chrome_options)
    
    try:
        print("🚀 Starting Kite login...")
        
        # Step 1: Open Kite login page
        login_url = f"https://kite.zerodha.com/connect/login?v=3&api_key={KITE_API_KEY}"
        driver.get(login_url)
        
        wait = WebDriverWait(driver, 30)
        
        # Step 2: Enter User ID
        print("⌛ Waiting for login page...")
        user_id_field = wait.until(EC.presence_of_element_located((By.ID, "userid")))
        user_id_field.send_keys(KITE_USER_ID)
        
        # Step 3: Enter Password
        password_field = driver.find_element(By.ID, "password")
        password_field.send_keys(KITE_PASSWORD)
        
        # Step 4: Click Login
        login_button = driver.find_element(By.XPATH, "//button[@type='submit']")
        login_button.click()
        
        # Step 5: Handle 2FA (TOTP)
        print("⌛ Waiting for 2FA...")
        time.sleep(2)
        
        try:
            pin_field = wait.until(EC.presence_of_element_located((By.ID, "totp")))
            totp_code = generate_totp(KITE_TOTP_SECRET)
            print(f"🔑 Generated TOTP: {totp_code}")
            pin_field.send_keys(totp_code)
            
            continue_button = driver.find_element(By.XPATH, "//button[@type='submit']")
            continue_button.click()
        except Exception as e:
            print(f"⚠️ 2FA might be disabled or using PIN: {e}")
            # Try PIN if TOTP fails
            try:
                pin_field = wait.until(EC.presence_of_element_located((By.ID, "pin")))
                pin_field.send_keys(KITE_TOTP_SECRET)  # Use secret as PIN if it's actually a PIN
                continue_button = driver.find_element(By.XPATH, "//button[@type='submit']")
                continue_button.click()
            except:
                pass
        
        # Step 6: Wait for redirect and extract token
        print("⌛ Waiting for redirect...")
        time.sleep(3)
        
        # Check if we're on the success page
        current_url = driver.current_url
        print(f"📍 Current URL: {current_url}")
        
        # Extract access token from URL
        if "success" in current_url or "request_token" in current_url:
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(current_url)
            params = parse_qs(parsed.query)
            
            request_token = params.get("request_token", [None])[0]
            
            if request_token:
                print(f"✅ Got request token: {request_token[:10]}...")
                
                # Exchange request token for access token via API
                access_token = exchange_request_token(request_token)
                return access_token
        
        # Alternative: Check if session is active
        print("⚠️  Could not extract token from URL. Checking cookies...")
        cookies = driver.get_cookies()
        
        for cookie in cookies:
            if "access_token" in cookie.get("name", "").lower():
                return cookie["value"]
        
        raise Exception("Could not extract access token")
        
    finally:
        driver.quit()


def exchange_request_token(request_token: str) -> str:
    """
    Exchange request token for access token using Kite API.
    """
    try:
        from kiteconnect import KiteConnect
    except ImportError:
        os.system("pip install kiteconnect")
        from kiteconnect import KiteConnect
    
    kite = KiteConnect(api_key=KITE_API_KEY)
    
    try:
        data = kite.generate_session(request_token, api_secret=os.getenv("KITE_API_SECRET", ""))
        access_token = data["access_token"]
        print(f"✅ Generated access token: {access_token[:10]}...")
        return access_token
    except Exception as e:
        print(f"❌ Error exchanging token: {e}")
        raise


def update_config_token(access_token: str):
    """Update config.json with new access token."""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r") as f:
            config = json.load(f)
    else:
        config = {}
    
    if "kite" not in config:
        config["kite"] = {}
    
    config["kite"]["access_token"] = access_token
    
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
    
    print(f"✅ Updated {CONFIG_FILE} with new access token")


def notify_telegram(message: str):
    """Send notification via Telegram."""
    if not CONFIG_FILE.exists():
        return
    
    with open(CONFIG_FILE, "r") as f:
        config = json.load(f)
    
    telegram = config.get("telegram", {})
    if not telegram.get("enabled"):
        return
    
    bot_token = telegram.get("bot_token")
    chat_id = telegram.get("chat_id")
    
    if not bot_token or not chat_id:
        return
    
    try:
        import httpx
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "Markdown"
        }
        httpx.post(url, json=payload, timeout=5.0)
    except Exception as e:
        print(f"Telegram error: {e}")


def main():
    print("=" * 50)
    print("🔐 Kite Access Token Fetcher")
    print("=" * 50)
    
    try:
        access_token = get_access_token()
        update_config_token(access_token)
        
        # Notify success
        notify_telegram(f"✅ *Kite Token Updated*\n\nToken refreshed successfully.\nReady for trading!")
        
        print("=" * 50)
        print("✅ Success! Token updated.")
        print("=" * 50)
        
    except Exception as e:
        error_msg = f"❌ *Token Fetch Failed*\n\nError: {str(e)}"
        notify_telegram(error_msg)
        
        print("=" * 50)
        print(f"❌ Failed: {e}")
        print("=" * 50)
        sys.exit(1)


if __name__ == "__main__":
    main()
