from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
import mysql.connector
import uuid
import os
import string
import random
import threading
import pandas as pd
import math
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from qr_generator import generate_qr
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask import request, redirect, url_for, session

app = Flask(__name__)
app.secret_key = 'mintruzz.dev_pro_code'
app.config['REMEMBER_COOKIE_DURATION'] = timedelta(days=7)
app.config['SESSION_PROTECTION'] = 'strong'

# --- Cấu hình MySQL ---
def db():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="", 
        database="warranty"
    )


db_lock = threading.Lock()

# --- User Class & Loader ---
class User(UserMixin):
    def __init__(self, id, username, password, role):
        self.id = id
        self.username = username
        self.password = password
        self.role = str(role).strip() if role else 'user'

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    conn = db()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    u = cur.fetchone()
    conn.close()
    if u:
        return User(u['id'], u['username'], u['password'], u['role'])
    return None

# --- Decorators ---
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            flash("Bạn không có quyền thực hiện hành động này!", "error")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def generate_auto_bill_code():
    prefix = datetime.now().strftime('%d%m')
    suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
    return f"{prefix}{suffix}"

# --- ROUTES ---
@app.before_request
def check_pending_after_view():
    # Các trang luôn được phép vào
    allowed = ['admin','static', 'login', 'logout', 'update_so_phieu', 'fix_pending_page', 'view_bill','delete_bill','delete_item','check_should_fix', 'get_pending_groups']
    if request.endpoint in allowed or not request.endpoint:
        return

    # Chỉ kiểm tra nếu người dùng đã từng vào xem bill (watching_bill = True)
    if session.get('watching_bill'):
        conn = db()
        cur = conn.cursor(dictionary=True)
        # Kiểm tra xem còn SP nào chưa có số phiếu không
        cur.execute("SELECT id FROM warranty_items WHERE so_phieu IS NULL OR so_phieu = '' LIMIT 1")
        pending = cur.fetchone()
        conn.close()

        if pending:
            flash("⚠️ Bạn chưa hoàn tất nhập Số Phiếu cho đợt hàng vừa xem!")
            # return redirect(url_for('fix_pending_page'))
        else:
            # Nếu đã nhập đủ rồi thì tắt cái đánh dấu này đi để họ đi lại tự do
            session.pop('watching_bill', None)

@app.route("/fix-pending")
@login_required
def fix_pending_page():
    conn = db()
    cur = conn.cursor(dictionary=True)
    # Lấy danh sách các ma_bill còn thiếu số phiếu và thông tin khách hàng/sản phẩm
    cur.execute("""
        SELECT ma_bill, GROUP_CONCAT(DISTINCT product_id) as p_ids, COUNT(*) as total 
        FROM warranty_items 
        WHERE so_phieu IS NULL OR so_phieu = '' 
        GROUP BY ma_bill
    """)
    pending_groups = cur.fetchall()
    conn.close()
    return render_template("fix_pending.html", groups=pending_groups)


@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user_name = request.form['username']
        pw = request.form['password']
        
        conn = db()
        cur = conn.cursor(dictionary=True)
        # Database vẫn tìm kiếm không phân biệt hoa thường (để đảm bảo user có tồn tại)
        cur.execute("SELECT * FROM users WHERE username = %s", (user_name,))
        u = cur.fetchone()
        conn.close()

        # SỬA Ở ĐÂY: Thêm điều kiện u['username'] == user_name
        # Python so sánh chuỗi có phân biệt hoa thường (strict)
        if u and u['username'] == user_name and check_password_hash(u['password'], pw):
            user_obj = User(u['id'], u['username'], u['password'], u['role']) 
            login_user(user_obj)
            return redirect(url_for('admin'))
            
        flash("Sai tài khoản hoặc mật khẩu!")
    return render_template("login.html", now=datetime.now())
