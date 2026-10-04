from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash
from auth_utils import get_all_users, create_user
from staff_utils import get_all_orders
from firebase_utils import (
    get_firebase_data, 
    post_firebase_data, 
    patch_firebase_data, 
    delete_firebase_data, 
    parse_firebase_data,
    upload_to_firebase_storage,
    delete_from_firebase_storage,
    allowed_file,
    admin_required,
    staff_required,
    DEFAULT_CATEGORIES
)

admin_bp = Blueprint('admin', __name__)

# ==========================================
# DASHBOARD & STATS
# ==========================================
@admin_bp.route('/admin')
@admin_required
def admin_dashboard():
    try:
        return render_template('admin/dashboard.html', username=session.get('username'), role=session.get('role'))
    except Exception:
        # Fallback กรณีเก็บไฟล์ไว้ที่ templates/dashboard.html
        return render_template('dashboard.html', username=session.get('username'), role=session.get('role'))

@admin_bp.route('/api/admin/dashboard_stats')
@admin_required
def dashboard_stats():
    today = datetime.now()
    today_str = today.strftime("%Y-%m-%d")
    start_of_week = today - timedelta(days=today.weekday())
    
    weekly_sales = [0.0] * 7
    sales_today = 0.0
    customers_today = 0
    
    orders_list = get_all_orders() or []
    
    for order in orders_list:
        if isinstance(order, dict):
            created_at = str(order.get('created_at') or '')
            status = str(order.get('status', '')).lower()
            
            if status in ['completed', 'paid']:
                try:
                    tot = order.get('total_price') if order.get('total_price') is not None else order.get('total_amount')
                    if tot is None:
                        tot = order.get('total', 0)
                    amount = float(tot)
                except (ValueError, TypeError):
                    amount = 0.0
                
                # รองรับการแยกวันที่ทั้งรูปแบบ ISO ('T') และรูปแบบเว้นวรรค
                clean_date_str = created_at.replace('T', ' ').split(' ')[0]
                
                if clean_date_str == today_str:
                    sales_today += amount
                    try:
                        customers_today += int(order.get('customer_count', order.get('guests', 0)))
                    except (ValueError, TypeError):
                        pass
                
                if clean_date_str and clean_date_str != '-':
                    try:
                        order_date = datetime.strptime(clean_date_str, "%Y-%m-%d")
                        delta_days = (order_date.date() - start_of_week.date()).days
                        if 0 <= delta_days < 7:
                            weekly_sales[delta_days] += amount
                    except Exception:
                        pass

    all_users = get_all_users()
    active_staff = 0
    if isinstance(all_users, dict):
        active_staff = sum(
            1 for uid, u in all_users.items() 
            if isinstance(u, dict) and u.get('role') in ['staff', 'admin'] and u.get('is_active', True)
        )

    return jsonify({
        'sales_today': round(sales_today, 2),
        'customers_today': customers_today,
        'active_staff': active_staff,
        'weekly_sales': [round(x, 2) for x in weekly_sales]
    })

# ==========================================
# MENU MANAGEMENT
# ==========================================
@admin_bp.route('/admin/menu')
@admin_required
def admin_menu_list():
    try:
        raw_menus = get_firebase_data('menus')
        menus = parse_firebase_data(raw_menus)
    except Exception as e:
        print(f"Error loading admin menus: {e}")
        menus = []
        flash("เกิดข้อผิดพลาดในการโหลดข้อมูลเมนู", "error")
        
    return render_template('admin/menu.html', menus=menus, categories=DEFAULT_CATEGORIES)

@admin_bp.route('/admin/menu/add', methods=['POST'])
@admin_required
def admin_menu_add():
    try:
        st = request.form.get('status', 'available')
        
        try:
            price = float(request.form.get('price', 0))
        except (ValueError, TypeError):
            flash("ราคาอาหารไม่ถูกต้อง กรุณาระบุเป็นตัวเลข", "error")
            return redirect(url_for('admin.admin_menu_list'))

        payload = {
            'name': request.form.get('name', '').strip(),
            'category': request.form.get('category', ''),
            'price': price,
            'spice_level': request.form.get('spice_level', 'ไม่เผ็ด'),
            'size': request.form.get('size', 'ปกติ'),
            'status': st,
            'is_available': (st == 'available'),
            'image_file': None
        }

        file = request.files.get('image')
        if file and allowed_file(file.filename):
            payload['image_file'] = upload_to_firebase_storage(file, folder="menus")

        if post_firebase_data('menus', payload):
            flash("เพิ่มรายการอาหารเรียบร้อยแล้ว", "success")
        else:
            flash("เกิดข้อผิดพลาดในการเพิ่มรายการอาหาร", "error")
    except Exception as e:
        flash(f"เกิดข้อผิดพลาดในการเพิ่มเมนู: {str(e)}", "error")
        
    return redirect(url_for('admin.admin_menu_list'))

