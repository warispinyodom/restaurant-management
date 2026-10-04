from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from firebase_utils import (
    get_firebase_data, 
    post_firebase_data, 
    patch_firebase_data, 
    parse_firebase_data, 
    DEFAULT_CATEGORIES
)

customer_bp = Blueprint('customer', __name__)

# API สำหรับดึงข้อมูลโต๊ะของระบบ
@customer_bp.route('/api/tables')
def api_get_tables():
    raw_tables = get_firebase_data('tables')
    tables = parse_firebase_data(raw_tables)
    return jsonify({'status': 'success', 'tables': tables})

@customer_bp.route('/customer')
def customer_dashboard():
    if session.get('role') != 'customer':
        flash("หน้านี้สำหรับลูกค้าเท่านั้น", "error")
        return redirect(url_for('home'))
    
    try:
        raw_menus = get_firebase_data('menus')
        menus = [
            m for m in parse_firebase_data(raw_menus) 
            if str(m.get('status')).lower() in ['available', 'true', 'active'] or m.get('is_available') is True
        ]
        
        existing_cats = set(m.get('category') for m in menus if m.get('category'))
        categories = [c for c in DEFAULT_CATEGORIES if c in existing_cats]
        for cat in existing_cats:
            if cat not in categories:
                categories.append(cat)

        raw_payments = get_firebase_data('payment_channels')
        payments = [
            p for p in parse_firebase_data(raw_payments) 
            if str(p.get('is_active')).lower() in ['1', 'true', 'on'] or p.get('is_active') == 1
        ]
    except Exception as e:
        print(f"Error loading customer data: {e}")
        menus, payments, categories = [], [], []
        flash("เกิดข้อผิดพลาดในการโหลดข้อมูลร้านค้า กรุณารีเฟรชหน้าเว็บ", "error")
    
    selected_table_no = session.get('selected_table_no', None)
    return render_template('customer/customer.html', menus=menus, payments=payments, categories=categories, selected_table_no=selected_table_no)

@customer_bp.route('/customer/choose_table', methods=['GET', 'POST'])
@customer_bp.route('/customer/choose-table', methods=['GET', 'POST'])
def customer_choose_table():
    if session.get('role') != 'customer':
        flash("หน้านี้สำหรับลูกค้าเท่านั้น", "error")
        return redirect(url_for('home'))

    if request.method == 'POST':
        table_id = request.form.get('table_id')
        table_no = request.form.get('table_no')

        if not table_id:
            flash("กรุณาเลือกโต๊ะก่อนดำเนินการต่อ", "error")
            return redirect(url_for('customer.customer_choose_table'))

        current_table = get_firebase_data(f'tables/{table_id}')
        if not current_table or current_table.get('status') != 'available':
            flash(f"ขออภัย โต๊ะ {table_no} ถูกใช้งานหรือถูกจองแล้ว กรุณาเลือกโต๊ะอื่น", "error")
            return redirect(url_for('customer.customer_choose_table'))

        session['selected_table_id'] = table_id
        session['selected_table_no'] = table_no

        patch_firebase_data('tables', table_id, {'status': 'occupied'})

        flash(f"เลือกโต๊ะ {table_no} เรียบร้อยแล้ว สามารถสั่งอาหารได้เลยครับ", "success")
        return redirect(url_for('customer.customer_dashboard'))

    try:
        raw_tables = get_firebase_data('tables')
        tables = parse_firebase_data(raw_tables)
        tables.sort(key=lambda x: str(x.get('table_no', '')))
    except Exception as e:
        print(f"Error loading tables for customer: {e}")
        tables = []
        flash("เกิดข้อผิดพลาดในการโหลดข้อมูลโต๊ะอาหาร", "error")

    return render_template('customer/choose_tables.html', tables=tables)

@customer_bp.route('/customer/checkout', methods=['POST'])
def customer_checkout():
    if session.get('role') != 'customer':
        return jsonify({'status': 'error', 'message': 'ไม่มีสิทธิ์เข้าถึง'}), 403

    data = request.get_json() or {}
    
    raw_total = data.get('total_amount') or data.get('total_price')
    try:
        total_amount = float(raw_total) if raw_total is not None else 0.0
    except (ValueError, TypeError):
        total_amount = 0.0

    raw_count = data.get('customer_count')
    try:
        customer_count = int(raw_count) if raw_count is not None else 1
        if customer_count < 1:
            customer_count = 1
    except (ValueError, TypeError):
        customer_count = 1

    payment_method = data.get('payment_method', 'เงินสด')
    items = data.get('items', []) 
    table_no = data.get('table_no') or session.get('selected_table_no', 'ไม่ระบุ')

    if not items:
        return jsonify({'status': 'error', 'message': 'ไม่มีสินค้าในตะกร้า'}), 400

    try:
        payload = {
            "table_no": table_no,
            "table_id": session.get('selected_table_id', ''),
            "customer_count": customer_count,
            "total_amount": total_amount,
            "total_price": total_amount,
            "payment_method": payment_method,
            "status": "pending",
            "items": items,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        response = post_firebase_data('orders', payload)
        if response and 'name' in response:
            return jsonify({
                'status': 'success', 
                'message': 'สั่งอาหารสำเร็จ! กรุณารอสักครู่', 
                'order_id': response.get('name')
            })
        else:
            raise Exception("Firebase Response Error")

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500