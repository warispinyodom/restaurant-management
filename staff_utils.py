import json
from datetime import datetime
from flask import Blueprint, render_template, request, session, flash, jsonify
from firebase_utils import (
    get_firebase_data, 
    post_firebase_data, 
    patch_firebase_data, 
    parse_firebase_data, 
    staff_required
)

staff_bp = Blueprint('staff', __name__)

# ==========================================
# STAFF DATABASE UTILITIES
# ==========================================
def sanitize_order_items(order):
    """
    ตรวจสอบและทำความสะอาดโครงสร้างข้อมูล Order ให้ปลอดภัย 100%
    ป้องกันการเกิด Error 'builtin_function_or_method' object is not iterable
    """
    if not isinstance(order, dict):
        return order
    
    raw_items = order.get('items')
    
    # หาก raw_items เป็น method หรือไม่ใช่ list ให้จัดการแปลงให้อยู่ในรูปแบบ list
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
    try:
        raw_orders = get_firebase_data('orders')
        orders = parse_firebase_data(raw_orders)
        
        if not isinstance(orders, list):
            if isinstance(orders, dict):
                orders = [{'id': k, **v} if isinstance(v, dict) else {'id': k, 'val': v} for k, v in orders.items()]
            else:
                orders = []

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
    return patch_firebase_data('orders', order_id, {'status': status})

def get_staff_status():
    try:
        status_data = get_firebase_data('staff_status')
        if isinstance(status_data, dict):
            return status_data.get('status', 'ready')
        return 'ready'
    except Exception:
        return 'ready'

