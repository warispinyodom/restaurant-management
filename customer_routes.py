import uuid
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


def get_current_user_keys():
    """ดึงรหัสระบุตัวตนทั้งหมดของลูกค้าใน Session ปัจจุบัน"""
    keys = set()

    for k in ['user_id', 'username', 'email', 'user', 'guest_id']:
        val = session.get(k)
        if val:
            keys.add(str(val).strip())

    if not keys:
        session['guest_id'] = f"guest_{uuid.uuid4().hex[:8]}"
        keys.add(session['guest_id'])

    return keys


def get_current_user_key():
    """ดึง Primary user key หลักสำหรับนำไปบันทึกข้อมูล"""
    user_key = (
        session.get('user_id')
        or session.get('username')
        or session.get('email')
        or session.get('user')
        or session.get('guest_id')
    )

    if not user_key:
        session['guest_id'] = f"guest_{uuid.uuid4().hex[:8]}"
        user_key = session['guest_id']

    return str(user_key).strip()


def sync_user_table_session():
    """ซิงก์โต๊ะที่ลูกค้าถือครองอยู่กลับเข้ามาใน Session"""
    if session.get('selected_table_ids') or session.get('selected_table_id'):
        return

    user_keys = get_current_user_keys()

    if not user_keys:
        return

    try:
        raw_tables = get_firebase_data('tables')
        all_tables = parse_firebase_data(raw_tables)

        user_tables = []

        for t in all_tables:
            status = str(t.get('status', '')).lower()
            occ_by = str(t.get('occupied_by', '')).strip()

            if (
                status == 'occupied'
                and occ_by
                and occ_by in user_keys
            ):
                user_tables.append(t)

        if user_tables:
            table_ids = [
                str(t.get('id'))
                for t in user_tables
            ]

            selected_nos = [
                str(t.get('table_no', ''))
                for t in user_tables
            ]

            customer_count = user_tables[0].get(
                'customer_count',
                1
            )

            try:
                customer_count = int(customer_count)

                if customer_count < 1:
                    customer_count = 1

            except (ValueError, TypeError):
                customer_count = 1

            session['selected_table_ids'] = table_ids
            session['selected_table_id'] = table_ids[0]
            session['selected_table_nos'] = selected_nos
            session['selected_table_no'] = ", ".join(selected_nos)
            session['customer_count'] = customer_count

    except Exception as e:
        print(
            f"Error syncing user table session: {e}"
        )


@customer_bp.route('/api/tables')
def api_get_tables():
    """API สำหรับดึงข้อมูลโต๊ะทั้งหมด"""
    raw_tables = get_firebase_data('tables')
    tables = parse_firebase_data(raw_tables)

    return jsonify({
        'status': 'success',
        'tables': tables
    })


@customer_bp.route('/customer')
def customer_dashboard():
    """หน้าหลักของลูกค้า"""

    if session.get('role') != 'customer':
        flash(
            "หน้านี้สำหรับลูกค้าเท่านั้น",
            "error"
        )
        return redirect(url_for('home'))

    sync_user_table_session()

    selected_table_id = session.get('selected_table_id')
    selected_table_ids = session.get('selected_table_ids')

    if not selected_table_id and not selected_table_ids:
        return redirect(
            url_for('customer.customer_choose_table')
        )

    try:
        raw_menus = get_firebase_data('menus')

        menus = [
            m
            for m in parse_firebase_data(raw_menus)
            if (
                str(m.get('status')).lower()
                in ['available', 'true', 'active']
                or m.get('is_available') is True
            )
        ]

        existing_cats = set(
            m.get('category')
            for m in menus
            if m.get('category')
        )

        categories = [
            c
            for c in DEFAULT_CATEGORIES
            if c in existing_cats
        ]

        for cat in existing_cats:
            if cat not in categories:
                categories.append(cat)

    except Exception as e:
        print(
            f"Error loading customer data: {e}"
        )

        menus = []
        categories = []

        flash(
            "เกิดข้อผิดพลาดในการโหลดข้อมูลร้านค้า กรุณารีเฟรชหน้าเว็บ",
            "error"
        )

    selected_table_no = session.get(
        'selected_table_no',
        None
    )

    customer_count = session.get(
        'customer_count',
        1
    )

    if (
        not isinstance(customer_count, int)
        or customer_count < 1
    ):
        customer_count = 1

    return render_template(
        'customer/customer.html',
        menus=menus,
        categories=categories,
        selected_table_no=selected_table_no,
        customer_count=customer_count
    )


