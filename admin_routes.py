import json
from datetime import datetime, timedelta
from collections import Counter, defaultdict
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

RESET_TABLE_PAYLOAD = {
    'status': 'available',
    'occupied_by': '',
    'customer_count': 0,
    'order': {'items': [], 'total_amount': 0.0}
}


def _get_user_by_id(user_id):
    """อ่านข้อมูลผู้ใช้เป้าหมายจาก Firebase อย่างปลอดภัย"""
    if not user_id:
        return None

    try:
        user = get_firebase_data(f'users/{user_id}')
        return user if isinstance(user, dict) else None
    except Exception as e:
        print(f"Error loading user {user_id}: {e}")
        return None


def _is_admin_account(user_id, user_data=None):
    """ตรวจว่าบัญชีเป้าหมายเป็น Admin หรือไม่"""
    if user_data is None:
        user_data = _get_user_by_id(user_id)

    if not isinstance(user_data, dict):
        return False

    return str(user_data.get('role', '')).strip().lower() == 'admin'


def _is_current_user(user_id):
    """ตรวจว่าบัญชีเป้าหมายคือบัญชีที่กำลัง Login อยู่หรือไม่"""
    current_user_id = str(session.get('user_id', '')).strip()
    target_user_id = str(user_id or '').strip()
    return bool(current_user_id and target_user_id and current_user_id == target_user_id)


def _admin_protected_response(message):
    """ตอบกลับเมื่อพยายามแก้ไข/ลบ/ปิดใช้งานบัญชี Admin"""
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
        return jsonify({'status': 'error', 'message': message}), 403

    flash(message, 'error')
    return redirect(url_for('admin.admin_staff_list'))

def _get_request_ids(request):
    """ฟังก์ชันช่วยดึงรายการ IDs จาก Request รองรับทั้ง JSON, Form Data และคีย์หลายรูปแบบ"""
    data = request.get_json(silent=True) or {}
    
    ids = data.get('ids') or data.get('table_ids') or data.get('menu_ids') or data.get('ids[]') or data.get('table_ids[]')
    
    if not ids:
        ids = (request.form.getlist('ids[]') or 
               request.form.getlist('table_ids[]') or 
               request.form.getlist('menu_ids[]') or 
               request.form.getlist('ids') or 
               request.form.getlist('table_ids'))
        
    if isinstance(ids, str):
        ids = [x.strip() for x in ids.split(',') if x.strip()]
        
    return ids or []

def _extract_order_items(order):
    """ดึงรายการสินค้าจากออเดอร์ไม่ว่าจะเก็บในคีย์ items, order_items, cart, ฯลฯ และแปลงเป็น List เสมอ"""
    if not isinstance(order, dict):
        return []

    raw_items = order.get('items')
    if raw_items is None:
        raw_items = (order.get('order_items') or 
                     order.get('cart') or 
                     order.get('cart_items') or 
                     order.get('details') or 
                     order.get('menu_items') or [])

    if isinstance(raw_items, str):
        try:
            raw_items = json.loads(raw_items)
        except Exception:
            raw_items = []

    items_list = []
    if isinstance(raw_items, dict):
        items_list = list(raw_items.values())
    elif isinstance(raw_items, list):
        items_list = raw_items

    clean_items = []
    for item in items_list:
        if isinstance(item, dict):
            name = item.get('name') or item.get('title') or item.get('menu_name') or 'ไม่ระบุชื่อ'
            
            try:
                price = float(item.get('price') if item.get('price') is not None else item.get('unit_price', 0))
            except (ValueError, TypeError):
                price = 0.0

            try:
                qty = int(item.get('quantity') if item.get('quantity') is not None else (item.get('qty') if item.get('qty') is not None else item.get('amount', 1)))
            except (ValueError, TypeError):
                qty = 1

            spice_level = item.get('spice_level') or item.get('spice')
            notes = item.get('notes') or item.get('note')
            spice_or_note = str(spice_level) if spice_level else (str(notes) if notes else '-')

            clean_items.append({
                'name': name,
                'price': price,
                'quantity': qty,
                'qty': qty,
                'spice_level': spice_or_note,
                'notes': str(notes or '-'),
                'total_price': price * qty
            })

    return clean_items

