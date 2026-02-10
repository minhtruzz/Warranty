// static/js/global_modal.js
document.addEventListener('DOMContentLoaded', function () {
    fetch('/check-should-fix')
        .then(res => res.json())
        .then(data => {
            if (data.should_open) {
                showGlobalFixModal();
            }
        });
});

function showGlobalFixModal() {
    fetch('/get-pending-groups')
        .then(res => res.json())
        .then(groups => {
            if (!groups || groups.length === 0) return;

            let tableRows = groups.map(g => `
                <tr>
                    <td style="text-align:left; padding:12px;">
                        <b style="color: #10b981;">${g.ma_bill}</b><br>
                        <small class="text-muted">${g.total} SP chưa có số</small>
                    </td>
                    <td style="padding:12px;">
                        <input type="text" class="form-control js-global-input" 
                               data-ma-bill="${g.ma_bill}" 
                               style="text-transform: uppercase; font-weight: 700; border: 2px solid #e2e8f0;"
                               /* CHỖ THAY ĐỔI: Thêm .replace(/\s/g, '') để xóa dấu cách */
                               oninput="this.value = this.value.toUpperCase().replace(/\\s/g, '')"
                               placeholder="NHẬP SỐ PHIẾU...">
                    </td>
                </tr>
            `).join('');

            let tableHtml = `
                <div style="max-height: 350px; overflow-y: auto; padding: 10px;">
                    <p style="color: #e74c3c; font-weight: bold; font-size: 0.9rem;">
                        ⚠️ Bạn cần cập nhật Số Phiếu cho đợt hàng vừa xem trước khi tiếp tục!
                    </p>
                    <table class="table table-sm" style="width: 100%; border-collapse: collapse;">
                        <thead class="table-light">
                            <tr><th>Mã đợt</th><th>Số phiếu</th></tr>
                        </thead>
                        <tbody>${tableRows}</tbody>
                    </table>
                </div>
            `;

            Swal.fire({
                title: 'NHẮC NHỞ CẬP NHẬT',
                html: tableHtml,
                width: '600px',
                showCancelButton: true,
                cancelButtonText: 'ĐÓNG TẠM THỜI',
                cancelButtonColor: '#6c757d',
                allowOutsideClick: true,
                allowEscapeKey: true,
                confirmButtonText: 'LƯU TẤT CẢ',
                confirmButtonColor: '#10b981',
                preConfirm: () => {
                    const inputs = document.querySelectorAll('.js-global-input');
                    const items = [];
                    inputs.forEach(input => {
                        // Vẫn dùng .trim() lần cuối cho chắc chắn
                        const val = input.value.trim().toUpperCase();
                        if (val) {
                            items.push({ ma_bill: input.getAttribute('data-ma-bill'), so_phieu: val });
                        }
                    });
                    if (items.length === 0) {
                        Swal.showValidationMessage('Bạn không thể bỏ qua bước này!');
                    }
                    return items;
                }
            }).then((result) => {
                if (result.isConfirmed) {
                    saveGlobalData(result.value);
                }
            });
        });
}

function saveGlobalData(items) {
    Swal.fire({ title: 'Đang lưu...', didOpen: () => Swal.showLoading() });
    fetch('/update-so-phieu', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ items: items })
    })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                Swal.fire('Thành công!', 'Dữ liệu đã khớp.', 'success');
            } else {
                Swal.fire('Lỗi trùng!', data.message, 'error').then(() => showGlobalFixModal());
            }
        });
}