@admin_bp.route('/admin/menu/edit/<id>', methods=['POST'])
@admin_required
def admin_menu_edit(id):
    try:
        st = request.form.get('status', 'available')
        
        try:
            price = float(request.form.get('price', 0))
        except (ValueError, TypeError):
            flash("ราคาอาหารไม่ถูกต้อง กรุณาระบุเป็นตัวเลข", "error")
            return redirect(url_for('admin.admin_menu_list'))

        payload = {
            'name': request.form.get('name', '').strip(),
            'category': request.form.get('category', ''),
            'price': price,
            'spice_level': request.form.get('spice_level'),
            'size': request.form.get('size'),
            'status': st,
            'is_available': (st == 'available')
        }

        file = request.files.get('image')
        if file and allowed_file(file.filename):
            old_menu = get_firebase_data(f'menus/{id}')
            if old_menu and isinstance(old_menu, dict) and old_menu.get('image_file'):
                delete_from_firebase_storage(old_menu['image_file'])

            payload['image_file'] = upload_to_firebase_storage(file, folder="menus")

        if patch_firebase_data('menus', id, payload):
            flash("อัปเดตรายการอาหารสำเร็จ", "success")
        else:
            flash("เกิดข้อผิดพลาดในการแก้ไขรายการอาหาร", "error")
    except Exception as e:
        flash(f"เกิดข้อผิดพลาดในการแก้ไข: {str(e)}", "error")

    return redirect(url_for('admin.admin_menu_list'))

@admin_bp.route('/admin/menu/delete/<id>', methods=['POST'])
@admin_required
def admin_menu_delete(id):
    try:
        menu = get_firebase_data(f'menus/{id}')
        if menu and isinstance(menu, dict) and menu.get('image_file'):
            delete_from_firebase_storage(menu['image_file'])

        if delete_firebase_data('menus', id):
            return jsonify({'status': 'success', 'message': 'ลบเมนูเรียบร้อยแล้ว'})
        return jsonify({'status': 'error', 'message': 'เกิดข้อผิดพลาดในการลบ'}), 500
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ==========================================
# STAFF MANAGEMENT
# ==========================================
@admin_bp.route('/admin/staff')
@admin_required
def admin_staff_list():
    users_dict = get_all_users()
    staff_members = []
    if isinstance(users_dict, dict):
        for uid, user in users_dict.items():
            if isinstance(user, dict) and user.get('role') != 'customer':
                user['id'] = uid
                staff_members.append(user)
            
    return render_template('admin/staff.html', staff_members=staff_members)

@admin_bp.route('/admin/staff/add', methods=['POST'])
@admin_required
def admin_staff_add():
    try:
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        role = request.form.get('role', 'staff')

        if len(username) < 3 or len(password) < 4:
            flash("ชื่อผู้ใช้ต้องมีอย่างน้อย 3 ตัวอักษร และรหัสผ่าน 4 ตัวอักษร", "error")
            return redirect(url_for('admin.admin_staff_list'))

        users = get_all_users() or {}
        is_duplicate = any(
            info.get('username') == username 
            for uid, info in users.items() 
            if isinstance(info, dict)
        )
        if is_duplicate:
            flash("ชื่อผู้ใช้นี้มีในระบบแล้ว", "error")
            return redirect(url_for('admin.admin_staff_list'))

        hashed_password = generate_password_hash(password)
        if create_user(username, hashed_password, role):
            flash("เพิ่มพนักงานเข้าสู่ระบบสำเร็จ", "success")
        else:
            flash("เกิดข้อผิดพลาดในการบันทึกพนักงานลง Firebase", "error")

    except Exception as e:
        flash(f"เกิดข้อผิดพลาด: {str(e)}", "error")

    return redirect(url_for('admin.admin_staff_list'))

