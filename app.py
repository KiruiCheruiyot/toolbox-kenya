
import os
import uuid
import secrets
import hashlib
import hmac

from datetime import datetime
from functools import wraps

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    send_file,
    session,
    jsonify
)

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

from tools.pdf_tools import merge_pdfs, compress_pdf
from tools.cv_builder import build_cv

from payments.paystack import (
    initiate_mpesa_charge,
    verify_transaction
)


load_dotenv()


app = Flask(__name__)

app.config["SECRET_KEY"] = os.getenv(
    "SECRET_KEY",
    "replace-this-secret"
)

app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URL",
    "sqlite:///toolbox.db"
)

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024
app.config["UPLOAD_FOLDER"] = "uploads"
app.config["OUTPUT_FOLDER"] = "processed"

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(app.config["OUTPUT_FOLDER"], exist_ok=True)


db = SQLAlchemy(app)


# =====================================================
# DATABASE MODELS
# =====================================================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    email = db.Column(
        db.String(160),
        unique=True,
        nullable=False
    )

    password_hash = db.Column(
        db.String(255),
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )


class Order(db.Model):
    id = db.Column(
        db.String(36),
        primary_key=True
    )

    tool = db.Column(
        db.String(60),
        nullable=False
    )

    amount = db.Column(
        db.Integer,
        nullable=False
    )

    phone = db.Column(db.String(20))

    status = db.Column(
        db.String(30),
        default="pending_payment",
        nullable=False
    )

    checkout_request_id = db.Column(
        db.String(120),
        unique=True
    )

    mpesa_receipt = db.Column(db.String(80))

    input_path = db.Column(db.String(500))

    output_path = db.Column(db.String(500))

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )


# =====================================================
# TOOL PRICES
# =====================================================

PRICES = {
    "pdf-merge": 20,
    "pdf-compress": 15,
    "cv-builder": 50
}


# =====================================================
# LOGIN REQUIRED
# =====================================================

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):

        if not session.get("user_id"):
            flash(
                "Please sign in first.",
                "warning"
            )

            return redirect(url_for("login"))

        return fn(*args, **kwargs)

    return wrapper


# =====================================================
# HOME PAGE
# =====================================================

@app.route("/")
def index():

    return render_template(
        "index.html",
        prices=PRICES
    )


# =====================================================
# REGISTER
# =====================================================

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        if not email or len(password) < 8:

            flash(
                "Enter a valid email and a password of at least 8 characters.",
                "danger"
            )

        elif User.query.filter_by(email=email).first():

            flash(
                "That email is already registered.",
                "danger"
            )

        else:

            user = User(
                email=email,
                password_hash=generate_password_hash(password)
            )

            db.session.add(user)
            db.session.commit()

            session["user_id"] = user.id

            flash(
                "Account created successfully.",
                "success"
            )

            return redirect(url_for("index"))

    return render_template(
        "auth.html",
        mode="Register"
    )


# =====================================================
# LOGIN
# =====================================================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        user = User.query.filter_by(
            email=request.form.get(
                "email",
                ""
            ).strip().lower()
        ).first()

        if user and check_password_hash(
            user.password_hash,
            request.form.get("password", "")
        ):

            session["user_id"] = user.id

            return redirect(url_for("index"))

        flash(
            "Incorrect email or password.",
            "danger"
        )

    return render_template(
        "auth.html",
        mode="Sign in"
    )


# =====================================================
# LOGOUT
# =====================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("index"))


# =====================================================
# TOOL PROCESSING
# =====================================================

