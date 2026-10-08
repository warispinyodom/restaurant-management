import os
import urllib.parse
import json
import uuid
from functools import wraps
from datetime import datetime
from flask import session, flash, redirect, url_for
import firebase_admin
from firebase_admin import credentials, storage, db

# ----------------------------------------------------
# Firebase Admin SDK Setup (สำหรับ Realtime Database & Storage)
# ----------------------------------------------------
FIREBASE_BUCKET = "webapplication-e7922.firebasestorage.app"
FIREBASE_URL = "https://webapplication-e7922-default-rtdb.asia-southeast1.firebasedatabase.app"

if not firebase_admin._apps:
    cred = None
    service_account_env = os.environ.get('FIREBASE_SERVICE_ACCOUNT')
    if service_account_env:
        try:
            cred_dict = json.loads(service_account_env)
            if 'private_key' in cred_dict:
                cred_dict['private_key'] = cred_dict['private_key'].replace('\\n', '\n')
            cred = credentials.Certificate(cred_dict)
        except Exception as e:
            print(f"Error parsing FIREBASE_SERVICE_ACCOUNT: {e}")

    if not cred:
        cred_path = os.path.join(os.path.dirname(__file__), "serviceAccountKey.json")
        if os.path.exists(cred_path):
            cred = credentials.Certificate(cred_path)

    options = {
        'storageBucket': FIREBASE_BUCKET,
        'databaseURL': FIREBASE_URL
    }

    if cred:
        firebase_admin.initialize_app(cred, options)
    else:
        firebase_admin.initialize_app(options=options)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}

DEFAULT_CATEGORIES = [
    "อาหารจานหลัก",
    "ยำ / ของว่างทานเล่น",
    "ชาบู / สุกี้ / ปิ้งย่าง",
    "เครื่องดื่ม",
    "ของหวาน",
    "เมนูแนะนำ / โปรโมชั่น",
    "อื่น ๆ"
]

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ==========================================
# Firebase Storage Helper Functions
# ==========================================
def upload_to_firebase_storage(file, folder="uploads"):
    """อัปโหลดไฟล์รูปภาพไปยัง Firebase Storage ผ่าน Firebase Admin SDK"""
    try:
        if not file or not file.filename:
            return None
            
        file.seek(0)  # รีเซ็ตตำแหน่งการอ่านไฟล์ใน Flask
        extension = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'jpg'
        unique_filename = f"{folder}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}.{extension}"
        storage_path = f"{folder}/{unique_filename}"
        
        bucket = storage.bucket()
        blob = bucket.blob(storage_path)
        
        content_type = file.content_type or 'image/jpeg'
        blob.upload_from_string(file.read(), content_type=content_type)
        
        try:
            blob.make_public()
            return blob.public_url
        except Exception:
            encoded_path = urllib.parse.quote(storage_path, safe='')
            return f"https://firebasestorage.googleapis.com/v0/b/{bucket.name}/o/{encoded_path}?alt=media"
    except Exception as e:
        print(f"Firebase Storage Upload Error: {e}")
        return None

def delete_from_firebase_storage(image_url):
    """ลบไฟล์ออกจาก Firebase Storage ตาม URL ที่กำหนด"""
    try:
        if not image_url or not isinstance(image_url, str):
            return False
            
        bucket = storage.bucket()
        
        if "firebasestorage.googleapis.com" in image_url or "storage.googleapis.com" in image_url:
            if "/o/" in image_url:
                path_part = image_url.split("/o/")[1].split("?")[0]
                storage_path = urllib.parse.unquote(path_part)
            else:
                storage_path = urllib.parse.unquote(image_url.split(f"{bucket.name}/")[-1])
            
            blob = bucket.blob(storage_path)
            if blob.exists():
                blob.delete()
                return True
    except Exception as e:
        print(f"Firebase Storage Delete Error: {e}")
    return False

# ==========================================
# Firebase RTDB Helper Functions (Firebase Admin SDK)
# ==========================================
def get_firebase_data(path):
    """ดึงข้อมูลจาก Firebase Realtime Database ตาม path ที่กำหนด"""
    try:
        clean_path = path.strip('/')
        ref = db.reference(clean_path)
        data = ref.get()
        return data if data is not None else {}
    except Exception as e:
        print(f"Error fetching {path}: {e}")
        return {}

def post_firebase_data(path, payload):
    """เพิ่มข้อมูลใหม่ลงใน path (push) ผ่าน Firebase Admin SDK"""
    try:
        clean_path = path.strip('/')
        ref = db.reference(clean_path)
        new_ref = ref.push(payload)
        return {'name': new_ref.key}
    except Exception as e:
        print(f"Error posting {path}: {e}")
        return None

def patch_firebase_data(path, item_id=None, payload=None):
    """อัปเดตข้อมูลบางส่วน (Update) ใน RTDB"""
    try:
        if payload is None:
            payload = item_id
            target_path = path.strip('/')
        else:
            target_path = f"{path.strip('/')}/{str(item_id).strip('/')}"

        ref = db.reference(target_path)
        if isinstance(payload, dict):
            ref.update(payload)
        else:
            ref.set(payload)
        return True
    except Exception as e:
        print(f"Error patching {path}/{item_id}: {e}")
        return False

def delete_firebase_data(path, item_id=None):
    """ลบข้อมูลจาก RTDB ผ่าน Firebase Admin SDK"""
    try:
        if item_id:
            target_path = f"{path.strip('/')}/{str(item_id).strip('/')}"
        else:
            target_path = path.strip('/')
            
        ref = db.reference(target_path)
        ref.delete()
        return True
    except Exception as e:
        print(f"Error deleting {path}/{item_id}: {e}")
        return False

def parse_firebase_data(data):
    """แปลงโครงสร้างข้อมูล Dict/List จาก RTDB ให้อยู่ในรูปแบบ List of Dicts มี id ในตัว"""
    if not data:
        return []
    if isinstance(data, dict):
        result = []
        for k, v in data.items():
            if isinstance(v, dict):
                item = dict(v)
                item['id'] = str(k)
                result.append(item)
            else:
                result.append({'id': str(k), 'value': v})
        return result
    elif isinstance(data, list):
        result = []
        for i, v in enumerate(data):
            if isinstance(v, dict):
                item = dict(v)
                item['id'] = str(i)
                result.append(item)
            elif v is not None:
                result.append({'id': str(i), 'value': v})
        return result
    return []

# ==========================================
# Guards / Decorators
# ==========================================
def admin_required(func_route):
    @wraps(func_route)
    def wrapper(*args, **kwargs):
        if session.get('role') != 'admin':
            flash("คุณไม่มีสิทธิ์เข้าถึงหน้านี้", "error")
            return redirect(url_for('home'))
        return func_route(*args, **kwargs)
    return wrapper

def staff_required(func_route):
    @wraps(func_route)
    def wrapper(*args, **kwargs):
        if session.get('role') not in ['staff', 'admin']:
            flash("คุณไม่มีสิทธิ์เข้าถึงหน้าพนักงาน", "error")
            return redirect(url_for('home'))
        return func_route(*args, **kwargs)
    return wrapper