########################################
@app.route('/api/get-customer-info', methods=['GET'])
def get_customer_info():
    phone = request.args.get('phone', '').strip()
    
    if not phone or len(phone) < 3:
        return jsonify({'found': False})

    try:
        conn = db()
        cur = conn.cursor(dictionary=True)
        
        # LOGIC MỚI: Dùng LIKE để tìm. 
        # Ví dụ nhập 090... nó sẽ tìm các số chứa 90... (bỏ qua số 0 đầu nếu DB bị mất)
        # %s%% nghĩa là tìm chuỗi bắt đầu bằng...
        
        search_term = phone
        # Nếu số bắt đầu bằng 0, thử tạo một biến tìm kiếm bỏ số 0 đi
        if phone.startswith('0'):
            search_term_no_zero = phone[1:] # Lấy từ ký tự thứ 2 trở đi
        else:
            search_term_no_zero = phone

        # Câu lệnh SQL tìm cả 2 trường hợp: Chính xác hoặc Chứa phần đuôi
        sql = """
            SELECT customer_name 
            FROM orders 
            WHERE customer_phone = %s 
               OR customer_phone = %s
               OR customer_phone LIKE %s
            ORDER BY id DESC 
            LIMIT 1
        """
        
        # Tham số: 1.Số gốc, 2.Số bỏ số 0, 3.Tìm đuôi (thêm % phía trước)
        cur.execute(sql, (phone, search_term_no_zero, f"%{search_term_no_zero}"))
        
        result = cur.fetchone()
        cur.close()
        conn.close()

        if result:
            return jsonify({
                'found': True, 
                'name': result['customer_name']
            })
        else:
            return jsonify({'found': False})
            
    except Exception as e:
        print(f"Error API: {e}")
        return jsonify({'found': False})
# --- HÀM ADMIN CHÍNH ---
@app.route("/admin", methods=["GET", "POST"])
@login_required
def admin():
    conn = db()
    cur = conn.cursor(dictionary=True)
    
    # ---------------------------------------------------------
    # PHẦN 1: XỬ LÝ POST (TẠO/CẬP NHẬT ĐƠN)
    # ---------------------------------------------------------
    if request.method == "POST":
        try:
            with db_lock:
                # 1. Lấy dữ liệu từ Form
                c_name = request.form.get("customer_name", "").strip().title()
                c_phone = request.form.get("customer_phone", "").strip()
                
                p_names = request.form.getlist('product_names[]')
                p_quants = request.form.getlist('quantities[]')
                p_war = request.form.getlist('warranty_months[]')
                
                if not p_names:
                    flash("❌ Lỗi: Chưa nhập sản phẩm!")
                    return redirect(url_for('admin'))

                # 2. KIỂM TRA KHÁCH HÀNG CŨ (Dựa trên SĐT)
                bill_id = None
                customer_code_tt = None
                is_new_customer = False

                if c_phone:
                    # Tìm xem ông này đã có trong danh sách orders chưa
                    cur.execute("SELECT id, bill_code, customer_name FROM orders WHERE customer_phone = %s LIMIT 1", (c_phone,))
                    existing_customer = cur.fetchone()
                    
                    if existing_customer:
                        # === KHÁCH CŨ: Dùng lại ID và Mã TT cũ ===
                        bill_id = existing_customer['id']
                        customer_code_tt = existing_customer['bill_code']
                        # Nếu tên mới nhập khác tên cũ thì có thể update lại tên (tuỳ chọn)
                        if not c_name: c_name = existing_customer['customer_name']
                        
                        # Cập nhật thời gian để khách nhảy lên đầu
                        cur.execute("UPDATE orders SET updated_at = %s WHERE id = %s", (datetime.now(), bill_id))
                    else:
                        is_new_customer = True
                else:
                    is_new_customer = True # Không có SĐT coi như khách mới (hoặc khách lẻ)

                # 3. NẾU LÀ KHÁCH MỚI -> TẠO DÒNG MỚI TRONG ORDERS
                if is_new_customer:
                    if not c_name: c_name = "Khách Lẻ"
                    
                    # Insert tạm để lấy ID
                    cur.execute("""
                        INSERT INTO orders (bill_code, customer_name, customer_phone, created_at, updated_at) 
                        VALUES ('TEMP', %s, %s, %s, %s)
                    """, (c_name, c_phone, datetime.now(), datetime.now()))
                    bill_id = cur.lastrowid
                    
                    # Update lại Mã KH chuẩn (TT-xxxxxx) theo ID vừa tạo
                    customer_code_tt = f"TT-{str(bill_id).zfill(6)}"
                    cur.execute("UPDATE orders SET bill_code = %s WHERE id = %s", (customer_code_tt, bill_id))

                # 4. TẠO MÃ SHOPEE (Cho lần mua hàng này)
                date_prefix = datetime.now().strftime("%y%m%d") 
                chars = string.ascii_uppercase + string.digits
                shopee_code = f"{date_prefix}{''.join(random.choices(chars, k=6))}"

                # 5. LƯU SẢN PHẨM VÀO BẢNG WARRANTY_ITEMS
                for i in range(len(p_names)):
                    current_name = p_names[i]
                    try:
                        qty = int(p_quants[i]) if p_quants[i] else 1
                        war = int(p_war[i]) if p_war[i] else 0
                    except: qty=1; war=0

                    # Kiểm tra/Tạo Product ID
                    cur.execute("SELECT id FROM products WHERE product_name = %s LIMIT 1", (current_name,))
                    res_prod = cur.fetchone()
                    if res_prod:
                        p_id = res_prod['id']
                    else:
                        p_code = f"PROD-{random.randint(1000, 9999)}"
                        cur.execute("INSERT INTO products (product_code, product_name) VALUES (%s, %s)", (p_code, current_name))
                        p_id = cur.lastrowid

                    # Insert từng cái bảo hành
                    for _ in range(qty):
                        u_id = str(uuid.uuid4())
                        
                        # A. LƯU VÀO DB
                        cur.execute("""
                            INSERT INTO warranty_items (uuid, bill_id, ma_bill, product_id, warranty_months, activated_at)
                            VALUES (%s, %s, %s, %s, %s, %s)
                        """, (u_id, bill_id, shopee_code, p_id, war, datetime.now()))

                        # B. TẠO FILE ẢNH QR (PHẦN MỚI THÊM)
                        # ---------------------------------------------------
                        try:
                            # Gọi hàm tạo ảnh từ file qr_generator.py
                            generate_qr(u_id, shopee_code, c_name, current_name)
                        except Exception as e:
                            print(f"Lỗi tạo QR Code: {str(e)}")
                        # ---------------------------------------------------
            
            conn.commit()
            
            if is_new_customer:
                flash(f"✅ Đã tạo Khách Hàng mới: {c_name} ({customer_code_tt})")
            else:
                flash(f"✅ Đã thêm đơn mới vào Khách Hàng cũ: {c_name} ({customer_code_tt})")
        
        except Exception as e:
            conn.rollback()
            if "Duplicate entry" in str(e) and "bill_code" in str(e):
                 flash("❌ Lỗi trùng mã Khách Hàng! Vui lòng kiểm tra lại database.")
            else:
                 flash(f"❌ Lỗi hệ thống: {str(e)}")
        finally:
            cur.close()
            conn.close()
        return redirect(url_for('admin'))

    # ---------------------------------------------------------
    # PHẦN 2: HIỂN THỊ DANH SÁCH (Chỉ hiện thông tin KH)
    # ---------------------------------------------------------
    page = request.args.get('page', 1, type=int)
    per_page = 12
    search = request.args.get("search", "").strip()

    where_clause = ""
    params = []

    if search:
        search_param = f"%{search}%"
        where_clause = "WHERE customer_name LIKE %s OR bill_code LIKE %s OR customer_phone LIKE %s"
        params = [search_param, search_param, search_param]

    # Phân trang
    cur.execute(f"SELECT COUNT(*) as total FROM orders {where_clause}", tuple(params))
    total_records = cur.fetchone()['total']
    total_pages = math.ceil(total_records / per_page) if total_records > 0 else 1
    offset = (page - 1) * per_page
    
    # Lấy danh sách khách hàng
    cur.execute(f"SELECT * FROM orders {where_clause} ORDER BY updated_at DESC, id DESC LIMIT {per_page} OFFSET {offset}", tuple(params))
    bills = cur.fetchall()

    # Lấy list tên sản phẩm để gợi ý nhập liệu
    cur.execute("SELECT DISTINCT product_name FROM products ORDER BY product_name ASC")
    all_products = cur.fetchall()
    
    cur.close()
    conn.close()

    return render_template("admin.html", bills=bills, all_products=all_products, 
                           search=search, current_user=current_user, now=datetime.now(),
                           current_page=page, total_pages=total_pages, per_page=per_page)

