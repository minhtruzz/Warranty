import mysql.connector
import uuid
import os
import string
import random
import threading
import pandas as pd
import math
import io
import json
import traceback
from flask import send_file
from flask import jsonify
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from qr_generator import generate_qr, generate_short_id
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
app.config["REMEMBER_COOKIE_DURATION"] = timedelta(days=30)
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
        self.id = str(id)
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
    cur.execute("SELECT * FROM users WHERE id = %s", (int(user_id),))
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
    cur.execute("""
        SELECT ma_bill, GROUP_CONCAT(DISTINCT product_id) as p_ids, COUNT(*) as total 
        FROM warranty_items 
        WHERE so_phieu IS NULL OR so_phieu = '' 
        GROUP BY ma_bill
    """)
    pending_groups = cur.fetchall()
    conn.close()
    return render_template("fix_pending.html", groups=pending_groups)


app.config["REMEMBER_COOKIE_DURATION"] = timedelta(days=30)


@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user_name = request.form.get("username")
        pw = request.form.get("password")

        # 2. Lấy giá trị checkbox "Ghi nhớ đăng nhập"
        remember_me = True if request.form.get("remember") else False

        conn = db()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT * FROM users WHERE username = %s", (user_name,))
        u = cur.fetchone()
        conn.close()

        if u and check_password_hash(u["password"], pw):
            user_obj = User(u["id"], u["username"], u["password"], u["role"])

            # 3. Truyền remember=True/False vào đây
            login_user(user_obj, remember=remember_me)

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
                        # ĐÃ SỬA: Bỏ comment để cập nhật updated_at cho khách cũ
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
                        "SELECT id, product_code FROM products WHERE product_name = %s LIMIT 1",
                        (current_name,),
                    )
                    res_prod = cur.fetchone()
                    if res_prod:
                        p_id = res_prod["id"]
                        p_code = res_prod["product_code"]
                    else:
                        p_code = f"SKU-{random.randint(1000, 9999)}"
                        cur.execute(
                            "INSERT INTO products (product_code, product_name) VALUES (%s, %s)",
                            (p_code, current_name),
                        )
                        p_id = cur.lastrowid

                    for _ in range(qty):
                        u_id = generate_short_id(7)
                        now = datetime.now()  # Lấy thời gian thực tại lúc tạo sản phẩm
                        cur.execute(
                            """INSERT INTO warranty_items 
                            (uuid, bill_id, ma_bill, product_id, warranty_months, activated_at, created_by, created_at, updated_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                            (
                                u_id,
                                bill_id,
                                shopee_code,
                                p_id,
                                war,
                                None,
                                current_user.username,
                                now,  # Ngày tạo sản phẩm (Không phụ thuộc vào bill_id)
                                now,  # Ngày cập nhật ban đầu
                            ),
                        )

                        # GỌI HÀM TẠO QR VỚI 5 THAM SỐ
                        try:
                            generate_qr(u_id, shopee_code, c_name, current_name, p_code)
                        except Exception as e:
                            print(f"Lỗi tạo QR: {str(e)}")

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

        where_clause = """WHERE customer_name LIKE %s 
                          OR bill_code LIKE %s 
                          OR customer_phone LIKE %s 
                          OR created_by LIKE %s 
                          OR id IN (SELECT bill_id FROM warranty_items WHERE ma_bill LIKE %s OR so_phieu LIKE %s)"""

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

    # ĐÃ SỬA: Đảm bảo ORDER BY updated_at DESC để khách mới/cập nhật luôn hiện lên đầu
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

    # 1. Lấy thông tin đơn hàng
    cur.execute("SELECT * FROM orders WHERE id = %s", (bill_id,))
    order_info = cur.fetchone()

    if not order_info:
        conn.close()  # Nhớ đóng kết nối trước khi return
        return "Không tìm thấy khách hàng", 404

    # 2. Lấy danh sách sản phẩm (đã thêm wi.product_id và wi.created_by)
    cur.execute(
        """
        SELECT wi.uuid, wi.ma_bill, p.product_name, wi.warranty_months, wi.activated_at, 
               wi.so_phieu, wi.bill_id, wi.warranty_count, wi.claim_history, 
               wi.created_by, wi.product_id 
        FROM warranty_items wi 
        JOIN products p ON wi.product_id = p.id 
        WHERE wi.bill_id = %s 
        ORDER BY wi.id DESC
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
        return redirect(url_for("admin"))

    conn = db()
    cur = conn.cursor(dictionary=True)

    cur.execute("SELECT id FROM orders WHERE bill_code = %s", (query,))
    order = cur.fetchone()

    if order:
        conn.close()
        return redirect(url_for("view_bill", bill_id=order["id"]))

    cur.execute("SELECT bill_id FROM warranty_items WHERE ma_bill = %s", (query,))
    item = cur.fetchone()
    conn.close()

    if item:
        return redirect(url_for("view_bill", bill_id=item["bill_id"]))

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
        ORDER BY wi.ma_bill, p.product_name
    """,
        (bill_id,),
    )
    qrs = cur.fetchall()
    conn.close()
    return render_template("print_qr.html", qrs=qrs, now=datetime.now())


@app.route("/print_selected")
@login_required
def print_selected_items():

    uuids_raw = request.args.get("uuids", "")
    if not uuids_raw:
        return "Vui lòng chọn sản phẩm", 400

    uuid_list = uuids_raw.split(",")

    conn = db()
    cur = conn.cursor(dictionary=True)

    placeholders = ",".join(["%s"] * len(uuid_list))

    cur.execute(
        f"""
        SELECT wi.uuid, wi.ma_bill, p.product_name 
        FROM warranty_items wi JOIN products p ON wi.product_id = p.id
        WHERE wi.uuid IN ({placeholders})
        ORDER BY wi.ma_bill, p.product_name
    """,
        tuple(uuid_list),
    )
    qrs = cur.fetchall()
    conn.close()

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

    # Truy vấn (giữ nguyên cấu trúc của bạn)
    cur.execute(
        """
    SELECT wi.*, o.created_at as bill_date, o.updated_at as update_date, 
           o.customer_name, p.product_name, p.info_warranty, o.customer_phone 
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

    # --- SỬA LỖI TẠI ĐÂY ---
    # Lấy wi.created_at làm gốc, nếu wi.created_at bị NULL thì dùng o.created_at (bill_date) làm dự phòng
    sale_date_origin = item.get("created_at") or item.get("bill_date") or datetime.now()

    # 1. Ngày xuất bán hiển thị
    update_date_str = sale_date_origin.strftime("%d/%m/%Y")

    # 2. Mốc tính hạn bảo hành
    base_date_for_calc = sale_date_origin

    claim_history_list = []
    warranty_count = item.get("warranty_count", 0) or 0

    if item.get("claim_history"):
        try:
            history_arr = json.loads(item["claim_history"])
            for idx, hist_item in enumerate(history_arr):
                ngay_str = ""
                dt_obj = None
                if isinstance(hist_item, str):
                    try:
                        dt_obj = datetime.strptime(hist_item, "%Y-%m-%d %H:%M:%S")
                        ngay_str = dt_obj.strftime("%d/%m/%Y %H:%M")
                    except:
                        ngay_str = hist_item

                # Reset mốc tính nếu có lần 1
                if idx == 0 and dt_obj:
                    base_date_for_calc = dt_obj

                claim_history_list.append({"lan": idx + 1, "ngay": ngay_str})
        except Exception as e:
            print(f"Lỗi đọc lịch sử: {e}")

    # 4. Tính toán (Sẽ không còn lỗi TypeError vì base_date_for_calc đã có giá trị dự phòng)
    warranty_months = item.get("warranty_months") or 0
    if warranty_months < 0:
        end_date = base_date_for_calc + relativedelta(days=abs(warranty_months))
    else:
        end_date = base_date_for_calc + relativedelta(months=warranty_months)

    end_date_str = end_date.strftime("%d/%m/%Y")
    remaining_days = (end_date.date() - datetime.now().date()).days

    # Các thông tin khác
    activated_date_str = (
        item["activated_at"].strftime("%d/%m/%Y")
        if item.get("activated_at")
        else "Chưa kích hoạt"
    )

    return render_template(
        "warranty.html",
        product=item,
        update_date_str=update_date_str,
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

        # Chuyển tên cột thành chữ hoa và xóa khoảng trắng để so khớp
        df.columns = [str(c).strip().upper() for c in df.columns]

        if "MA_KH" not in df.columns:
            return jsonify({"success": False, "message": "File Excel thiếu cột MA_KH"})

        # Lấy danh sách mã vận đơn hợp lệ
        excel_bill_codes = [
            str(code).strip().upper()
            for code in df["MA_KH"].unique()
            if str(code).strip().upper() not in ["NAN", "", "NONE"]
        ]

        # Bước 1: Trả về số lượng để xác nhận
        if not is_confirmed:
            return jsonify(
                {
                    "success": True,
                    "require_confirm": True,
                    "count": len(excel_bill_codes),
                }
            )

        # Bước 2: Thực hiện Insert/Update khi đã confirm
        conn = db()
        cur = conn.cursor()
        updated_count = 0
        inserted_count = 0

        # ĐÃ SỬA: Dùng datetime.now() một lần để đồng bộ
        now = datetime.now()

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

                # Kiểm tra tồn tại
                cur.execute(
                    "SELECT count(*) FROM orders WHERE bill_code = %s", (bill_code,)
                )
                exists = cur.fetchone()[0] > 0

                if exists:
                    # ĐÃ SỬA: Cập nhật updated_at = NOW() để đẩy lên đầu danh sách
                    cur.execute(
                        "UPDATE orders SET customer_name = %s, customer_phone = %s, customer_address = %s, updated_at = %s WHERE bill_code = %s",
                        (ten_kh, sdt, dia_chi, now, bill_code),
                    )
                    updated_count += 1
                else:
                    # ĐÃ SỬA: Thêm updated_at = NOW()
                    cur.execute(
                        "INSERT INTO orders (bill_code, customer_name, customer_phone, customer_address, created_at, updated_at, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (bill_code, ten_kh, sdt, dia_chi, now, now, current_user.username),
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

    new_code = request.form.get("product_code")
    new_name = request.form.get("product_name")
    new_info = request.form.get("info_warranty")

    if not new_name:
        flash("Tên sản phẩm không được để trống", "error")
        return redirect(url_for("manage_products"))

    if not new_code:
        flash("Mã sản phẩm (SKU) không được để trống", "error")
        return redirect(url_for("manage_products"))

    try:
        cur.execute(
            "UPDATE products SET product_name=%s, product_code=%s, info_warranty=%s WHERE id=%s",
            (new_name, new_code, new_info, p_id),
        )
        conn.commit()
        flash("Cập nhật sản phẩm thành công!", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Lỗi hệ thống: {str(e)}", "error")
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

    # ĐÃ SỬA: ORDER BY updated_at DESC để hiển thị mới nhất lên đầu
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
        # ĐÃ SỬA: Thêm updated_at = NOW() để đẩy lên đầu danh sách
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

        format_strings = ",".join(["%s"] * len(ids))

        cur.execute(
            f"DELETE FROM warranty_items WHERE bill_id IN ({format_strings})",
            tuple(ids),
        )

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
            SELECT 
                wi.id, 
                wi.uuid, 
                p.product_name, 
                wi.so_phieu, 
                wi.product_id,
                wi.warranty_months, 
                wi.activated_at,
                wi.created_by
            FROM warranty_items wi 
            JOIN products p ON wi.product_id = p.id
            JOIN orders o ON wi.bill_id = o.id 
            WHERE o.bill_code = %s 
            ORDER BY wi.id DESC
        """
        cur.execute(sql, (bill_code,))
        raw_items = cur.fetchall()

        items = []
        for i in raw_items:
            items.append(
                {
                    "id": i["id"],
                    "uuid": i["uuid"],
                    "product_id": i["product_id"],
                    "product_name": i["product_name"],
                    "so_phieu": i["so_phieu"] or "",
                    "warranty_months": i["warranty_months"],
                    "created_by": i["created_by"] or "Admin",
                    "activated_at": (
                        i["activated_at"].strftime("%d/%m/%Y %H:%M")
                        if i["activated_at"]
                        else "Chưa kích hoạt"
                    ),
                }
            )

        cur.close()
        conn.close()
        return jsonify({"success": True, "items": items})
    except Exception as e:
        if "cur" in locals():
            cur.close()
        if "conn" in locals():
            conn.close()
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
def update_item():
    try:
        data = request.json

        item_id = data.get("id") or data.get("item_id")

        if not item_id:
            return jsonify(
                {
                    "success": False,
                    "message": "Lỗi: Không nhận diện được ID của đơn hàng cần sửa từ Frontend!",
                }
            )

        product_id = data.get("product_id")
        so_phieu = data.get("so_phieu")
        created_by = data.get("created_by")

        try:
            warranty_months = int(data.get("warranty_months", 0))
        except ValueError:
            return jsonify(
                {
                    "success": False,
                    "message": "Lỗi: Thời gian bảo hành phải là định dạng số!",
                }
            )

        conn = db()
        cur = conn.cursor()

        # ĐÃ SỬA: Chỉ cấm trùng số phiếu với item KHÁC BILL
        if so_phieu and str(so_phieu).strip():
            so_phieu_clean = str(so_phieu).strip()
            
            cur.execute("SELECT bill_id FROM warranty_items WHERE id = %s", (item_id,))
            current_item = cur.fetchone()
            
            if current_item:
                current_bill_id = current_item[0]
                
                cur.execute(
                    """
                    SELECT id, bill_id FROM warranty_items 
                    WHERE so_phieu = %s 
                    AND id != %s
                    AND bill_id != %s
                    LIMIT 1
                    """,
                    (so_phieu_clean, item_id, current_bill_id),
                )
                
                existing_item = cur.fetchone()
                if existing_item:
                    return jsonify(
                        {
                            "success": False,
                            "message": f"Lỗi: Số phiếu '{so_phieu_clean}' đã tồn tại ở một đơn hàng khác (Item ID: {existing_item[0]}, Bill ID: {existing_item[1]}). Vui lòng kiểm tra lại!",
                        }
                    )

        cur.execute(
            """
            UPDATE warranty_items 
            SET product_id = %s, so_phieu = %s, created_by = %s, warranty_months = %s 
            WHERE id = %s
        """,
            (product_id, so_phieu_clean, created_by, warranty_months, item_id),
        )

        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": True, "message": "Cập nhật thành công!"})

    except Exception as e:
        if "conn" in locals() and conn:
            conn.rollback()
        return jsonify({"success": False, "message": f"Lỗi hệ thống: {str(e)}"})


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

    history = []
    if item.get("claim_history"):
        try:
            history = json.loads(item["claim_history"])
        except:
            pass
    history.append(now.strftime("%Y-%m-%d %H:%M:%S"))
    new_history_str = json.dumps(history)

    is_activated = item.get("activated_at") is not None

    if not is_activated:

        cur.execute(
            """UPDATE warranty_items 
               SET warranty_count = %s, 
                   claim_history = %s 
               WHERE uuid = %s""",
            (new_count, new_history_str, uuid_code),
        )
        msg = f"Thành công! Đã ghi nhận bảo hành Lần {new_count} (Hàng lưu kho, chưa kích hoạt khách lẻ)."
    else:

        if current_count == 0:

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


@app.route("/api/delete-multiple-products", methods=["POST"])
@login_required
def delete_multiple_products():
    try:
        data = request.get_json()
        product_ids = data.get("ids", [])

        if not product_ids:
            return (
                jsonify(
                    {"success": False, "message": "Không có sản phẩm nào được chọn."}
                ),
                400,
            )

        conn = db()
        cur = conn.cursor()

        format_strings = ",".join(["%s"] * len(product_ids))
        query = f"DELETE FROM products WHERE id IN ({format_strings})"

        cur.execute(query, tuple(product_ids))
        conn.commit()

        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "message": f"Đã xóa {len(product_ids)} sản phẩm thành công.",
            }
        )

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/export_products_excel")
@login_required
def export_products_excel():
    try:
        conn = db()
        query = "SELECT product_code, product_name, info_warranty FROM products"
        df = pd.read_sql(query, conn)
        conn.close()

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Products")
        output.seek(0)

        return send_file(
            output,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=f"Mau_Import_SanPham_{datetime.now().strftime('%Y%m%d')}.xlsx",
        )
    except Exception as e:
        flash(f"Lỗi xuất file: {str(e)}", "danger")
        return redirect(url_for("manage_products"))


@app.route("/import_products_excel", methods=["POST"])
@login_required
def import_products_excel():
    if "file" not in request.files:
        flash("Không tìm thấy file nào được tải lên.", "error")
        return redirect(url_for("manage_products"))

    file = request.files["file"]
    if file.filename == "":
        flash("Chưa chọn file", "error")
        return redirect(url_for("manage_products"))

    try:
        if file.filename.endswith(".csv"):
            df = pd.read_csv(file, encoding="utf-8-sig", on_bad_lines="skip")
        else:
            df = pd.read_excel(file)

        df.columns = [str(c).strip().upper() for c in df.columns]

        conn = db()
        cur = conn.cursor()

        count_insert = 0
        count_update = 0

        for index, row in df.iterrows():
            product_code = ""
            if "MA_SP" in df.columns:
                product_code = str(row["MA_SP"]).strip()
            elif "PRODUCT_CODE" in df.columns:
                product_code = str(row["PRODUCT_CODE"]).strip()
            else:
                product_code = str(row.iloc[0]).strip() if len(df.columns) > 0 else ""

            product_name = ""
            if "TEN_SP" in df.columns:
                product_name = str(row["TEN_SP"]).strip()
            elif "PRODUCT_NAME" in df.columns:
                product_name = str(row["PRODUCT_NAME"]).strip()
            else:
                product_name = str(row.iloc[1]).strip() if len(df.columns) > 1 else ""

            info_warranty = ""
            if "NOI_DUNG" in df.columns:
                info_warranty = str(row["NOI_DUNG"]).strip()
            elif "INFO_WARRANTY" in df.columns:
                info_warranty = str(row["INFO_WARRANTY"]).strip()
            else:
                info_warranty = str(row.iloc[2]).strip() if len(df.columns) > 2 else ""

            if product_code.lower() == "nan":
                product_code = ""
            if product_name.lower() == "nan":
                product_name = ""
            if info_warranty.lower() == "nan":
                info_warranty = ""

            if product_code:
                cur.execute(
                    "SELECT id, product_name, info_warranty FROM products WHERE product_code = %s",
                    (product_code,),
                )
                exists = cur.fetchone()

                if not exists:
                    final_name = product_name if product_name else "Chưa có tên"
                    cur.execute(
                        "INSERT INTO products (product_code, product_name, info_warranty) VALUES (%s, %s, %s)",
                        (product_code, final_name, info_warranty),
                    )
                    count_insert += 1
                else:
                    final_name = product_name if product_name else exists[1]
                    final_info = info_warranty if info_warranty else exists[2]

                    cur.execute(
                        "UPDATE products SET product_name = %s, info_warranty = %s WHERE product_code = %s",
                        (final_name, final_info, product_code),
                    )
                    count_update += 1

        conn.commit()
        conn.close()

        flash(
            f"Import thành công: Thêm mới {count_insert} mã - Cập nhật lại {count_update} mã!",
            "success",
        )

    except Exception as e:
        print(f"Lỗi import Excel: {e}")
        flash(
            "Lỗi khi đọc file. Hãy chắc chắn file có Cột 1 (Mã), Cột 2 (Tên), Cột 3 (Nội dung).",
            "error",
        )

    return redirect(url_for("manage_products"))


@app.route("/san-pham-bao-hanh")
@login_required
def manage_product_warranties():
    """Route hiển thị giao diện danh sách sản phẩm"""
    conn = db()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM products ORDER BY product_name ASC")
    products = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template("product_warranty.html", products=products)


@app.route("/api/khach-hang-bao-hanh/<int:product_id>")
@login_required
def api_khach_hang_bao_hanh(product_id):
    try:
        """API lấy danh sách khách hàng theo ID sản phẩm (Có phân trang & Tìm kiếm)"""
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 12, type=int)
        search_query = request.args.get("search", "").strip()

        offset = (page - 1) * per_page

        conn = db()
        cursor = conn.cursor(dictionary=True)

        base_query = """
            FROM warranty_items wi
            LEFT JOIN orders o ON wi.bill_id = o.id
            WHERE wi.product_id = %s
        """
        params = [product_id]

        if search_query:
            search_term = f"%{search_query}%"
            base_query += " AND (wi.ma_bill LIKE %s OR wi.so_phieu LIKE %s OR o.bill_code LIKE %s)"
            params.extend([search_term, search_term, search_term])

        cursor.execute(f"SELECT COUNT(*) as total {base_query}", tuple(params))
        total_items = cursor.fetchone()["total"]

        query = f"""
            SELECT wi.ma_bill, wi.so_phieu, wi.activated_at, wi.warranty_count, o.customer_name 
            {base_query}
            ORDER BY wi.id DESC
            LIMIT {per_page} OFFSET {offset}
        """
        cursor.execute(query, tuple(params))
        warranties = cursor.fetchall()

        cursor.close()
        conn.close()

        import math

        total_pages = math.ceil(total_items / per_page) if total_items > 0 else 1

        items = []
        for item in warranties:
            ngay_kh = (
                item.get("activated_at").strftime("%d/%m/%Y")
                if item.get("activated_at")
                else ""
            )

            so_lan_bh = item.get("warranty_count") or 0

            if so_lan_bh > 0:
                trang_thai = f"Đã BH ({so_lan_bh} lần)"
            elif item.get("activated_at"):
                trang_thai = "Đã Kích Hoạt"
            else:
                trang_thai = "Chưa kích hoạt"

            items.append(
                {
                    "ma_don": item.get("ma_bill") or "",
                    "so_phieu": item.get("so_phieu") or "",
                    "ten_khach": item.get("customer_name") or "Khách lẻ",
                    "ngay_kich_hoat": ngay_kh,
                    "trang_thai": trang_thai,
                }
            )
        return jsonify(
            {
                "items": items,
                "total_pages": total_pages,
                "current_page": page,
                "total_items": total_items,
            }
        )

    except Exception as e:
        print(f"LỖI API KHÁCH HÀNG BẢO HÀNH: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/all-users")
@login_required
def get_all_users():
    try:
        conn = db()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT username FROM users ORDER BY username ASC")
        users = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify({"success": True, "users": users})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


def background_generate_qr_task(qr_tasks):
    for task in qr_tasks:
        try:
            generate_qr(
                task["u_id"],
                task["ma_bill"],
                task["c_name"],
                task["ten_sp"],
                task["p_code"],
            )
        except Exception as e:
            print(f"Lỗi tạo QR ngầm: {str(e)}")


@app.route("/quick-import-excel", methods=["POST"])
@login_required
def quick_import_excel():
    try:
        file = request.files.get("file")
        is_confirmed = request.form.get("confirm") == "true"
        if not file:
            return jsonify({"success": False, "message": "Chưa chọn file!"})

        file.seek(0)
        df = (
            pd.read_csv(file) if file.filename.endswith(".csv") else pd.read_excel(file)
        )
        df.columns = [str(c).strip().upper() for c in df.columns]

        col_sl = next(
            (c for c in ["SL", "SO_LUONG", "SOLUONG", "SỐ LƯỢNG"] if c in df.columns),
            None,
        )
        col_ten_kh = next(
            (c for c in ["TEN_KH", "TEN_KHACH_HANG", "NGƯỜI NHẬN"] if c in df.columns),
            None,
        )
        col_sdt = next(
            (
                c
                for c in ["DIEN_THOAI", "SDT", "PHONE", "SỐ ĐIỆN THOẠI"]
                if c in df.columns
            ),
            None,
        )
        col_bh = next(
            (
                c
                for c in ["WARRANTY_MONTHS", "BAO_HANH", "THANG_BH", "THÁNG BẢO HÀNH"]
                if c in df.columns
            ),
            None,
        )
        col_ten_sp = next(
            (c for c in ["TEN_SP", "PRODUCT_NAME", "TÊN SẢN PHẨM"] if c in df.columns),
            "TEN_SP",
        )

        data_list = []
        for _, row in df.iterrows():
            sdt = str(row.get(col_sdt, "")).strip().replace(".0", "")
            if sdt and len(sdt) == 9 and not sdt.startswith("0"):
                sdt = "0" + sdt

            raw_bh = str(row.get(col_bh, "0")).strip().lower()
            val_bh = 0
            if raw_bh not in ["không bảo hành", "none", "nan", "", "0"]:
                is_negative = "-" in raw_bh
                digits = "".join([c for c in raw_bh if c.isdigit()])
                try:
                    num = int(digits)
                    if is_negative:
                        num = -num

                    if "ngày" in raw_bh or "ngay" in raw_bh:
                        val_bh = -abs(num)
                    else:
                        val_bh = num
                except:
                    val_bh = 0

            data_list.append(
                {
                    "ten_kh": str(row.get(col_ten_kh, "Khách Lẻ")).strip(),
                    "sdt": sdt,
                    "ten_sp": str(row.get(col_ten_sp, "Sản phẩm Import")).strip(),
                    "so_luong": int(float(row.get(col_sl, 1))) if col_sl else 1,
                    "warranty_months": val_bh,
                }
            )

        if not is_confirmed:
            return jsonify(
                {"success": True, "require_confirm": True, "preview_data": data_list}
            )

        conn = db()
        cur = conn.cursor(dictionary=True)
        qr_tasks = []
        now = datetime.now()

        customer_bills = {}

        try:
            with db_lock:
                for item in data_list:
                    c_name_final = item["ten_kh"].title()

                    cust_key = (c_name_final, item["sdt"])

                    if cust_key not in customer_bills:
                        customer_bills[cust_key] = (
                            f"{now.strftime('%y%m%d')}{''.join(random.choices(string.ascii_uppercase + string.digits, k=6))}"
                        )

                    current_ma_bill = customer_bills[cust_key]

                    bill_id = None
                    if item["sdt"]:
                        cur.execute(
                            "SELECT id, customer_name FROM orders WHERE customer_phone = %s LIMIT 1",
                            (item["sdt"],),
                        )
                        existing = cur.fetchone()
                        if existing:
                            bill_id = existing["id"]
                            c_name_final = existing["customer_name"]
                            # ĐÃ SỬA: Cập nhật updated_at cho khách cũ
                            cur.execute(
                                "UPDATE orders SET updated_at = %s WHERE id = %s",
                                (now, bill_id),
                            )

                    if not bill_id:
                        cur.execute(
                            """INSERT INTO orders (bill_code, customer_name, customer_phone, created_at, updated_at, created_by) 
                                       VALUES ('TEMP', %s, %s, %s, %s, %s)""",
                            (
                                c_name_final,
                                item["sdt"],
                                now,
                                now,
                                current_user.username,
                            ),
                        )
                        bill_id = cur.lastrowid
                        cur.execute(
                            "UPDATE orders SET bill_code = %s WHERE id = %s",
                            (f"TT-{str(bill_id).zfill(6)}", bill_id),
                        )

                    # 2. KIỂM TRA SKU SẢN PHẨM (Tên SP)
                    cur.execute(
                        "SELECT id, product_code FROM products WHERE product_name = %s LIMIT 1",
                        (item["ten_sp"],),
                    )
                    res_prod = cur.fetchone()
                    if res_prod:
                        p_id, p_code = res_prod["id"], res_prod["product_code"]
                    else:
                        p_code = f"SKU-{random.randint(1000, 9999)}"
                        cur.execute(
                            "INSERT INTO products (product_code, product_name) VALUES (%s, %s)",
                            (p_code, item["ten_sp"]),
                        )
                        p_id = cur.lastrowid

                    # 3. TẠO SẢN PHẨM BẢO HÀNH
                    for _ in range(item["so_luong"]):
                        u_id = generate_short_id(7)
                        cur.execute(
                            """INSERT INTO warranty_items (uuid, bill_id, product_id, warranty_months, ma_bill, activated_at, created_at, updated_at, created_by)
                                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                            (
                                u_id,
                                bill_id,
                                p_id,
                                item["warranty_months"],
                                current_ma_bill,
                                None,
                                now,
                                now,
                                current_user.username,
                            ),
                        )

                        qr_tasks.append(
                            {
                                "u_id": u_id,
                                "ma_bill": current_ma_bill,
                                "c_name": c_name_final,
                                "ten_sp": item["ten_sp"],
                                "p_code": p_code,
                            }
                        )

            conn.commit()
            if qr_tasks:
                threading.Thread(
                    target=background_generate_qr_task, args=(qr_tasks,), daemon=True
                ).start()

            all_generated_bills = ", ".join(list(customer_bills.values()))
            return jsonify(
                {
                    "success": True,
                    "message": f"Import thành công. Các mã đơn tạo ra: {all_generated_bills}",
                }
            )
        except Exception as e:
            conn.rollback()
            return jsonify({"success": False, "message": f"Lỗi Database: {str(e)}"})
        finally:
            cur.close()
            conn.close()
    except Exception as e:
        return jsonify({"success": False, "message": f"Lỗi hệ thống: {str(e)}"})


@app.route("/api/get-missing-receipts", methods=["GET"])
@login_required
def get_missing_receipts():
    try:
        conn = db()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT wi.id, wi.ma_bill, p.product_name as ten_sp 
            FROM warranty_items wi
            JOIN products p ON wi.product_id = p.id
            WHERE wi.so_phieu IS NULL OR wi.so_phieu = ''
            ORDER BY wi.id DESC
        """)
        items = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify({"success": True, "items": items})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route("/api/save-receipts", methods=["POST"])
@login_required
def save_receipts():
    try:
        data = request.json
        updates = data.get("updates", [])

        if not updates:
            return jsonify({"success": False, "message": "Không có dữ liệu gửi lên"})

        conn = db()
        cur = conn.cursor(dictionary=True)

        submitted_phieu = list(
            set(
                [item["so_phieu"] for item in updates if item["so_phieu"].strip() != ""]
            )
        )

        if submitted_phieu:
            format_strings = ",".join(["%s"] * len(submitted_phieu))
            cur.execute(
                f"SELECT so_phieu, ma_bill FROM warranty_items WHERE so_phieu IN ({format_strings})",
                tuple(submitted_phieu),
            )
            existing_phieu = cur.fetchall()

            if existing_phieu:
                trung_lap_details = []
                for row in existing_phieu:
                    sp = row["so_phieu"] if isinstance(row, dict) else row[0]
                    mb = row["ma_bill"] if isinstance(row, dict) else row[1]
                    trung_lap_details.append(f"{sp} (đang nằm ở đơn {mb})")

                cur.close()
                conn.close()
                return jsonify(
                    {
                        "success": False,
                        "message": f"Bị trùng lặp! Các số phiếu sau đã tồn tại: {', '.join(trung_lap_details)}",
                    }
                )

        for item in updates:
            item_id = item["id"]
            so_phieu = item["so_phieu"]
            cur.execute(
                "UPDATE warranty_items SET so_phieu = %s WHERE id = %s",
                (so_phieu, item_id),
            )

        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        if "conn" in locals() and conn:
            conn.rollback()
        return jsonify({"success": False, "message": str(e)})


if __name__ == "__main__":
    app.run(host="192.168.153.1", debug=True, port=5000)