def update_staff_status_db(status):
    return patch_firebase_data('staff_status', 'main', {
        'status': status, 
        'updated_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })

def get_all_menus():
    try:
        raw_menus = get_firebase_data('menus')
        menus = parse_firebase_data(raw_menus)
        if not isinstance(menus, list):
            if isinstance(menus, dict):
                menus = [{'id': k, **v} if isinstance(v, dict) else {'id': k, 'val': v} for k, v in menus.items()]
            else:
                menus = []
        return [m for m in menus if isinstance(m, dict)]
    except Exception as e:
        print(f"Error in get_all_menus: {e}")
        return []

def update_menu_item_db(menu_id, fields):
    return patch_firebase_data('menus', menu_id, fields)

def bulk_update_menu_items_db(items_dict):
    if not isinstance(items_dict, dict):
        return False
    success = True
    for menu_id, fields in items_dict.items():
        if isinstance(fields, dict):
            if not patch_firebase_data('menus', menu_id, fields):
                success = False
    return success

def get_bill_by_table(table_no):
    orders = get_all_orders()
    table_orders = [
        o for o in orders 
        if isinstance(o, dict) 
        and str(o.get('table_no', '')) == str(table_no) 
        and str(o.get('status', '')).lower() not in ['completed', 'paid', 'voided', 'cancelled']
    ]
    return table_orders

# ==========================================
# STAFF ROUTES
# ==========================================

# --- ORDERS MANAGEMENT ---
@staff_bp.route('/staff/orders')
@staff_required
def staff_orders():
    try:
        staff_status = session.get('staff_status') or get_staff_status()
        session['staff_status'] = staff_status
        orders = get_all_orders() or []
        return render_template('staff/orders.html', orders=orders, staff_status=staff_status)
            
    except Exception as e:
        print(f"Error staff_orders: {e}")
        flash(f"เกิดข้อผิดพลาดในการโหลดออเดอร์: {str(e)}", "error")
        return render_template('staff/orders.html', orders=[], staff_status='ready')

@staff_bp.route('/staff/api/orders')
@staff_bp.route('/api/staff/orders')
@staff_required
def api_staff_orders():
    try:
        orders = get_all_orders() or []
        return jsonify({'status': 'success', 'orders': orders})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@staff_bp.route('/staff/order/update-status', methods=['POST'])
@staff_bp.route('/staff/order/update-status/<order_id>', methods=['POST'])
@staff_required
def update_order_status(order_id=None):
    try:
        if request.is_json:
            data = request.get_json() or {}
        else:
            data = request.form.to_dict() or {}

        target_order_id = order_id or data.get('order_id') or data.get('id')
        new_status = data.get('status') or data.get('new_status')

        if not target_order_id or not new_status:
            return jsonify({'status': 'error', 'message': 'ข้อมูลไม่ครบถ้วน'}), 400
        
        if update_order_status_db(target_order_id, new_status):
            return jsonify({'status': 'success', 'message': f'อัปเดตสถานะเป็น {new_status} สำเร็จ'})
        return jsonify({'status': 'error', 'message': 'ไม่สามารถอัปเดตสถานะออเดอร์ได้'}), 500
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@staff_bp.route('/staff/status/update', methods=['POST'])
@staff_required
def update_staff_status():
    try:
        if request.is_json:
            data = request.get_json() or {}
        else:
            data = request.form.to_dict() or {}

        new_status = data.get('status', 'ready')
        session['staff_status'] = new_status
        update_staff_status_db(new_status)
        return jsonify({'status': 'success', 'message': f'เปลี่ยนสถานะพนักงานเป็น {new_status} สำเร็จ', 'staff_status': new_status})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# --- CHECK BILL MANAGEMENT ---
@staff_bp.route('/staff/check-bill')
@staff_required
def staff_check_bill():
    try:
        orders = get_all_orders() or []
        unpaid_orders = [
            o for o in orders 
            if isinstance(o, dict) and str(o.get('status', '')).lower() not in ['completed', 'paid', 'voided', 'cancelled']
        ]
        
        raw_tables = get_firebase_data('tables')
        tables = parse_firebase_data(raw_tables)
        if not isinstance(tables, list):
            tables = []
        tables = [t for t in tables if isinstance(t, dict)]
        tables.sort(key=lambda x: str(x.get('table_no', '')))
        
        raw_payments = get_firebase_data('payment_channels')
        payments_data = parse_firebase_data(raw_payments)
        if not isinstance(payments_data, list):
            payments_data = []
            
        payments = [
            p for p in payments_data 
            if isinstance(p, dict) and (str(p.get('is_active', '')).lower() in ['1', 'true', 'on'] or p.get('is_active') == 1)
        ]
        
        return render_template('staff/check_bill.html', orders=unpaid_orders, tables=tables, payments=payments)

    except Exception as e:
        print(f"Error loading check bill page: {e}")
        flash(f"เกิดข้อผิดพลาดในการโหลดข้อมูลเช็คบิล: {str(e)}", "error")
        return render_template('staff/check_bill.html', orders=[], tables=[], payments=[])

@staff_bp.route('/staff/api/check-bill')
@staff_required
def api_staff_check_bill():
    try:
        orders = get_all_orders() or []
        unpaid_orders = [
            o for o in orders 
            if isinstance(o, dict) and str(o.get('status', '')).lower() not in ['completed', 'paid', 'voided', 'cancelled']
        ]

        raw_tables = get_firebase_data('tables')
        tables = parse_firebase_data(raw_tables)
        if not isinstance(tables, list):
            tables = []
        tables = [t for t in tables if isinstance(t, dict)]

        raw_payments = get_firebase_data('payment_channels')
        payments_data = parse_firebase_data(raw_payments)
        if not isinstance(payments_data, list):
            payments_data = []

        payments = [
            p for p in payments_data 
            if isinstance(p, dict) and (str(p.get('is_active', '')).lower() in ['1', 'true', 'on'] or p.get('is_active') == 1)
        ]
        return jsonify({'status': 'success', 'orders': unpaid_orders, 'tables': tables, 'payments': payments})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@staff_bp.route('/staff/check-bill/process', methods=['POST'])
@staff_required
def staff_process_payment():
    try:
        if request.is_json:
            data = request.get_json() or {}
        else:
            data = request.form.to_dict() or {}

        order_id = data.get('order_id') or data.get('id')
        table_id = data.get('table_id')
        table_no = data.get('table_no')
        payment_method = data.get('payment_method', 'เงินสด')
        
        def to_float(val, default=0.0):
            try:
                return float(val) if val is not None and val != "" else default
            except (ValueError, TypeError):
                return default

        # คำนวณยอดเงิน รายละเอียดส่วนลด ค่าบริการ และภาษี
        subtotal = to_float(data.get('subtotal'))
        discount_type = str(data.get('discount_type', 'fixed'))
        discount_value = to_float(data.get('discount_value'))
        discount_amount = to_float(data.get('discount_amount'))
        service_charge_percent = to_float(data.get('service_charge_percent'))
        service_charge_amount = to_float(data.get('service_charge_amount'))
        tax_percent = to_float(data.get('tax_percent'))
        tax_amount = to_float(data.get('tax_amount'))
        total_amount = to_float(data.get('total_amount'))
        received_amount = to_float(data.get('received_amount'))
        change_amount = to_float(data.get('change_amount'))

        if not order_id:
            return jsonify({'status': 'error', 'message': 'ไม่พบรหัสออเดอร์ที่ต้องการชำระเงิน'}), 400

        order_update = {
            'status': 'completed',
            'payment_method': payment_method,
            'subtotal': subtotal,
            'discount_type': discount_type,
            'discount_value': discount_value,
            'discount_amount': discount_amount,
            'service_charge_percent': service_charge_percent,
            'service_charge_amount': service_charge_amount,
            'tax_percent': tax_percent,
            'tax_amount': tax_amount,
            'total_amount': total_amount,
            'received_amount': received_amount,
            'change_amount': change_amount,
            'paid_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        if patch_firebase_data('orders', order_id, order_update):
            if not table_id and table_no:
                raw_tables = get_firebase_data('tables')
                tables = parse_firebase_data(raw_tables)
                if isinstance(tables, list):
                    for t in tables:
                        if isinstance(t, dict) and str(t.get('table_no')) == str(table_no):
                            table_id = t.get('id')
                            break

            if table_id:
                patch_firebase_data('tables', table_id, {
                    'status': 'available',
                    'order': {'items': [], 'total_amount': 0.0}
                })

            return jsonify({
                'status': 'success', 
                'message': f'เช็คบิลออเดอร์ โต๊ะ {table_no or ""} เรียบร้อยแล้ว',
                'order_id': order_id,
                'receipt_data': order_update
            })

        return jsonify({'status': 'error', 'message': 'ไม่สามารถบันทึกการชำระเงินได้'}), 500

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# API ดึงข้อมูลใบเสร็จ
@staff_bp.route('/staff/receipt/<order_id>')
@staff_required
def get_receipt(order_id):
    try:
        raw_order = get_firebase_data(f'orders/{order_id}')
        if not raw_order or not isinstance(raw_order, dict):
            all_orders = get_all_orders()
            for o in all_orders:
                if str(o.get('id')) == str(order_id):
                    raw_order = o
                    break
        
        if isinstance(raw_order, dict):
            raw_order = sanitize_order_items(raw_order)
            raw_order['id'] = order_id
            return jsonify({'status': 'success', 'order': raw_order})
        return jsonify({'status': 'error', 'message': 'ไม่พบข้อมูลออเดอร์'}), 404
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# --- TABLES STATUS MANAGEMENT FOR STAFF ---
@staff_bp.route('/staff/tables')
@staff_required
def staff_tables():
    try:
        raw_tables = get_firebase_data('tables')
        tables = parse_firebase_data(raw_tables)
        if not isinstance(tables, list):
            tables = []
        tables = [t for t in tables if isinstance(t, dict)]
        tables.sort(key=lambda x: str(x.get('table_no', '')))
        return render_template('admin/tables.html', tables=tables)
    except Exception as e:
        print(f"Error staff_tables: {e}")
        flash(f"เกิดข้อผิดพลาดในการโหลดผังโต๊ะ: {str(e)}", "error")
        return render_template('admin/tables.html', tables=[])

# --- MENU MANAGEMENT FOR STAFF ---
@staff_bp.route('/staff/menu-manage')
@staff_required
def staff_menu_manage():
    try:
        menus = get_all_menus() or []
    except Exception as e:
        print(f"Error loading staff menus: {e}")
        menus = []
        flash("เกิดข้อผิดพลาดในการดึงข้อมูลเมนู กรุณาลองใหม่อีกครั้ง", "error")

    return render_template('staff/menu_manage.html', menus=menus)

@staff_bp.route('/staff/api/menus')
@staff_required
def api_staff_menus():
    try:
        menus = get_all_menus() or []
        return jsonify({'status': 'success', 'menus': menus})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@staff_bp.route('/staff/menu/quick-update/<menu_id>', methods=['POST'])
@staff_required
def quick_update_menu(menu_id):
    try:
        if request.is_json:
            data = request.get_json() or {}
        else:
            data = request.form.to_dict() or {}

        update_fields = {}
        
        if 'price' in data and data['price'] is not None and data['price'] != "":
            try:
                update_fields['price'] = abs(float(data['price']))
            except ValueError:
                pass

        if 'discount' in data and data['discount'] is not None and data['discount'] != "":
            try:
                update_fields['discount'] = abs(float(data['discount']))
            except ValueError:
                pass

        if 'stock' in data:
            stock_val = data['stock']
            try:
                update_fields['stock'] = abs(int(stock_val)) if (stock_val is not None and stock_val != "") else None
            except ValueError:
                pass

        if 'status' in data:
            st = str(data['status']).lower().strip()
            update_fields['status'] = st
            update_fields['is_available'] = (st in ['available', 'true', 'active'])
            
        if update_menu_item_db(menu_id, update_fields):
            return jsonify({'status': 'success', 'message': 'ปรับปรุงข้อมูลเมนูสำเร็จ'})
        return jsonify({'status': 'error', 'message': 'ไม่สามารถอัปเดตข้อมูลได้'}), 500
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@staff_bp.route('/staff/menu/bulk-update', methods=['POST'])
@staff_required
def bulk_update_menu():
    try:
        if request.is_json:
            data = request.get_json() or {}
        else:
            data = request.form.to_dict() or {}

        items_data = data.get('items', {})
        if isinstance(items_data, str):
            try:
                items_data = json.loads(items_data)
            except Exception:
                pass
        
        if not items_data or not isinstance(items_data, dict):
            return jsonify({'status': 'error', 'message': 'ไม่พบรายการที่ต้องการบันทึก'}), 400

        if bulk_update_menu_items_db(items_data):
            return jsonify({'status': 'success', 'message': 'อัปเดตรายการสินค้าทั้งหมดเรียบร้อยแล้ว'})
        return jsonify({'status': 'error', 'message': 'ไม่สามารถบันทึกข้อมูลแบบกลุ่มได้'}), 500
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500