@app.route("/bill/<int:bill_id>")
@login_required
def view_bill(bill_id):
    session['watching_bill'] = True
    conn = db()
    cur = conn.cursor(dictionary=True)
    
    # --- SỬA Ở ĐÂY: Phải SELECT * để lấy cả bill_code (TT-xxx), sđt, địa chỉ... ---
    cur.execute("SELECT * FROM orders WHERE id = %s", (bill_id,))
    order_info = cur.fetchone()
    
    if not order_info: 
        return "Không tìm thấy khách hàng", 404

    # Lấy danh sách sản phẩm
    cur.execute("""
        SELECT wi.uuid, wi.ma_bill, p.product_name, wi.warranty_months, 
               wi.activated_at, wi.so_phieu, wi.bill_id
        FROM warranty_items wi
        JOIN products p ON wi.product_id = p.id
        WHERE wi.bill_id = %s
        ORDER BY wi.activated_at DESC
    """, (bill_id,))
    
    items = cur.fetchall()
    conn.close()

    missing_items = [i for i in items if not i['so_phieu'] or i['so_phieu'] == '']
    
    missing_groups = []
    if missing_items:
        # Gom nhóm lại để hợp với code HTML của bạn
        # Ở đây 1 bill chỉ có 1 mã bill nên ta tạo 1 group duy nhất
        missing_groups.append({
            'ma_bill': items[0]['ma_bill'] if items else 'UNKNOWN',
            'total': len(missing_items)
        })
    return render_template("view_bill.html", 
                           items=items, 
                           customer_name=order_info['customer_name'], 
                           customer_phone=order_info['customer_phone'],
                           order=order_info,
                           timedelta = timedelta,
                           groups=missing_groups,
                           now=datetime.now())