@admin_bp.route('/admin/staff/edit/<user_id>', methods=['POST'])
@admin_required
def admin_staff_edit(user_id):
    try:
        username = request.form.get('username', '').strip()
        role = request.form.get('role', 'staff')
        status_input = request.form.get('is_active', 'true')
        password = request.form.get('password', '').strip()

        if username:
            users = get_all_users()
            if isinstance(users, dict):
                is_duplicate = any(
                    info.get('username') == username 
                    for uid, info in users.items() 
                    if uid != user_id and isinstance(info, dict)
                )
                if is_duplicate:
                    flash("ชื่อผู้ใช้นี้มีในระบบแล้ว", "error")
                    return redirect(url_for('admin.admin_staff_list'))

        is_active = True if role == 'admin' else (str(status_input).lower() in ['true', 'on', '1'])

        update_data = {
            "role": role,
            "is_active": is_active
        }

        if username:
            update_data["username"] = username

        if password:
            update_data["password"] = generate_password_hash(password)

        if patch_firebase_data('users', user_id, update_data):
            flash("อัปเดตข้อมูลพนักงานสำเร็จ", "success")
        else:
            flash("ไม่สามารถอัปเดตข้อมูลไปยัง Firebase ได้", "error")

    except Exception as e:
        flash(f"เกิดข้อผิดพลาด: {str(e)}", "error")

    return redirect(url_for('admin.admin_staff_list'))

@admin_bp.route('/admin/staff/toggle-status/<user_id>', methods=['POST'])
@admin_required
def admin_staff_toggle_status(user_id):
    try:
        target_user = get_firebase_data(f"users/{user_id}")
        if isinstance(target_user, dict) and target_user.get('role') == 'admin':
            return jsonify({'status': 'error', 'message': 'ไม่สามารถเปลี่ยนสถานะผู้ดูแลระบบได้!'}), 400

        current_status = target_user.get('is_active', True) if isinstance(target_user, dict) else True
        new_status = not current_status

        if patch_firebase_data('users', user_id, {"is_active": new_status}):
            status_text = "เปิดใช้งาน" if new_status else "ถูกระงับ"
            return jsonify({'status': 'success', 'message': f'เปลี่ยนสถานะบัญชีเป็น "{status_text}" เรียบร้อยแล้ว'})

        return jsonify({'status': 'error', 'message': 'ไม่สามารถอัปเดตข้อมูลได้'}), 500
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@admin_bp.route('/admin/staff/delete/<id>', methods=['POST'])
@admin_required
def admin_staff_delete(id):
    try:
        if id == session.get('user_id'):
            return jsonify({'status': 'error', 'message': 'ไม่สามารถลบบัญชีของตัวเองที่กำลังใช้งานอยู่ได้'}), 400

        if delete_firebase_data('users', id):
            return jsonify({'status': 'success', 'message': 'ลบพนักงานเรียบร้อยแล้ว'})
        return jsonify({'status': 'error', 'message': 'เกิดข้อผิดพลาดในการลบ'}), 500
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ==========================================
# PAYMENT CHANNELS MANAGEMENT
# ==========================================
@admin_bp.route('/admin/payments')
@admin_required
def admin_payments_list():
    raw_payments = get_firebase_data('payment_channels')
    payments = parse_firebase_data(raw_payments)
    return render_template('admin/payment.html', payments=payments)

@admin_bp.route('/admin/payments/add', methods=['POST'])
@admin_required
def admin_payments_add():
    try:
        payload = {
            'bank_name': request.form.get('bank_name', '').strip(),
            'account_name': request.form.get('account_name', '').strip(),
            'promptpay_no': request.form.get('promptpay_no', '').strip(),
            'is_active': 1 if request.form.get('is_active') in ['on', 'true', '1'] else 0,
            'qr_image': None
        }

        file = request.files.get('qr_image')
        if not file or not allowed_file(file.filename):
            flash("กรุณาอัปโหลดรูปภาพ QR Code ที่ถูกต้อง", "error")
            return redirect(url_for('admin.admin_payments_list'))

        payload['qr_image'] = upload_to_firebase_storage(file, folder="payments")

        if post_firebase_data('payment_channels', payload):
            flash("เพิ่มช่องทางชำระเงินสำเร็จ", "success")
        else:
            flash("เกิดข้อผิดพลาดในการเพิ่มช่องทาง", "error")
    except Exception as e:
        flash(f"เกิดข้อผิดพลาด: {str(e)}", "error")

    return redirect(url_for('admin.admin_payments_list'))

