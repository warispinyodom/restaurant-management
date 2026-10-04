import json
import ssl
import urllib.request
import urllib.error
import urllib.parse

FIREBASE_URL = "https://webapplication-e7922-default-rtdb.asia-southeast1.firebasedatabase.app"

ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# ==================== 1. จัดการออเดอร์และเช็คบิล (Orders & Bills) ====================

def get_all_orders():
    """ดึงข้อมูลออเดอร์ทั้งหมดจาก Firebase (GET /orders.json) พร้อมคลีนข้อมูลซิงค์ Frontend"""
    url = f"{FIREBASE_URL}/orders.json"
    try:
        req = urllib.request.Request(url, method='GET')
        with urllib.request.urlopen(req, context=ssl_context, timeout=10) as response:
            if response.status == 200:
                raw_data = response.read().decode('utf-8')
                data = json.loads(raw_data) if raw_data else {}
                if not data:
                    return []
                
                orders = []

                def process_order(order_id, order_info):
                    if not isinstance(order_info, dict):
                        return None

                    item = dict(order_info)
                    item['id'] = str(order_id)
                    item['order_id'] = str(order_id)
                    
                    # 1. จัดการสถานะ (status)
                    status_raw = str(item.get('status', 'pending')).lower().strip()
                    if not status_raw or status_raw in ['null', 'none']:
                        status_raw = 'pending'
                    item['status'] = status_raw
                    
                    # 2. จัดการเลขโต๊ะ (ซิงค์ทุกคีย์ที่ Frontend อาจเรียกใช้)
                    table_val = None
                    for key in ['table_no', 'table', 'table_number', 'tableNo']:
                        if key in item and item[key] is not None:
                            table_val = item[key]
                            break
                    
                    if table_val is None or str(table_val).strip() in ['-', '', 'None', 'null', 'undefined']:
                        clean_table = 'ไม่ระบุ'
                    else:
                        clean_table = str(table_val).strip()
                    
                    item['table_no'] = clean_table
                    item['table'] = clean_table
                    item['table_number'] = clean_table
                    
                    # 3. จัดการรายการสินค้า (items / order_items / menu_items)
                    raw_items = item.get('items') or item.get('order_items') or item.get('menu_items') or []
                    if isinstance(raw_items, dict):
                        raw_items_list = []
                        for k, v in raw_items.items():
                            if isinstance(v, dict):
                                v_copy = dict(v)
                                if 'id' not in v_copy:
                                    v_copy['id'] = str(k)
                                raw_items_list.append(v_copy)
                            else:
                                raw_items_list.append(v)
                    elif isinstance(raw_items, list):
                        raw_items_list = raw_items
                    else:
                        raw_items_list = []
                    
                    cleaned_items = []
                    calculated_total = 0.0

                    for raw_item in raw_items_list:
                        if isinstance(raw_item, dict):
                            it_name = raw_item.get('name') or raw_item.get('menu_name') or raw_item.get('title') or 'ไม่ระบุชื่ออาหาร'
                            
                            try:
                                qty_val = raw_item.get('quantity') if raw_item.get('quantity') is not None else raw_item.get('qty', 1)
                                it_qty = max(1, int(qty_val))
                            except (ValueError, TypeError):
                                it_qty = 1

                            try:
                                it_price = float(raw_item.get('price', 0))
                            except (ValueError, TypeError):
                                it_price = 0.0

                            try:
                                subtotal_raw = raw_item.get('subtotal')
                                if subtotal_raw is not None and str(subtotal_raw).strip() not in ['', 'None', 'null']:
                                    subtotal = float(subtotal_raw)
                                else:
                                    subtotal = it_price * it_qty
                            except (ValueError, TypeError):
                                subtotal = it_price * it_qty

                            calculated_total += subtotal

                            cleaned_items.append({
                                'name': str(it_name),
                                'menu_name': str(it_name),
                                'quantity': it_qty,
                                'qty': it_qty,
                                'price': it_price,
                                'subtotal': subtotal
                            })

                    item['items'] = cleaned_items
                    item['order_items'] = cleaned_items
                    item['menu_items'] = cleaned_items
                    item['bill_items'] = cleaned_items

                    # 4. จัดการราคารวม (total_price / total_amount / total)
                    tot = item.get('total_price') if item.get('total_price') is not None else item.get('total_amount')
                    if tot is None:
                        tot = item.get('total')
                    
                    try:
                        total_val = float(tot) if tot is not None and str(tot).strip() not in ['', 'None', 'null'] else calculated_total
                    except (ValueError, TypeError):
                        total_val = calculated_total

                    item['total_price'] = total_val
                    item['total_amount'] = total_val
                    item['total'] = total_val

                    # 5. จัดการเวลา
                    if 'created_at' not in item or not item['created_at']:
                        item['created_at'] = '-'

                    return item

                if isinstance(data, dict):
                    for order_id, order_info in data.items():
                        processed = process_order(order_id, order_info)
                        if processed:
                            orders.append(processed)
                elif isinstance(data, list):
                    for idx, order_info in enumerate(data):
                        if order_info is not None:
                            processed = process_order(idx, order_info)
                            if processed:
                                orders.append(processed)

                # เรียงลำดับออเดอร์ตามเวลาสร้างล่าสุดขึ้นก่อน
                orders.sort(key=lambda x: str(x.get('created_at') or ''), reverse=True)
                return orders

    except Exception as e:
        print(f"System Error (get_all_orders): {e}")
    return []