@app.route("/update-so-phieu", methods=["POST"])
@login_required
def update_so_phieu():
    data = request.get_json()
    items = data.get('items', [])
    
    if not items:
        return jsonify({"success": False, "message": "Không có dữ liệu để cập nhật"}), 400
        
    try:
        conn = db()
        cur = conn.cursor(dictionary=True)
        target_bill_id = None
        duplicates = [] # Danh sách lưu các số phiếu bị trùng

        for item in items:
            ma_bill = item.get('ma_bill', "").strip().upper()
            val = item.get('so_phieu', "").strip().upper()
            
            if not ma_bill or not val:
                continue

            # --- BẮT ĐẦU KIỂM TRA TRÙNG ---
            # Kiểm tra xem số phiếu (val) này đã được dùng cho ma_bill khác chưa
            query_check = """
                SELECT ma_bill 
                FROM warranty_items 
                WHERE UPPER(TRIM(so_phieu)) = %s 
                AND UPPER(TRIM(ma_bill)) != %s 
                LIMIT 1
            """
            cur.execute(query_check, (val, ma_bill))
            existing_record = cur.fetchone()

            if existing_record:
                # Nếu tìm thấy, lưu lại để báo lỗi và không UPDATE dòng này
                duplicates.append(f"Số phiếu '{val}' đã tồn tại ở đợt hàng {existing_record['ma_bill']}")
                continue 
            # --- KẾT THÚC KIỂM TRA TRÙNG ---

            # Nếu không trùng thì tiến hành cập nhật
            cur.execute("UPDATE warranty_items SET so_phieu = %s WHERE UPPER(TRIM(ma_bill)) = %s", (val, ma_bill))
            
            if not target_bill_id:
                cur.execute("SELECT bill_id FROM warranty_items WHERE UPPER(TRIM(ma_bill)) = %s LIMIT 1", (ma_bill,))
                res = cur.fetchone()
                if res: target_bill_id = res['bill_id']

        conn.commit()

        # Nếu có lỗi trùng nhưng vẫn có những dòng khác cập nhật thành công
        if duplicates:
            msg = "Cập nhật một phần. Lỗi: " + ", ".join(duplicates)
            return jsonify({"success": False, "message": msg})

        # Giải phóng session nếu đã hết phiếu trống
        cur.execute("SELECT id FROM warranty_items WHERE so_phieu IS NULL OR so_phieu = '' LIMIT 1")
        if not cur.fetchone():
            session.pop('watching_bill', None)

        cur.close()
        conn.close()

        redirect_to = url_for('view_bill', bill_id=target_bill_id) if target_bill_id else url_for('admin')
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
    return redirect(url_for('admin'))

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

# @app.route("/register", methods=["GET", "POST"])
# def register():
#     if request.method == "POST":
#         user = request.form['username']
#         password = request.form['password']
#         confirm_password = request.form['confirm_password']
#         if password != confirm_password:
#             flash("Mật khẩu nhập lại không khớp!", "danger")
#             return render_template("register.html", now=datetime.now())
#         pw_hash = generate_password_hash(password)
#         conn = db()
#         cur = conn.cursor()
#         try:
#             cur.execute("INSERT INTO users (username, password, role) VALUES (%s, %s, %s)", (user, pw_hash, 'user'))
#             conn.commit()
#             flash("Đăng ký thành công!", "success")
#             return redirect(url_for('login'))
#         except:
#             conn.rollback()
#             flash("Tên đăng nhập đã tồn tại!")
#         finally:
#             cur.close()
#             conn.close()
#     return render_template("register.html", now=datetime.now())

