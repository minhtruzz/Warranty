import qrcode
from PIL import Image, ImageDraw, ImageFont
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "static", "qr")
FONT_PATH = os.path.join(BASE_DIR, "Roboto-Bold.ttf")
BASE_URL = "http://192.168.22.11:5000/warranty"

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)


def short_name(text: str, is_product=False) -> str:
    text = str(text).strip()
    if is_product:
        if "-" in text:
            parts = text.split("-")
            if len(parts) >= 2:
                text = parts[1].strip()
        parts = text.split()
        if parts:
            return parts[-1]
        return text
    else:
        # Lấy toàn bộ tên khách hàng
        if "-" in text:
            text = text.split("-")[0].strip()
        return text.title()


def wrap_text(text, font, draw, max_width, max_lines=3):
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

    # Xử lý cắt bớt nếu vượt quá số dòng cho phép và thêm "..."
    if len(lines) > max_lines:
        lines = lines[:max_lines]  # Lấy đúng số dòng tối đa
        last_line = lines[-1]

        # Cắt dần ký tự của dòng cuối cùng để nhét vừa dấu "..."
        while len(last_line) > 0:
            bbox = draw.textbbox((0, 0), last_line + "...", font=font)
            if bbox[2] - bbox[0] <= max_width:
                break
            last_line = last_line[:-1]

        lines[-1] = last_line + "..."

    return lines


def generate_qr(uuid, bill_code, customer, product):
    qr_url = f"{BASE_URL}/{uuid}"
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=1,
    )
    qr.add_data(qr_url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    DPI = 300
    CM_TO_INCH = 2.54
    W = int((1.5 / CM_TO_INCH) * DPI)  # Chiều ngang 15mm
    H = int((0.8 / CM_TO_INCH) * DPI)  # Chiều dọc 8mm

    canvas = Image.new("RGB", (W, H), "white")

    qr_size = H - 8  # Lề trên dưới 4px
    qr_img = qr_img.resize((qr_size, qr_size), Image.Resampling.NEAREST)
    canvas.paste(qr_img, (4, 4))  # Lề trái 4, trên 4

    draw = ImageDraw.Draw(canvas)

    try:
        font_main = ImageFont.truetype(FONT_PATH, 10)  # Size chữ chính
        font_sub = ImageFont.truetype(FONT_PATH, 8)  # Size chữ phụ (Mã)
    except IOError:
        font_main = ImageFont.load_default()
        font_sub = ImageFont.load_default()

    s_customer = short_name(customer, is_product=False)
    s_product = short_name(product, is_product=True)

    label_text = f"{s_customer} | {s_product}"
    bill_text = f"Mã:{bill_code}"

    text_start_x = 4 + qr_size + 4
    max_text_width = W - text_start_x - 4

    # ÉP SỐ DÒNG: Tên/Sản phẩm tối đa 2 dòng, Mã tối đa 1 dòng
    lines_main = wrap_text(label_text, font_main, draw, max_text_width, max_lines=2)
    lines_sub = wrap_text(bill_text, font_sub, draw, max_text_width, max_lines=1)

    all_lines = []
    for line in lines_main:
        bbox = draw.textbbox((0, 0), line, font=font_main)
        all_lines.append(
            {"text": line, "font": font_main, "h": bbox[3] - bbox[1], "fill": "black"}
        )

    for line in lines_sub:
        bbox = draw.textbbox((0, 0), line, font=font_sub)
        all_lines.append(
            {"text": line, "font": font_sub, "h": bbox[3] - bbox[1], "fill": "black"}
        )

    line_spacing = 1  # Khoảng cách các dòng giảm tối đa
    total_text_height = sum([item["h"] for item in all_lines]) + line_spacing * (
        len(all_lines) - 1
    )

    # Căn giữa theo chiều dọc
    current_y = (H - total_text_height) // 2
    if current_y < 2:
        current_y = 2

    for item in all_lines:
        draw.text(
            (text_start_x, current_y),
            item["text"],
            font=item["font"],
            fill=item["fill"],
        )
        current_y += item["h"] + line_spacing

    file_path = os.path.join(OUTPUT_DIR, f"{uuid}.png")
    canvas.save(file_path, dpi=(DPI, DPI))
    return file_path