# ==========================================
# DASHBOARD & STATS
# ==========================================
@admin_bp.route('/admin')
@admin_required
def admin_dashboard():
    try:
        return render_template('admin/dashboard.html', username=session.get('username'), role=session.get('role'))
    except Exception:
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
    item_counter = Counter()
    
    raw_orders = get_firebase_data('orders')
    orders_list = parse_firebase_data(raw_orders)
    if not orders_list:
        orders_list = get_all_orders() or []
    
    for order in orders_list:
        if isinstance(order, dict):
            created_at = str(order.get('created_at') or order.get('date') or order.get('timestamp') or '')
            status = str(order.get('status', '')).lower()
            
            if status in ['completed', 'paid', 'success']:
                try:
                    tot = order.get('total_price') if order.get('total_price') is not None else order.get('total_amount')
                    if tot is None:
                        tot = order.get('total', 0)
                    amount = float(tot)
                except (ValueError, TypeError):
                    amount = 0.0
                
                clean_date_str = created_at.replace('T', ' ').split(' ')[0] if created_at else ''
                
                if clean_date_str == today_str:
                    sales_today += amount
                    try:
                        customers_today += int(order.get('customer_count', order.get('guests', 0)))
                    except (ValueError, TypeError):
                        pass

                    items = _extract_order_items(order)
                    for item in items:
                        item_name = item.get('name')
                        qty = item.get('quantity', 1)
                        if item_name:
                            item_counter[item_name] += qty
                
                if clean_date_str and clean_date_str != '-':
                    try:
                        order_date = datetime.strptime(clean_date_str, "%Y-%m-%d")
                        delta_days = (order_date.date() - start_of_week.date()).days
                        if 0 <= delta_days < 7:
                            weekly_sales[delta_days] += amount
                    except Exception:
                        pass

    top_selling_today = [
        {'name': name, 'qty': qty} 
        for name, qty in item_counter.most_common(5)
    ]

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
        'weekly_sales': [round(x, 2) for x in weekly_sales],
        'top_selling_today': top_selling_today
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
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'status': 'error', 'message': 'ราคาอาหารไม่ถูกต้อง'}), 400
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
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'status': 'success', 'message': 'เพิ่มรายการอาหารเรียบร้อยแล้ว'})
            flash("เพิ่มรายการอาหารเรียบร้อยแล้ว", "success")
        else:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'status': 'error', 'message': 'เกิดข้อผิดพลาดในการเพิ่มรายการอาหาร'}), 500
            flash("เกิดข้อผิดพลาดในการเพิ่มรายการอาหาร", "error")
    except Exception as e:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'status': 'error', 'message': str(e)}), 500
        flash(f"เกิดข้อผิดพลาดในการเพิ่มเมนู: {str(e)}", "error")
        
    return redirect(url_for('admin.admin_menu_list'))

@admin_bp.route('/admin/menu/bulk-add', methods=['POST'])
@admin_required
def admin_menu_bulk_add():
    try:
        names = request.form.getlist('name[]')
        categories = request.form.getlist('category[]')
        prices = request.form.getlist('price[]')
        spice_levels = request.form.getlist('spice_level[]')
        sizes = request.form.getlist('size[]')
        statuses = request.form.getlist('status[]')
        images = request.files.getlist('image[]')

        success_count = 0
        for i in range(len(names)):
            name = names[i].strip() if i < len(names) else ''
            if not name:
                continue

            try:
                price = float(prices[i]) if i < len(prices) else 0.0
            except (ValueError, TypeError):
                price = 0.0

            st = statuses[i] if i < len(statuses) else 'available'

            payload = {
                'name': name,
                'category': categories[i] if i < len(categories) else '',
                'price': price,
                'spice_level': spice_levels[i] if i < len(spice_levels) else 'ไม่เผ็ด',
                'size': sizes[i] if i < len(sizes) else 'ปกติ',
                'status': st,
                'is_available': (st == 'available'),
                'image_file': None
            }

            if i < len(images) and images[i] and allowed_file(images[i].filename):
                payload['image_file'] = upload_to_firebase_storage(images[i], folder="menus")

            if post_firebase_data('menus', payload):
                success_count += 1

        flash(f"เพิ่มรายการอาหารสำเร็จ {success_count} รายการ", "success")
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