@app.route("/logout")
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route("/print/<int:bill_id>")
@login_required
def print_qr(bill_id):
    conn = db()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT wi.uuid, wi.ma_bill, p.product_name 
        FROM warranty_items wi 
        JOIN products p ON wi.product_id = p.id
        WHERE wi.bill_id=%s
    """, (bill_id,))
    qrs = cur.fetchall()
    conn.close()
    return render_template("print_qr.html", qrs=qrs, now=datetime.now())
@app.route("/single_qr/<string:uuid>")
@login_required
def print_single_qr(uuid):
    conn = db()
    cur = conn.cursor(dictionary=True)
    
    # Chỉ select ĐÚNG 1 cái sản phẩm dựa theo uuid
    cur.execute("""
        SELECT wi.uuid, wi.ma_bill, p.product_name 
        FROM warranty_items wi 
        JOIN products p ON wi.product_id = p.id
        WHERE wi.uuid = %s
    """, (uuid,))
    
    one_item = cur.fetchone()
    conn.close()

    if one_item:
        # Quan trọng: Phải để trong list [] vì file html của bạn đang dùng vòng lặp (for qr in qrs)
        return render_template("print_qr.html", qrs=[one_item], now=datetime.now())
    else:
        return "Không tìm thấy sản phẩm này", 404
@app.route("/warranty/<uuid_code>")
def warranty(uuid_code):
    conn = db()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT wi.*, o.customer_name, p.product_name, p.info_warranty
        FROM warranty_items wi
        JOIN orders o ON wi.bill_id=o.id
        JOIN products p ON wi.product_id=p.id
        WHERE wi.uuid=%s
    """, (uuid_code,))
    item = cur.fetchone()
    conn.close()
    if not item: return "QR không hợp lệ", 404

    activated_at = item["activated_at"]
    end_date = activated_at + relativedelta(months=item["warranty_months"])
    remaining_days = (end_date.date() - datetime.now().date()).days

    return render_template("warranty.html", product=item, 
                           activated_date_str=activated_at.strftime("%d/%m/%Y"), 
                           end_date_str=end_date.strftime("%d/%m/%Y"), 
                           remaining_days=remaining_days, now=datetime.now())

@app.route("/check-should-fix")
@login_required
def check_should_fix():
    # Kiểm tra điều kiện: Phải là sau khi xem bill (session có watching_bill)
    if session.get('watching_bill'):
        conn = db()
        cur = conn.cursor(dictionary=True)
        # Kiểm tra xem thực tế còn bản ghi nào trống số phiếu không
        cur.execute("SELECT id FROM warranty_items WHERE so_phieu IS NULL OR so_phieu = '' LIMIT 1")
        pending = cur.fetchone()
        conn.close()
        
        if pending:
            return jsonify({"should_open": True})
        else:
            # Nếu đã sạch bóng số phiếu trống, xóa session để không làm phiền nữa
            session.pop('watching_bill', None)
            
    return jsonify({"should_open": False})

