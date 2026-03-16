import mysql.connector
import uuid
import os
import string
import random
import threading
import pandas as pd
import math
import io
import json  # <-- Thêm thư viện này để xử lý Lịch sử
from flask import send_file
from flask import jsonify
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from qr_generator import generate_qr
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    login_required,
    logout_user,
    current_user,
)
from flask import request, redirect, url_for, session
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
    session,
)

app = Flask(__name__)
app.secret_key = "mintruzz.dev_pro_code"
app.config["REMEMBER_COOKIE_DURATION"] = timedelta(days=7)
app.config["SESSION_PROTECTION"] = "strong"


# --- Cấu hình MySQL ---
def db():
    return mysql.connector.connect(
        host="localhost", user="root", password="", database="warranty"
    )


db_lock = threading.Lock()


# --- User Class & Loader ---
class User(UserMixin):
    def __init__(self, id, username, password, role):
        self.id = id
        self.username = username
        self.password = password
        self.role = str(role).strip() if role else "user"


login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


@login_manager.user_loader
def load_user(user_id):
    conn = db()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    u = cur.fetchone()
    conn.close()
    if u:
        return User(u["id"], u["username"], u["password"], u["role"])
    return None


# --- Decorators ---
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != "admin":
            flash("Bạn không có quyền thực hiện hành động này!", "error")
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated_function


def generate_auto_bill_code():
    prefix = datetime.now().strftime("%d%m")
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=10))
    return f"{prefix}{suffix}"


# --- ROUTES ---
@app.before_request
def check_pending_after_view():
    allowed = [
        "admin",
        "static",
        "login",
        "logout",
        "update_so_phieu",
        "fix_pending_page",
        "view_bill",
        "delete_bill",
        "delete_item",
        "check_should_fix",
        "get_pending_groups",
    ]
    if request.endpoint in allowed or not request.endpoint:
        return

    if session.get("watching_bill"):
        conn = db()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id FROM warranty_items WHERE so_phieu IS NULL OR so_phieu = '' LIMIT 1"
        )
        pending = cur.fetchone()
        conn.close()

        if pending:
            flash("⚠️ Bạn chưa hoàn tất nhập Số Phiếu cho đợt hàng vừa xem!")
        else:
            session.pop("watching_bill", None)


@app.route("/fix-pending")
@login_required
def fix_pending_page():
    conn = db()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """
        SELECT ma_bill, GROUP_CONCAT(DISTINCT product_id) as p_ids, COUNT(*) as total 
        FROM warranty_items 
        WHERE so_phieu IS NULL OR so_phieu = '' 
        GROUP BY ma_bill
    """
    )
    pending_groups = cur.fetchall()
    conn.close()
    return render_template("fix_pending.html", groups=pending_groups)


@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user_name = request.form["username"]
        pw = request.form["password"]

        conn = db()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT * FROM users WHERE username = %s", (user_name,))
        u = cur.fetchone()
        conn.close()

        if u and u["username"] == user_name and check_password_hash(u["password"], pw):
            user_obj = User(u["id"], u["username"], u["password"], u["role"])
            login_user(user_obj)
            return redirect(url_for("admin"))

        flash("Sai tài khoản hoặc mật khẩu!")
    return render_template("login.html", now=datetime.now())


@app.route("/api/get-customer-info", methods=["GET"])
def get_customer_info():
    phone = request.args.get("phone", "").strip()
    if not phone or len(phone) < 3:
        return jsonify({"found": False})

    try:
        conn = db()
        cur = conn.cursor(dictionary=True)
        search_term = phone
        if phone.startswith("0"):
            search_term_no_zero = phone[1:]
        else:
            search_term_no_zero = phone

        sql = """
            SELECT customer_name 
            FROM orders 
            WHERE customer_phone = %s 
               OR customer_phone = %s
               OR customer_phone LIKE %s
            ORDER BY id DESC 
            LIMIT 1
        """
        cur.execute(sql, (phone, search_term_no_zero, f"%{search_term_no_zero}"))
        result = cur.fetchone()
        cur.close()
        conn.close()

        if result:
            return jsonify({"found": True, "name": result["customer_name"]})
        else:
            return jsonify({"found": False})
    except Exception as e:
        print(f"Error API: {e}")
        return jsonify({"found": False})


