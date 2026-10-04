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
    customer_count = session.get('customer_count', 1)
    if not isinstance(customer_count, int) or customer_count < 1:
        customer_count = 1

    return render_template(
        'customer/customer.html', 
        menus=menus, 
        payments=payments, 
        categories=categories, 
        selected_table_no=selected_table_no,
        customer_count=customer_count
    )

@customer_bp.route('/customer/choose_table', methods=['GET', 'POST'])
@customer_bp.route('/customer/choose-table', methods=['GET', 'POST'])
def customer_choose_table():
    if session.get('role') != 'customer':
        flash("หน้านี้สำหรับลูกค้าเท่านั้น", "error")
        return redirect(url_for('home'))

    if request.method == 'POST':
        action = request.form.get('action', 'select')

        # ----------------------------------------------------
        # กรณีที่ 1: ยกเลิกการเลือกโต๊ะอาหาร
        # ----------------------------------------------------
        if action == 'cancel':
            selected_ids = session.get('selected_table_ids', [])
            
            # หากมี ID เดียวเดิมที่เก็บเป็น string ให้แปลงเป็น list
            if not selected_ids and session.get('selected_table_id'):
                selected_ids = [session.get('selected_table_id')]

            # คืนสถานะโต๊ะใน Firebase เป็น available
            for tid in selected_ids:
                if tid:
                    patch_firebase_data('tables', tid, {'status': 'available'})

            # ล้างค่า Session เกี่ยวกับโต๊ะทั้งหมด
            session.pop('selected_table_id', None)
            session.pop('selected_table_ids', None)
            session.pop('selected_table_no', None)
            session.pop('selected_table_nos', None)
            session.pop('customer_count', None)

            flash("ยกเลิกการเลือกโต๊ะอาหารเรียบร้อยแล้ว", "success")
            return redirect(url_for('customer.customer_choose_table'))

        # ----------------------------------------------------
        # กรณีที่ 2: ยืนยันเลือกโต๊ะอาหาร (รองรับหลายโต๊ะ)
        # ----------------------------------------------------
        table_ids = request.form.getlist('table_ids')
        try:
            customer_count = int(request.form.get('customer_count', 1))
            if customer_count < 1:
                customer_count = 1
        except (ValueError, TypeError):
            customer_count = 1

        if not table_ids:
            flash("กรุณาเลือกโต๊ะอาหารอย่างน้อย 1 โต๊ะ", "error")
            return redirect(url_for('customer.customer_choose_table'))

        # โหลดข้อมูลโต๊ะทั้งหมดเพื่อตรวจสอบความถูกต้อง
        raw_tables = get_firebase_data('tables')
        all_tables = parse_firebase_data(raw_tables)
        tables_map = {str(t.get('id')): t for t in all_tables}

        # หากมีโต๊ะเดิมที่เคยเลือกไว้ ให้คืนสถานะก่อน
        old_ids = session.get('selected_table_ids', [])
        if not old_ids and session.get('selected_table_id'):
            old_ids = [session.get('selected_table_id')]
        for old_id in old_ids:
            if old_id and old_id not in table_ids:
                patch_firebase_data('tables', old_id, {'status': 'available'})

        selected_nos = []
        for tid in table_ids:
            table_info = tables_map.get(str(tid))
            if not table_info:
                flash("พบข้อมูลโต๊ะไม่ถูกต้อง กรุณาลองใหม่อีกครั้ง", "error")
                return redirect(url_for('customer.customer_choose_table'))
            
            # ตรวจสอบสถานะ (หากถูกผู้อื่นเลือกไปแล้ว และไม่ใช่โต๊ะที่เราเลือกอยู่เดิม)
            if table_info.get('status') != 'available' and tid not in old_ids:
                flash(f"ขออภัย โต๊ะ {table_info.get('table_no')} ถูกใช้งานหรือถูกจองแล้ว", "error")
                return redirect(url_for('customer.customer_choose_table'))
            
            selected_nos.append(str(table_info.get('table_no', '')))

        # อัปเดตสถานะโต๊ะใหม่ใน Firebase เป็น occupied
        for tid in table_ids:
            patch_firebase_data('tables', tid, {'status': 'occupied'})

        # บันทึกลงใน Session
        session['selected_table_ids'] = table_ids
        session['selected_table_id'] = table_ids[0] if table_ids else ''
        session['selected_table_nos'] = selected_nos
        session['selected_table_no'] = ", ".join(selected_nos)
        session['customer_count'] = customer_count

        flash(f"เลือกโต๊ะ {session['selected_table_no']} (จำนวน {customer_count} ท่าน) เรียบร้อยแล้ว", "success")
        return redirect(url_for('customer.customer_dashboard'))

    # GET Request: แสดงรายการโต๊ะ
    try:
        raw_tables = get_firebase_data('tables')
        tables = parse_firebase_data(raw_tables)
        
        # เรียงลำดับหมายเลขโต๊ะแบบเป็นระเบียบ
        def sort_key(t):
            no = str(t.get('table_no', ''))
            digits = ''.join(filter(str.isdigit, no))
            return int(digits) if digits else no
            
        tables.sort(key=sort_key)
    except Exception as e:
        print(f"Error loading tables for customer: {e}")
        tables = []
        flash("เกิดข้อผิดพลาดในการโหลดข้อมูลโต๊ะอาหาร", "error")

    # ข้อมูลสถานะเดิมของ Session เพื่อแสดงผลใน UI
    current_selected_ids = session.get('selected_table_ids', [])
    if not current_selected_ids and session.get('selected_table_id'):
        current_selected_ids = [session.get('selected_table_id')]

    current_selected_no = session.get('selected_table_no', '')
    
    raw_customer_count = session.get('customer_count', 1)
    try:
        current_customer_count = int(raw_customer_count)
        if current_customer_count < 1:
            current_customer_count = 1
    except (ValueError, TypeError):
        current_customer_count = 1

    return render_template(
        'customer/choose_tables.html', 
        tables=tables,
        current_selected_ids=current_selected_ids,
        current_selected_no=current_selected_no,
        current_customer_count=current_customer_count
    )

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

    raw_count = data.get('customer_count') or session.get('customer_count', 1)
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
            "table_ids": session.get('selected_table_ids', []),
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