@customer_bp.route(
    '/customer/choose_table',
    methods=['GET', 'POST']
)
@customer_bp.route(
    '/customer/choose-table',
    methods=['GET', 'POST']
)
def customer_choose_table():
    """หน้าเลือกโต๊ะของลูกค้า"""

    if session.get('role') != 'customer':
        flash(
            "หน้านี้สำหรับลูกค้าเท่านั้น",
            "error"
        )
        return redirect(url_for('home'))

    sync_user_table_session()

    if request.method == 'POST':

        action = request.form.get(
            'action',
            'select'
        )

        client_request_id = str(
            request.form.get('client_request_id', '')
        ).strip()

        if client_request_id and len(client_request_id) > 120:
            flash('รหัสคำขอไม่ถูกต้อง กรุณาลองใหม่อีกครั้ง', 'error')
            return redirect(url_for('customer.customer_choose_table'))

        processed_table_requests = session.get(
            'customer_processed_table_requests', []
        )
        if client_request_id and client_request_id in processed_table_requests:
            if action == 'cancel':
                return redirect(url_for('customer.customer_choose_table'))
            return redirect(url_for('customer.customer_dashboard'))

        # ยกเลิกโต๊ะ
        if action == 'cancel':

            selected_ids = session.get(
                'selected_table_ids',
                []
            )

            if (
                not selected_ids
                and session.get('selected_table_id')
            ):
                selected_ids = [
                    session.get('selected_table_id')
                ]

            for tid in selected_ids:

                if tid:
                    patch_firebase_data(
                        'tables',
                        tid,
                        {
                            'status': 'available',
                            'occupied_by': '',
                            'customer_count': 0,
                            'order': {
                                'items': [],
                                'total_amount': 0.0
                            }
                        }
                    )

            session.pop('selected_table_id', None)
            session.pop('selected_table_ids', None)
            session.pop('selected_table_no', None)
            session.pop('selected_table_nos', None)
            session.pop('customer_count', None)

            flash(
                "ยกเลิกการเลือกโต๊ะอาหารเรียบร้อยแล้ว",
                "success"
            )

            if client_request_id:
                processed = session.get('customer_processed_table_requests', [])
                processed = (processed + [client_request_id])[-20:]
                session['customer_processed_table_requests'] = processed

            return redirect(
                url_for(
                    'customer.customer_choose_table'
                )
            )

        # รับรายการโต๊ะที่ลูกค้าเลือก
        table_ids = request.form.getlist(
            'table_ids'
        )

        try:
            customer_count = int(
                request.form.get(
                    'customer_count',
                    1
                )
            )

            if customer_count < 1:
                customer_count = 1

        except (ValueError, TypeError):
            customer_count = 1

        if not table_ids:
            flash(
                "กรุณาเลือกโต๊ะอาหารอย่างน้อย 1 โต๊ะ",
                "error"
            )

            return redirect(
                url_for(
                    'customer.customer_choose_table'
                )
            )

        raw_tables = get_firebase_data('tables')
        all_tables = parse_firebase_data(raw_tables)

        tables_map = {
            str(t.get('id')): t
            for t in all_tables
        }

        user_keys = get_current_user_keys()
        primary_user_key = get_current_user_key()

        old_ids = session.get(
            'selected_table_ids',
            []
        )

        if (
            not old_ids
            and session.get('selected_table_id')
        ):
            old_ids = [
                session.get('selected_table_id')
            ]

        # คืนโต๊ะเก่าที่ไม่ได้เลือกแล้ว
        for old_id in old_ids:

            if (
                old_id
                and old_id not in table_ids
            ):
                patch_firebase_data(
                    'tables',
                    old_id,
                    {
                        'status': 'available',
                        'occupied_by': '',
                        'customer_count': 0,
                        'order': {
                            'items': [],
                            'total_amount': 0.0
                        }
                    }
                )

        selected_nos = []

        # ตรวจสอบโต๊ะก่อนจอง
        for tid in table_ids:

            table_info = tables_map.get(
                str(tid)
            )

            if not table_info:

                flash(
                    "พบข้อมูลโต๊ะไม่ถูกต้อง กรุณาลองใหม่อีกครั้ง",
                    "error"
                )

                return redirect(
                    url_for(
                        'customer.customer_choose_table'
                    )
                )

            occ_by = str(
                table_info.get(
                    'occupied_by',
                    ''
                )
            ).strip()

            is_own_table = (
                occ_by in user_keys
                if user_keys
                else False
            )

            if (
                table_info.get('status')
                != 'available'
                and tid not in old_ids
                and not is_own_table
            ):
                flash(
                    f"ขออภัย โต๊ะ {table_info.get('table_no')} ถูกใช้งานหรือถูกจองแล้ว",
                    "error"
                )

                return redirect(
                    url_for(
                        'customer.customer_choose_table'
                    )
                )

            selected_nos.append(
                str(
                    table_info.get(
                        'table_no',
                        ''
                    )
                )
            )

        # เปลี่ยนสถานะโต๊ะเป็น occupied
        for tid in table_ids:

            patch_firebase_data(
                'tables',
                tid,
                {
                    'status': 'occupied',
                    'occupied_by': (
                        primary_user_key
                        if primary_user_key
                        else ''
                    ),
                    'customer_count': customer_count
                }
            )

        session['selected_table_ids'] = table_ids
        session['selected_table_id'] = table_ids[0] if table_ids else ''
        session['selected_table_nos'] = selected_nos
        session['selected_table_no'] = ", ".join(selected_nos)
        session['customer_count'] = customer_count

        flash(
            f"เลือกโต๊ะ {session['selected_table_no']} "
            f"(จำนวน {customer_count} ท่าน) เรียบร้อยแล้ว",
            "success"
        )

        if client_request_id:
            processed = session.get('customer_processed_table_requests', [])
            processed = (processed + [client_request_id])[-20:]
            session['customer_processed_table_requests'] = processed

        return redirect(
            url_for(
                'customer.customer_dashboard'
            )
        )

    # GET - โหลดข้อมูลโต๊ะ
    try:

        raw_tables = get_firebase_data('tables')
        tables = parse_firebase_data(raw_tables)

        def sort_key(t):
            no = str(t.get('table_no', ''))
            digits = ''.join(filter(str.isdigit, no))
            return int(digits) if digits else no

        tables.sort(key=sort_key)

    except Exception as e:

        print(f"Error loading tables for customer: {e}")
        tables = []

        flash(
            "เกิดข้อผิดพลาดในการโหลดข้อมูลโต๊ะอาหาร",
            "error"
        )

    current_selected_ids = session.get(
        'selected_table_ids',
        []
    )

    if (
        not current_selected_ids
        and session.get('selected_table_id')
    ):
        current_selected_ids = [
            session.get('selected_table_id')
        ]

    current_selected_ids = [
        str(tid)
        for tid in current_selected_ids
    ]

    current_selected_no = session.get(
        'selected_table_no',
        ''
    )

    raw_customer_count = session.get(
        'customer_count',
        1
    )

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