@app.route("/import-excel", methods=["POST"])
@login_required
def import_excel():
    try:
        file = request.files.get('file')
        is_confirmed = request.form.get('confirm') == 'true'

        if not file:
            return jsonify({"success": False, "message": "Chưa chọn file!"})

        # Đọc file Excel
        # Lưu ý: Cần cài đặt thư viện: pip install openpyxl xlrd
        if file.filename.endswith('.csv'):
            df = pd.read_csv(file)
        else:
            df = pd.read_excel(file)

        # Chuẩn hóa tên cột thành chữ in hoa
        df.columns = [str(c).strip().upper() for c in df.columns]

        # Kiểm tra cột bắt buộc
        if 'MA_KH' not in df.columns:
            return jsonify({"success": False, "message": "File Excel thiếu cột MA_KH"})

        # Lấy danh sách mã từ Excel
        excel_bill_codes = [
            str(code).strip().upper() 
            for code in df['MA_KH'].unique() 
            if str(code).strip().upper() not in ['NAN', '', 'NONE']
        ]

        # ---------------------------------------------------------
        # BƯỚC 1: BÁO SỐ LƯỢNG TÌM THẤY (ĐỂ HIỆN POPUP)
        # ---------------------------------------------------------
        if not is_confirmed:
            return jsonify({
                "success": True, 
                "require_confirm": True, 
                "count": len(excel_bill_codes) # Báo tổng số mã tìm thấy trong file
            })

        # ---------------------------------------------------------
        # BƯỚC 2: XỬ LÝ DỮ LIỆU (UPDATE HOẶC INSERT)
        # ---------------------------------------------------------
        conn = db()
        cur = conn.cursor()
        
        updated_count = 0
        inserted_count = 0
        
        print("--- BẮT ĐẦU XỬ LÝ ---")

        for _, row in df.iterrows():
            bill_code = str(row.get('MA_KH', '')).strip().upper()
            
            if bill_code in excel_bill_codes:
                # Lấy dữ liệu
                ten_kh = str(row.get('TEN_KH', '')).strip()
                if ten_kh.lower() == 'nan': ten_kh = ''

                sdt = str(row.get('DIEN_THOAI', '')).strip()
                if sdt.lower() == 'nan': sdt = '' 

                dia_chi = str(row.get('DIA_CHI', '')).strip()
                if dia_chi.lower() == 'nan': dia_chi = ''
                
                # --- KIỂM TRA MÃ ĐÃ TỒN TẠI CHƯA ---
                cur.execute("SELECT count(*) FROM orders WHERE bill_code = %s", (bill_code,))
                exists = cur.fetchone()[0] > 0

                if exists:
                    # --- NẾU CÓ RỒI THÌ UPDATE ---
                    sql_update = """
                        UPDATE orders 
                        SET customer_name = %s, 
                            customer_phone = %s, 
                            customer_address = %s 
                        WHERE bill_code = %s
                    """
                    cur.execute(sql_update, (ten_kh, sdt, dia_chi, bill_code))
                    updated_count += 1
                    print(f"-> Update mã: {bill_code}")
                else:
                    # --- NẾU CHƯA CÓ THÌ INSERT (THÊM MỚI) ---
                    # Lưu ý: Các cột khác sẽ để mặc định hoặc NULL
                    sql_insert = """
                        INSERT INTO orders (bill_code, customer_name, customer_phone, customer_address, created_at)
                        VALUES (%s, %s, %s, %s, NOW())
                    """
                    cur.execute(sql_insert, (bill_code, ten_kh, sdt, dia_chi))
                    inserted_count += 1
                    print(f"-> Thêm mới mã: {bill_code}")

        conn.commit()
        cur.close()
        conn.close()

        msg = f"Xong! Đã cập nhật {updated_count} đơn cũ và thêm mới {inserted_count} đơn."
        print(msg)

        return jsonify({
            "success": True, 
            "require_confirm": False, 
            "message": msg
        })

    except Exception as e:
        print(f"Lỗi: {e}")
        return jsonify({"success": False, "message": f"Lỗi: {str(e)}"})
# ------------------------------------------
# 👤 QUẢN LÝ TÀI KHOẢN (CUSTOMERS/USERS)
# ------------------------------------------

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
    return render_template("customers.html", customers=all_customers,now=datetime.now())

# --- THÊM TÀI KHOẢN (Chỉ xử lý POST từ Modal) ---
@app.route("/add-user", methods=["POST"])
@login_required
@admin_required 
def add_user():
    username = request.form.get('username')
    password = request.form.get('password')
    role = request.form.get('role', 'user') # Mặc định là user nếu không chọn

    if not username or not password:
        flash("Vui lòng điền đầy đủ thông tin!", "error")
        return redirect(url_for('manage_customers'))

    conn = db()
    cur = conn.cursor()
    try:
        # Kiểm tra trùng tên
        cur.execute("SELECT id FROM users WHERE username = %s", (username,))
        if cur.fetchone():
            flash("Tên đăng nhập đã tồn tại, vui lòng chọn tên khác!", "error")
        else:
            hashed_pw = generate_password_hash(password)
            cur.execute("INSERT INTO users (username, password, role) VALUES (%s, %s, %s)", 
                        (username, hashed_pw, role))
            conn.commit()
            flash("Thêm tài khoản mới thành công!", "success")
    except Exception as e:
        flash(f"Lỗi hệ thống: {str(e)}", "error")
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('manage_customers'))

# --- XÓA TÀI KHOẢN ---
@app.route("/delete-user/<int:user_id>", methods=["POST"]) 
@login_required
@admin_required
def delete_user(user_id):
    # Ngăn không cho tự xóa chính mình
    if user_id == current_user.id:
        flash("Bạn không thể tự xóa tài khoản đang đăng nhập!", "error")
        return redirect(url_for('manage_customers'))

    try:
        conn = db()
        cur = conn.cursor()
        cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()
        flash("Đã xóa tài khoản thành công!", "success")
    except Exception as e:
        if "foreign key" in str(e).lower():
            flash("Không thể xóa: Tài khoản này đang chứa dữ liệu đơn hàng/bảo hành!", "error")
        else:
            flash(f"Lỗi khi xóa: {str(e)}", "error")
    finally:
        if 'cur' in locals(): cur.close()
        if 'conn' in locals(): conn.close()
    
    return redirect(url_for('manage_customers'))