@admin_bp.route('/admin/payments/edit/<id>', methods=['POST'])
@admin_required
def admin_payments_edit(id):
    try:
        payload = {
            'bank_name': request.form.get('bank_name', '').strip(),
            'account_name': request.form.get('account_name', '').strip(),
            'promptpay_no': request.form.get('promptpay_no', '').strip(),
            'is_active': 1 if request.form.get('is_active') in ['on', 'true', '1'] else 0
        }

        file = request.files.get('qr_image')
        if file and allowed_file(file.filename):
            old_payment = get_firebase_data(f'payment_channels/{id}')
            if old_payment and isinstance(old_payment, dict) and old_payment.get('qr_image'):
                delete_from_firebase_storage(old_payment['qr_image'])

            payload['qr_image'] = upload_to_firebase_storage(file, folder="payments")

        if patch_firebase_data('payment_channels', id, payload):
            flash("อัปเดตช่องทางชำระเงินสำเร็จ", "success")
        else:
            flash("เกิดข้อผิดพลาดในการอัปเดตช่องทาง", "error")
    except Exception as e:
        flash(f"เกิดข้อผิดพลาด: {str(e)}", "error")

    return redirect(url_for('admin.admin_payments_list'))

@admin_bp.route('/admin/payments/delete/<id>', methods=['POST'])
@admin_required
def admin_payments_delete(id):
    try:
        payment = get_firebase_data(f'payment_channels/{id}')
        if payment and isinstance(payment, dict) and payment.get('qr_image'):
            delete_from_firebase_storage(payment['qr_image'])

        if delete_firebase_data('payment_channels', id):
            return jsonify({'status': 'success', 'message': 'ลบช่องทางชำระเงินเรียบร้อยแล้ว'})
        return jsonify({'status': 'error', 'message': 'เกิดข้อผิดพลาดในการลบ'}), 500
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ==========================================
# SALES HISTORY & ORDERS
# ==========================================
@admin_bp.route('/admin/sales')
@admin_required
def admin_sales_history():
    raw_orders = get_firebase_data('orders')
    orders = parse_firebase_data(raw_orders)
    orders.sort(key=lambda x: str(x.get('created_at') or ''), reverse=True)
    return render_template('admin/sales.html', orders=orders)

@admin_bp.route('/admin/sales/void/<id>', methods=['POST'])
@admin_required
def admin_sales_void(id):
    try:
        if patch_firebase_data('orders', id, {'status': 'voided'}):
            return jsonify({'status': 'success', 'message': 'ยกเลิกรายการสั่งซื้อเรียบร้อยแล้ว'})
        return jsonify({'status': 'error', 'message': 'เกิดข้อผิดพลาดในการยกเลิกออเดอร์'}), 500
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ==========================================
# TABLE MANAGEMENT ROUTES
# ==========================================
def _table_sort_key(table):
    """ฟังก์ชันจัดเรียงเลขโต๊ะให้ถูกต้องตามหลักตัวเลข (เช่น 1, 2, 10)"""
    val = str(table.get('table_no', ''))
    if val.isdigit():
        return (0, int(val), val)
    return (1, 0, val)

@admin_bp.route('/admin/tables')
@staff_required
def admin_tables_list():
    try:
        raw_tables = get_firebase_data('tables')
        tables = parse_firebase_data(raw_tables)
        tables.sort(key=_table_sort_key)
    except Exception as e:
        print(f"Error loading tables: {e}")
        tables = []
        flash("เกิดข้อผิดพลาดในการโหลดข้อมูลโต๊ะอาหาร", "error")

    return render_template('admin/tables.html', tables=tables)

