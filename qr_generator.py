import qrcode
from PIL import Image, ImageDraw, ImageFont
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "static", "qr")

# Thay IP/Domain thực tế của bạn vào đây
BASE_URL = "http://192.168.22.11:5000/warranty" 

# Đảm bảo thư mục tồn tại
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

def short_name(text: str, is_product=False) -> str:
    text = str(text).strip()
    
    # 1. SẢN PHẨM: Lấy mã ngắn (VD: "Máy khò Quick 2008" -> "2008")
    if is_product:
        if "-" in text: # Nếu có gạch ngang (SS-P3)
            parts = text.split("-")
            if len(parts) >= 2:
                text = parts[1].strip()
        
        # Lấy cụm từ cuối cùng
        parts = text.split()
        if parts:
            return parts[-1]
        return text

    # 2. KHÁCH HÀNG: Lấy FULL TÊN (Bỏ phần SĐT nếu có)
    else:
        # Nếu nhập dạng "Nguyễn Văn A - 098xxx" -> Lấy "Nguyễn Văn A"
        if "-" in text:
            return text.split("-")[0].strip().title()
        return text.title()

def generate_qr(uuid, bill_code, customer, product):
    # 1. Tạo QR Code
    qr_url = f"{BASE_URL}/{uuid}"
    qr = qrcode.QRCode(version=4, box_size=10, border=2)
    qr.add_data(qr_url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    # 2. Tạo khung ảnh (Canvas)
    W, H = 500, 520 # Tăng chiều cao lên chút để thoải mái chữ
    canvas = Image.new("RGB", (W, H), "white")
    
    # Dán QR vào giữa, dịch lên trên một chút
    qr_size = 380
    qr_img = qr_img.resize((qr_size, qr_size))
    canvas.paste(qr_img, ((W - qr_size) // 2, 10))

    draw = ImageDraw.Draw(canvas)
    
    # 3. Xử lý Font chữ (Dự phòng trường hợp không có Arial)
    try:
        # Thử load font Arial đậm cho tên, Arial thường cho mã
        font_main = ImageFont.truetype("arialbd.ttf", 32)
        font_sub = ImageFont.truetype("arial.ttf", 24)
    except IOError:
        try:
            # Nếu không có arialbd, thử arial thường
            font_main = ImageFont.truetype("arial.ttf", 32)
            font_sub = ImageFont.truetype("arial.ttf", 24)
        except IOError:
            # Nếu không có cả 2, dùng default (sẽ rất xấu và nhỏ)
            font_main = ImageFont.load_default()
            font_sub = ImageFont.load_default()

    # 4. Xử lý nội dung Text
    s_customer = short_name(customer, is_product=False) # Full tên
    s_product = short_name(product, is_product=True)    # Tên ngắn SP
    
    # Dòng 1: Tên Khách | Tên SP (VD: Nguyễn Văn A | P3)
    label_text = f"{s_customer} | {s_product}"
    
    # Dòng 2: Mã Shopee (VD: 260209XH...)
    bill_text = f"Mã: {bill_code}"

    # 5. Căn giữa và Vẽ Text
    # Hàm textbbox giúp đo độ rộng chữ chính xác
    bbox_main = draw.textbbox((0, 0), label_text, font=font_main)
    w_main = bbox_main[2] - bbox_main[0]
    
    bbox_sub = draw.textbbox((0, 0), bill_text, font=font_sub)
    w_sub = bbox_sub[2] - bbox_sub[0]

    # Vẽ dòng 1 (Tên)
    draw.text(((W - w_main) / 2, 400), label_text, font=font_main, fill="black")
    
    # Vẽ dòng 2 (Mã Bill)
    draw.text(((W - w_sub) / 2, 450), bill_text, font=font_sub, fill="#555")

    # 6. Lưu file
    file_path = os.path.join(OUTPUT_DIR, f"{uuid}.png")
    canvas.save(file_path)
    return file_path