@customer_bp.route(
    '/customer/checkout',
    methods=['POST']
)
def customer_checkout():
    """สร้างรายการสั่งอาหารเข้าครัว"""

    if session.get('role') != 'customer':
        return jsonify({
            'status': 'error',
            'message': 'ไม่มีสิทธิ์เข้าถึง'
        }), 403

    sync_user_table_session()

    data = request.get_json() or {}

    client_request_id = str(data.get('client_request_id') or '').strip()
    if client_request_id and len(client_request_id) > 120:
        return jsonify({
            'status': 'error',
            'message': 'รหัสคำขอไม่ถูกต้อง'
        }), 400

    table_id = (
        data.get('table_id')
        or session.get('selected_table_id')
    )

    table_no = (
        data.get('table_no')
        or session.get('selected_table_no')
    )

    if not table_id or not table_no:
        return jsonify({
            'status': 'error',
            'message': 'กรุณาเลือกโต๊ะอาหารก่อนสั่งซื้อ'
        }), 400

    raw_total = (
        data.get('total_amount')
        or data.get('total_price')
    )

    try:
        total_amount = float(raw_total) if raw_total is not None else 0.0
    except (ValueError, TypeError):
        total_amount = 0.0

    raw_count = (
        data.get('customer_count')
        or session.get('customer_count', 1)
    )

    try:
        customer_count = int(raw_count) if raw_count is not None else 1
        if customer_count < 1:
            customer_count = 1
    except (ValueError, TypeError):
        customer_count = 1

    # กำหนดสถานะการชำระเงินเริ่มต้นให้พนักงานมาเช็คบิลแทน
    payment_method = data.get('payment_method', 'เงินสด (เช็คบิลกับพนักงาน)')

    items = data.get('items', [])

    if not items:
        return jsonify({
            'status': 'error',
            'message': 'ไม่มีสินค้าในตะกร้า'
        }), 400

    try:
        user_key = get_current_user_key()

        if client_request_id:
            raw_existing_orders = get_firebase_data('orders')
            existing_orders = parse_firebase_data(raw_existing_orders)
            for existing in reversed(existing_orders):
                if (
                    str(existing.get('client_request_id', '')).strip() == client_request_id
                    and str(existing.get('user_key', '')).strip() == str(user_key).strip()
                ):
                    existing_id = existing.get('id') or existing.get('order_id')
                    if existing_id:
                        return jsonify({
                            'status': 'success',
                            'message': 'ออเดอร์นี้ถูกส่งไปแล้ว',
                            'order_id': existing_id,
                            'duplicate': True
                        })

        payload = {
            "table_no": table_no,
            "table_id": table_id,
            "table_ids": session.get(
                'selected_table_ids',
                [table_id]
            ),
            "customer_count": customer_count,
            "total_amount": total_amount,
            "total_price": total_amount,
            "payment_method": payment_method,
            "status": "pending",
            "items": items,
            "user_key": user_key or "",
            "client_request_id": client_request_id or "",
            "created_at": datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        }

        response = post_firebase_data(
            'orders',
            payload
        )

        if response and 'name' in response:
            return jsonify({
                'status': 'success',
                'message': 'สั่งอาหารสำเร็จ! กรุณารอสักครู่',
                'order_id': response.get('name')
            })

        raise Exception("Firebase Response Error")

    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@customer_bp.route(
    '/customer/call_staff',
    methods=['POST']
)
def customer_call_staff():
    """สร้างคำขอเรียกพนักงาน โดยป้องกันคำขอซ้ำ"""

    if session.get('role') != 'customer':
        return jsonify({
            'status': 'error',
            'message': 'ไม่มีสิทธิ์เข้าถึง'
        }), 403

    sync_user_table_session()

    data = request.get_json() or {}

    client_request_id = str(data.get('client_request_id') or '').strip()
    if client_request_id and len(client_request_id) > 120:
        return jsonify({
            'status': 'error',
            'message': 'รหัสคำขอไม่ถูกต้อง'
        }), 400

    table_no = (
        data.get('table_no')
        or session.get('selected_table_no')
    )

    table_id = (
        data.get('table_id')
        or session.get('selected_table_id')
    )

    if not table_id:
        selected_ids = session.get('selected_table_ids', [])
        if selected_ids:
            table_id = selected_ids[0]

    if not table_no:
        return jsonify({
            'status': 'error',
            'message': 'กรุณาเลือกโต๊ะก่อนเรียกพนักงาน'
        }), 400

    request_type = str(
        data.get('request_type', 'เรียกพนักงาน')
    ).strip() or 'เรียกพนักงาน'

    user_key = get_current_user_key()

    try:
        raw_existing = get_firebase_data('service_requests')
        existing_requests = parse_firebase_data(raw_existing)

        if client_request_id:
            for existing in reversed(existing_requests):
                if (
                    str(existing.get('client_request_id', '')).strip() == client_request_id
                    and str(existing.get('user_key', '')).strip() == str(user_key).strip()
                ):
                    existing_id = existing.get('id') or existing.get('request_id')
                    if existing_id:
                        return jsonify({
                            'status': 'success',
                            'message': 'คำขอนี้ถูกส่งไปแล้ว',
                            'id': existing_id,
                            'request_id': existing_id,
                            'duplicate': True
                        })

        active_statuses = {'pending', 'in_progress', 'accepted'}

        for existing in reversed(existing_requests):
            existing_status = str(existing.get('status', '')).strip().lower()
            existing_user = str(existing.get('user_key', '')).strip()
            existing_table = str(existing.get('table_no', '')).strip()
            existing_type = str(existing.get('request_type', '')).strip()

            is_duplicate = (
                existing_status in active_statuses
                and existing_user == str(user_key).strip()
                and existing_table == str(table_no).strip()
                and existing_type == request_type
            )

            if is_duplicate:
                existing_id = existing.get('id') or existing.get('request_id')
                if existing_id:
                    return jsonify({
                        'status': 'success',
                        'message': 'มีคำขอนี้อยู่แล้ว กำลังรอพนักงานดำเนินการ',
                        'id': existing_id,
                        'request_id': existing_id,
                        'duplicate': True
                    })

        payload = {
            "table_no": table_no,
            "table_id": table_id or "",
            "request_type": request_type,
            "status": "pending",
            "user_key": user_key or "",
            "client_request_id": client_request_id or "",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        response = post_firebase_data('service_requests', payload)

        if response and 'name' in response:
            req_id = response.get('name')
            return jsonify({
                'status': 'success',
                'message': 'แจ้งพนักงานเรียบร้อยแล้ว',
                'id': req_id,
                'request_id': req_id,
                'duplicate': False
            })

        raise Exception("Firebase Response Error")

    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@customer_bp.route('/customer/api/service_requests')
def customer_api_service_requests():
    """API ดึงข้อมูลสถานะคำขอเรียกพนักงานของลูกค้าแบบ Real-time"""

    if session.get('role') != 'customer':
        return jsonify({
            'status': 'error',
            'message': 'ไม่มีสิทธิ์เข้าถึง'
        }), 403

    sync_user_table_session()

    user_keys = get_current_user_keys()
    current_table_no = str(session.get('selected_table_no', '')).strip()

    req_ids_str = request.args.get('request_ids', '').strip()
    param_req_ids = (
        set(x.strip() for x in req_ids_str.split(',') if x.strip())
        if req_ids_str
        else set()
    )

    try:
        raw_requests = get_firebase_data('service_requests')
        all_requests = parse_firebase_data(raw_requests)

        matched_requests = []

        for req in all_requests:
            req_id = str(req.get('id', ''))
            req_user_key = str(req.get('user_key', '')).strip()
            req_table_no = str(req.get('table_no', '')).strip()

            is_user_match = bool(req_user_key and req_user_key in user_keys)
            is_id_match = bool(req_id and req_id in param_req_ids)
            is_table_match = bool(current_table_no and req_table_no == current_table_no)

            if is_user_match or is_id_match or is_table_match:
                matched_requests.append(req)

        return jsonify({
            'status': 'success',
            'requests': matched_requests
        })

    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@customer_bp.route('/customer/api/orders')
def customer_api_orders():
    """API ดึงข้อมูลออเดอร์ของลูกค้าสำหรับติดตามสถานะ"""

    if session.get('role') != 'customer':
        return jsonify({
            'status': 'error',
            'message': 'ไม่มีสิทธิ์เข้าถึง'
        }), 403

    sync_user_table_session()

    user_keys = get_current_user_keys()

    req_order_ids = request.args.get('order_ids', '').strip()
    param_order_ids = (
        set(x.strip() for x in req_order_ids.split(',') if x.strip())
        if req_order_ids
        else set()
    )

    current_table_id = str(session.get('selected_table_id', ''))
    current_table_ids = [str(x) for x in session.get('selected_table_ids', [])]
    current_table_no = str(session.get('selected_table_no', '')).strip()

    try:
        raw_orders = get_firebase_data('orders')
        all_orders = parse_firebase_data(raw_orders)

        matched_orders = []

        for ord_item in all_orders:
            ord_id = str(ord_item.get('id', ''))
            ord_user_key = str(ord_item.get('user_key', '')).strip()
            ord_status = str(ord_item.get('status', '')).lower()

            if ord_status == 'cancelled':
                continue

            ord_table_id = str(ord_item.get('table_id', ''))
            ord_table_ids = [str(x) for x in ord_item.get('table_ids', [])]
            ord_table_no = str(ord_item.get('table_no', '')).strip()

            is_user_match = bool(ord_user_key and ord_user_key in user_keys)
            is_id_match = bool(ord_id and ord_id in param_order_ids)
            is_table_match = bool(
                (current_table_id and ord_table_id == current_table_id)
                or any(tid in current_table_ids for tid in ord_table_ids if tid)
                or (current_table_no and ord_table_no == current_table_no)
            )

            if is_user_match or is_id_match or is_table_match:
                matched_orders.append(ord_item)

        matched_orders.sort(
            key=lambda x: str(x.get('created_at', '')),
            reverse=True
        )

        return jsonify({
            'status': 'success',
            'orders': matched_orders
        })

    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500