@admin_bp.route('/admin/tables/add', methods=['POST'])
@admin_required
def admin_table_add():
    try:
        add_type = request.form.get('add_type', 'single')
        
        if add_type == 'bulk':
            prefix = request.form.get('prefix', '').strip()
            try:
                start_no = int(request.form.get('start_no', 1))
                quantity = int(request.form.get('quantity', 1))
                capacity = int(request.form.get('bulk_capacity', 4))
            except (ValueError, TypeError):
                flash("ข้อมูลตัวเลขสำหรับการสร้างโต๊ะแบบกลุ่มไม่ถูกต้อง", "error")
                return redirect(url_for('admin.admin_tables_list'))

            if quantity < 1 or quantity > 50:
                flash("สามารถสร้างโต๊ะได้ครั้งละ 1 - 50 โต๊ะเท่านั้น", "error")
                return redirect(url_for('admin.admin_tables_list'))

            success_count = 0
            for i in range(quantity):
                num = start_no + i
                num_str = f"{num:02d}" if (start_no + quantity) > 10 else f"{num}"
                table_no = f"{prefix}{num_str}" if prefix else f"{num}"

                payload = {
                    'table_no': table_no,
                    'capacity': capacity,
                    'status': 'available',
                    'order': {'items': [], 'total_amount': 0.0}
                }
                if post_firebase_data('tables', payload):
                    success_count += 1

            flash(f"สร้างโต๊ะใหม่สำเร็จเรียบร้อยจำนวน {success_count} โต๊ะ", "success")

        else:
            table_no = request.form.get('table_no', '').strip()
            try:
                capacity = int(request.form.get('capacity', 4))
            except (ValueError, TypeError):
                capacity = 4

            if not table_no:
                flash("กรุณาระบุหมายเลข/ชื่อโต๊ะ", "error")
                return redirect(url_for('admin.admin_tables_list'))

            payload = {
                'table_no': table_no,
                'capacity': capacity,
                'status': 'available',
                'order': {'items': [], 'total_amount': 0.0}
            }

            if post_firebase_data('tables', payload):
                flash("เพิ่มโต๊ะอาหารเรียบร้อยแล้ว", "success")
            else:
                flash("เกิดข้อผิดพลาดในการเพิ่มโต๊ะ", "error")

    except Exception as e:
        flash(f"เกิดข้อผิดพลาด: {str(e)}", "error")

    return redirect(url_for('admin.admin_tables_list'))

@admin_bp.route('/admin/tables/edit/<table_id>', methods=['POST'])
@staff_required
def admin_table_edit(table_id):
    try:
        table_no = request.form.get('table_no', '').strip()
        try:
            capacity = int(request.form.get('capacity', 4))
        except (ValueError, TypeError):
            capacity = 4

        status = request.form.get('status', 'available')

        if not table_no:
            flash("กรุณาระบุหมายเลข/ชื่อโต๊ะ", "error")
            return redirect(url_for('admin.admin_tables_list'))

        payload = {
            'table_no': table_no,
            'capacity': capacity,
            'status': status
        }

        if patch_firebase_data('tables', table_id, payload):
            flash("แก้ไขข้อมูลโต๊ะเรียบร้อยแล้ว", "success")
        else:
            flash("เกิดข้อผิดพลาดในการแก้ไขข้อมูลโต๊ะ", "error")

    except Exception as e:
        flash(f"เกิดข้อผิดพลาด: {str(e)}", "error")

    return redirect(url_for('admin.admin_tables_list'))

@admin_bp.route('/admin/tables/status/<table_id>', methods=['POST'])
@staff_required
def admin_table_status(table_id):
    try:
        data = request.get_json() or {}
        new_status = data.get('status', 'available')

        update_payload = {'status': new_status}
        if new_status == 'available':
            update_payload['order'] = {'items': [], 'total_amount': 0.0}

        if patch_firebase_data('tables', table_id, update_payload):
            return jsonify({'status': 'success', 'message': 'อัปเดตสถานะโต๊ะสำเร็จ'})
        return jsonify({'status': 'error', 'message': 'ไม่สามารถอัปเดตสถานะได้'}), 500
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@admin_bp.route('/admin/tables/clear/<table_id>', methods=['POST'])
@staff_required
def admin_table_clear(table_id):
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

@admin_bp.route('/admin/tables/delete/<table_id>', methods=['POST'])
@admin_required
def admin_table_delete(table_id):
    try:
        if delete_firebase_data('tables', table_id):
            return jsonify({'status': 'success', 'message': 'ลบข้อมูลโต๊ะเรียบร้อยแล้ว'})
        return jsonify({'status': 'error', 'message': 'เกิดข้อผิดพลาดในการลบ'}), 500
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500