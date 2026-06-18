import requests
import base64
from datetime import datetime
from flask import current_app

class MpesaAPI:
    def __init__(self):
        self.consumer_key = "frg0uKdeFuGVEIJyxAigzUkoijNAvgg1UJgTkdJuowp9T33f"  
        self.consumer_secret = "0DI7b8lItIA0AQcV6WxFq2kKOjYujb9viWn4MulQnYiAV7OuG4oECHjBozzmjAdx"
        self.shortcode = "3349188"  
        self.passkey = "YOUR_PASSKEY_HERE" 
        self.base_url = "https://sandbox.safaricom.co.ke" 

    def get_access_token(self):
        """Fetches access token from Safaricom API."""
        url = f"{self.base_url}/oauth/v1/generate?grant_type=client_credentials"
        try:
            response = requests.get(url, auth=(self.consumer_key, self.consumer_secret))
            response.raise_for_status()  
            return response.json().get("access_token")
        except requests.exceptions.RequestException as e:
            current_app.logger.error(f"Error getting M-Pesa access token: {e}")
            return None

    def stk_push(self, phone, amount, username):
        """Initiates an M-Pesa STK push request."""
        access_token = self.get_access_token()
        if not access_token:
            return {"error": "Failed to get access token"}

        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        password = base64.b64encode(f"{self.shortcode}{self.passkey}{timestamp}".encode()).decode()

        payload = {
            "BusinessShortCode": self.shortcode,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": amount,
            "PartyA": phone,
            "PartyB": self.shortcode,  
            "PhoneNumber": phone,
            "CallBackURL": "https://yourdomain.com/mpesa/callback",  
            "AccountReference": username,  
            "TransactionDesc": "Deposit to Wallet"
        }

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        try:
            response = requests.post(f"{self.base_url}/mpesa/stkpush/v1/processrequest", json=payload, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            current_app.logger.error(f"Error sending STK push: {e}")
            return {"error": "Failed to process STK push"}