def get_orders_by_table(table_no):
    """ดึงออเดอร์ทั้งหมดของโต๊ะที่ระบุ"""
    all_orders = get_all_orders()
    target_table = str(table_no).strip().lower()
    return [
        ord for ord in all_orders 
        if str(ord.get('table_no', '')).strip().lower() == target_table
    ]

def get_bill_by_table(table_no):
    """ดึงและรวบรวมข้อมูลเช็คบิลของโต๊ะที่ระบุ (พร้อมรวมรายการอาหารและคำนวณราคารวม)"""
    table_orders = get_orders_by_table(table_no)
    
    # กรองเฉพาะออเดอร์ที่ยังไม่ได้ชำระเงินหรือยกเลิก
    active_orders = [
        ord for ord in table_orders 
        if str(ord.get('status')).lower() not in ['completed', 'cancelled', 'paid']
    ]

    all_items = []
    total_amount = 0.0

    for ord in active_orders:
        items_list = ord.get('order_items') or ord.get('items') or []
        if isinstance(items_list, list):
            for item in items_list:
                if isinstance(item, dict):
                    all_items.append(item)
                    total_amount += float(item.get('subtotal', 0.0))

    return {
        'table_no': str(table_no),
        'orders': active_orders,
        'items': all_items,       # สำหรับการเรียกผ่าน dict['items']
        'bill_items': all_items,  # ป้องกันการชนกับ dict.items ใน Python / Jinja2 (bill.bill_items)
        'items_list': all_items,  # Alias สำหรับดึงรายการอาหาร
        'total_amount': total_amount,
        'item_count': len(all_items),
        'order_count': len(active_orders)
    }

def update_order_status_db(order_id, status):
    """อัปเดตสถานะออเดอร์ใน Firebase (PATCH /orders/{order_id}.json)"""
    safe_order_id = urllib.parse.quote(str(order_id), safe='')
    url = f"{FIREBASE_URL}/orders/{safe_order_id}.json"
    payload = {"status": str(status).lower().strip()}
    data = json.dumps(payload).encode('utf-8')
    try:
        req = urllib.request.Request(
            url, 
            data=data, 
            headers={'Content-Type': 'application/json'}, 
            method='PATCH'
        )
        with urllib.request.urlopen(req, context=ssl_context, timeout=10) as response:
            return response.status in [200, 201]
    except Exception as e:
        print(f"System Error (update_order_status_db): {e}")
        return False

# ==================== 2. จัดการสถานะพนักงาน (Staff Status) ====================

def get_staff_status():
    """ดึงสถานะพนักงาน (GET /staff_status.json)"""
    url = f"{FIREBASE_URL}/staff_status.json"
    try:
        req = urllib.request.Request(url, method='GET')
        with urllib.request.urlopen(req, context=ssl_context, timeout=10) as response:
            if response.status == 200:
                raw_data = response.read().decode('utf-8')
                data = json.loads(raw_data) if raw_data else {}
                if isinstance(data, dict):
                    return data.get('status', 'ready')
                elif isinstance(data, str):
                    return data
    except Exception as e:
        print(f"System Error (get_staff_status): {e}")
    return 'ready'