# --- SỬA TÀI KHOẢN (Chỉ xử lý POST từ Modal) ---
@app.route("/edit-user/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def edit_user(user_id):
    new_username = request.form.get('username')
    new_password = request.form.get('password')
    new_role = request.form.get('role')

    conn = db()
    cur = conn.cursor()
    
    try:
        # Nếu có nhập mật khẩu mới -> Update cả pass
        if new_password and new_password.strip() != "":
            hashed_pw = generate_password_hash(new_password)
            cur.execute("UPDATE users SET username=%s, password=%s, role=%s WHERE id=%s", 
                        (new_username, hashed_pw, new_role, user_id))
        else:
            # Nếu không nhập pass -> Giữ nguyên pass cũ
            cur.execute("UPDATE users SET username=%s, role=%s WHERE id=%s", 
                        (new_username, new_role, user_id))
        
        conn.commit()
        flash("Cập nhật thông tin thành công!", "success")
            
    except Exception as e:
        flash(f"Lỗi (có thể trùng tên đăng nhập): {str(e)}", "error")
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('manage_customers'))
# ========= quản lý =======
# ==========================================
# 📦 QUẢN LÝ SẢN PHẨM (PRODUCTS) - CHỈ QUẢN LÝ TÊN
# ==========================================

# 1. Danh sách sản phẩm
@app.route("/manage-products")
@login_required
@admin_required
def manage_products():
    conn = db()
    cur = conn.cursor(dictionary=True)
    # CHỈ LẤY ID VÀ TÊN (Không lấy price, stock nữa)
    cur.execute("SELECT * FROM products ORDER BY id DESC")
    products = cur.fetchall()
    cur.close()
    conn.close()
    return render_template("manage_products.html", products=products,now=datetime.now())

# 2. Thêm sản phẩm mới
@app.route("/add-product", methods=["POST"])
@login_required
@admin_required
def add_product():
    if request.method == "POST":
        p_name = request.form.get('product_name')
        # Bỏ qua price và stock

        conn = db()
        cur = conn.cursor()
        try:
            # Nếu DB bạn có cột product_code thì thêm, không thì bỏ dòng product_code đi
            p_code = f"PROD-{random.randint(1000,9999)}"
            
            # Câu lệnh INSERT ngắn gọn lại
            cur.execute("INSERT INTO products (product_code, product_name) VALUES (%s, %s)", 
                        (p_code, p_name))
            conn.commit()
            flash("Đã thêm sản phẩm mới thành công!", "success")
        except Exception as e:
            flash(f"Lỗi khi thêm sản phẩm: {str(e)}", "error")
        finally:
            cur.close()
            conn.close()
        
        return redirect(url_for('manage_products'))

# 3. Sửa sản phẩm
@app.route("/edit-product/<int:p_id>", methods=["POST"]) # Chỉ cần POST
@login_required
@admin_required
def edit_product(p_id):
    conn = db()
    cur = conn.cursor()
    
    # Lấy tên mới từ form modal
    new_name = request.form.get('product_name')
    
    if not new_name:
        flash("Tên sản phẩm không được để trống", "error")
        return redirect(url_for('manage_products'))

    try:
        cur.execute("UPDATE products SET product_name=%s WHERE id=%s", (new_name, p_id))
        conn.commit()
        flash("Cập nhật tên sản phẩm thành công!", "success")
    except Exception as e:
        flash(f"Lỗi: {str(e)}", "error")
    finally:
        cur.close()
        conn.close()
        
    return redirect(url_for('manage_products'))

# 4. Xóa sản phẩm
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
    return redirect(url_for('manage_products'))


# ==========================================
# 📄 QUẢN LÝ ĐƠN HÀNG (ORDERS)
# ==========================================

# 1. Danh sách đơn hàng
@app.route("/manage-orders")
@login_required
@admin_required
def manage_orders():
    conn = db()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM orders ORDER BY created_at DESC")
    bills = cur.fetchall()
    cur.close()
    conn.close()
    page = request.args.get('page', 1, type=int) # Lấy trang hiện tại
    per_page = 10                                # Số đơn hàng trên 1 trang (tùy chỉnh)
    
    total = len(bills)                           # Tổng số đơn
    total_pages = (total + per_page - 1) // per_page # Tính tổng số trang
    
    # Cắt danh sách bills để chỉ hiện thị theo trang
    start = (page - 1) * per_page
    end = start + per_page
    bills_paginated = bills[start:end] 
    # -------------------------------------------

    # SỬA DÒNG RETURN DƯỚI CÙNG THÀNH:
    return render_template("manage_orders.html", 
                           bills=bills_paginated, # Đổi bills thành bills_paginated
                           total_pages=total_pages, # Truyền biến này qua
                           current_page=page,       # Truyền biến này qua
                           now=datetime.now())

