import json
from datetime import datetime
from collections import Counter
from flask import Blueprint, render_template, request, session, flash, jsonify
from firebase_utils import (
    get_firebase_data, 
    post_firebase_data, 
    patch_firebase_data, 
    parse_firebase_data, 
    staff_required
)

staff_bp = Blueprint('staff', __name__)

# โครงสร้างสำหรับรีเซ็ตโต๊ะให้เป็นค่าว่างเริ่มต้น
RESET_TABLE_PAYLOAD = {
    'status': 'available',
    'occupied_by': '',
    'customer_count': 0,
    'occupied_time': '',
    'order': {'items': [], 'total_amount': 0.0}
}

# ==========================================
# STAFF DATABASE UTILITIES & HELPERS
# ==========================================

def to_float(val, default=0.0):
    """แปลงค่าเป็น float อย่างปลอดภัย"""
    try:
        return float(val) if val is not None and val != "" else default
    except (ValueError, TypeError):
        return default

def sanitize_order_items(order):
    """ทำความสะอาดและจัดโครงสร้างรายการอาหารในออเดอร์ให้เป็น List"""
    if not isinstance(order, dict):
        return order
    
    raw_items = order.get('items')
    
    if callable(raw_items) or not isinstance(raw_items, list):
        raw_order_items = order.get('order_items')
        if isinstance(raw_order_items, list):
            order['items'] = raw_order_items
        elif isinstance(raw_items, dict):
            order['items'] = list(raw_items.values())
        elif isinstance(raw_order_items, dict):
            order['items'] = list(raw_order_items.values())
        else:
            order['items'] = []
            
    clean_items = []
    for item in order.get('items', []):
        if isinstance(item, dict):
            clean_items.append(item)
    order['items'] = clean_items
    
    return order

def get_all_orders():
    """ดึงข้อมูลออเดอร์ทั้งหมดจาก Firebase"""
    try:
        raw_orders = get_firebase_data('orders')
        orders = parse_firebase_data(raw_orders)

        valid_orders = []
        for o in orders:
            if isinstance(o, dict):
                valid_orders.append(sanitize_order_items(o))

        valid_orders.sort(key=lambda x: str(x.get('created_at') or ''), reverse=True)
        return valid_orders
    except Exception as e:
        print(f"Error in get_all_orders: {e}")
        return []