@admin_bp.route('/admin/menu/bulk-status', methods=['POST'])
@admin_required
def admin_menu_bulk_status():
    try:
        ids = _get_request_ids(request)
        data = request.get_json(silent=True) or {}
        new_status = data.get('status') or request.form.get('status', 'available')

        if not ids:
            return jsonify({'status': 'error', 'message': 'กรุณาเลือกรายการอาหาร'}), 400

        payload = {
            'status': new_status,
            'is_available': (new_status == 'available')
        }

        for menu_id in ids:
            patch_firebase_data('menus', menu_id, payload)

        return jsonify({'status': 'success', 'message': 'อัปเดตสถานะสำเร็จ'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@admin_bp.route('/admin/menu/batch-edit', methods=['POST'])
@admin_required
def admin_menu_batch_edit():
    try:
        ids = _get_request_ids(request)
        data = request.get_json(silent=True) or {}
        category = data.get('category') or request.form.get('category')
        status = data.get('status') or request.form.get('status')
        price = data.get('price') or request.form.get('price')

        if not ids:
            return jsonify({'status': 'error', 'message': 'กรุณาเลือกรายการอาหารที่ต้องการแก้ไข'}), 400

        update_payload = {}
        if category:
            update_payload['category'] = category
        if status:
            update_payload['status'] = status
            update_payload['is_available'] = (status == 'available')
        if price is not None and price != "":
            try:
                update_payload['price'] = float(price)
            except (ValueError, TypeError):
                pass

        if not update_payload:
            return jsonify({'status': 'error', 'message': 'ไม่มีข้อมูลที่ต้องอัปเดต'}), 400

        for menu_id in ids:
            patch_firebase_data('menus', menu_id, update_payload)

        return jsonify({'status': 'success', 'message': f'อัปเดตรายการอาหารสำเร็จ {len(ids)} รายการ'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

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

@admin_bp.route('/admin/menu/bulk-delete', methods=['POST'])
@admin_bp.route('/admin/menu/batch-delete', methods=['POST'])
@admin_required
def admin_menu_batch_delete():
    try:
        ids = _get_request_ids(request)

        if not ids:
            return jsonify({'status': 'error', 'message': 'กรุณาเลือกรายการอาหารที่ต้องการลบ'}), 400

        for menu_id in ids:
            menu = get_firebase_data(f'menus/{menu_id}')
            if menu and isinstance(menu, dict) and menu.get('image_file'):
                delete_from_firebase_storage(menu['image_file'])
            delete_firebase_data('menus', menu_id)

        return jsonify({'status': 'success', 'message': f'ลบรายการอาหารสำเร็จ {len(ids)} รายการ'})
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

@admin_bp.route('/admin/staff/batch-add', methods=['POST'])
@admin_required
def admin_staff_batch_add():
    """เพิ่มพนักงานหลายบัญชีในคำขอเดียว พร้อมตรวจข้อมูลซ้ำก่อนเขียน Firebase"""
    try:
        data = request.get_json(silent=True) or {}
        users = data.get('users')

        if not isinstance(users, list) or not users:
            return jsonify({'status': 'error', 'message': 'กรุณาระบุข้อมูลพนักงานที่ต้องการเพิ่ม'}), 400

        if len(users) > 50:
            return jsonify({'status': 'error', 'message': 'สามารถเพิ่มพนักงานพร้อมกันได้ไม่เกิน 50 รายการ'}), 400

        existing_users = get_all_users() or {}
        existing_usernames = {
            str(info.get('username', '')).strip().lower()
            for info in existing_users.values()
            if isinstance(info, dict) and str(info.get('username', '')).strip()
        }

        created = []
        skipped = []
        failed = []
        request_usernames = set()

        for index, item in enumerate(users, start=1):
            if not isinstance(item, dict):
                failed.append(f'รายการที่ {index}: รูปแบบข้อมูลไม่ถูกต้อง')
                continue

            username = str(item.get('username', '')).strip()
            password = str(item.get('password', '')).strip()
            role = str(item.get('role', 'staff')).strip().lower()
            username_key = username.lower()

            if len(username) < 3 or len(password) < 4:
                failed.append(f'รายการที่ {index} ({username or "ไม่ระบุชื่อ"}): ชื่อผู้ใช้ต้องมีอย่างน้อย 3 ตัวอักษร และรหัสผ่านอย่างน้อย 4 ตัวอักษร')
                continue

            if role not in ['staff', 'admin']:
                failed.append(f'รายการที่ {index} ({username}): ตำแหน่งไม่ถูกต้อง')
                continue

            if username_key in request_usernames:
                skipped.append(f'{username} (ซ้ำในรายการเดียวกัน)')
                continue

            request_usernames.add(username_key)

            if username_key in existing_usernames:
                skipped.append(f'{username} (มีอยู่ในระบบแล้ว)')
                continue

            try:
                hashed_password = generate_password_hash(password)
                if create_user(username, hashed_password, role):
                    created.append(username)
                    existing_usernames.add(username_key)
                else:
                    failed.append(f'{username} (ไม่สามารถบันทึก Firebase ได้)')
            except Exception as item_error:
                failed.append(f'{username} ({str(item_error)})')

        total_requested = len(users)
        if not created and failed and not skipped:
            status = 'error'
        elif failed or skipped:
            status = 'partial'
        else:
            status = 'success'

        parts = [f'เพิ่มสำเร็จ {len(created)} จาก {total_requested} รายการ']
        if skipped:
            parts.append(f'ข้าม {len(skipped)} รายการ: {", ".join(skipped[:5])}' + (' และรายการอื่น ๆ' if len(skipped) > 5 else ''))
        if failed:
            parts.append(f'ไม่สำเร็จ {len(failed)} รายการ: {", ".join(failed[:5])}' + (' และรายการอื่น ๆ' if len(failed) > 5 else ''))

        return jsonify({
            'status': status,
            'message': ' | '.join(parts),
            'created_count': len(created),
            'skipped_count': len(skipped),
            'failed_count': len(failed),
            'created': created,
            'skipped': skipped,
            'failed': failed
        }), (400 if status == 'error' else 200)

    except Exception as e:
        return jsonify({'status': 'error', 'message': f'เกิดข้อผิดพลาดในการเพิ่มพนักงานหลายรายการ: {str(e)}'}), 500


@admin_bp.route('/admin/staff/batch-edit', methods=['POST'])
@admin_required
def admin_staff_batch_edit():
    """แก้ไข Staff หลายบัญชีพร้อมกัน โดยป้องกันการลดสิทธิ์/ปิดใช้งาน Admin"""
    try:
        ids = _get_request_ids(request)
        data = request.get_json(silent=True) or {}
        role = data.get('role')
        is_active = data.get('is_active')

        if not ids:
            return jsonify({'status': 'error', 'message': 'กรุณาเลือกพนักงานอย่างน้อย 1 รายการ'}), 400

        # ทำให้ IDs ไม่ซ้ำและตัดค่าที่ว่างออก เพื่อไม่ให้เขียน Firebase ซ้ำ
        unique_ids = []
        seen_ids = set()
        for raw_id in ids:
            user_id = str(raw_id or '').strip()
            if user_id and user_id not in seen_ids:
                seen_ids.add(user_id)
                unique_ids.append(user_id)

        role = str(role).strip().lower() if role is not None and str(role).strip() else None
        is_active = str(is_active).strip().lower() if is_active is not None and str(is_active).strip() else None

        if role is not None and role not in ['staff', 'admin']:
            return jsonify({'status': 'error', 'message': 'ตำแหน่งผู้ใช้ไม่ถูกต้อง'}), 400
        if is_active is not None and is_active not in ['true', 'false', '1', '0', 'on', 'off']:
            return jsonify({'status': 'error', 'message': 'สถานะการใช้งานไม่ถูกต้อง'}), 400
        if role is None and is_active is None:
            return jsonify({'status': 'error', 'message': 'ไม่มีข้อมูลที่ต้องอัปเดต'}), 400

        requested_active = None
        if is_active is not None:
            requested_active = is_active in ['true', '1', 'on']

        updated = []
        skipped = []
        failed = []

        for user_id in unique_ids:
            target_user = _get_user_by_id(user_id)
            if not target_user:
                failed.append(f'{user_id} (ไม่พบข้อมูลบัญชี)')
                continue

            current_role = str(target_user.get('role', 'staff')).strip().lower()
            is_admin = _is_admin_account(user_id, target_user)
            is_current = _is_current_user(user_id)

            # Admin ต้องคงสิทธิ์ admin และเปิดใช้งานเสมอ
            if is_admin:
                if role == 'staff' or requested_active is False:
                    reason = 'บัญชี Admin ห้ามลดสิทธิ์หรือปิดใช้งาน'
                    skipped.append(f'{target_user.get("username", user_id)} ({reason})')
                    continue
                # หากไม่ได้สั่งเปลี่ยน role/status หรือสั่งเป็นค่าที่ปลอดภัย ให้คงค่าเดิมของ Admin
                update_data = {}
                if role == 'admin':
                    update_data['role'] = 'admin'
                if requested_active is True:
                    update_data['is_active'] = True
                if not update_data:
                    skipped.append(f'{target_user.get("username", user_id)} (ไม่มีการเปลี่ยนแปลง)')
                    continue
            else:
                update_data = {}
                if role is not None:
                    update_data['role'] = role
                if requested_active is not None:
                    update_data['is_active'] = requested_active

                # ป้องกัน Admin ที่กำลัง Login อยู่ถูกทำให้เข้าใช้งานต่อไม่ได้จากคำขอแบบกลุ่ม
                if is_current and current_role == 'admin':
                    if update_data.get('role') == 'staff' or update_data.get('is_active') is False:
                        skipped.append(f'{target_user.get("username", user_id)} (เป็นบัญชี Admin ที่กำลังใช้งานอยู่)')
                        continue

            if not update_data:
                skipped.append(f'{target_user.get("username", user_id)} (ไม่มีการเปลี่ยนแปลง)')
                continue

            try:
                if patch_firebase_data('users', user_id, update_data):
                    updated.append(target_user.get('username', user_id))
                else:
                    failed.append(f'{target_user.get("username", user_id)} (Firebase ไม่ตอบรับการอัปเดต)')
            except Exception as item_error:
                failed.append(f'{target_user.get("username", user_id)} ({str(item_error)})')

        if not updated and failed and not skipped:
            status = 'error'
        elif failed or skipped:
            status = 'partial'
        else:
            status = 'success'

        parts = [f'อัปเดตสำเร็จ {len(updated)} รายการ จากที่เลือก {len(unique_ids)} รายการ']
        if skipped:
            parts.append(f'ข้าม {len(skipped)} รายการ: {", ".join(skipped[:5])}' + (' และรายการอื่น ๆ' if len(skipped) > 5 else ''))
        if failed:
            parts.append(f'ไม่สำเร็จ {len(failed)} รายการ: {", ".join(failed[:5])}' + (' และรายการอื่น ๆ' if len(failed) > 5 else ''))

        return jsonify({
            'status': status,
            'message': ' | '.join(parts),
            'updated_count': len(updated),
            'skipped_count': len(skipped),
            'failed_count': len(failed),
            'updated': updated,
            'skipped': skipped,
            'failed': failed
        }), (400 if status == 'error' else 200)

    except Exception as e:
        return jsonify({'status': 'error', 'message': f'เกิดข้อผิดพลาดในการแก้ไขพนักงานหลายรายการ: {str(e)}'}), 500


@admin_bp.route('/admin/staff/batch-delete', methods=['POST'])
@admin_required
def admin_staff_batch_delete():
    """ลบ Staff หลายบัญชีพร้อมกัน โดยไม่อนุญาตให้ลบ Admin หรือบัญชีที่กำลัง Login"""
    try:
        ids = _get_request_ids(request)
        if not ids:
            return jsonify({'status': 'error', 'message': 'กรุณาเลือกพนักงานอย่างน้อย 1 รายการ'}), 400

        unique_ids = []
        seen_ids = set()
        for raw_id in ids:
            user_id = str(raw_id or '').strip()
            if user_id and user_id not in seen_ids:
                seen_ids.add(user_id)
                unique_ids.append(user_id)

        deleted = []
        skipped = []
        failed = []

        for user_id in unique_ids:
            target_user = _get_user_by_id(user_id)
            if not target_user:
                failed.append(f'{user_id} (ไม่พบข้อมูลบัญชี)')
                continue

            username = str(target_user.get('username', user_id)).strip() or user_id

            if _is_current_user(user_id):
                skipped.append(f'{username} (ไม่สามารถลบบัญชีที่กำลังใช้งานอยู่)')
                continue

            if _is_admin_account(user_id, target_user):
                skipped.append(f'{username} (ไม่สามารถลบบัญชี Admin)')
                continue

            try:
                if delete_firebase_data('users', user_id):
                    deleted.append(username)
                else:
                    failed.append(f'{username} (ไม่สามารถลบจาก Firebase ได้)')
            except Exception as item_error:
                failed.append(f'{username} ({str(item_error)})')

        if not deleted and failed and not skipped:
            status = 'error'
        elif failed or skipped:
            status = 'partial'
        else:
            status = 'success'

        parts = [f'ลบสำเร็จ {len(deleted)} รายการ จากที่เลือก {len(unique_ids)} รายการ']
        if skipped:
            parts.append(f'ข้าม {len(skipped)} รายการ: {", ".join(skipped[:5])}' + (' และรายการอื่น ๆ' if len(skipped) > 5 else ''))
        if failed:
            parts.append(f'ไม่สำเร็จ {len(failed)} รายการ: {", ".join(failed[:5])}' + (' และรายการอื่น ๆ' if len(failed) > 5 else ''))

        return jsonify({
            'status': status,
            'message': ' | '.join(parts),
            'deleted_count': len(deleted),
            'skipped_count': len(skipped),
            'failed_count': len(failed),
            'deleted': deleted,
            'skipped': skipped,
            'failed': failed
        }), (400 if status == 'error' else 200)

    except Exception as e:
        return jsonify({'status': 'error', 'message': f'เกิดข้อผิดพลาดในการลบพนักงานหลายรายการ: {str(e)}'}), 500


@admin_bp.route('/admin/staff/edit/<user_id>', methods=['POST'])
@admin_required
def admin_staff_edit(user_id):
    try:
        target_user = _get_user_by_id(user_id)
        if not target_user:
            return _admin_protected_response("ไม่พบข้อมูลบัญชีผู้ใช้ที่ต้องการแก้ไข")

        username = request.form.get('username', '').strip()
        requested_role = str(request.form.get('role', target_user.get('role', 'staff'))).strip().lower()
        status_input = request.form.get('is_active', 'true')
        password = request.form.get('password', '').strip()

        if requested_role not in ['staff', 'admin']:
            flash("สิทธิ์ผู้ใช้ไม่ถูกต้อง", "error")
            return redirect(url_for('admin.admin_staff_list'))

        # บัญชี Admin เป็นบัญชีที่ได้รับการป้องกัน:
        # - ห้ามลด role จาก admin เป็น staff
        # - ห้ามเปลี่ยน username ผ่านหน้าแก้ไข
        # - ห้ามปิดใช้งาน
        # - อนุญาตให้เปลี่ยน password ได้
        if _is_admin_account(user_id, target_user):
            if requested_role != 'admin':
                return _admin_protected_response("ไม่สามารถลดสิทธิ์บัญชี Admin เป็น Staff ได้")

            old_username = str(target_user.get('username', '')).strip()
            if username and username != old_username:
                return _admin_protected_response("ไม่สามารถเปลี่ยนชื่อผู้ใช้ของบัญชี Admin ได้")

            update_data = {
                'role': 'admin',
                'is_active': True
            }

            if password:
                update_data['password'] = generate_password_hash(password)

            if patch_firebase_data('users', user_id, update_data):
                flash("อัปเดตข้อมูลบัญชี Admin สำเร็จ (บัญชี Admin ยังคงเปิดใช้งานและสิทธิ์เดิม)", "success")
            else:
                flash("ไม่สามารถอัปเดตข้อมูลไปยัง Firebase ได้", "error")

            return redirect(url_for('admin.admin_staff_list'))

        # บัญชี Staff/ผู้ใช้ทั่วไปสามารถแก้ไขข้อมูลได้ตามปกติ
        users = get_all_users() or {}
        if isinstance(users, dict) and username:
            is_duplicate = any(
                isinstance(info, dict)
                and uid != user_id
                and str(info.get('username', '')).strip() == username
                for uid, info in users.items()
            )
            if is_duplicate:
                flash("ชื่อผู้ใช้นี้มีในระบบแล้ว", "error")
                return redirect(url_for('admin.admin_staff_list'))

        is_active = str(status_input).lower() in ['true', 'on', '1']

        update_data = {
            'role': requested_role,
            'is_active': is_active
        }

        if username:
            update_data['username'] = username

        if password:
            update_data['password'] = generate_password_hash(password)

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
        target_user = _get_user_by_id(user_id)
        if not target_user:
            return jsonify({'status': 'error', 'message': 'ไม่พบข้อมูลบัญชีผู้ใช้'}), 404

        if _is_admin_account(user_id, target_user):
            return jsonify({
                'status': 'error',
                'message': 'ไม่สามารถเปลี่ยนสถานะบัญชี Admin ได้ บัญชี Admin ต้องเปิดใช้งานอยู่เสมอ'
            }), 403

        current_status = bool(target_user.get('is_active', True))
        new_status = not current_status

        if patch_firebase_data('users', user_id, {'is_active': new_status}):
            status_text = "เปิดใช้งาน" if new_status else "ถูกระงับ"
            return jsonify({
                'status': 'success',
                'message': f'เปลี่ยนสถานะบัญชีเป็น "{status_text}" เรียบร้อยแล้ว',
                'is_active': new_status
            })

        return jsonify({'status': 'error', 'message': 'ไม่สามารถอัปเดตข้อมูลได้'}), 500
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@admin_bp.route('/admin/staff/delete/<id>', methods=['POST'])
@admin_required
def admin_staff_delete(id):
    try:
        target_user = _get_user_by_id(id)
        if not target_user:
            return jsonify({'status': 'error', 'message': 'ไม่พบข้อมูลบัญชีผู้ใช้ที่ต้องการลบ'}), 404

        if _is_current_user(id):
            return jsonify({'status': 'error', 'message': 'ไม่สามารถลบบัญชีของตัวเองที่กำลังใช้งานอยู่ได้'}), 400

        if _is_admin_account(id, target_user):
            return jsonify({
                'status': 'error',
                'message': 'ไม่สามารถลบบัญชี Admin ได้ เพื่อป้องกันระบบหลักถูกล็อกออกจากสิทธิ์ผู้ดูแล'
            }), 403

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

@admin_bp.route('/admin/payments/batch-add', methods=['POST'])
@admin_required
def admin_payments_batch_add():
    try:
        items = {}
        for key, val in request.form.items():
            if key.startswith('payments['):
                parts = key.split('[')
                if len(parts) >= 3:
                    idx = parts[1].rstrip(']')
                    field = parts[2].rstrip(']')
                    if idx not in items:
                        items[idx] = {}
                    items[idx][field] = val.strip()

        for key, file in request.files.items():
            if key.startswith('payments['):
                parts = key.split('[')
                if len(parts) >= 3:
                    idx = parts[1].rstrip(']')
                    field = parts[2].rstrip(']')
                    if idx not in items:
                        items[idx] = {}
                    items[idx][field] = file

        success_count = 0
        for idx in sorted(items.keys(), key=lambda x: int(x) if x.isdigit() else x):
            item = items[idx]
            bank_name = item.get('bank_name', '')
            account_name = item.get('account_name', '')
            promptpay_no = item.get('promptpay_no', '')
            file = item.get('qr_image')

            if not account_name or not promptpay_no:
                continue

            qr_image_url = None
            if file and hasattr(file, 'filename') and file.filename and allowed_file(file.filename):
                qr_image_url = upload_to_firebase_storage(file, folder="payments")

            payload = {
                'bank_name': bank_name,
                'account_name': account_name,
                'promptpay_no': promptpay_no,
                'is_active': 1,
                'qr_image': qr_image_url
            }

            if post_firebase_data('payment_channels', payload):
                success_count += 1

        return jsonify({'status': 'success', 'message': f'บันทึกช่องทางชำระเงินสำเร็จ {success_count} รายการ'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

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

@admin_bp.route('/admin/payments/batch-edit', methods=['POST'])
@admin_required
def admin_payments_batch_edit():
    try:
        ids = _get_request_ids(request)
        data = request.get_json(silent=True) or {}
        is_active = 1 if data.get('is_active') or request.form.get('is_active') else 0

        if not ids:
            return jsonify({'status': 'error', 'message': 'กรุณาเลือกช่องทางชำระเงิน'}), 400

        for pay_id in ids:
            patch_firebase_data('payment_channels', pay_id, {'is_active': is_active})

        return jsonify({'status': 'success', 'message': 'อัปเดตสถานะช่องทางชำระเงินเรียบร้อย'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

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

@admin_bp.route('/admin/payments/batch-delete', methods=['POST'])
@admin_required
def admin_payments_batch_delete():
    try:
        ids = _get_request_ids(request)

        if not ids:
            return jsonify({'status': 'error', 'message': 'กรุณาเลือกช่องทางชำระเงิน'}), 400

        for pay_id in ids:
            payment = get_firebase_data(f'payment_channels/{pay_id}')
            if payment and isinstance(payment, dict) and payment.get('qr_image'):
                delete_from_firebase_storage(payment['qr_image'])
            delete_firebase_data('payment_channels', pay_id)

        return jsonify({'status': 'success', 'message': 'ลบช่องทางชำระเงินเรียบร้อยแล้ว'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ==========================================
# SALES HISTORY & REPORTS
# ==========================================
@admin_bp.route('/admin/sales')
@admin_required
def admin_sales_history():
    raw_orders = get_firebase_data('orders')
    orders = parse_firebase_data(raw_orders)
    if not orders:
        orders = get_all_orders() or []
    
    start_date_str = request.args.get('start_date', '').strip()
    end_date_str = request.args.get('end_date', '').strip()
    
    daily_sales_map = defaultdict(lambda: {'total_amount': 0.0, 'order_count': 0, 'item_count': 0})
    item_sales_map = defaultdict(lambda: {'qty': 0, 'total_revenue': 0.0})
    
    filtered_orders = []
    total_revenue = 0.0
    total_completed_orders = 0
    total_pending_orders = 0
    total_voided_orders = 0
    total_items_sold = 0

    for order in orders:
        if not isinstance(order, dict):
            continue

        clean_items = _extract_order_items(order)
        order['items'] = clean_items

        order_id = str(order.get('id') or order.get('order_id') or order.get('_id') or 'N/A')
        order['id'] = order_id
        order['modal_id'] = ''.join(c if c.isalnum() else '_' for c in order_id)

        table_no = str(order.get('table_no') or order.get('table') or order.get('table_id') or order.get('tableno') or '-')
        order['table_no'] = table_no

        payment_method = str(order.get('payment_method') or order.get('payment_type') or order.get('payment') or order.get('pay_method') or 'ไม่ระบุ')
        order['payment_method'] = payment_method

        try:
            tot = order.get('total_price') if order.get('total_price') is not None else (order.get('total_amount') if order.get('total_amount') is not None else order.get('total', 0))
            total_price = float(tot)
        except (ValueError, TypeError):
            total_price = 0.0
        order['total_price'] = total_price

        created_at = str(order.get('created_at') or order.get('date') or order.get('timestamp') or '-')
        order['created_at'] = created_at

        status = str(order.get('status', 'completed')).lower()
        order['status'] = status

        clean_date_str = created_at.replace('T', ' ').split(' ')[0] if created_at and created_at != '-' else ''

        if start_date_str and clean_date_str and clean_date_str < start_date_str:
            continue
        if end_date_str and clean_date_str and clean_date_str > end_date_str:
            continue

        filtered_orders.append(order)

        if status in ['completed', 'paid', 'success']:
            total_revenue += total_price
            total_completed_orders += 1

            if clean_date_str:
                daily_sales_map[clean_date_str]['total_amount'] += total_price
                daily_sales_map[clean_date_str]['order_count'] += 1

            for item in clean_items:
                item_name = item['name']
                qty = item['quantity']
                item_revenue = item['price'] * qty

                item_sales_map[item_name]['qty'] += qty
                item_sales_map[item_name]['total_revenue'] += item_revenue
                total_items_sold += qty
                if clean_date_str:
                    daily_sales_map[clean_date_str]['item_count'] += qty
        elif status in ['voided', 'cancelled']:
            total_voided_orders += 1
        else:
            total_pending_orders += 1

    top_selling_menus = [
        {
            'name': name,
            'qty': data['qty'],
            'total_revenue': round(data['total_revenue'], 2)
        }
        for name, data in sorted(item_sales_map.items(), key=lambda x: x[1]['qty'], reverse=True)[:5]
    ]

    daily_sales_report = [
        {
            'date': date_key,
            'total_amount': round(info['total_amount'], 2),
            'order_count': info['order_count'],
            'item_count': info['item_count']
        }
        for date_key, info in sorted(daily_sales_map.items(), key=lambda x: x[0], reverse=True)
    ]

    filtered_orders.sort(key=lambda x: str(x.get('created_at') or ''), reverse=True)

    return render_template(
        'admin/sales.html', 
        orders=filtered_orders,
        daily_sales_report=daily_sales_report,
        top_selling_menus=top_selling_menus,
        total_revenue=round(total_revenue, 2),
        total_completed_orders=total_completed_orders,
        total_pending_orders=total_pending_orders,
        total_voided_orders=total_voided_orders,
        total_items_sold=total_items_sold,
        start_date=start_date_str,
        end_date=end_date_str
    )

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
    val = str(table.get('table_no', ''))
    digits = ''.join(filter(str.isdigit, val))
    return (0, int(digits), val) if digits else (1, 0, val)

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
                    'occupied_by': '',
                    'customer_count': 0,
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
                'occupied_by': '',
                'customer_count': 0,
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
        if status == 'available':
            payload.update(RESET_TABLE_PAYLOAD)

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
        data = request.get_json(silent=True) or {}
        new_status = data.get('status') or request.form.get('status', 'available')

        update_payload = {'status': new_status}
        if new_status == 'available':
            update_payload.update(RESET_TABLE_PAYLOAD)

        if patch_firebase_data('tables', table_id, update_payload):
            return jsonify({'status': 'success', 'message': 'อัปเดตสถานะโต๊ะสำเร็จ'})
        return jsonify({'status': 'error', 'message': 'ไม่สามารถอัปเดตสถานะได้'}), 500
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@admin_bp.route('/admin/tables/bulk-status', methods=['POST'])
@admin_bp.route('/admin/tables/batch-status', methods=['POST'])
@staff_required
def admin_table_bulk_status():
    try:
        ids = _get_request_ids(request)
        data = request.get_json(silent=True) or {}
        new_status = data.get('status') or request.form.get('status', 'available')

        if not ids:
            return jsonify({'status': 'error', 'message': 'กรุณาเลือกโต๊ะอาหาร'}), 400

        update_payload = {'status': new_status}
        if new_status == 'available':
            update_payload.update(RESET_TABLE_PAYLOAD)

        for table_id in ids:
            patch_firebase_data('tables', table_id, update_payload)

        return jsonify({'status': 'success', 'message': 'อัปเดตสถานะโต๊ะเรียบร้อยแล้ว'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@admin_bp.route('/admin/tables/clear/<table_id>', methods=['POST'])
@staff_required
def admin_table_clear(table_id):
    try:
        if patch_firebase_data('tables', table_id, RESET_TABLE_PAYLOAD):
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

@admin_bp.route('/admin/tables/bulk-delete', methods=['POST'])
@admin_bp.route('/admin/tables/batch-delete', methods=['POST'])
@admin_required
def admin_table_bulk_delete():
    try:
        ids = _get_request_ids(request)

        if not ids:
            return jsonify({'status': 'error', 'message': 'กรุณาเลือกโต๊ะอาหารที่ต้องการลบ'}), 400

        for table_id in ids:
            delete_firebase_data('tables', table_id)

        return jsonify({'status': 'success', 'message': f'ลบโต๊ะอาหารสำเร็จ {len(ids)} รายการ'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500