@app.route("/admin", methods=["GET", "POST"])
@login_required
def admin():
    conn = db()
    cur = conn.cursor(dictionary=True)

    if request.method == "POST":
        try:
            with db_lock:
                c_name = request.form.get("customer_name", "").strip().title()
                c_phone = request.form.get("customer_phone", "").strip()

                p_names = request.form.getlist("product_names[]")
                p_quants = request.form.getlist("quantities[]")
                p_war = request.form.getlist("warranty_months[]")

                if not p_names:
                    flash("❌ Lỗi: Chưa nhập sản phẩm!")
                    return redirect(url_for("admin"))

                bill_id = None
                customer_code_tt = None
                is_new_customer = False

                if c_phone:
                    cur.execute(
                        "SELECT id, bill_code, customer_name FROM orders WHERE customer_phone = %s LIMIT 1",
                        (c_phone,),
                    )
                    existing_customer = cur.fetchone()

                    if existing_customer:
                        bill_id = existing_customer["id"]
                        customer_code_tt = existing_customer["bill_code"]
                        if not c_name:
                            c_name = existing_customer["customer_name"]
                        cur.execute(
                            "UPDATE orders SET updated_at = %s WHERE id = %s",
                            (datetime.now(), bill_id),
                        )
                    else:
                        is_new_customer = True
                else:
                    is_new_customer = True

                if is_new_customer:
                    if not c_name:
                        c_name = "Khách Lẻ"

                    # 🔥 Cập nhật: Thêm created_by vào lệnh INSERT
                    cur.execute(
                        """
                        INSERT INTO orders (bill_code, customer_name, customer_phone, created_at, updated_at, created_by) 
                        VALUES ('TEMP', %s, %s, %s, %s, %s)
                    """,
                        (
                            c_name,
                            c_phone,
                            datetime.now(),
                            datetime.now(),
                            current_user.username,
                        ),
                    )
                    bill_id = cur.lastrowid
                    customer_code_tt = f"TT-{str(bill_id).zfill(6)}"
                    cur.execute(
                        "UPDATE orders SET bill_code = %s WHERE id = %s",
                        (customer_code_tt, bill_id),
                    )

                date_prefix = datetime.now().strftime("%y%m%d")
                chars = string.ascii_uppercase + string.digits
                shopee_code = f"{date_prefix}{''.join(random.choices(chars, k=6))}"

                for i in range(len(p_names)):
                    current_name = p_names[i]
                    try:
                        qty = int(p_quants[i]) if p_quants[i] else 1
                        war = int(p_war[i]) if p_war[i] else 0
                    except:
                        qty = 1
                        war = 0

                    cur.execute(
                        "SELECT id FROM products WHERE product_name = %s LIMIT 1",
                        (current_name,),
                    )
                    res_prod = cur.fetchone()
                    if res_prod:
                        p_id = res_prod["id"]
                    else:
                        p_code = f"PROD-{random.randint(1000, 9999)}"
                        cur.execute(
                            "INSERT INTO products (product_code, product_name) VALUES (%s, %s)",
                            (p_code, current_name),
                        )
                        p_id = cur.lastrowid

                    for _ in range(qty):
                        u_id = str(uuid.uuid4())
                        cur.execute(
                            """
                            INSERT INTO warranty_items (uuid, bill_id, ma_bill, product_id, warranty_months, activated_at)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            """,
                            (u_id, bill_id, shopee_code, p_id, war, None),
                        )
                        try:
                            generate_qr(u_id, shopee_code, c_name, current_name)
                        except Exception as e:
                            print(f"Lỗi tạo QR Code: {str(e)}")

            conn.commit()

            if is_new_customer:
                flash(f"✅ Đã tạo Khách Hàng mới: {c_name} ({customer_code_tt})")
            else:
                flash(
                    f"✅ Đã thêm đơn mới vào Khách Hàng cũ: {c_name} ({customer_code_tt})"
                )
        except Exception as e:
            conn.rollback()
            if "Duplicate entry" in str(e) and "bill_code" in str(e):
                flash("❌ Lỗi trùng mã Khách Hàng! Vui lòng kiểm tra lại database.")
            else:
                flash(f"❌ Lỗi hệ thống: {str(e)}")
        finally:
            cur.close()
            conn.close()
        return redirect(url_for("admin"))

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 12, type=int)
    search = request.args.get("search", "").strip()

    where_clause = ""
    params = []

    if search:
        search_param = f"%{search}%"
        # Thêm Subquery: OR id IN (SELECT bill_id FROM warranty_items WHERE ma_bill LIKE %s)
        where_clause = """WHERE customer_name LIKE %s 
                          OR bill_code LIKE %s 
                          OR customer_phone LIKE %s 
                          OR created_by LIKE %s 
                          OR id IN (SELECT bill_id FROM warranty_items WHERE ma_bill LIKE %s OR so_phieu LIKE %s)"""

        # Có 6 dấu %s ở trên nên params phải có 6 cái search_param tương ứng
        params = [
            search_param,
            search_param,
            search_param,
            search_param,
            search_param,
            search_param,
        ]

    cur.execute(f"SELECT COUNT(*) as total FROM orders {where_clause}", tuple(params))
    total_records = cur.fetchone()["total"]
    total_pages = math.ceil(total_records / per_page) if total_records > 0 else 1
    offset = (page - 1) * per_page

    cur.execute(
        f"SELECT * FROM orders {where_clause} ORDER BY updated_at DESC, id DESC LIMIT {per_page} OFFSET {offset}",
        tuple(params),
    )
    bills = cur.fetchall()

    cur.execute("SELECT DISTINCT product_name FROM products ORDER BY product_name ASC")
    all_products = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "admin.html",
        bills=bills,
        all_products=all_products,
        search=search,
        current_user=current_user,
        now=datetime.now(),
        current_page=page,
        total_pages=total_pages,
        per_page=per_page,
    )


