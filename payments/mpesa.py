
import os
import base64
import requests

from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

# Load environment variables from the project .env file
load_dotenv(override=True)

ENVIRONMENT = os.getenv("MPESA_ENV", "sandbox").strip().lower()

if ENVIRONMENT == "production":
    BASE_URL = "https://api.safaricom.co.ke"
elif ENVIRONMENT == "sandbox":
    BASE_URL = "https://sandbox.safaricom.co.ke"
else:
    raise ValueError("MPESA_ENV must be sandbox or production")


def handle_response(response):
    """Read Safaricom responses and expose useful error messages."""

    try:
        data = response.json()
    except ValueError:
        data = {"response": response.text}

    if not response.ok:
        raise ValueError(
            f"Safaricom HTTP {response.status_code}: {data}"
        )

    return data


def get_access_token():

    consumer_key = os.getenv("MPESA_CONSUMER_KEY")
    consumer_secret = os.getenv("MPESA_CONSUMER_SECRET")

    if not consumer_key or not consumer_secret:
        raise ValueError(
            "Missing MPESA_CONSUMER_KEY or MPESA_CONSUMER_SECRET in .env"
        )

    response = requests.get(
        BASE_URL + "/oauth/v1/generate?grant_type=client_credentials",
        auth=(consumer_key, consumer_secret),
        timeout=30
    )

    data = handle_response(response)

    token = data.get("access_token")

    if not token:
        raise ValueError(f"Access token missing: {data}")

    return token


def get_timestamp():

    return datetime.now(
        ZoneInfo("Africa/Nairobi")
    ).strftime("%Y%m%d%H%M%S")


def get_password(shortcode, passkey, timestamp):

    raw = shortcode + passkey + timestamp

    return base64.b64encode(
        raw.encode("utf-8")
    ).decode("utf-8")


def normalize_phone(phone):

    phone = phone.strip().replace(" ", "").replace("-", "")

    if phone.startswith("+"):
        phone = phone[1:]

    if phone.startswith("0"):
        phone = "254" + phone[1:]

    elif phone.startswith("7") or phone.startswith("1"):
        phone = "254" + phone

    if not phone.startswith("254") or len(phone) != 12:
        raise ValueError(
            "Enter a valid Kenyan phone number, e.g. 0712345678"
        )

    return phone


def get_mpesa_settings():

    shortcode = os.getenv("MPESA_SHORTCODE")
    passkey = os.getenv("MPESA_PASSKEY")
    callback_url = os.getenv("MPESA_CALLBACK_URL")

    if not shortcode:
        raise ValueError("MPESA_SHORTCODE is missing in .env")

    if not passkey:
        raise ValueError("MPESA_PASSKEY is missing in .env")

    if not callback_url:
        raise ValueError("MPESA_CALLBACK_URL is missing in .env")

    if not callback_url.startswith("https://"):
        raise ValueError("M-Pesa callback URL must use HTTPS")

    return shortcode, passkey, callback_url


def initiate_stk_push(phone, amount, account_reference):

    token = get_access_token()

    shortcode, passkey, callback_url = get_mpesa_settings()

    phone = normalize_phone(phone)

    amount = int(amount)

    if amount < 1:
        raise ValueError("Payment amount must be at least KSh 1")

    timestamp = get_timestamp()

    password = get_password(
        shortcode,
        passkey,
        timestamp
    )

    transaction_type = os.getenv(
        "MPESA_TRANSACTION_TYPE",
        "CustomerPayBillOnline"
    )

    party_b = os.getenv(
        "MPESA_PARTY_B",
        shortcode
    )

    payload = {
        "BusinessShortCode": shortcode,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": transaction_type,
        "Amount": amount,
        "PartyA": phone,
        "PartyB": party_b,
        "PhoneNumber": phone,
        "CallBackURL": callback_url,
        "AccountReference": str(account_reference)[:12],
        "TransactionDesc": "ToolBox"
    }

    response = requests.post(
        BASE_URL + "/mpesa/stkpush/v1/processrequest",
        json=payload,
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json"
        },
        timeout=30
    )

    data = handle_response(response)

    if data.get("ResponseCode") != "0":
        raise ValueError(
            data.get(
                "errorMessage",
                data.get(
                    "ResponseDescription",
                    str(data)
                )
            )
        )

    return data


def query_stk_status(checkout_request_id):

    token = get_access_token()

    shortcode, passkey, callback_url = get_mpesa_settings()

    timestamp = get_timestamp()

    password = get_password(
        shortcode,
        passkey,
        timestamp
    )

    payload = {
        "BusinessShortCode": shortcode,
        "Password": password,
        "Timestamp": timestamp,
        "CheckoutRequestID": checkout_request_id
    }

    response = requests.post(
        BASE_URL + "/mpesa/stkpushquery/v1/query",
        json=payload,
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json"
        },
        timeout=30
    )

    return handle_response(response)
