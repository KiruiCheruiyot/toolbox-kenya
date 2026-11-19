
import os
import uuid
import secrets
from datetime import datetime
from functools import wraps

from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, send_file, session, jsonify
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

from tools.pdf_tools import merge_pdfs, compress_pdf
from tools.cv_builder import build_cv
from payments.mpesa import initiate_stk_push, query_stk_status

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "replace-this-secret")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URL", "sqlite:///toolbox.db"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024
app.config["UPLOAD_FOLDER"] = "uploads"
app.config["OUTPUT_FOLDER"] = "processed"

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(app.config["OUTPUT_FOLDER"], exist_ok=True)

db = SQLAlchemy(app)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(160), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Order(db.Model):
    id = db.Column(db.String(36), primary_key=True)
    tool = db.Column(db.String(60), nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    phone = db.Column(db.String(20))
    status = db.Column(db.String(30), default="pending_payment", nullable=False)
    checkout_request_id = db.Column(db.String(120), unique=True)
    mpesa_receipt = db.Column(db.String(80))
    input_path = db.Column(db.String(500))
    output_path = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


PRICES = {
    "pdf-merge": 20,
    "pdf-compress": 15,
    "cv-builder": 50
}


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please sign in first.", "warning")
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


@app.route("/")
def index():
    return render_template("index.html", prices=PRICES)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or len(password) < 8:
            flash("Enter a valid email and a password of at least 8 characters.", "danger")

        elif User.query.filter_by(email=email).first():
            flash("That email is already registered.", "danger")

        else:
            user = User(
                email=email,
                password_hash=generate_password_hash(password)
            )
            db.session.add(user)
            db.session.commit()

            session["user_id"] = user.id
            flash("Account created successfully.", "success")
            return redirect(url_for("index"))

    return render_template("auth.html", mode="Register")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = User.query.filter_by(
            email=request.form.get("email", "").strip().lower()
        ).first()

        if user and check_password_hash(
            user.password_hash,
            request.form.get("password", "")
        ):
            session["user_id"] = user.id
            return redirect(url_for("index"))

        flash("Incorrect email or password.", "danger")

    return render_template("auth.html", mode="Sign in")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


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
                f for f in uploads if f and f.filename
            ]

            if not valid_uploads:
                raise ValueError("Choose at least one PDF file.")

            if tool_name == "pdf-merge" and len(valid_uploads) < 2:
                raise ValueError("Select at least two PDF files to merge.")

            for uploaded_file in valid_uploads:
                if not uploaded_file.filename.lower().endswith(".pdf"):
                    raise ValueError("Only PDF files are accepted.")

                filename = secure_filename(uploaded_file.filename)

                saved_path = os.path.join(
                    app.config["UPLOAD_FOLDER"],
                    order_id + "_" + secrets.token_hex(4) + "_" + filename
                )

                uploaded_file.save(saved_path)
                input_paths.append(saved_path)

            if tool_name == "pdf-merge":
                merge_pdfs(input_paths, out_path)
            else:
                compress_pdf(input_paths[0], out_path)

        else:
            details = {
                key: request.form.get(key, "").strip()
                for key in [
                    "full_name", "email", "phone", "location",
                    "summary", "education", "experience", "skills"
                ]
            }

            if not details["full_name"]:
                raise ValueError("Your full name is required.")

            build_cv(details, out_path)

        if not os.path.exists(out_path):
            raise ValueError("The file could not be generated.")

        order = Order(
            id=order_id,
            tool=tool_name,
            amount=PRICES[tool_name],
            status="pending_payment",
            output_path=out_path
        )

        db.session.add(order)
        db.session.commit()

        return redirect(url_for("payment_page", order_id=order.id))

    except Exception as exc:
        for path in input_paths:
            if os.path.exists(path):
                os.remove(path)

        if os.path.exists(out_path):
            os.remove(out_path)

        db.session.rollback()
        flash(str(exc), "danger")
        return redirect(url_for("tool", tool_name=tool_name))


@app.route("/payment/<order_id>")
def payment_page(order_id):
    order = Order.query.get_or_404(order_id)

    return render_template("payment.html", order=order)