@app.route("/bill/<int:bill_id>")
@login_required
def view_bill(bill_id):
    session["watching_bill"] = True
    conn = db()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM orders WHERE id = %s", (bill_id,))
    order_info = cur.fetchone()

    if not order_info:
        return "Không tìm thấy khách hàng", 404

    cur.execute(
        """
        SELECT wi.uuid, wi.ma_bill, p.product_name, wi.warranty_months, wi.activated_at, 
               wi.so_phieu, wi.bill_id, wi.warranty_count, wi.claim_history 
        FROM warranty_items wi 
        JOIN products p ON wi.product_id = p.id 
        WHERE wi.bill_id = %s 
        ORDER BY wi.activated_at DESC
        """,
        (bill_id,),
    )

    items = cur.fetchall()
    conn.close()

    missing_items = [i for i in items if not i["so_phieu"] or i["so_phieu"] == ""]
    missing_groups = []
    if missing_items:
        missing_groups.append(
            {
                "ma_bill": items[0]["ma_bill"] if items else "UNKNOWN",
                "total": len(missing_items),
            }
        )
    return render_template(
        "view_bill.html",
        items=items,
        customer_name=order_info["customer_name"],
        customer_phone=order_info["customer_phone"],
        order=order_info,
        timedelta=timedelta,
        groups=missing_groups,
        now=datetime.now(),
    )


@app.route("/search_bill")
@login_required
def search_bill():
    query = request.args.get("query", "").strip()
    if not query:
        return redirect(url_for("admin"))  # Hoặc trang danh sách chính của bạn

    conn = db()
    cur = conn.cursor(dictionary=True)

    # 1. Thử tìm theo Mã đơn (bill_code trong bảng orders)
    cur.execute("SELECT id FROM orders WHERE bill_code = %s", (query,))
    order = cur.fetchone()

    if order:
        conn.close()
        return redirect(url_for("view_bill", bill_id=order["id"]))

    # 2. Nếu không thấy, thử tìm theo Mã Bill sản phẩm (ma_bill trong bảng warranty_items)
    cur.execute("SELECT bill_id FROM warranty_items WHERE ma_bill = %s", (query,))
    item = cur.fetchone()
    conn.close()

    if item:
        return redirect(url_for("view_bill", bill_id=item["bill_id"]))

    # Nếu không tìm thấy gì cả
    flash(f"Không tìm thấy đơn hàng hoặc sản phẩm có mã: {query}", "error")
    return redirect(request.referrer or url_for("admin"))


@app.route("/update-so-phieu", methods=["POST"])
@login_required
def update_so_phieu():
    data = request.get_json()
    items = data.get("items", [])

    if not items:
        return (
            jsonify({"success": False, "message": "Không có dữ liệu để cập nhật"}),
            400,
        )

    try:
        conn = db()
        cur = conn.cursor(dictionary=True)
        target_bill_id = None
        duplicates = []

        for item in items:
            ma_bill = item.get("ma_bill", "").strip().upper()
            val = item.get("so_phieu", "").strip().upper()
            if not ma_bill or not val:
                continue

            query_check = """
                SELECT ma_bill FROM warranty_items 
                WHERE UPPER(TRIM(so_phieu)) = %s AND UPPER(TRIM(ma_bill)) != %s LIMIT 1
            """
            cur.execute(query_check, (val, ma_bill))
            existing_record = cur.fetchone()

            if existing_record:
                duplicates.append(
                    f"Số phiếu '{val}' đã tồn tại ở đợt hàng {existing_record['ma_bill']}"
                )
                continue

            cur.execute(
                "UPDATE warranty_items SET so_phieu = %s WHERE UPPER(TRIM(ma_bill)) = %s",
                (val, ma_bill),
            )

            if not target_bill_id:
                cur.execute(
                    "SELECT bill_id FROM warranty_items WHERE UPPER(TRIM(ma_bill)) = %s LIMIT 1",
                    (ma_bill,),
                )
                res = cur.fetchone()
                if res:
                    target_bill_id = res["bill_id"]

        conn.commit()
        if duplicates:
            return jsonify(
                {
                    "success": False,
                    "message": "Cập nhật một phần. Lỗi: " + ", ".join(duplicates),
                }
            )

        cur.execute(
            "SELECT id FROM warranty_items WHERE so_phieu IS NULL OR so_phieu = '' LIMIT 1"
        )
        if not cur.fetchone():
            session.pop("watching_bill", None)

        cur.close()
        conn.close()

        redirect_to = (
            url_for("view_bill", bill_id=target_bill_id)
            if target_bill_id
            else url_for("admin")
        )
        return jsonify({"success": True, "redirect_url": redirect_to})

    except Exception as e:
        return jsonify({"success": False, "message": f"Lỗi hệ thống: {str(e)}"}), 500


@app.route("/delete-bill/<int:bill_id>", methods=["POST"])
@login_required
@admin_required
def delete_bill(bill_id):
    conn = db()
    cur = conn.cursor()
    cur.execute("DELETE FROM warranty_items WHERE bill_id=%s", (bill_id,))
    cur.execute("DELETE FROM orders WHERE id=%s", (bill_id,))
    conn.commit()
    conn.close()
    flash(f"❌ Đã xóa toàn bộ dữ liệu Bill ID: {bill_id}", "danger")
    return redirect(url_for("admin"))


@app.route("/delete-warranty-item/<uuid_code>", methods=["POST"])
@login_required
@admin_required
def delete_warranty_item(uuid_code):
    try:
        conn = db()
        cur = conn.cursor()
        cur.execute("DELETE FROM warranty_items WHERE uuid = %s", (uuid_code,))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/print/<int:bill_id>")
@login_required
def print_qr(bill_id):
    conn = db()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """
        SELECT wi.uuid, wi.ma_bill, p.product_name 
        FROM warranty_items wi JOIN products p ON wi.product_id = p.id
        WHERE wi.bill_id=%s
    """,
        (bill_id,),
    )
    qrs = cur.fetchall()
    conn.close()
    return render_template("print_qr.html", qrs=qrs, now=datetime.now())


