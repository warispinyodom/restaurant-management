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
def get_all_orders():
    raw_orders = get_firebase_data('orders')
    orders = parse_firebase_data(raw_orders)
    orders.sort(key=lambda x: str(x.get('created_at') or ''), reverse=True)
    return orders

def update_order_status_db(order_id, status):
    return patch_firebase_data('orders', order_id, {'status': status})

def get_staff_status():
    status_data = get_firebase_data('staff_status')
    if isinstance(status_data, dict):
        return status_data.get('status', 'ready')
    return 'ready'

def update_staff_status_db(status):
    return patch_firebase_data('staff_status', 'main', {'status': status, 'updated_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")})

def get_all_menus():
    raw_menus = get_firebase_data('menus')
    return parse_firebase_data(raw_menus)

def update_menu_item_db(menu_id, fields):
    return patch_firebase_data('menus', menu_id, fields)

def bulk_update_menu_items_db(items_dict):
    success = True
    for menu_id, fields in items_dict.items():
        if not patch_firebase_data('menus', menu_id, fields):
            success = False
    return success

def get_bill_by_table(table_no):
    orders = get_all_orders()
    table_orders = [o for o in orders if str(o.get('table_no')) == str(table_no) and o.get('status') not in ['completed', 'paid', 'voided', 'cancelled']]
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
        
        for o in orders:
            if isinstance(o, dict):
                raw_items = o.get('items')
                if not isinstance(raw_items, list):
                    raw_order_items = o.get('order_items')
                    o['items'] = raw_order_items if isinstance(raw_order_items, list) else []

        try:
            return render_template('staff/orders.html', orders=orders, staff_status=staff_status)
        except Exception:
            return render_template('orders.html', orders=orders, staff_status=staff_status)
            
    except Exception as e:
        flash(f"เกิดข้อผิดพลาดในการเชื่อมต่อฐานข้อมูล: {str(e)}", "error")
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
        unpaid_orders = []
        
        for o in orders:
            if isinstance(o, dict) and str(o.get('status', '')).lower() not in ['completed', 'paid', 'voided', 'cancelled']:
                raw_items = o.get('items')
                if not isinstance(raw_items, list):
                    raw_order_items = o.get('order_items')
                    o['items'] = raw_order_items if isinstance(raw_order_items, list) else []
                unpaid_orders.append(o)
        
        raw_tables = get_firebase_data('tables')
        tables = parse_firebase_data(raw_tables)
        tables.sort(key=lambda x: str(x.get('table_no', '')))
        
        raw_payments = get_firebase_data('payment_channels')
        payments = [
            p for p in parse_firebase_data(raw_payments) 
            if str(p.get('is_active')).lower() in ['1', 'true', 'on'] or p.get('is_active') == 1
        ]
        
        try:
            return render_template('staff/check_bill.html', orders=unpaid_orders, tables=tables, payments=payments)
        except Exception:
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
        unpaid_orders = []
        for o in orders:
            if isinstance(o, dict) and str(o.get('status', '')).lower() not in ['completed', 'paid', 'voided', 'cancelled']:
                raw_items = o.get('items')
                if not isinstance(raw_items, list):
                    raw_order_items = o.get('order_items')
                    o['items'] = raw_order_items if isinstance(raw_order_items, list) else []
                unpaid_orders.append(o)

        raw_tables = get_firebase_data('tables')
        tables = parse_firebase_data(raw_tables)
        raw_payments = get_firebase_data('payment_channels')
        payments = [
            p for p in parse_firebase_data(raw_payments) 
            if str(p.get('is_active')).lower() in ['1', 'true', 'on'] or p.get('is_active') == 1
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
        
        try:
            received_amount = float(data.get('received_amount', 0))
        except (ValueError, TypeError):
            received_amount = 0.0

        try:
            change_amount = float(data.get('change_amount', 0))
        except (ValueError, TypeError):
            change_amount = 0.0

        if not order_id:
            return jsonify({'status': 'error', 'message': 'ไม่พบรหัสออเดอร์ที่ต้องการชำระเงิน'}), 400

        order_update = {
            'status': 'completed',
            'payment_method': payment_method,
            'received_amount': received_amount,
            'change_amount': change_amount,
            'paid_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        if patch_firebase_data('orders', order_id, order_update):
            if not table_id and table_no:
                raw_tables = get_firebase_data('tables')
                tables = parse_firebase_data(raw_tables)
                for t in tables:
                    if str(t.get('table_no')) == str(table_no):
                        table_id = t.get('id')
                        break

            if table_id:
                patch_firebase_data('tables', table_id, {
                    'status': 'available',
                    'order': {'items': [], 'total_amount': 0.0}
                })

            return jsonify({'status': 'success', 'message': f'เช็คบิลออเดอร์ โต๊ะ {table_no or ""} เรียบร้อยแล้ว'})

        return jsonify({'status': 'error', 'message': 'ไม่สามารถบันทึกการชำระเงินได้'}), 500

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# --- MENU MANAGEMENT ---
@staff_bp.route('/staff/menu-manage')
@staff_required
def staff_menu_manage():
    try:
        menus = get_all_menus() or []
    except Exception as e:
        print(f"Error loading staff menus: {e}")
        menus = []
        flash("เกิดข้อผิดพลาดในการเชื่อมต่อฐานข้อมูลเมนู กรุณาลองใหม่อีกครั้ง", "error") 

    try:
        return render_template('staff/menu_manage.html', menus=menus)
    except Exception:
        return render_template('menu_manage.html', menus=menus)

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