def update_staff_status_db(status):
    """อัปเดตสถานะพนักงานใน Firebase (PATCH /staff_status.json)"""
    url = f"{FIREBASE_URL}/staff_status.json"
    payload = {"status": str(status)}
    data = json.dumps(payload).encode('utf-8')
    try:
        req = urllib.request.Request(
            url, 
            data=data, 
            headers={'Content-Type': 'application/json'}, 
            method='PATCH'
        )
        with urllib.request.urlopen(req, context=ssl_context, timeout=10) as response:
            return response.status in [200, 201]
    except Exception as e:
        print(f"System Error (update_staff_status_db): {e}")
        return False

# ==================== 3. จัดการเมนูและหมวดหมู่ (Menus & Categories) ====================

def get_all_categories():
    """ดึงข้อมูลหมวดหมู่ทั้งหมดจาก Firebase"""
    url = f"{FIREBASE_URL}/categories.json"
    try:
        req = urllib.request.Request(url, method='GET')
        with urllib.request.urlopen(req, context=ssl_context, timeout=10) as response:
            if response.status == 200:
                raw_data = response.read().decode('utf-8')
                data = json.loads(raw_data) if raw_data else {}
                return data if isinstance(data, (dict, list)) else {}
    except Exception as e:
        print(f"System Error (get_all_categories): {e}")
    return {}

def get_all_menus():
    """ดึงรายการเมนูทั้งหมดจาก Firebase (GET /menus.json) พร้อมซิงค์ status และ is_available"""
    categories = get_all_categories()
    url = f"{FIREBASE_URL}/menus.json"
    try:
        req = urllib.request.Request(url, method='GET')
        with urllib.request.urlopen(req, context=ssl_context, timeout=10) as response:
            if response.status == 200:
                data = json.loads(response.read().decode('utf-8'))
                if not data:
                    return []
                
                menus = []
                
                def process_item(menu_id, menu_info):
                    if isinstance(menu_info, dict):
                        item = dict(menu_info)
                        item['id'] = str(menu_id)
                        item['menu_id'] = str(menu_id)
                        
                        cat_id = item.get('category_id', '')
                        cat_name_from_db = None
                        
                        if isinstance(categories, dict) and str(cat_id) in categories:
                            cat_info = categories[str(cat_id)]
                            cat_name_from_db = cat_info.get('name') if isinstance(cat_info, dict) else str(cat_info)
                        elif isinstance(categories, list):
                            try:
                                idx = int(cat_id)
                                if 0 <= idx < len(categories):
                                    cat_info = categories[idx]
                                    cat_name_from_db = cat_info.get('name') if isinstance(cat_info, dict) else str(cat_info)
                            except (ValueError, TypeError):
                                pass

                        cat_final = cat_name_from_db or item.get('category', 'ทั่วไป')
                        item['category'] = str(cat_final)

                        # แปลงราคาและส่วนลดเป็น float ป้องกันประเภทข้อมูลผิดพลาด
                        try:
                            item['price'] = float(item.get('price', 0))
                        except (ValueError, TypeError):
                            item['price'] = 0.0

                        try:
                            item['discount'] = float(item.get('discount', 0))
                        except (ValueError, TypeError):
                            item['discount'] = 0.0

                        # แปลงจำนวนสต็อก
                        stock_val = item.get('stock')
                        if stock_val is not None and str(stock_val).strip() not in ['', 'None', 'null', 'ไม่จำกัด']:
                            try:
                                item['stock'] = int(stock_val)
                            except (ValueError, TypeError):
                                item['stock'] = None
                        else:
                            item['stock'] = None

                        # ซิงค์ทั้งคีย์ status และ is_available ให้ตรงกันเสมอ
                        raw_status = item.get('status')
                        if raw_status is not None:
                            status_str = str(raw_status).lower().strip()
                            if status_str in ['available', 'true', 'active', 'พร้อมขาย']:
                                item['status'] = 'available'
                                item['is_available'] = True
                            else:
                                item['status'] = 'out_of_stock'
                                item['is_available'] = False
                        else:
                            is_avail = bool(item.get('is_available', True))
                            item['is_available'] = is_avail
                            item['status'] = 'available' if is_avail else 'out_of_stock'

                        return item
                    return None

                if isinstance(data, dict):
                    for menu_id, menu_info in data.items():
                        processed = process_item(menu_id, menu_info)
                        if processed:
                            menus.append(processed)
                            
                elif isinstance(data, list):
                    for idx, menu_info in enumerate(data):
                        if menu_info is not None:
                            processed = process_item(idx, menu_info)
                            if processed:
                                menus.append(processed)

                return menus
    except Exception as e:
        print(f"System Error (get_all_menus): {e}")
    return []