@app.route("/print_selected")
@login_required
def print_selected_items():
    # Lấy danh sách uuid từ link: /print_selected?uuids=uuid1,uuid2...
    uuids_raw = request.args.get("uuids", "")
    if not uuids_raw:
        return "Vui lòng chọn sản phẩm", 400

    uuid_list = uuids_raw.split(",")

    conn = db()
    cur = conn.cursor(dictionary=True)

    # Tạo các dấu %s tương ứng với số lượng uuid để truyền vào SQL
    placeholders = ",".join(["%s"] * len(uuid_list))

    # Câu lệnh SELECT này tôi copy y hệt từ hàm print_qr của bạn, chỉ thay WHERE bill_id thành WHERE uuid IN
    cur.execute(
        f"""
        SELECT wi.uuid, wi.ma_bill, p.product_name 
        FROM warranty_items wi JOIN products p ON wi.product_id = p.id
        WHERE wi.uuid IN ({placeholders})
    """,
        tuple(uuid_list),
    )
    qrs = cur.fetchall()
    conn.close()

    # Dùng chung template print_qr.html và các biến qrs, now giống hệt hàm cũ
    return render_template("print_qr.html", qrs=qrs, now=datetime.now())


@app.route("/single_qr/<string:uuid>")
@login_required
def print_single_qr(uuid):
    conn = db()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """
        SELECT wi.uuid, wi.ma_bill, p.product_name 
        FROM warranty_items wi JOIN products p ON wi.product_id = p.id
        WHERE wi.uuid = %s
    """,
        (uuid,),
    )
    one_item = cur.fetchone()
    conn.close()
    if one_item:
        return render_template("print_qr.html", qrs=[one_item], now=datetime.now())
    else:
        return "Không tìm thấy sản phẩm này", 404


@app.route("/warranty/<uuid_code>")
def warranty(uuid_code):
    conn = db()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """
        SELECT wi.*, o.created_at as bill_date, o.customer_name, p.product_name, o.customer_phone
        FROM warranty_items wi
        JOIN orders o ON wi.bill_id = o.id
        JOIN products p ON wi.product_id = p.id
        WHERE wi.uuid = %s
    """,
        (uuid_code,),
    )
    item = cur.fetchone()
    conn.close()

    if not item:
        return "QR không hợp lệ", 404

    # 1. Hiển thị ngày xuất bán và ngày kích hoạt (Chỉ để xem, không dùng tính toán)
    created_date_str = (
        item["bill_date"].strftime("%d/%m/%Y") if item["bill_date"] else "---"
    )
    activated_date_str = (
        item["activated_at"].strftime("%d/%m/%Y")
        if item["activated_at"]
        else "Chưa kích hoạt"
    )

    # 2. Thiết lập ngày gốc mặc định là ngày xuất bán (bill_date)
    base_date = item["bill_date"]
    warranty_months = item.get("warranty_months") or 0

    claim_history_list = []
    warranty_count = item.get("warranty_count", 0) or 0

    # 3. Xử lý lịch sử bảo hành và kiểm tra logic RESET
    if item.get("claim_history"):
        try:
            history_arr = json.loads(item["claim_history"])
            for idx, hist_item in enumerate(history_arr):
                ngay_str = ""
                dt_obj = None

                # Chuyển đổi dữ liệu lịch sử thành object datetime
                if isinstance(hist_item, str):
                    try:
                        dt_obj = datetime.strptime(hist_item, "%Y-%m-%d %H:%M:%S")
                        ngay_str = dt_obj.strftime("%d/%m/%Y %H:%M")
                    except:
                        ngay_str = hist_item

                # --- LOGIC QUAN TRỌNG: RESET NGÀY BẢO HÀNH ---
                # Nếu tìm thấy lịch sử Lần 1 (idx == 0), lấy ngày này làm base_date mới
                if idx == 0 and dt_obj:
                    base_date = dt_obj

                claim_history_list.append({"lan": idx + 1, "ngay": ngay_str})
        except Exception as e:
            print(f"Lỗi đọc lịch sử: {e}")

    # 4. Tính toán ngày hết hạn dựa trên base_date (đã được reset nếu có Lần 1)
    end_date = base_date + relativedelta(months=warranty_months)
    end_date_str = end_date.strftime("%d/%m/%Y")

    # 5. Tính số ngày còn lại dựa trên ngày hiện tại của PC
    remaining_days = (end_date.date() - datetime.now().date()).days

    return render_template(
        "warranty.html",
        product=item,
        created_date_str=created_date_str,
        activated_date_str=activated_date_str,
        end_date_str=end_date_str,
        remaining_days=remaining_days,
        warranty_count=warranty_count,
        claim_history_list=claim_history_list,
        now=datetime.now(),
    )


@app.route("/check-should-fix")
@login_required
def check_should_fix():
    if session.get("watching_bill"):
        conn = db()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id FROM warranty_items WHERE so_phieu IS NULL OR so_phieu = '' LIMIT 1"
        )
        pending = cur.fetchone()
        conn.close()
        if pending:
            return jsonify({"should_open": True})
        else:
            session.pop("watching_bill", None)
    return jsonify({"should_open": False})