def update_order_status_db(order_id, status):
    """อัปเดตสถานะออเดอร์ใน Firebase"""
    return patch_firebase_data('orders', order_id, {
        'status': status,
        'updated_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })

def get_staff_status():
    """ดึงสถานะการทำงานของพนักงาน"""
    try:
        status_data = get_firebase_data('staff_status')
        if isinstance(status_data, dict):
            return status_data.get('status', 'ready')
        return 'ready'
    except Exception:
        return 'ready'

def update_staff_status_db(status):
    """อัปเดตสถานะการทำงานของพนักงาน"""
    return patch_firebase_data('staff_status', 'main', {
        'status': status, 
        'updated_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })

def get_all_menus():
    """ดึงเมนูอาหารทั้งหมด"""
    try:
        raw_menus = get_firebase_data('menus')
        menus = parse_firebase_data(raw_menus)
        return [m for m in menus if isinstance(m, dict)]
    except Exception as e:
        print(f"Error in get_all_menus: {e}")
        return []

def get_all_tables():
    """ดึงผังโต๊ะทั้งหมดและจัดเรียงลำดับหมายเลขโต๊ะอย่างถูกต้อง"""
    try:
        raw_tables = get_firebase_data('tables')
        tables = parse_firebase_data(raw_tables)
        valid_tables = [t for t in tables if isinstance(t, dict)]
        
        def _sort_key(t):
            val = str(t.get('table_no') or t.get('number') or t.get('name') or '')
            digits = ''.join(filter(str.isdigit, val))
            return (0, int(digits), val) if digits else (1, 0, val)

        valid_tables.sort(key=_sort_key)
        return valid_tables
    except Exception as e:
        print(f"Error in get_all_tables: {e}")
        return []

def get_all_service_requests():
    """ดึงการเรียกพนักงาน/บริการ"""
    try:
        raw_requests = get_firebase_data('service_requests')
        if not raw_requests:
            raw_requests = get_firebase_data('service_calls')

        requests = parse_firebase_data(raw_requests)
        requests.sort(key=lambda x: str(x.get('created_at') or x.get('timestamp') or x.get('id') or ''), reverse=True)
        return requests
    except Exception as e:
        print(f"Error in get_all_service_requests: {e}")
        return []

# ==========================================
# STAFF ROUTES & CONTROLLERS
# ==========================================

# ------------------------------------------
# SERVICE REQUESTS (เรียกพนักงาน) ROUTES
# ------------------------------------------

@staff_bp.route('/staff/service-requests')
@staff_required
def staff_service_requests_page():
    """หน้ารายการแจ้งเรียกพนักงาน"""
    try:
        requests_list = get_all_service_requests()
        return render_template('staff/service_requests.html', service_requests=requests_list)
    except Exception as e:
        flash(f"เกิดข้อผิดพลาดในการโหลดรายการเรียกพนักงาน: {str(e)}", "error")
        return render_template('staff/service_requests.html', service_requests=[])

@staff_bp.route('/staff/api/service-requests')
@staff_bp.route('/api/staff/service-requests')
@staff_required
def api_staff_service_requests():
    """API ดึงรายการเรียกพนักงานสำหรับ Auto-refresh/AJAX"""
    try:
        requests_list = get_all_service_requests() or []
        return jsonify({'status': 'success', 'requests': requests_list})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@staff_bp.route('/staff/service-request/update-status', methods=['POST'])
@staff_bp.route('/staff/service-requests/resolve', methods=['POST'])
@staff_required
def staff_update_service_request_status():
    """อัปเดตสถานะ/ปิดงานการเรียกพนักงาน (pending -> in_progress -> resolved)"""
    try:
        data = request.get_json(silent=True) or request.form.to_dict() or {}
        request_id = data.get('request_id') or data.get('id')
        new_status = data.get('status', 'resolved')

        if not request_id:
            return jsonify({'status': 'error', 'message': 'ไม่พบรายการที่ต้องการ'}), 400

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        patch_payload = {
            'status': new_status,
            'updated_at': now_str
        }
        if new_status in ['resolved', 'completed']:
            patch_payload['resolved_at'] = now_str

        if patch_firebase_data('service_requests', request_id, patch_payload):
            return jsonify({'status': 'success', 'message': 'อัปเดตสถานะเรียบร้อยแล้ว'})
        return jsonify({'status': 'error', 'message': 'ไม่สามารถอัปเดตรายการในระบบได้'}), 500
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ------------------------------------------
# TABLES MANAGEMENT ROUTES
# ------------------------------------------

@staff_bp.route('/staff/tables')
@staff_required
def staff_tables():
    """หน้าผังและสถานะโต๊ะอาหาร"""
    try:
        tables = get_all_tables()
        return render_template('staff/tables.html', tables=tables)
    except Exception as e:
        flash(f"เกิดข้อผิดพลาดในการโหลดผังโต๊ะ: {str(e)}", "error")
        return render_template('staff/tables.html', tables=[])

@staff_bp.route('/staff/api/tables')
@staff_bp.route('/api/staff/tables')
@staff_required
def api_staff_tables():
    """API ดึงข้อมูลโต๊ะทั้งหมดสำหรับ Auto-refresh/AJAX"""
    try:
        tables = get_all_tables() or []
        return jsonify({'status': 'success', 'tables': tables})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@staff_bp.route('/staff/tables/update-status', methods=['POST'])
@staff_required
def staff_update_table_status():
    """อัปเดตสถานะโต๊ะ / เปิดโต๊ะ (Check-In) / เคลียร์โต๊ะ"""
    try:
        data = request.get_json(silent=True) or request.form.to_dict() or {}
        table_id = data.get('table_id')
        new_status = str(data.get('status', 'available')).lower()
        customer_count = data.get('customer_count')

        if not table_id:
            return jsonify({'status': 'error', 'message': 'ไม่พบรหัสโต๊ะที่ต้องการอัปเดต'}), 400

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        payload = {
            'status': new_status,
            'updated_at': now_str
        }

        if new_status in ['available', 'ว่าง']:
            payload.update(RESET_TABLE_PAYLOAD)
            payload['status'] = 'available'
            payload['updated_at'] = now_str

        elif new_status in ['occupied', 'มีลูกค้า']:
            payload['status'] = 'occupied'
            payload['occupied_time'] = now_str
            if customer_count is not None:
                try:
                    payload['customer_count'] = int(customer_count)
                except (ValueError, TypeError):
                    payload['customer_count'] = 1

        elif new_status in ['cleaning', 'ทำความสะอาด']:
            payload['status'] = 'cleaning'
        elif new_status in ['reserved', 'จองแล้ว']:
            payload['status'] = 'reserved'

        if patch_firebase_data('tables', table_id, payload):
            return jsonify({'status': 'success', 'message': 'อัปเดตสถานะโต๊ะสำเร็จ', 'data': payload})
        return jsonify({'status': 'error', 'message': 'ไม่สามารถอัปเดตข้อมูลในระบบได้'}), 500
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ------------------------------------------
# ORDERS MANAGEMENT ROUTES
# ------------------------------------------

@staff_bp.route('/staff/orders')
@staff_required
def staff_orders():
    """หน้ารายการออเดอร์และการรับสั่งอาหาร"""
    try:
        staff_status = session.get('staff_status') or get_staff_status()
        session['staff_status'] = staff_status
        orders = get_all_orders() or []
        selected_table = request.args.get('table', '')
        return render_template('staff/orders.html', orders=orders, staff_status=staff_status, selected_table=selected_table)
    except Exception as e:
        print(f"Error staff_orders: {e}")
        flash(f"เกิดข้อผิดพลาดในการโหลดออเดอร์: {str(e)}", "error")
        return render_template('staff/orders.html', orders=[], staff_status='ready', selected_table='')

@staff_bp.route('/staff/api/orders')
@staff_bp.route('/api/staff/orders')
@staff_required
def api_staff_orders():
    """API ดึงรายการออเดอร์ทั้งหมด"""
    try:
        orders = get_all_orders() or []
        return jsonify({'status': 'success', 'orders': orders})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@staff_bp.route('/staff/order/update-status', methods=['POST'])
@staff_bp.route('/staff/order/update-status/<order_id>', methods=['POST'])
@staff_required
def update_order_status(order_id=None):
    """อัปเดตสถานะออเดอร์"""
    try:
        data = request.get_json(silent=True) or request.form.to_dict() or {}
        target_order_id = order_id or data.get('order_id') or data.get('id')
        new_status = data.get('status') or data.get('new_status')

        if not target_order_id or not new_status:
            return jsonify({'status': 'error', 'message': 'ข้อมูลไม่ครบถ้วน'}), 400
        
        if update_order_status_db(target_order_id, new_status):
            return jsonify({'status': 'success', 'message': f'อัปเดตสถานะเป็น {new_status} สำเร็จ'})
        return jsonify({'status': 'error', 'message': 'ไม่สามารถอัปเดตสถานะออเดอร์ได้'}), 500
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@staff_bp.route('/staff/order/create', methods=['POST'])
@staff_required
def staff_create_order():
    """สร้างออเดอร์ใหม่โดยพนักงาน"""
    try:
        data = request.get_json(silent=True) if request.is_json else request.form.to_dict()
        table_no = data.get('table_no')
        order_type = data.get('order_type', 'dine_in')
        items = data.get('items', [])
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except Exception:
                items = []

        if not items:
            return jsonify({'status': 'error', 'message': 'ไม่มีรายการอาหารในออเดอร์'}), 400

        total_amount = sum(to_float(item.get('price', 0)) * to_float(item.get('quantity', 1)) for item in items)
        
        new_order = {
            'table_no': table_no if order_type == 'dine_in' else 'Takeaway/หน้าร้าน',
            'order_type': order_type,
            'items': items,
            'total_amount': total_amount,
            'total_price': total_amount,
            'status': 'pending',
            'created_by': 'staff',
            'created_at': now_str
        }
        
        res = post_firebase_data('orders', new_order)
        
        if order_type == 'dine_in' and table_no:
            tables = get_all_tables()
            for t in tables:
                t_no = str(t.get('table_no') or t.get('number') or t.get('name') or '')
                if t_no == str(table_no):
                    patch_firebase_data('tables', t.get('id'), {
                        'status': 'occupied',
                        'occupied_time': now_str,
                        'updated_at': now_str
                    })
                    
        return jsonify({'status': 'success', 'message': 'สร้างออเดอร์เรียบร้อยแล้ว', 'data': res})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@staff_bp.route('/staff/order/item/cancel', methods=['POST'])
@staff_required
def cancel_order_item():
    """ยกเลิกบางรายการอาหารในออเดอร์"""
    try:
        data = request.get_json(silent=True) if request.is_json else request.form.to_dict()
        order_id = data.get('order_id')
        item_index = data.get('item_index')

        if not order_id or item_index is None:
            return jsonify({'status': 'error', 'message': 'ข้อมูลระบุออเดอร์ไม่ครบถ้วน'}), 400

        item_idx = int(item_index)
        raw_order = get_firebase_data(f'orders/{order_id}')
        
        if not raw_order or not isinstance(raw_order, dict):
            return jsonify({'status': 'error', 'message': 'ไม่พบออเดอร์ที่ต้องการ'}), 404

        order = dict(raw_order)
        order['id'] = order_id
        order = sanitize_order_items(order)
        items = order.get('items', [])

        if 0 <= item_idx < len(items):
            removed_item = items.pop(item_idx)
            new_total = sum(to_float(i.get('price', 0)) * to_float(i.get('quantity', 1)) for i in items)
            
            patch_firebase_data('orders', order_id, {
                'items': items,
                'total_amount': new_total,
                'total_price': new_total,
                'updated_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            return jsonify({'status': 'success', 'message': f"ยกเลิก {removed_item.get('name', 'รายการ')} เรียบร้อยแล้ว", 'new_total': new_total})
        
        return jsonify({'status': 'error', 'message': 'ตำแหน่งรายการอาหารไม่ถูกต้อง'}), 400
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ------------------------------------------
# CHECK BILL & PAYMENT ROUTES
# ------------------------------------------

@staff_bp.route('/staff/check-bill')
@staff_required
def staff_check_bill():
    """หน้าเช็คบิล/รับชำระเงิน"""
    try:
        orders = get_all_orders() or []
        unpaid_orders = [
            o for o in orders 
            if isinstance(o, dict) and str(o.get('status', '')).lower() not in ['completed', 'paid', 'voided', 'cancelled']
        ]
        
        tables = get_all_tables()
        raw_payments = get_firebase_data('payment_channels')
        payments_data = parse_firebase_data(raw_payments)
            
        payments = [
            p for p in payments_data 
            if isinstance(p, dict) and (str(p.get('is_active', '')).lower() in ['1', 'true', 'on'] or p.get('is_active') == 1)
        ]
        
        selected_table = request.args.get('table', '')
        return render_template('staff/check_bill.html', orders=unpaid_orders, tables=tables, payments=payments, selected_table=selected_table)
    except Exception as e:
        print(f"Error loading check bill page: {e}")
        flash(f"เกิดข้อผิดพลาดในการโหลดข้อมูลเช็คบิล: {str(e)}", "error")
        return render_template('staff/check_bill.html', orders=[], tables=[], payments=[], selected_table='')

@staff_bp.route('/staff/api/check-bill')
@staff_required
def api_staff_check_bill():
    """API ดึงรายการเช็คบิลที่ยังไม่ชำระเงิน"""
    try:
        orders = get_all_orders() or []
        unpaid_orders = [
            o for o in orders 
            if isinstance(o, dict) and str(o.get('status', '')).lower() not in ['completed', 'paid', 'voided', 'cancelled']
        ]
        tables = get_all_tables()
        return jsonify({'status': 'success', 'orders': unpaid_orders, 'tables': tables})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@staff_bp.route('/staff/check-bill/process', methods=['POST'])
@staff_required
def staff_process_check_bill():
    """ประมวลผลการรับชำระเงิน และรีเซ็ตโต๊ะเป็นว่าง"""
    try:
        data = request.get_json(silent=True) or request.form.to_dict() or {}
        table_no = data.get('table_no')
        order_id = data.get('order_id')
        payment_method = data.get('payment_method', 'เงินสด')
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if not table_no and not order_id:
            return jsonify({'status': 'error', 'message': 'กรุณาระบุหมายเลขโต๊ะหรือรหัสออเดอร์'}), 400

        orders = get_all_orders()
        target_orders = []
        if order_id:
            target_orders = [o for o in orders if str(o.get('id')) == str(order_id)]
        elif table_no:
            target_orders = [
                o for o in orders 
                if str(o.get('table_no')) == str(table_no) and str(o.get('status')).lower() not in ['completed', 'paid', 'voided']
            ]

        for o in target_orders:
            patch_firebase_data('orders', o['id'], {
                'status': 'completed',
                'payment_method': payment_method,
                'paid_at': now_str,
                'updated_at': now_str
            })

        if table_no:
            tables = get_all_tables()
            for t in tables:
                t_no = str(t.get('table_no') or t.get('number') or t.get('name') or '')
                if t_no == str(table_no):
                    payload = RESET_TABLE_PAYLOAD.copy()
                    payload['updated_at'] = now_str
                    patch_firebase_data('tables', t['id'], payload)

        return jsonify({'status': 'success', 'message': f'รับชำระเงินเรียบร้อยแล้ว (โต๊ะ {table_no or "-"})'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ------------------------------------------
# OTHER STAFF UTILITIES & MENU MANAGEMENT
# ------------------------------------------

@staff_bp.route('/staff/status/update', methods=['POST'])
@staff_required
def update_staff_status():
    """อัปเดตสถานะพร้อมทำงานของพนักงาน"""
    try:
        data = request.get_json(silent=True) or request.form.to_dict() or {}
        new_status = data.get('status', 'ready')
        session['staff_status'] = new_status
        update_staff_status_db(new_status)
        return jsonify({'status': 'success', 'message': f'เปลี่ยนสถานะพนักงานเป็น {new_status} สำเร็จ', 'staff_status': new_status})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@staff_bp.route('/staff/menu-manage')
@staff_required
def staff_menu_manage():
    """หน้าจัดการเมนูอาหาร (เปิด/ปิดสถานะหมด)"""
    try:
        menus = get_all_menus()
        return render_template('staff/menu_manage.html', menus=menus)
    except Exception as e:
        flash(f"เกิดข้อผิดพลาดในการโหลดรายการเมนู: {str(e)}", "error")
        return render_template('staff/menu_manage.html', menus=[])

@staff_bp.route('/staff/menu-manage/toggle-status', methods=['POST'])
@staff_required
def staff_toggle_menu_status():
    """สลับสถานะเมนู (พร้อมขาย / สินค้าหมด)"""
    try:
        data = request.get_json(silent=True) or request.form.to_dict() or {}
        menu_id = data.get('menu_id')
        is_available = data.get('is_available')

        if not menu_id:
            return jsonify({'status': 'error', 'message': 'ไม่พบรายการเมนู'}), 400

        status_str = 'available' if is_available else 'out_of_stock'
        patch_payload = {
            'is_available': bool(is_available),
            'status': status_str,
            'updated_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        if patch_firebase_data('menus', menu_id, patch_payload):
            return jsonify({'status': 'success', 'message': 'อัปเดตสถานะเมนูเรียบร้อย'})
        return jsonify({'status': 'error', 'message': 'ไม่สามารถอัปเดตเมนูได้'}), 500
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@staff_bp.route('/staff/menu/quick-update/<menu_id>', methods=['POST'])
@staff_required
def staff_quick_update_menu(menu_id):
    """อัปเดตราคาส่วนลด สต็อก และสถานะ ของเมนูรายการเดียว"""
    try:
        data = request.get_json(silent=True) or request.form.to_dict() or {}
        if not menu_id:
            return jsonify({'status': 'error', 'message': 'ไม่พบรหัสเมนู'}), 400

        price = to_float(data.get('price'), 0.0)
        discount = to_float(data.get('discount'), 0.0)
        stock = data.get('stock')
        status = data.get('status', 'available')

        is_available = (status == 'available')

        patch_payload = {
            'price': abs(price),
            'discount': abs(discount),
            'stock': int(abs(stock)) if stock is not None and str(stock).isdigit() else None,
            'status': status,
            'is_available': is_available,
            'updated_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        if patch_firebase_data('menus', menu_id, patch_payload):
            return jsonify({'status': 'success', 'message': 'อัปเดตรายการเรียบร้อยแล้ว'})
        return jsonify({'status': 'error', 'message': 'ไม่สามารถอัปเดตข้อมูลลงฐานข้อมูลได้'}), 500
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@staff_bp.route('/staff/menu/bulk-update', methods=['POST'])
@staff_required
def staff_bulk_update_menus():
    """อัปเดตข้อมูลเมนูแบบหลายรายการพร้อมกัน (Bulk Update)"""
    try:
        data = request.get_json(silent=True) or {}
        items = data.get('items', {})

        if not items or not isinstance(items, dict):
            return jsonify({'status': 'error', 'message': 'ไม่พบรายการข้อมูลที่ส่งมา'}), 400

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        success_count = 0

        for menu_id, item_data in items.items():
            if not isinstance(item_data, dict):
                continue

            price = to_float(item_data.get('price'), 0.0)
            discount = to_float(item_data.get('discount'), 0.0)
            stock = item_data.get('stock')
            status = item_data.get('status', 'available')
            is_available = (status == 'available')

            patch_payload = {
                'price': abs(price),
                'discount': abs(discount),
                'stock': int(abs(stock)) if stock is not None and str(stock).isdigit() else None,
                'status': status,
                'is_available': is_available,
                'updated_at': now_str
            }

            if patch_firebase_data('menus', menu_id, patch_payload):
                success_count += 1

        return jsonify({
            'status': 'success',
            'message': f'อัปเดตข้อมูลสำเร็จ {success_count} รายการ'
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@staff_bp.route('/staff/daily-summary')
@staff_required
def staff_daily_summary():
    """สรุปยอดขายประจำวันพนักงาน"""
    try:
        selected_date = request.args.get('date', '').strip()
        
        try:
            if selected_date:
                datetime.strptime(selected_date, "%Y-%m-%d")
                target_date_str = selected_date
            else:
                target_date_str = datetime.now().strftime("%Y-%m-%d")
        except ValueError:
            target_date_str = datetime.now().strftime("%Y-%m-%d")

        orders = get_all_orders()
        target_orders = []
        for o in orders:
            if not isinstance(o, dict):
                continue
            created_at = str(o.get('created_at', ''))
            paid_at = str(o.get('paid_at', ''))
            status = str(o.get('status', '')).lower()
            
            is_date_match = created_at.startswith(target_date_str) or paid_at.startswith(target_date_str)
            is_paid = status in ['completed', 'paid']
            
            if is_date_match and is_paid:
                target_orders.append(o)

        total_sales = sum(to_float(o.get('total_price') if o.get('total_price') is not None else o.get('total_amount', 0)) for o in target_orders)
        total_orders = len(target_orders)
        
        payment_breakdown = {}
        item_counter = Counter()

        for o in target_orders:
            pm = o.get('payment_method') or 'เงินสด'
            amt = to_float(o.get('total_price') if o.get('total_price') is not None else o.get('total_amount', 0))
            payment_breakdown[pm] = payment_breakdown.get(pm, 0.0) + amt

            for item in o.get('items', []):
                if isinstance(item, dict):
                    name = item.get('name')
                    qty = to_float(item.get('quantity', 1))
                    if name:
                        item_counter[name] += int(qty)

        top_items = [{'name': name, 'qty': qty} for name, qty in item_counter.most_common(5)]

        summary_data = {
            'date': target_date_str,
            'total_sales': round(total_sales, 2),
            'total_orders': total_orders,
            'total_bills': total_orders,
            'payment_breakdown': payment_breakdown,
            'top_items': top_items
        }

        return render_template('staff/daily_summary.html', summary=summary_data)
    except Exception as e:
        print(f"Error staff_daily_summary: {e}")
        flash(f"เกิดข้อผิดพลาดในการสรุปยอดประจำวัน: {str(e)}", "error")
        today_str = datetime.now().strftime("%Y-%m-%d")
        return render_template('staff/daily_summary.html', summary={
            'date': today_str,
            'total_sales': 0.0,
            'total_orders': 0,
            'total_bills': 0,
            'payment_breakdown': {},
            'top_items': []
        })