@app.route("/pay/<order_id>", methods=["POST"])
def pay(order_id):
    order = Order.query.get_or_404(order_id)

    if order.status not in ("pending_payment", "stk_requested"):
        return jsonify({
            "error": "This order cannot accept another payment request."
        }), 400

    phone = request.form.get("phone", "").strip()

    try:
        result = initiate_stk_push(
            phone=phone,
            amount=order.amount,
            account_reference=order.id
        )

        checkout_id = result.get("CheckoutRequestID")

        if not checkout_id:
            return jsonify({
                "error": result.get(
                    "errorMessage",
                    result.get("ResponseDescription", "M-Pesa did not return a checkout ID.")
                )
            }), 400

        order.phone = phone
        order.checkout_request_id = checkout_id
        order.status = "stk_requested"

        db.session.commit()

        return jsonify({
            "message": "Payment request sent. Check your phone and enter your M-Pesa PIN.",
            "checkout_request_id": checkout_id
        })

    except Exception as exc:
        db.session.rollback()
        return jsonify({"error": str(exc)}), 400


@app.route("/payment-status/<order_id>")
def payment_status(order_id):
    order = Order.query.get_or_404(order_id)

    return jsonify({
        "status": order.status,
        "paid": order.status == "paid_completed",
        "receipt": order.mpesa_receipt
    })


@app.route("/mpesa/callback", methods=["POST"])
def mpesa_callback():
    payload = request.get_json(silent=True) or {}

    callback = (
        payload.get("Body", {})
        .get("stkCallback", {})
    )

    checkout_id = callback.get("CheckoutRequestID")
    result_code = callback.get("ResultCode")

    order = Order.query.filter_by(
        checkout_request_id=checkout_id
    ).first()

    if not order:
        return jsonify({
            "ResultCode": 0,
            "ResultDesc": "Callback received"
        })

    if result_code != 0:
        order.status = "payment_failed"
        db.session.commit()

        return jsonify({
            "ResultCode": 0,
            "ResultDesc": "Payment failure recorded"
        })

    # Callback data alone is not trusted.
    # Confirm the transaction directly with Daraja.
    try:
        verification = query_stk_status(checkout_id)

        if str(verification.get("ResultCode")) != "0":
            order.status = "verification_pending"
            db.session.commit()

            return jsonify({
                "ResultCode": 0,
                "ResultDesc": "Payment verification pending"
            })

        metadata = callback.get("CallbackMetadata", {}).get("Item", [])

        values = {
            item.get("Name"): item.get("Value")
            for item in metadata
            if item.get("Name")
        }

        receipt = values.get("MpesaReceiptNumber")
        paid_amount = values.get("Amount")
        paid_phone = values.get("PhoneNumber")

        if not receipt or paid_amount is None or paid_phone is None:
            order.status = "verification_pending"
            db.session.commit()

            return jsonify({
                "ResultCode": 0,
                "ResultDesc": "Payment details incomplete"
            })

        expected_phone = order.phone.replace("+", "").replace(" ", "")
        actual_phone = str(paid_phone)

        if expected_phone.startswith("0"):
            expected_phone = "254" + expected_phone[1:]

        if (
            int(float(paid_amount)) != order.amount
            or actual_phone != expected_phone
        ):
            order.status = "verification_failed"
            db.session.commit()

            return jsonify({
                "ResultCode": 0,
                "ResultDesc": "Payment details did not match"
            })

        order.mpesa_receipt = receipt
        order.status = "paid_completed"
        db.session.commit()

    except Exception as exc:
        app.logger.exception("M-Pesa verification error: %s", exc)
        order.status = "verification_pending"
        db.session.commit()

    return jsonify({
        "ResultCode": 0,
        "ResultDesc": "Callback processed"
    })


@app.route("/download/<order_id>")
def download(order_id):
    order = Order.query.get_or_404(order_id)

    if order.status != "paid_completed":
        return "Payment has not been verified. Download unavailable.", 403

    if not order.output_path or not os.path.exists(order.output_path):
        return "File is not available.", 404

    return send_file(
        order.output_path,
        as_attachment=True,
        download_name=f"toolbox-{order.tool}.pdf"
    )


@app.route("/health")
def health():
    return {"status": "ok"}


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true"
    )