@app.route("/tool/<tool_name>", methods=["GET", "POST"])
def tool(tool_name):

    if tool_name not in PRICES:
        return "Tool not found", 404

    if request.method == "GET":

        return render_template(
            "tool.html",
            tool_name=tool_name,
            price=PRICES[tool_name]
        )

    order_id = str(uuid.uuid4())

    out_path = os.path.join(
        app.config["OUTPUT_FOLDER"],
        order_id + ".pdf"
    )

    input_paths = []

    try:

        if tool_name in ("pdf-merge", "pdf-compress"):

            uploads = request.files.getlist("files")

            valid_uploads = [
                f for f in uploads
                if f and f.filename
            ]

            if not valid_uploads:
                raise ValueError(
                    "Choose at least one PDF file."
                )

            if tool_name == "pdf-merge" and len(valid_uploads) < 2:
                raise ValueError(
                    "Select at least two PDF files to merge."
                )

            for uploaded_file in valid_uploads:

                if not uploaded_file.filename.lower().endswith(".pdf"):
                    raise ValueError(
                        "Only PDF files are accepted."
                    )

                filename = secure_filename(
                    uploaded_file.filename
                )

                saved_path = os.path.join(
                    app.config["UPLOAD_FOLDER"],
                    order_id + "_" + secrets.token_hex(4) + "_" + filename
                )

                uploaded_file.save(saved_path)

                input_paths.append(saved_path)

            if tool_name == "pdf-merge":

                merge_pdfs(
                    input_paths,
                    out_path
                )

            else:

                compress_pdf(
                    input_paths[0],
                    out_path
                )

        else:

            details = {
                key: request.form.get(
                    key,
                    ""
                ).strip()

                for key in [
                    "full_name",
                    "email",
                    "phone",
                    "location",
                    "summary",
                    "education",
                    "experience",
                    "skills"
                ]
            }

            if not details["full_name"]:
                raise ValueError(
                    "Your full name is required."
                )

            build_cv(
                details,
                out_path
            )

        if not os.path.exists(out_path):
            raise ValueError(
                "The file could not be generated."
            )

        order = Order(
            id=order_id,
            tool=tool_name,
            amount=PRICES[tool_name],
            status="pending_payment",
            output_path=out_path
        )

        db.session.add(order)
        db.session.commit()

        return redirect(
            url_for(
                "payment_page",
                order_id=order.id
            )
        )

    except Exception as exc:

        for path in input_paths:

            if os.path.exists(path):
                os.remove(path)

        if os.path.exists(out_path):
            os.remove(out_path)

        db.session.rollback()

        flash(
            str(exc),
            "danger"
        )

        return redirect(
            url_for(
                "tool",
                tool_name=tool_name
            )
        )


# =====================================================
# PAYMENT PAGE
# =====================================================

@app.route("/payment/<order_id>")
def payment_page(order_id):

    order = Order.query.get_or_404(order_id)

    return render_template(
        "payment.html",
        order=order
    )


# =====================================================
# VERIFY AND COMPLETE PAYMENT
# =====================================================

def verify_and_complete_order(order, reference):

    payment = verify_transaction(reference)

    payment_status = payment.get("status")

    # A pending payment is not a failed payment.
    if payment_status != "success":

        if payment_status in ("failed", "abandoned", "reversed"):

            order.status = "payment_failed"
            db.session.commit()

        return False

    # Verify transaction reference.
    if payment.get("reference") != reference:

        order.status = "verification_failed"
        db.session.commit()

        return False

    # Verify amount.
    try:

        paid_amount = int(
            payment.get("amount", 0)
        )

    except (TypeError, ValueError):

        order.status = "verification_failed"
        db.session.commit()

        return False

    if paid_amount != order.amount * 100:

        order.status = "verification_failed"
        db.session.commit()

        return False

    # Verify currency.
    if payment.get("currency") != "KES":

        order.status = "verification_failed"
        db.session.commit()

        return False

    # Avoid processing the same payment twice.
    if order.status != "paid_completed":

        order.mpesa_receipt = str(
            payment.get("receipt_number")
            or payment.get("id")
            or reference
        )

        order.status = "paid_completed"

        db.session.commit()

    return True


# =====================================================
# INITIATE M-PESA PAYMENT
# =====================================================