@app.route("/import-excel", methods=["POST"])
@login_required
def import_excel():
    try:
        file = request.files.get("file")
        is_confirmed = request.form.get("confirm") == "true"
        if not file:
            return jsonify({"success": False, "message": "Chưa chọn file!"})

        if file.filename.endswith(".csv"):
            df = pd.read_csv(file)
        else:
            df = pd.read_excel(file)

        df.columns = [str(c).strip().upper() for c in df.columns]
        if "MA_KH" not in df.columns:
            return jsonify({"success": False, "message": "File Excel thiếu cột MA_KH"})

        excel_bill_codes = [
            str(code).strip().upper()
            for code in df["MA_KH"].unique()
            if str(code).strip().upper() not in ["NAN", "", "NONE"]
        ]

        if not is_confirmed:
            return jsonify(
                {
                    "success": True,
                    "require_confirm": True,
                    "count": len(excel_bill_codes),
                }
            )

        conn = db()
        cur = conn.cursor()
        updated_count = 0
        inserted_count = 0

        for _, row in df.iterrows():
            bill_code = str(row.get("MA_KH", "")).strip().upper()
            if bill_code in excel_bill_codes:
                ten_kh = str(row.get("TEN_KH", "")).strip()
                if ten_kh.lower() == "nan":
                    ten_kh = ""
                sdt = str(row.get("DIEN_THOAI", "")).strip()
                if sdt.lower() == "nan":
                    sdt = ""
                dia_chi = str(row.get("DIA_CHI", "")).strip()
                if dia_chi.lower() == "nan":
                    dia_chi = ""

                cur.execute(
                    "SELECT count(*) FROM orders WHERE bill_code = %s", (bill_code,)
                )
                exists = cur.fetchone()[0] > 0

                if exists:
                    cur.execute(
                        "UPDATE orders SET customer_name = %s, customer_phone = %s, customer_address = %s WHERE bill_code = %s",
                        (ten_kh, sdt, dia_chi, bill_code),
                    )
                    updated_count += 1
                else:
                    # 🔥 Cập nhật: Lưu thêm created_by khi Import Excel
                    cur.execute(
                        "INSERT INTO orders (bill_code, customer_name, customer_phone, customer_address, created_at, created_by) VALUES (%s, %s, %s, %s, NOW(), %s)",
                        (bill_code, ten_kh, sdt, dia_chi, current_user.username),
                    )
                    inserted_count += 1

        conn.commit()
        cur.close()
        conn.close()

        msg = f"Xong! Đã cập nhật {updated_count} đơn cũ và thêm mới {inserted_count} đơn."
        return jsonify({"success": True, "require_confirm": False, "message": msg})

    except Exception as e:
        return jsonify({"success": False, "message": f"Lỗi: {str(e)}"})


@app.route("/export_excel")
@login_required
def export_excel():
    try:
        conn = db()
        # 🔥 Cập nhật: Xuất thêm cột "Người Tạo" ra Excel
        sql = """
            SELECT o.bill_code AS 'Mã Đơn', o.customer_name AS 'Tên Khách Hàng',
                o.customer_phone AS 'SĐT', o.customer_address AS 'Địa Chỉ',
                o.created_at AS 'Ngày Tạo Đơn', o.created_by AS 'Người Tạo', p.product_name AS 'Sản Phẩm',
                wi.so_phieu AS 'Số Phiếu/Note', wi.warranty_months AS 'Bảo Hành (Tháng)',
                wi.activated_at AS 'Ngày Kích Hoạt', wi.uuid AS 'Mã UUID'
            FROM warranty_items wi JOIN orders o ON wi.bill_id = o.id
            JOIN products p ON wi.product_id = p.id ORDER BY o.created_at DESC
        """
        df = pd.read_sql(sql, conn)
        conn.close()

        if df.empty:
            flash("Không có dữ liệu để xuất!", "warning")
            return redirect(request.referrer)

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            df.to_excel(writer, index=False, sheet_name="Chi Tiết Đơn Hàng")
            workbook = writer.book
            worksheet = writer.sheets["Chi Tiết Đơn Hàng"]
            format_header = workbook.add_format(
                {"bold": True, "align": "center", "bg_color": "#D7E4BC"}
            )
            for i, col in enumerate(df.columns):
                worksheet.set_column(i, i, len(col) + 5)
                worksheet.write(0, i, col, format_header)

        output.seek(0)
        filename = f"Chi_Tiet_Don_Hang_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        return send_file(
            output,
            download_name=filename,
            as_attachment=True,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    except Exception as e:
        flash(f"Lỗi khi xuất file: {str(e)}", "error")
        return redirect(request.referrer)


@app.route("/customers")
@login_required
@admin_required
def manage_customers():
    conn = db()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM users ORDER BY id DESC")
    all_customers = cur.fetchall()
    cur.close()
    conn.close()
    return render_template(
        "customers.html", customers=all_customers, now=datetime.now()
    )


