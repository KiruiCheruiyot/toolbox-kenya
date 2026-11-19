# ToolBox Kenya — starter project

A Flask starter for a Kenyan pay-per-use online tools business.

## Included
- Homepage and tool catalogue
- PDF merger
- PDF compressor
- Basic CV-to-PDF builder
- SQLite database models for users and orders
- Registration/sign-in starter
- Daraja STK Push request scaffold
- Callback endpoint that deliberately does NOT mark a payment as paid

## Important payment safety notice
This project runs in **development preview mode**. Tool results are generated without payment. Do not advertise it as a paid service or deploy it to collect real money yet.

Before launch, implement and test:
1. A server-side order creation flow before initiating STK Push.
2. Daraja STK Query verification of every successful callback.
3. Callback authenticity/consistency checks, amount, shortcode, phone and account reference matching.
4. Idempotency and duplicate callback handling.
5. Only generate/release paid outputs after verified payment.
6. HTTPS, production database, secure secrets, rate limits, logging, privacy notice and file retention/deletion.
7. User ownership checks on orders/downloads and admin authorization.

The current `/pay/<order_id>` route is only a scaffold; the current tool form creates a `completed_demo` order and does not charge the customer.

## Windows setup
Open Command Prompt in the extracted folder:

```cmd
py -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env` and set a long random `SECRET_KEY`. Leave Daraja values blank until configuring sandbox credentials.

Run:

```cmd
python app.py
```

Open http://127.0.0.1:5000

## Test
- PDF Merger: select at least two PDFs.
- PDF Compressor: select one PDF.
- CV Builder: enter your name and optional details.

## Next development steps
- Add a pending order/payment page and integrate STK Push into the normal tool workflow.
- Implement Daraja STK Query verification before unlocking output.
- Add customer order history and proper account ownership.
- Add admin dashboard and production deployment.
- Move to PostgreSQL and private object storage for production.