@app.route("/pay/<order_id>", methods=["POST"])
def pay(order_id):

    order = Order.query.get_or_404(order_id)

    if order.status not in (
        "pending_payment",
        "payment_failed"
    ):

        return jsonify({
            "error": "This order already has a payment request or cannot accept another payment."
        }), 400

    phone = request.form.get(
        "phone",
        ""
    ).strip()

    email = request.form.get(
        "email",
        ""
    ).strip()

    if not phone or not email:

        return jsonify({
            "error": "Enter your email address and M-Pesa phone number."
        }), 400

    # Generate a fresh reference for each attempt.
    reference = "TB" + uuid.uuid4().hex

    try:

        result = initiate_mpesa_charge(
            phone=phone,
            email=email,
            amount=order.amount,
            reference=reference
        )

        payment_status = result.get("status")

        order.phone = phone
        order.checkout_request_id = reference

        # Explicit failure responses.
        if payment_status in (
            "failed",
            "timeout",
            "abandoned"
        ):

            order.status = "payment_failed"
            db.session.commit()

            return jsonify({
                "error": result.get(
                    "message",
                    "The payment request failed. Please try again."
                )
            }), 400

        # Immediate success still requires verification.
        if payment_status == "success":

            order.status = "paystack_pending"
            db.session.commit()

            if verify_and_complete_order(order, reference):

                return jsonify({
                    "message": "Payment confirmed! Your file is ready.",
                    "paid": True
                })

            return jsonify({
                "message": "Payment is awaiting confirmation.",
                "paid": False
            })

        # pay_offline and other non-failure states remain pending.
        order.status = "paystack_pending"
        db.session.commit()

        return jsonify({
            "message": (
                result.get("display_text")
                or "Payment request sent. Check your phone and follow the M-Pesa payment instructions."
            ),
            "reference": reference,
            "paid": False
        })

    except Exception as exc:

        db.session.rollback()

        app.logger.exception(
            "Paystack payment initiation failed"
        )

        return jsonify({
            "error": str(exc)
        }), 400


# =====================================================
# CHECK PAYMENT STATUS
# =====================================================

@app.route("/payment-status/<order_id>")
def payment_status(order_id):

    order = Order.query.get_or_404(order_id)

    # Ask Paystack for the latest status while waiting.
    if (
        order.status == "paystack_pending"
        and order.checkout_request_id
    ):

        try:

            verify_and_complete_order(
                order,
                order.checkout_request_id
            )

        except Exception:

            db.session.rollback()

            app.logger.exception(
                "Paystack payment status check failed"
            )

    return jsonify({
        "status": order.status,
        "paid": order.status == "paid_completed",
        "receipt": order.mpesa_receipt
    })


# =====================================================
# PAYSTACK WEBHOOK
# =====================================================

@app.route("/paystack/webhook", methods=["POST"])
def paystack_webhook():

    secret_key = os.getenv(
        "PAYSTACK_SECRET_KEY"
    )

    if not secret_key:

        return jsonify({
            "error": "Payment configuration missing"
        }), 500

    signature = request.headers.get(
        "x-paystack-signature",
        ""
    )

    expected_signature = hmac.new(
        secret_key.encode("utf-8"),
        request.get_data(),
        hashlib.sha512
    ).hexdigest()

    if not hmac.compare_digest(
        signature,
        expected_signature
    ):

        return jsonify({
            "error": "Invalid signature"
        }), 401

    payload = request.get_json(
        silent=True
    ) or {}

    if payload.get("event") != "charge.success":

        return jsonify({
            "message": "Event ignored"
        }), 200

    payment_data = payload.get(
        "data",
        {}
    )

    reference = payment_data.get(
        "reference"
    )

    if not reference:

        return jsonify({
            "error": "Missing transaction reference"
        }), 400

    order = Order.query.filter_by(
        checkout_request_id=reference
    ).first()

    if not order:

        return jsonify({
            "message": "Order not found"
        }), 200

    if order.status == "paid_completed":

        return jsonify({
            "message": "Already processed"
        }), 200

    try:

        verify_and_complete_order(
            order,
            reference
        )

    except Exception:

        db.session.rollback()

        app.logger.exception(
            "Paystack webhook verification failed"
        )

        return jsonify({
            "error": "Verification failed"
        }), 500

    return jsonify({
        "message": "Webhook processed"
    }), 200


# =====================================================
# DOWNLOAD FILE
# =====================================================

@app.route("/download/<order_id>")
def download(order_id):

    order = Order.query.get_or_404(order_id)

    if order.status != "paid_completed":

        return (
            "Payment has not been verified. Download unavailable.",
            403
        )

    if (
        not order.output_path
        or not os.path.exists(order.output_path)
    ):

        return "File is not available.", 404

    return send_file(
        order.output_path,
        as_attachment=True,
        download_name=f"toolbox-{order.tool}.pdf"
    )


# =====================================================
# HEALTH CHECK
# =====================================================

@app.route("/health")
def health():

    return {
        "status": "ok"
    }


# =====================================================
# CREATE DATABASE TABLES
# =====================================================

with app.app_context():

    db.create_all()


# =====================================================
# RUN APPLICATION
# =====================================================

if __name__ == "__main__":

    app.run(
        debug=os.getenv(
            "FLASK_DEBUG",
            "false"
        ).lower() == "true"
    )
