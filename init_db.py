from app import app, db, Account
from werkzeug.security import generate_password_hash

# Chạy trong ngữ cảnh ứng dụng Flask
with app.app_context():
    # 1. Tạo lại bảng nếu chưa có (cho chắc chắn)
    db.create_all()

    # 2. Kiểm tra xem user 'admin' đã có chưa
    admin_user = Account.query.filter_by(username='admin').first()

    if not admin_user:
        # Nếu chưa có -> Tạo mới
        print("⚠️ Chưa có Admin. Đang tạo mới...")
        new_admin = Account(
            username='admin',
            password=generate_password_hash('123456'), # Mật khẩu là 123456
            role='admin'
        )
        db.session.add(new_admin)
        print("✅ Đã TẠO tài khoản Admin thành công!")
    else:
        # Nếu có rồi -> Reset mật khẩu
        print("⚠️ Tài khoản Admin đã tồn tại. Đang đặt lại mật khẩu...")
        admin_user.password = generate_password_hash('123456')
        admin_user.role = 'admin' # Đảm bảo quyền là admin
        print("✅ Đã RESET mật khẩu Admin về: 123456")

    # 3. Lưu vào DB
    db.session.commit()
    print("------------------------------------------")
    print("👉 Bạn hãy đăng nhập bằng:")
    print("   User: admin")
    print("   Pass: 123456")