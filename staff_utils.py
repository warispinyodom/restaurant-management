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
# STAFF DATABASE UTILITIES & HELPERS
# ==========================================

def to_float(val, default=0.0):
    """แปลงค่าเป็น float อย่างปลอดภัย ป้องกันกรณี None หรือ String ว่าง"""
    try:
        return float(val) if val is not None and val != "" else default
    except (ValueError, TypeError):
        return default


def sanitize_order_items(order):
    """
    ตรวจสอบและทำความสะอาดโครงสร้างข้อมูล Order ให้ปลอดภัย 100%
    ป้องกันการเกิด Error 'builtin_function_or_method' object is not iterable
    """
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
    """ดึงข้อมูลรายการออเดอร์ทั้งหมดจาก Firebase และเรียงลำดับตามเวลาล่าสุด"""
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
    """อัปเดตสถานะออเดอร์ในฐานข้อมูล Firebase"""
    return patch_firebase_data('orders', order_id, {
        'status': status,
        'updated_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })


def get_staff_status():
    """ดึงสถานะความพร้อมของพนักงาน (ready, busy, break, offline)"""
    try:
        status_data = get_firebase_data('staff_status')
        if isinstance(status_data, dict):
            return status_data.get('status', 'ready')
        return 'ready'
    except Exception:
        return 'ready'


def update_staff_status_db(status):
    """บันทึกการเปลี่ยนสถานะของพนักงานลง Firebase"""
    return patch_firebase_data('staff_status', 'main', {
        'status': status, 
        'updated_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })


def get_all_menus():
    """ดึงข้อมูลรายการเมนูอาหารทั้งหมด"""
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
    """อัปเดตข้อมูลเมนูอาหารเฉพาะรายการ"""
    return patch_firebase_data('menus', menu_id, fields)


def bulk_update_menu_items_db(items_dict):
    """อัปเดตข้อมูลเมนูอาหารหลายรายการพร้อมกัน"""
    if not isinstance(items_dict, dict):
        return False
    success = True
    for menu_id, fields in items_dict.items():
        if isinstance(fields, dict):
            if not patch_firebase_data('menus', menu_id, fields):
                success = False
    return success


def get_bill_by_table(table_no):
    """ดึงรายการออเดอร์ค้างชำระของโต๊ะที่ระบุ"""
    orders = get_all_orders()
    table_orders = [
        o for o in orders 
        if isinstance(o, dict) 
        and str(o.get('table_no', '')) == str(table_no) 
        and str(o.get('status', '')).lower() not in ['completed', 'paid', 'voided', 'cancelled']
    ]
    return table_orders


def get_all_tables():
    """ดึงข้อมูลโต๊ะทั้งหมดและเรียงตามหมายเลขโต๊ะ"""
    try:
        raw_tables = get_firebase_data('tables')
        tables = parse_firebase_data(raw_tables)
        if not isinstance(tables, list):
            if isinstance(tables, dict):
                tables = [{'id': k, **v} if isinstance(v, dict) else {'id': k, 'val': v} for k, v in tables.items()]
            else:
                tables = []
        valid_tables = [t for t in tables if isinstance(t, dict)]
        valid_tables.sort(key=lambda x: str(x.get('table_no', '')))
        return valid_tables
    except Exception as e:
        print(f"Error in get_all_tables: {e}")
        return []


def get_all_service_requests():
    """ดึงข้อมูลคำขอเรียกพนักงานจากฝั่งลูกค้าอย่างครอบคลุมทุก Node และรูปแบบ"""
    try:
        # ค้นหาจากทั้ง service_requests, service_calls และ calls เพื่อป้องกัน Path ไม่ตรง
        raw_requests = get_firebase_data('service_requests')
        if not raw_requests:
            raw_requests = get_firebase_data('service_calls')
        if not raw_requests:
            raw_requests = get_firebase_data('calls')

        requests = parse_firebase_data(raw_requests)
        
        req_list = []
        if isinstance(requests, dict):
            for k, v in requests.items():
                if isinstance(v, dict):
                    req_list.append({'id': k, **v})
                else:
                    req_list.append({'id': k, 'val': v})
        elif isinstance(requests, list):
            for idx, r in enumerate(requests):
                if isinstance(r, dict):
                    if 'id' not in r:
                        r['id'] = str(idx)
                    req_list.append(r)
        elif raw_requests and isinstance(raw_requests, dict):
            for k, v in raw_requests.items():
                if isinstance(v, dict):
                    req_list.append({'id': k, **v})

        valid_requests = [r for r in req_list if isinstance(r, dict)]
        valid_requests.sort(key=lambda x: str(x.get('created_at') or x.get('timestamp') or x.get('time') or x.get('id') or ''), reverse=True)
        return valid_requests
    except Exception as e:
        print(f"Error in get_all_service_requests: {e}")
        return []


def get_member_by_phone(phone):
    """ค้นหาข้อมูลสมาชิกด้วยเบอร์โทรศัพท์"""
    try:
        raw_members = get_firebase_data('members')
        members = parse_firebase_data(raw_members)
        if isinstance(members, dict):
            members = [{'id': k, **v} if isinstance(v, dict) else {'id': k, 'val': v} for k, v in members.items()]
        if isinstance(members, list):
            clean_phone = str(phone).strip().replace('-', '')
            for m in members:
                if isinstance(m, dict):
                    m_phone = str(m.get('phone', '')).strip().replace('-', '')
                    if m_phone == clean_phone:
                        return m
        return None
    except Exception as e:
        print(f"Error in get_member_by_phone: {e}")
        return None


def get_daily_sales_summary(date_str=None):
    """คำนวณสรุปยอดขายประจำวันสำหรับพนักงาน"""
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")
    
    orders = get_all_orders()
    completed_orders = []
    
    for o in orders:
        status = str(o.get('status', '')).lower()
        paid_at = str(o.get('paid_at') or o.get('created_at') or '')
        if status in ['completed', 'paid'] and paid_at.startswith(date_str):
            completed_orders.append(o)
            
    total_sales = sum(to_float(o.get('total_amount') or o.get('total_price')) for o in completed_orders)
    total_orders = len(completed_orders)
    
    payment_breakdown = {}
    for o in completed_orders:
        method = str(o.get('payment_method', 'เงินสด'))
        amt = to_float(o.get('total_amount') or o.get('total_price'))
        payment_breakdown[method] = payment_breakdown.get(method, 0.0) + amt
        
    return {
        'date': date_str,
        'total_sales': total_sales,
        'total_orders': total_orders,
        'payment_breakdown': payment_breakdown,
        'orders': completed_orders
    }


# ==========================================
# STAFF ROUTES & CONTROLLERS
# ==========================================

# --- 1. ORDERS MANAGEMENT ---

@staff_bp.route('/staff/orders')
@staff_required
def staff_orders():
    """หน้าจอแสดงรายการออเดอร์ทั้งหมดสำหรับพนักงาน"""
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
    """API สำหรับดึงรายการออเดอร์แบบ Real-time / AJAX"""
    try:
        orders = get_all_orders() or []
        return jsonify({'status': 'success', 'orders': orders})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@staff_bp.route('/staff/order/update-status', methods=['POST'])
@staff_bp.route('/staff/order/update-status/<order_id>', methods=['POST'])
@staff_required
def update_order_status(order_id=None):
    """อัปเดตสถานะออเดอร์ (pending -> cooking -> served -> completed / cancelled)"""
    try:
        if request.is_json:
            data = request.get_json(silent=True) or {}
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


@staff_bp.route('/staff/order/create', methods=['POST'])
@staff_required
def staff_create_order():
    """สร้างออเดอร์ใหม่โดยพนักงาน (สั่งอาหารแทนลูกค้า / หน้าร้าน / Takeaway)"""
    try:
        data = request.get_json(silent=True) if request.is_json else request.form.to_dict()
        table_no = data.get('table_no')
        order_type = data.get('order_type', 'dine_in')
        items = data.get('items', [])
        
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
            'created_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        res = post_firebase_data('orders', new_order)
        
        if order_type == 'dine_in' and table_no:
            tables = get_all_tables()
            for t in tables:
                if str(t.get('table_no', '')) == str(table_no):
                    patch_firebase_data('tables', t.get('id'), {'status': 'occupied'})
                    
        return jsonify({'status': 'success', 'message': 'สร้างออเดอร์เรียบร้อยแล้ว', 'data': res})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@staff_bp.route('/staff/order/item/cancel', methods=['POST'])
@staff_required
def cancel_order_item():
    """ยกเลิกเฉพาะบางรายการสินค้าในออเดอร์"""
    try:
        data = request.get_json(silent=True) if request.is_json else request.form.to_dict()
        order_id = data.get('order_id')
        item_index = data.get('item_index')

        if not order_id or item_index is None:
            return jsonify({'status': 'error', 'message': 'ข้อมูลระบุออเดอร์ไม่ครบถ้วน'}), 400

        item_idx = int(item_index)
        raw_order = get_firebase_data(f'orders/{order_id}')
        order = parse_firebase_data(raw_order) if raw_order else None

        if not order or not isinstance(order, dict):
            return jsonify({'status': 'error', 'message': 'ไม่พบออเดอร์ที่ต้องการ'}), 404

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


@staff_bp.route('/staff/status/update', methods=['POST'])
@staff_required
def update_staff_status():
    """เปลี่ยนสถานะการทำงานของพนักงาน"""
    try:
        if request.is_json:
            data = request.get_json(silent=True) or {}
        else:
            data = request.form.to_dict() or {}

        new_status = data.get('status', 'ready')
        session['staff_status'] = new_status
        update_staff_status_db(new_status)
        return jsonify({'status': 'success', 'message': f'เปลี่ยนสถานะพนักงานเป็น {new_status} สำเร็จ', 'staff_status': new_status})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# --- 2. CHECK BILL & PAYMENT MANAGEMENT ---

@staff_bp.route('/staff/check-bill')
@staff_required
def staff_check_bill():
    """หน้าจอเช็คบิลและรับชำระเงิน"""
    try:
        orders = get_all_orders() or []
        unpaid_orders = [
            o for o in orders 
            if isinstance(o, dict) and str(o.get('status', '')).lower() not in ['completed', 'paid', 'voided', 'cancelled']
        ]
        
        tables = get_all_tables()
        
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
    """API ดึงข้อมูลยอดค้างชำระ โต๊ะ และช่องทางชำระเงิน"""
    try:
        orders = get_all_orders() or []
        unpaid_orders = [
            o for o in orders 
            if isinstance(o, dict) and str(o.get('status', '')).lower() not in ['completed', 'paid', 'voided', 'cancelled']
        ]

        tables = get_all_tables()

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
    """บันทึกการชำระเงิน คำนวณส่วนลด ทิป ภาษี แต้มสะสม และปรับสถานะโต๊ะ/ออเดอร์"""
    try:
        if request.is_json:
            data = request.get_json(silent=True) or {}
        else:
            data = request.form.to_dict() or {}

        order_id = data.get('order_id') or data.get('id')
        table_id = data.get('table_id')
        table_no = data.get('table_no')
        payment_method = data.get('payment_method', 'เงินสด')
        member_phone = data.get('member_phone')

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

        if not order_id and not table_no:
            return jsonify({'status': 'error', 'message': 'กรุณาระบุออเดอร์หรือโต๊ะที่ต้องการชำระเงิน'}), 400

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

        if member_phone:
            order_update['member_phone'] = member_phone

        if order_id:
            patch_firebase_data('orders', order_id, order_update)

        if table_no or table_id:
            orders = get_all_orders()
            for o in orders:
                if str(o.get('table_no', '')) == str(table_no) and str(o.get('status', '')).lower() not in ['completed', 'paid', 'voided', 'cancelled']:
                    patch_firebase_data('orders', o.get('id'), order_update)

            if table_id:
                patch_firebase_data('tables', table_id, {
                    'status': 'available',
                    'order': {'items': [], 'total_amount': 0.0}
                })
            elif table_no:
                tables = get_all_tables()
                for t in tables:
                    if str(t.get('table_no', '')) == str(table_no):
                        patch_firebase_data('tables', t.get('id'), {
                            'status': 'available',
                            'order': {'items': [], 'total_amount': 0.0}
                        })

        if member_phone:
            member = get_member_by_phone(member_phone)
            if member:
                earned_points = int(total_amount // 25)
                current_points = int(member.get('points', 0))
                patch_firebase_data('members', member.get('id'), {
                    'points': current_points + earned_points,
                    'last_visited': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })

        return jsonify({'status': 'success', 'message': 'ชำระเงินและปิดบิลเรียบร้อยแล้ว', 'order_id': order_id})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@staff_bp.route('/staff/receipt/<order_id>')
@staff_required
def get_receipt(order_id):
    """ดึงข้อมูลใบเสร็จรับเงินสำหรับสั่งพิมพ์หรือแสดงผล"""
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


# --- 3. TABLES MANAGEMENT ---

@staff_bp.route('/staff/tables')
@staff_required
def staff_tables():
    """หน้าผังโต๊ะอาหารสำหรับพนักงาน"""
    try:
        tables = get_all_tables()
        return render_template('admin/tables.html', tables=tables)
    except Exception as e:
        print(f"Error staff_tables: {e}")
        flash(f"เกิดข้อผิดพลาดในการโหลดผังโต๊ะ: {str(e)}", "error")
        return render_template('admin/tables.html', tables=[])


@staff_bp.route('/staff/table/clear/<table_id>', methods=['POST'])
@staff_required
def staff_clear_table(table_id):
    """เคลียร์สถานะโต๊ะกลับเป็นว่าง (available)"""
    try:
        payload = {
            'status': 'available',
            'order': {'items': [], 'total_amount': 0.0}
        }
        if patch_firebase_data('tables', table_id, payload):
            return jsonify({'status': 'success', 'message': 'เคลียร์โต๊ะเรียบร้อยแล้ว'})
        return jsonify({'status': 'error', 'message': 'ไม่สามารถเคลียร์โต๊ะได้'}), 500
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@staff_bp.route('/staff/table/update-status', methods=['POST'])
@staff_required
def staff_update_table_status():
    """ปรับเปลี่ยนสถานะของโต๊ะ (available, occupied, reserved, cleaning)"""
    try:
        data = request.get_json(silent=True) if request.is_json else request.form.to_dict()
        table_id = data.get('table_id')
        new_status = data.get('status', 'available')

        if not table_id:
            return jsonify({'status': 'error', 'message': 'ไม่พบ ID ของโต๊ะ'}), 400

        if patch_firebase_data('tables', table_id, {'status': new_status}):
            return jsonify({'status': 'success', 'message': f'อัปเดตสถานะโต๊ะเป็น {new_status} เรียบร้อย'})
        return jsonify({'status': 'error', 'message': 'ไม่สามารถอัปเดตสถานะโต๊ะได้'}), 500
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@staff_bp.route('/staff/table/move', methods=['POST'])
@staff_required
def staff_move_table():
    """ย้ายออเดอร์จากโต๊ะต้นทางไปยังโต๊ะปลายทาง"""
    try:
        data = request.get_json(silent=True) if request.is_json else request.form.to_dict()
        from_table = data.get('from_table')
        to_table = data.get('to_table')

        if not from_table or not to_table:
            return jsonify({'status': 'error', 'message': 'กรุณาระบุโต๊ะต้นทางและปลายทาง'}), 400

        orders = get_all_orders()
        moved_count = 0

        for o in orders:
            if str(o.get('table_no', '')) == str(from_table) and str(o.get('status', '')).lower() not in ['completed', 'paid', 'voided', 'cancelled']:
                patch_firebase_data('orders', o.get('id'), {'table_no': to_table})
                moved_count += 1

        if moved_count > 0:
            tables = get_all_tables()
            for t in tables:
                t_no = str(t.get('table_no', ''))
                if t_no == str(from_table):
                    patch_firebase_data('tables', t.get('id'), {'status': 'available'})
                elif t_no == str(to_table):
                    patch_firebase_data('tables', t.get('id'), {'status': 'occupied'})

            return jsonify({'status': 'success', 'message': f'ย้ายออเดอร์จากโต๊ะ {from_table} ไปยังโต๊ะ {to_table} สำเร็จ'})
        
        return jsonify({'status': 'error', 'message': f'ไม่พบออเดอร์ที่ค้างชำระในโต๊ะ {from_table}'}), 404
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@staff_bp.route('/staff/table/merge', methods=['POST'])
@staff_required
def staff_merge_tables():
    """รวมบิล/ออเดอร์จากโต๊ะต้นทาง เข้าสู่โต๊ะปลายทาง"""
    try:
        data = request.get_json(silent=True) if request.is_json else request.form.to_dict()
        source_table = data.get('source_table')
        target_table = data.get('target_table')

        if not source_table or not target_table:
            return jsonify({'status': 'error', 'message': 'กรุณาระบุโต๊ะที่จะนำมารวม'}), 400

        orders = get_all_orders()
        source_orders = [o for o in orders if str(o.get('table_no', '')) == str(source_table) and str(o.get('status', '')).lower() not in ['completed', 'paid', 'voided', 'cancelled']]

        if not source_orders:
            return jsonify({'status': 'error', 'message': f'ไม่พบออเดอร์ที่โต๊ะ {source_table}'}), 404

        for o in source_orders:
            patch_firebase_data('orders', o.get('id'), {'table_no': target_table, 'merged_from': source_table})

        tables = get_all_tables()
        for t in tables:
            if str(t.get('table_no', '')) == str(source_table):
                patch_firebase_data('tables', t.get('id'), {'status': 'available'})

        return jsonify({'status': 'success', 'message': f'รวมโต๊ะ {source_table} เข้ากับโต๊ะ {target_table} เรียบร้อยแล้ว'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# --- 4. MENU MANAGEMENT ---

@staff_bp.route('/staff/menu-manage')
@staff_bp.route('/staff/menu')
@staff_required
def staff_menu_manage():
    """หน้าจัดการเมนูอาหาร (เปิด/ปิดสถานะเมนู ปรับราคา สต็อก)"""
    try:
        menus = get_all_menus() or []
        return render_template('staff/menu_manage.html', menus=menus)
    except Exception as e:
        print(f"Error staff_menu_manage: {e}")
        flash(f"เกิดข้อผิดพลาดในการโหลดข้อมูลเมนู: {str(e)}", "error")
        return render_template('staff/menu_manage.html', menus=[])


@staff_bp.route('/staff/api/menus')
@staff_required
def api_staff_menus():
    """API ดึงรายการเมนูทั้งหมด"""
    try:
        menus = get_all_menus() or []
        return jsonify({'status': 'success', 'menus': menus})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@staff_bp.route('/staff/menu/update-status', methods=['POST'])
@staff_required
def update_menu_status():
    """สลับสถานะเปิด/ปิดขายเมนูอาหาร"""
    try:
        if request.is_json:
            data = request.get_json(silent=True) or {}
        else:
            data = request.form.to_dict() or {}

        menu_id = data.get('menu_id') or data.get('id')
        is_available = data.get('is_available')

        if not menu_id:
            return jsonify({'status': 'error', 'message': 'ไม่พบ ID ของเมนู'}), 400

        if update_menu_item_db(menu_id, {'is_available': is_available}):
            return jsonify({'status': 'success', 'message': 'อัปเดตสถานะเมนูสำเร็จ'})
        return jsonify({'status': 'error', 'message': 'ไม่สามารถอัปเดตสถานะเมนูได้'}), 500
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@staff_bp.route('/staff/menu/quick-update/<menu_id>', methods=['POST'])
@staff_required
def quick_update_menu(menu_id):
    """ปรับแก้ไข ราคา ส่วนลด สต็อก ของเมนูแบบเร่งด่วน"""
    try:
        if request.is_json:
            data = request.get_json(silent=True) or {}
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
    """อัปเดตข้อมูลเมนูอาหารหลายรายการพร้อมกัน"""
    try:
        if request.is_json:
            data = request.get_json(silent=True) or {}
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


# --- 5. SERVICE REQUESTS MANAGEMENT ---

@staff_bp.route('/staff/service-requests')
@staff_required
def staff_service_requests_page():
    """หน้าจอรายการการเรียกพนักงานจากลูกค้า"""
    try:
        requests = get_all_service_requests() or []
        return render_template('staff/service_requests.html', service_requests=requests)
    except Exception as e:
        return render_template('staff/service_requests.html', service_requests=[])


@staff_bp.route('/staff/api/service-requests')
@staff_required
def api_staff_service_requests():
    """API สำหรับดึงรายการเรียกพนักงานจากลูกค้าแบบ Real-time"""
    try:
        requests = get_all_service_requests() or []
        pending_requests = [
            r for r in requests 
            if isinstance(r, dict) and str(r.get('status', 'pending')).lower() not in ['completed', 'done', 'resolved', 'finish']
        ]
        return jsonify({'status': 'success', 'requests': requests, 'pending_requests': pending_requests})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@staff_bp.route('/staff/service-request/update-status', methods=['POST'])
@staff_required
def update_service_request_status():
    """อัปเดตสถานะการเข้าช่วยเหลือลูกค้า (pending -> completed)"""
    try:
        data = request.get_json(silent=True) if request.is_json else request.form.to_dict()
        request_id = data.get('request_id') or data.get('id')
        new_status = data.get('status', 'completed')

        if not request_id:
            return jsonify({'status': 'error', 'message': 'ไม่ระบุ ID ของรายการเรียกร้อง'}), 400

        update_payload = {
            'status': new_status,
            'handled_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        patch_firebase_data('service_requests', request_id, update_payload)
        patch_firebase_data('service_calls', request_id, update_payload)
        patch_firebase_data('calls', request_id, update_payload)

        return jsonify({'status': 'success', 'message': 'อัปเดตสถานะการเรียกพนักงานเรียบร้อย'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# --- 6. MEMBER & LOYALTY SYSTEM ---

@staff_bp.route('/staff/api/member/search', methods=['GET', 'POST'])
@staff_required
def api_search_member():
    """ค้นหาข้อมูลสมาชิกจากเบอร์โทรศัพท์สำหรับรับส่วนลด/แต้มสะสม"""
    try:
        phone = request.args.get('phone') if request.method == 'GET' else (request.get_json(silent=True) or {}).get('phone')
        if not phone:
            return jsonify({'status': 'error', 'message': 'กรุณาระบุเบอร์โทรศัพท์'}), 400
            
        member = get_member_by_phone(phone)
        if member:
            return jsonify({'status': 'success', 'member': member})
        return jsonify({'status': 'error', 'message': 'ไม่พบข้อมูลสมาชิกในระบบ'}), 404
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# --- 7. DAILY SALES SUMMARY ---

@staff_bp.route('/staff/daily-summary', methods=['GET'])
@staff_required
def staff_daily_summary():
    """สรุปยอดขายประจำวันสำหรับพนักงาน"""
    try:
        date_str = request.args.get('date', datetime.now().strftime("%Y-%m-%d"))
        summary = get_daily_sales_summary(date_str)
        if request.args.get('json') == '1':
            return jsonify({'status': 'success', 'data': summary})
        return render_template('staff/daily_summary.html', summary=summary)
    except Exception as e:
        print(f"Error staff_daily_summary: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500