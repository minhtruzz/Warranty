import qrcode
from PIL import Image, ImageDraw, ImageFont
import os
import random
import string

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "static", "qr")
FONT_PATH = os.path.join(BASE_DIR, "Roboto-Bold.ttf")
BASE_URL = "https://192.168.153.1/warranty"

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)


def generate_short_id(length=7):
    characters = string.ascii_letters + string.digits
    return "".join(random.choice(characters) for i in range(length))


def wrap_text(text, font, draw, max_width, max_lines=3):
    """Giữ nguyên hàm wrap_text cũ của bạn"""
    lines = []
    words = text.split()
    current_line = ""
    for word in words:
        test_line = f"{current_line} {word}".strip()
        bbox = draw.textbbox((0, 0), test_line, font=font)
        w = bbox[2] - bbox[0]
        if w <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last_line = lines[-1]
        while len(last_line) > 0:
            bbox = draw.textbbox((0, 0), last_line + "...", font=font)
            if bbox[2] - bbox[0] <= max_width:
                break
            last_line = last_line[:-1]
        lines[-1] = last_line + "..."
    return lines


def generate_qr(short_uuid, bill_code, customer, product, product_code=""):
    """Cấu trúc cũ, thêm tham số product_code để nhận SKU"""
    qr_url = f"{BASE_URL}/{short_uuid}"
    DPI = 600
    CM_TO_INCH = 2.54
    W = int((2.5 / CM_TO_INCH) * DPI)  # ~590px
    H = int((1.3 / CM_TO_INCH) * DPI)  # ~307px

    qr = qrcode.QRCode(
        version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, border=1
    )
    qr.add_data(qr_url)
    qr.make(fit=True)

    # Tính toán size QR (Ép size để không bị tràn khung H)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    qr_display_size = int(H * 0.82)  # QR chiếm 82% chiều cao
    qr_img = qr_img.resize((qr_display_size, qr_display_size), Image.Resampling.LANCZOS)

    canvas = Image.new("RGB", (W, H), "white")
    qr_y_offset = (H - qr_display_size) // 2
    qr_x_offset = 15
    canvas.paste(qr_img, (qr_x_offset, qr_y_offset))

    draw = ImageDraw.Draw(canvas)
    try:
        font_main = ImageFont.truetype(FONT_PATH, 35)  # Tên SP
        font_sub = ImageFont.truetype(FONT_PATH, 28)  # SKU và Mã Đơn
    except IOError:
        font_main = font_sub = ImageFont.load_default()

    # Thiết lập nội dung theo yêu cầu mới
    sku_text = f"SKU: {product_code}"
    product_text = str(product).strip()
    bill_text = f"Mã: {bill_code}"

    text_start_x = qr_x_offset + qr_display_size + 15
    max_text_width = W - text_start_x - 10

    lines_info = []

    # 1. Xử lý SKU (Dùng cấu trúc lặp ký tự của bạn)
    curr_sku = ""
    for char in sku_text:
        bbox = draw.textbbox((0, 0), curr_sku + char, font=font_sub)
        if (bbox[2] - bbox[0]) <= max_text_width:
            curr_sku += char
        else:
            break
    lines_info.append({"text": curr_sku, "font": font_sub, "h": 32})

    # 2. Xử lý Tên sản phẩm (Dùng wrap_text cũ)
    lines_main = wrap_text(product_text, font_main, draw, max_text_width, max_lines=2)
    for line in lines_main:
        bbox = draw.textbbox((0, 0), line, font=font_main)
        lines_info.append({"text": line, "font": font_main, "h": 40})

    # 3. Xử lý Mã đơn (Dùng cấu trúc lặp ký tự của bạn)
    curr_bill = ""
    for char in bill_text:
        bbox = draw.textbbox((0, 0), curr_bill + char, font=font_sub)
        if (bbox[2] - bbox[0]) <= max_text_width:
            curr_bill += char
        else:
            break
    lines_info.append({"text": curr_bill, "font": font_sub, "h": 32})

    # Tính toán vị trí Y để căn giữa cụm chữ
    line_spacing = 6
    total_h = sum([item["h"] for item in lines_info]) + (
        line_spacing * (len(lines_info) - 1)
    )
    current_y = (H - total_h) // 2

    for item in lines_info:
        draw.text(
            (text_start_x, current_y), item["text"], font=item["font"], fill="black"
        )
        current_y += item["h"] + line_spacing

    file_path = os.path.join(OUTPUT_DIR, f"{short_uuid}.png")
    canvas.save(file_path, dpi=(DPI, DPI))
    return file_path
