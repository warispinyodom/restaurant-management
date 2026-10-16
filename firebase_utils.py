import os
import urllib.parse
import json
import uuid
import requests
from functools import wraps
from datetime import datetime
from flask import session, flash, redirect, url_for
import firebase_admin
from firebase_admin import credentials, db

# ----------------------------------------------------
# Supabase Storage Configuration
# ----------------------------------------------------
SUPABASE_URL = os.environ.get('NEXT_PUBLIC_SUPABASE_URL', 'https://ihwacywjyvucosrygmbz.supabase.co').rstrip('/')
SUPABASE_BUCKET = os.environ.get('NEXT_PUBLIC_SUPABASE_BUCKET', 'restaurant-images')
SUPABASE_SECRET_KEY = os.environ.get('SUPABASE_SECRET_KEY', '')

# ----------------------------------------------------
# Firebase Admin SDK Setup (รองรับทั้ง Localhost และ Vercel)
# ----------------------------------------------------
FIREBASE_URL = os.environ.get('FIREBASE_DATABASE_URL') or os.environ.get(
    'FIREBASE_URL',
    "https://restaurant-management-startup-default-rtdb.asia-southeast1.firebasedatabase.app"
)

if not firebase_admin._apps:
    cred = None
    service_account_env = os.environ.get('FIREBASE_SERVICE_ACCOUNT')
    
    # 1. อ่านค่าจาก Environment Variable
    if service_account_env:
        try:
            val_str = service_account_env.strip()
            if val_str.startswith('{'):
                # กรณีเป็น JSON String (Vercel)
                cred_dict = json.loads(val_str)
                if 'private_key' in cred_dict:
                    cred_dict['private_key'] = cred_dict['private_key'].replace('\\n', '\n')
                cred = credentials.Certificate(cred_dict)
            elif os.path.exists(val_str):
                # กรณีเป็น Path ไฟล์ตรงๆ ในเครื่อง
                cred = credentials.Certificate(val_str)
        except Exception as e:
            print(f"Error parsing FIREBASE_SERVICE_ACCOUNT: {e}")

    # 2. Fallback: หาไฟล์ Key JSON ในเครื่องอัตโนมัติ
    if not cred:
        possible_keys = [
            "restaurant-management-startup-firebase-adminsdk-fbsvc-acf373906a.json",
            "serviceAccountKey.json"
        ]
        for key_file in possible_keys:
            key_path = os.path.join(os.path.dirname(__file__), key_file)
            if os.path.exists(key_path):
                cred = credentials.Certificate(key_path)
                break

    options = {
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
# Supabase Storage Helper Functions
# ==========================================
def upload_to_supabase_storage(file, folder="uploads"):
    """อัปโหลดไฟล์รูปภาพไปยัง Supabase Storage Bucket"""
    try:
        if not file or not file.filename:
            return None
            
        file.seek(0)
        file_data = file.read()
        
        extension = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'jpg'
        unique_filename = f"{folder}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}.{extension}"
        storage_path = f"{folder}/{unique_filename}" if folder else unique_filename
        
        upload_url = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{storage_path}"
        
        headers = {
            "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
            "apiKey": SUPABASE_SECRET_KEY,
            "Content-Type": file.content_type or 'image/jpeg',
            "x-upsert": "true"
        }
        
        res = requests.post(upload_url, data=file_data, headers=headers)
        
        if res.status_code in [200, 201]:
            public_url = f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{storage_path}"
            return public_url
        else:
            print(f"Supabase Storage Upload Error [{res.status_code}]: {res.text}")
            return None
    except Exception as e:
        print(f"Supabase Storage Upload Exception: {e}")
        return None

def delete_from_supabase_storage(image_url):
    """ลบไฟล์ออกจาก Supabase Storage ตาม Public URL"""
    try:
        if not image_url or not isinstance(image_url, str):
            return False
            
        if f"/storage/v1/object/public/{SUPABASE_BUCKET}/" in image_url:
            storage_path = image_url.split(f"/storage/v1/object/public/{SUPABASE_BUCKET}/")[1]
        elif f"/storage/v1/object/{SUPABASE_BUCKET}/" in image_url:
            storage_path = image_url.split(f"/storage/v1/object/{SUPABASE_BUCKET}/")[1]
        else:
            return False

        storage_path = urllib.parse.unquote(storage_path)
        delete_url = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{storage_path}"
        
        headers = {
            "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
            "apiKey": SUPABASE_SECRET_KEY
        }
        
        res = requests.delete(delete_url, headers=headers)
        return res.status_code in [200, 204]
    except Exception as e:
        print(f"Supabase Storage Delete Exception: {e}")
        return False

# Alias เพื่อความเข้ากันได้ย้อนหลัง (Backward Compatibility)
upload_to_firebase_storage = upload_to_supabase_storage
delete_from_firebase_storage = delete_from_supabase_storage

# ==========================================
# Firebase RTDB Helper Functions
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