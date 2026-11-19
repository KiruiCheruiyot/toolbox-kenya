
import os
import requests

from dotenv import load_dotenv

load_dotenv()

PAYSTACK_BASE_URL = "https://api.paystack.co"


def get_secret_key():
    secret_key = os.getenv("PAYSTACK_SECRET_KEY")

    if not secret_key:
        raise ValueError("PAYSTACK_SECRET_KEY is missing.")

    return secret_key


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

    return "+" + phone


def initiate_mpesa_charge(phone, email, amount, reference):
    secret_key = get_secret_key()

    phone = normalize_phone(phone)
    email = email.strip().lower()
    amount = int(amount)

    if not email or "@" not in email:
        raise ValueError("Enter a valid email address.")

    if amount < 1:
        raise ValueError("Payment amount must be at least KSh 1.")

    payload = {
        "email": email,
        "amount": amount * 100,
        "currency": "KES",
        "reference": reference,
        "mobile_money": {
            "phone": phone,
            "provider": "mpesa"
        }
    }

    try:
        response = requests.post(
            PAYSTACK_BASE_URL + "/charge",
            json=payload,
            headers={
                "Authorization": "Bearer " + secret_key,
                "Content-Type": "application/json"
            },
            timeout=30
        )
    except requests.RequestException as error:
        raise ValueError(
            "Could not connect to Paystack. Please try again."
        ) from error

    try:
        result = response.json()
    except ValueError:
        raise ValueError(
            "Paystack returned an invalid response."
        )

    if response.status_code >= 400 or result.get("status") is False:
        raise ValueError(
            result.get("message", "Paystack payment request failed.")
        )

    data = result.get("data") or {}

    if not data:
        raise ValueError(
            "Paystack did not return payment details."
        )

    # Charge attempted / pay_offline means the request
    # has been initiated and is awaiting customer action.
    return data


def verify_transaction(reference):
    secret_key = get_secret_key()

    try:
        response = requests.get(
            PAYSTACK_BASE_URL + "/transaction/verify/" + reference,
            headers={
                "Authorization": "Bearer " + secret_key
            },
            timeout=30
        )
    except requests.RequestException as error:
        raise ValueError(
            "Could not connect to Paystack to verify payment."
        ) from error

    try:
        result = response.json()
    except ValueError:
        raise ValueError(
            "Paystack returned an invalid verification response."
        )

    if response.status_code >= 400 or result.get("status") is False:
        raise ValueError(
            result.get("message", "Payment verification failed.")
        )

    return result.get("data", {})