def update_menu_item_db(menu_id, update_data):
    """อัปเดตราคา สต็อก และสถานะอาหารใน Firebase (PATCH /menus/{menu_id}.json)"""
    safe_menu_id = urllib.parse.quote(str(menu_id), safe='')
    url = f"{FIREBASE_URL}/menus/{safe_menu_id}.json"
    
    payload = {}
    if 'price' in update_data:
        try:
            payload['price'] = float(update_data['price'])
        except (ValueError, TypeError):
            payload['price'] = 0.0

    if 'discount' in update_data:
        try:
            payload['discount'] = float(update_data['discount'])
        except (ValueError, TypeError):
            payload['discount'] = 0.0

    if 'stock' in update_data:
        st_val = update_data['stock']
        if st_val is not None and str(st_val).strip() not in ['', 'None', 'null', 'ไม่จำกัด']:
            try:
                payload['stock'] = int(st_val)
            except (ValueError, TypeError):
                payload['stock'] = None
        else:
            payload['stock'] = None

    if 'status' in update_data:
        st = str(update_data['status']).lower().strip()
        payload['status'] = st
        payload['is_available'] = (st in ['available', 'true', 'active'])
    elif 'is_available' in update_data:
        is_avail = bool(update_data['is_available'])
        payload['is_available'] = is_avail
        payload['status'] = 'available' if is_avail else 'out_of_stock'

    if not payload:
        return True

    data = json.dumps(payload).encode('utf-8')
    try:
        req = urllib.request.Request(
            url, 
            data=data, 
            headers={'Content-Type': 'application/json'}, 
            method='PATCH'
        )
        with urllib.request.urlopen(req, context=ssl_context, timeout=10) as response:
            return response.status in [200, 201]
    except Exception as e:
        print(f"System Error (update_menu_item_db): {e}")
        return False

def bulk_update_menu_items_db(items_data):
    """อัปเดตข้อมูลแบบกลุ่มหลายรายการพร้อมกันใน Firebase"""
    if not items_data or not isinstance(items_data, dict):
        return False

    url = f"{FIREBASE_URL}/menus.json"
    payload = {}

    for menu_id, update_data in items_data.items():
        safe_menu_id = urllib.parse.quote(str(menu_id), safe='')
        if 'price' in update_data:
            try:
                payload[f"{safe_menu_id}/price"] = float(update_data['price'])
            except (ValueError, TypeError):
                payload[f"{safe_menu_id}/price"] = 0.0

        if 'discount' in update_data:
            try:
                payload[f"{safe_menu_id}/discount"] = float(update_data['discount'])
            except (ValueError, TypeError):
                payload[f"{safe_menu_id}/discount"] = 0.0

        if 'stock' in update_data:
            st_val = update_data['stock']
            if st_val is not None and str(st_val).strip() not in ['', 'None', 'null', 'ไม่จำกัด']:
                try:
                    payload[f"{safe_menu_id}/stock"] = int(st_val)
                except (ValueError, TypeError):
                    payload[f"{safe_menu_id}/stock"] = None
            else:
                payload[f"{safe_menu_id}/stock"] = None

        if 'status' in update_data:
            st = str(update_data['status']).lower().strip()
            payload[f"{safe_menu_id}/status"] = st
            payload[f"{safe_menu_id}/is_available"] = (st in ['available', 'true', 'active'])
        elif 'is_available' in update_data:
            is_avail = bool(update_data['is_available'])
            payload[f"{safe_menu_id}/is_available"] = is_avail
            payload[f"{safe_menu_id}/status"] = 'available' if is_avail else 'out_of_stock'

    if not payload:
        return True

    data = json.dumps(payload).encode('utf-8')
    try:
        req = urllib.request.Request(
            url, 
            data=data, 
            headers={'Content-Type': 'application/json'}, 
            method='PATCH'
        )
        with urllib.request.urlopen(req, context=ssl_context, timeout=10) as response:
            return response.status in [200, 201]
    except Exception as e:
        print(f"System Error (bulk_update_menu_items_db): {e}")
        return False