# 2. Sửa thông tin đơn hàng (Chỉ xử lý POST từ Modal)
# --- Code xử lý SỬA ĐƠN HÀNG (Khớp với Modal HTML) ---
@app.route('/edit_order/<int:bill_id>', methods=['POST'])
def edit_order(bill_id):
    # 1. Lấy dữ liệu từ cái Modal gửi lên
    # (name="customer_name", name="customer_phone", name="customer_address")
    customer_name = request.form.get('customer_name')
    customer_phone = request.form.get('customer_phone')
    customer_address = request.form.get('customer_address') 

    conn = db()
    cur = conn.cursor()

    try:
        # 2. Câu lệnh SQL update bảng bills
        # Lưu ý: Bảng của bạn tên là 'bills' (theo ảnh Adminer cũ)
        sql = """
            UPDATE orders 
            SET customer_name = %s, 
                customer_phone = %s, 
                customer_address = %s 
            WHERE id = %s
        """
        val = (customer_name, customer_phone, customer_address, bill_id)
        
        cur.execute(sql, val)
        conn.commit()
        
        flash('Cập nhật đơn hàng thành công!', 'success')

    except Exception as e:
        conn.rollback()
        flash(f'Lỗi cập nhật: {str(e)}', 'error')
        print(f"Lỗi SQL: {e}") # In ra terminal để dễ debug nếu lỗi

    finally:
        cur.close()
        conn.close()

    # 3. Quay lại trang danh sách đơn hàng (admin dashboard)
    return redirect(request.referrer or url_for('admin'))

#=============bảo hành===============
@app.route("/manage-warranties")
@login_required 
def manage_warranties():
    conn = db()
    cur = conn.cursor(dictionary=True)
    
    # 1. Lấy từ khóa tìm kiếm từ URL (nếu có)
    search_query = request.args.get('search', '').lower().strip()

    # Lấy dữ liệu từ database
    sql = """
        SELECT w.*, o.bill_code, p.product_name
        FROM warranty_items w
        JOIN orders o ON w.bill_id = o.id
        LEFT JOIN products p ON w.product_id = p.id
        ORDER BY w.activated_at DESC
    """
    cur.execute(sql)
    items = cur.fetchall()
    
    # Đóng kết nối DB sớm vì đã lấy xong dữ liệu
    cur.close()
    conn.close()
    
    today = datetime.now().date()
    processed_items = []

    for item in items:
        # --- XỬ LÝ NGÀY THÁNG (Giữ nguyên code của bạn) ---
        item['warranty_expiry'] = "Chưa kích hoạt"
        item['activated_date_display'] = "---"
        item['is_expired'] = False

        if item['activated_at'] and item['warranty_months'] is not None:
            start_date = item['activated_at']
            if isinstance(start_date, datetime):
                start_date = start_date.date()
            
            item['activated_date_display'] = start_date.strftime("%d/%m/%Y")
            
            # Tính ngày hết hạn
            expiry_date = start_date + relativedelta(months=int(item['warranty_months']))
            item['warranty_expiry'] = expiry_date.strftime("%d/%m/%Y")
            
            if expiry_date < today:
                item['is_expired'] = True
            else:
                item['is_expired'] = False
        
        # --- XỬ LÝ TÌM KIẾM (MỚI THÊM) ---
        # Nếu có từ khóa tìm kiếm, kiểm tra xem có khớp Mã Bill hoặc Tên SP không
        if search_query:
            bill_code = str(item.get('bill_code', '')).lower()
            product_name = str(item.get('product_name', '')).lower()
            
            # Nếu không tìm thấy trong cả mã bill lẫn tên sp thì BỎ QUA (không thêm vào list)
            if search_query not in bill_code and search_query not in product_name:
                continue 
        
        # Nếu thỏa mãn điều kiện tìm kiếm (hoặc không tìm gì) thì thêm vào danh sách
        processed_items.append(item)


    # --- PHÂN TRANG (PAGINATION) ---
    page = request.args.get('page', 1, type=int)
    per_page = 15 # Số dòng mỗi trang
    
    total = len(processed_items) # Tổng số sau khi đã lọc tìm kiếm
    total_pages = (total + per_page - 1) // per_page
    
    start = (page - 1) * per_page
    end = start + per_page
    
    # Cắt danh sách theo trang
    items_paginated = processed_items[start:end]
    
    return render_template("manage_warranty_items.html", 
                           warranty_items=items_paginated,
                           total_pages=total_pages,
                           current_page=page,
                           now=datetime.now())


if __name__ == "__main__":
    app.run(host="192.168.22.11", debug=True, port=5000)