@app.route("/add-user", methods=["POST"])
@login_required
@admin_required
def add_user():
    username = request.form.get("username")
    password = request.form.get("password")
    role = request.form.get("role", "user")

    if not username or not password:
        flash("Vui lòng điền đầy đủ thông tin!", "error")
        return redirect(url_for("manage_customers"))

    conn = db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM users WHERE username = %s", (username,))
        if cur.fetchone():
            flash("Tên đăng nhập đã tồn tại, vui lòng chọn tên khác!", "error")
        else:
            hashed_pw = generate_password_hash(password)
            cur.execute(
                "INSERT INTO users (username, password, role) VALUES (%s, %s, %s)",
                (username, hashed_pw, role),
            )
            conn.commit()
            flash("Thêm tài khoản mới thành công!", "success")
    except Exception as e:
        flash(f"Lỗi hệ thống: {str(e)}", "error")
    finally:
        cur.close()
        conn.close()

    return redirect(url_for("manage_customers"))


@app.route("/delete-user/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def delete_user(user_id):
    if user_id == current_user.id:
        flash("Bạn không thể tự xóa tài khoản đang đăng nhập!", "error")
        return redirect(url_for("manage_customers"))

    try:
        conn = db()
        cur = conn.cursor()
        cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()
        flash("Đã xóa tài khoản thành công!", "success")
    except Exception as e:
        if "foreign key" in str(e).lower():
            flash(
                "Không thể xóa: Tài khoản này đang chứa dữ liệu đơn hàng/bảo hành!",
                "error",
            )
        else:
            flash(f"Lỗi khi xóa: {str(e)}", "error")
    finally:
        if "cur" in locals():
            cur.close()
        if "conn" in locals():
            conn.close()

    return redirect(url_for("manage_customers"))


@app.route("/edit-user/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def edit_user(user_id):
    new_username = request.form.get("username")
    new_password = request.form.get("password")
    new_role = request.form.get("role")

    conn = db()
    cur = conn.cursor()
    try:
        if new_password and new_password.strip() != "":
            hashed_pw = generate_password_hash(new_password)
            cur.execute(
                "UPDATE users SET username=%s, password=%s, role=%s WHERE id=%s",
                (new_username, hashed_pw, new_role, user_id),
            )
        else:
            cur.execute(
                "UPDATE users SET username=%s, role=%s WHERE id=%s",
                (new_username, new_role, user_id),
            )

        conn.commit()
        flash("Cập nhật thông tin thành công!", "success")
    except Exception as e:
        flash(f"Lỗi (có thể trùng tên đăng nhập): {str(e)}", "error")
    finally:
        cur.close()
        conn.close()

    return redirect(url_for("manage_customers"))


@app.route("/manage-products")
@login_required
@admin_required
def manage_products():
    conn = db()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM products ORDER BY id DESC")
    products = cur.fetchall()
    cur.close()
    conn.close()
    return render_template(
        "manage_products.html", products=products, now=datetime.now()
    )


@app.route("/add-product", methods=["POST"])
@login_required
@admin_required
def add_product():
    if request.method == "POST":
        p_name = request.form.get("product_name")
        conn = db()
        cur = conn.cursor()
        try:
            p_code = f"PROD-{random.randint(1000,9999)}"
            cur.execute(
                "INSERT INTO products (product_code, product_name) VALUES (%s, %s)",
                (p_code, p_name),
            )
            conn.commit()
            flash("Đã thêm sản phẩm mới thành công!", "success")
        except Exception as e:
            flash(f"Lỗi khi thêm sản phẩm: {str(e)}", "error")
        finally:
            cur.close()
            conn.close()
        return redirect(url_for("manage_products"))


@app.route("/edit-product/<int:p_id>", methods=["POST"])
@login_required
@admin_required
def edit_product(p_id):
    conn = db()
    cur = conn.cursor()
    new_name = request.form.get("product_name")
    if not new_name:
        flash("Tên sản phẩm không được để trống", "error")
        return redirect(url_for("manage_products"))
    try:
        cur.execute("UPDATE products SET product_name=%s WHERE id=%s", (new_name, p_id))
        conn.commit()
        flash("Cập nhật tên sản phẩm thành công!", "success")
    except Exception as e:
        flash(f"Lỗi: {str(e)}", "error")
    finally:
        cur.close()
        conn.close()
    return redirect(url_for("manage_products"))


@app.route("/delete-product/<int:p_id>", methods=["POST"])
@login_required
@admin_required
def delete_product(p_id):
    conn = db()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM products WHERE id = %s", (p_id,))
        conn.commit()
        flash("Đã xóa sản phẩm!", "success")
    except Exception as e:
        if "foreign key" in str(e).lower():
            flash("Không thể xóa: Sản phẩm này đã có dữ liệu bảo hành!", "error")
        else:
            flash(f"Lỗi: {str(e)}", "error")
    finally:
        cur.close()
        conn.close()
    return redirect(url_for("manage_products"))


@app.route("/manage-orders")
@login_required
@admin_required
def manage_orders():
    conn = db()
    cur = conn.cursor(dictionary=True)

    search = request.args.get("search", "").strip()
    per_page = request.args.get("per_page", 12, type=int)
    page = request.args.get("page", 1, type=int)

    where_clause = ""
    params = []

    if search:
        search_param = f"%{search}%"
        # 🔥 Cập nhật: Cho phép tìm kiếm bằng tên Người tạo (created_by)
        where_clause = "WHERE bill_code LIKE %s OR customer_name LIKE %s OR customer_phone LIKE %s OR customer_address LIKE %s OR created_by LIKE %s"
        params = [search_param, search_param, search_param, search_param, search_param]

    cur.execute(f"SELECT COUNT(*) as total FROM orders {where_clause}", tuple(params))
    total_records = cur.fetchone()["total"]

    total_pages = (total_records + per_page - 1) // per_page if total_records > 0 else 1

    if page > total_pages:
        page = total_pages
    if page < 1:
        page = 1

    start = (page - 1) * per_page

    sql = f"SELECT * FROM orders {where_clause} ORDER BY updated_at DESC, id DESC LIMIT %s OFFSET %s"
    params.extend([per_page, start])
    cur.execute(sql, tuple(params))
    bills_paginated = cur.fetchall()

    cur.close()
    conn.close()

    def get_pagination(current, total):
        if total <= 7:
            return list(range(1, total + 1))
        if current <= 4:
            return [1, 2, 3, 4, 5, "...", total]
        if current >= total - 3:
            return [1, "...", total - 4, total - 3, total - 2, total - 1, total]
        return [1, "...", current - 1, current, current + 1, "...", total]

    pagination_pages = get_pagination(page, total_pages)

    return render_template(
        "manage_orders.html",
        bills=bills_paginated,
        total_pages=total_pages,
        current_page=page,
        per_page=per_page,
        search=search,
        pagination_pages=pagination_pages,
        now=datetime.now(),
    )


@app.route("/edit_order/<int:bill_id>", methods=["POST"])
@login_required
def edit_order(bill_id):
    customer_name = request.form.get("customer_name")
    customer_phone = request.form.get("customer_phone")
    customer_address = request.form.get("customer_address", "")
    customer_address = customer_address.strip() if customer_address else ""
    created_at_raw = request.form.get("created_at")
    created_at = created_at_raw.replace("T", " ") if created_at_raw else None

    conn = db()
    cur = conn.cursor()
    try:
        sql = """
            UPDATE orders SET customer_name = %s, customer_phone = %s, 
                customer_address = %s, created_at = %s, updated_at = NOW() WHERE id = %s
        """
        cur.execute(
            sql, (customer_name, customer_phone, customer_address, created_at, bill_id)
        )
        conn.commit()
        flash("Cập nhật đơn hàng thành công!", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Lỗi cập nhật: {str(e)}", "error")
    finally:
        cur.close()
        conn.close()
    return redirect(request.referrer or url_for("admin"))


@app.route("/api/delete-multiple-bills", methods=["POST"])
@login_required
@admin_required
def delete_multiple_bills():
    """API hỗ trợ nút 'Xóa đã chọn' từ giao diện manage_orders.html"""
    data = request.get_json()
    ids = data.get("ids", [])

    if not ids:
        return (
            jsonify({"success": False, "message": "Không có đơn hàng nào được chọn."}),
            400,
        )

    try:
        conn = db()
        cur = conn.cursor()

        # Tạo chuỗi định dạng biến %s, %s... theo số lượng đơn cần xóa
        format_strings = ",".join(["%s"] * len(ids))

        # 1. Xóa các sản phẩm bảo hành nằm trong các Bill này trước
        cur.execute(
            f"DELETE FROM warranty_items WHERE bill_id IN ({format_strings})",
            tuple(ids),
        )

        # 2. Xóa các hóa đơn trong bảng orders
        cur.execute(f"DELETE FROM orders WHERE id IN ({format_strings})", tuple(ids))

        conn.commit()
        cur.close()
        conn.close()

        return jsonify(
            {"success": True, "message": f"Đã xóa thành công {len(ids)} đơn hàng."}
        )
    except Exception as e:
        return jsonify({"success": False, "message": f"Lỗi hệ thống: {str(e)}"}), 500


@app.route("/api/get-items/<string:bill_code>", methods=["GET"])
@login_required
def get_items_api(bill_code):
    try:
        conn = db()
        cur = conn.cursor(dictionary=True)
        sql = """
            SELECT wi.id, wi.uuid, p.product_name, wi.so_phieu, wi.product_id,
                   wi.warranty_months, wi.activated_at
            FROM warranty_items wi JOIN products p ON wi.product_id = p.id
            JOIN orders o ON wi.bill_id = o.id WHERE o.bill_code = %s ORDER BY wi.id DESC
        """
        cur.execute(sql, (bill_code,))
        items = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify({"success": True, "items": items})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/all-products", methods=["GET"])
@login_required
def get_all_products_api():
    try:
        conn = db()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id, product_name FROM products ORDER BY product_name ASC")
        products = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify({"success": True, "products": products})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/update-item", methods=["POST"])
@login_required
def update_item_api():
    try:
        data = request.json
        item_id = data.get("id")
        new_product_id = data.get("product_id")
        new_note = data.get("so_phieu")

        conn = db()
        cur = conn.cursor()
        if new_note and str(new_note).strip():
            check_sql = "SELECT id FROM warranty_items WHERE so_phieu = %s AND id != %s"
            cur.execute(check_sql, (new_note, item_id))
            if cur.fetchone():
                cur.close()
                conn.close()
                return jsonify(
                    {
                        "success": False,
                        "message": f'Số phiếu "{new_note}" đã tồn tại ở đơn hàng khác!',
                    }
                )

        sql = "UPDATE warranty_items SET product_id = %s, so_phieu = %s WHERE id = %s"
        cur.execute(sql, (new_product_id, new_note, item_id))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/delete-item", methods=["POST"])
@login_required
def delete_item_api():
    try:
        data = request.json
        item_id = data.get("id")
        conn = db()
        cur = conn.cursor()
        cur.execute("DELETE FROM warranty_items WHERE id = %s", (item_id,))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/manage-warranties")
@login_required
def manage_warranties():
    conn = db()
    cur = conn.cursor(dictionary=True)
    search_query = request.args.get("search", "").lower().strip()

    sql = """
        SELECT w.*, o.bill_code, p.product_name
        FROM warranty_items w JOIN orders o ON w.bill_id = o.id
        LEFT JOIN products p ON w.product_id = p.id ORDER BY w.activated_at DESC
    """
    cur.execute(sql)
    items = cur.fetchall()
    cur.close()
    conn.close()

    today = datetime.now().date()
    processed_items = []

    for item in items:
        item["warranty_expiry"] = "Chưa kích hoạt"
        item["activated_date_display"] = "---"
        item["is_expired"] = False

        if item["activated_at"] and item["warranty_months"] is not None:
            start_date = item["activated_at"]
            if isinstance(start_date, datetime):
                start_date = start_date.date()
            item["activated_date_display"] = start_date.strftime("%d/%m/%Y")
            expiry_date = start_date + relativedelta(
                months=int(item["warranty_months"])
            )
            item["warranty_expiry"] = expiry_date.strftime("%d/%m/%Y")
            if expiry_date < today:
                item["is_expired"] = True

        if search_query:
            bill_code = str(item.get("bill_code", "")).lower()
            product_name = str(item.get("product_name", "")).lower()
            if search_query not in bill_code and search_query not in product_name:
                continue

        processed_items.append(item)

    page = request.args.get("page", 1, type=int)
    per_page = 15
    total = len(processed_items)
    total_pages = (total + per_page - 1) // per_page
    start = (page - 1) * per_page
    end = start + per_page
    items_paginated = processed_items[start:end]

    return render_template(
        "manage_warranty_items.html",
        warranty_items=items_paginated,
        total_pages=total_pages,
        current_page=page,
        now=datetime.now(),
    )


@app.route("/api/activate-warranty/<string:uuid_code>", methods=["POST"])
def activate_warranty_api(uuid_code):
    try:
        conn = db()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT activated_at FROM warranty_items WHERE uuid = %s", (uuid_code,)
        )
        item = cur.fetchone()
        if not item:
            return jsonify({"success": False, "message": "Không tìm thấy mã!"}), 404
        if item["activated_at"]:
            return jsonify({"success": False, "message": "Đã kích hoạt rồi!"})

        cur.execute(
            "UPDATE warranty_items SET activated_at = %s WHERE uuid = %s",
            (datetime.now(), uuid_code),
        )
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/claim-warranty/<uuid_code>", methods=["POST"])
@login_required
def claim_warranty(uuid_code):
    if current_user.role != "admin":
        return jsonify({"success": False, "message": "Không có quyền!"})

    conn = db()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM warranty_items WHERE uuid = %s", (uuid_code,))
    item = cur.fetchone()

    if not item:
        conn.close()
        return jsonify({"success": False, "message": "Không tìm thấy sản phẩm"})

    now = datetime.now()
    current_count = item.get("warranty_count", 0) or 0
    new_count = current_count + 1

    # Cập nhật mảng lịch sử bảo hành
    history = []
    if item.get("claim_history"):
        try:
            history = json.loads(item["claim_history"])
        except:
            pass
    history.append(now.strftime("%Y-%m-%d %H:%M:%S"))
    new_history_str = json.dumps(history)

    # Kiểm tra xem sản phẩm ĐÃ ĐƯỢC KÍCH HOẠT CHO KHÁCH LẺ chưa
    is_activated = item.get("activated_at") is not None

    if not is_activated:
        # TRƯỜNG HỢP 1: Hàng lưu kho (Chưa kích hoạt)
        # -> Bấm bảo hành thì CHỈ tăng số lần và lưu lịch sử, KHÔNG gán ngày kích hoạt
        cur.execute(
            """UPDATE warranty_items 
               SET warranty_count = %s, 
                   claim_history = %s 
               WHERE uuid = %s""",
            (new_count, new_history_str, uuid_code),
        )
        msg = f"Thành công! Đã ghi nhận bảo hành Lần {new_count} (Hàng lưu kho, chưa kích hoạt khách lẻ)."
    else:
        # TRƯỜNG HỢP 2: Đã kích hoạt cho khách lẻ
        if current_count == 0:
            # Nếu là bảo hành Lần 1 -> Cập nhật lại activated_at để reset ngày hết hạn
            cur.execute(
                """UPDATE warranty_items 
                   SET activated_at = %s, 
                       warranty_count = %s, 
                       claim_history = %s 
                   WHERE uuid = %s""",
                (now, new_count, new_history_str, uuid_code),
            )
            msg = f"Thành công! Lần 1: Đã reset hạn bảo hành tính từ hôm nay."
        else:
            # Nếu là bảo hành Lần 2 trở đi -> KHÔNG đụng tới activated_at nữa
            cur.execute(
                """UPDATE warranty_items 
                   SET warranty_count = %s, 
                       claim_history = %s 
                   WHERE uuid = %s""",
                (new_count, new_history_str, uuid_code),
            )
            msg = f"Thành công! Đã tiếp nhận bảo hành Lần {new_count} (Giữ nguyên hạn bảo hành cũ)."

    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": msg})


if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True, port=5000)
