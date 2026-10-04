import os
import ssl
import urllib.request
import urllib.parse
import json
import uuid
from functools import wraps
from datetime import datetime
from flask import session, flash, redirect, url_for
import firebase_admin
from firebase_admin import credentials, storage

# ----------------------------------------------------
# Firebase Admin SDK Setup (สำหรับจัดการ Storage)
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

    if cred:
        firebase_admin.initialize_app(cred, {'storageBucket': FIREBASE_BUCKET})
    else:
        firebase_admin.initialize_app(options={'storageBucket': FIREBASE_BUCKET})

ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

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

def upload_to_firebase_storage(file, folder="uploads"):
    try:
        if not file or not file.filename:
            return None
            
        extension = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'jpg'
        unique_filename = f"{folder}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}.{extension}"
        storage_path = f"{folder}/{unique_filename}"
        
        bucket = storage.bucket()
        blob = bucket.blob(storage_path)
        
        content_type = file.content_type or 'image/jpeg'
        blob.upload_from_string(file.read(), content_type=content_type)
        
        encoded_path = urllib.parse.quote(storage_path, safe='')
        return f"https://firebasestorage.googleapis.com/v0/b/{bucket.name}/o/{encoded_path}?alt=media"
    except Exception as e:
        print(f"Firebase Storage Upload Error: {e}")
        return None

def delete_from_firebase_storage(image_url):
    try:
        if not image_url or not isinstance(image_url, str):
            return False
            
        if "/o/" in image_url:
            path_part = image_url.split("/o/")[1].split("?")[0]
            storage_path = urllib.parse.unquote(path_part)
            
            bucket = storage.bucket()
            blob = bucket.blob(storage_path)
            if blob.exists():
                blob.delete()
                return True
    except Exception as e:
        print(f"Firebase Storage Delete Error: {e}")
    return False

# ==========================================
# Firebase RTDB Helper Functions
# ==========================================
def get_firebase_data(path):
    try:
        url = f"{FIREBASE_URL}/{path}.json"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, context=ssl_context, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            return data if data is not None else {}
    except Exception as e:
        print(f"Error fetching {path}: {e}")
        return {}

def post_firebase_data(path, payload):
    try:
        url = f"{FIREBASE_URL}/{path}.json"
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), 
                                     headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(req, context=ssl_context, timeout=10) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"Error posting {path}: {e}")
        return None

def patch_firebase_data(path, item_id, payload):
    try:
        safe_item_id = urllib.parse.quote(str(item_id), safe='')
        url = f"{FIREBASE_URL}/{path}/{safe_item_id}.json"
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), 
                                     headers={'Content-Type': 'application/json'}, method='PATCH')
        with urllib.request.urlopen(req, context=ssl_context, timeout=10) as response:
            return response.status == 200
    except Exception as e:
        print(f"Error patching {path}/{item_id}: {e}")
        return False

def delete_firebase_data(path, item_id):
    try:
        safe_item_id = urllib.parse.quote(str(item_id), safe='')
        url = f"{FIREBASE_URL}/{path}/{safe_item_id}.json"
        req = urllib.request.Request(url, method='DELETE')
        with urllib.request.urlopen(req, context=ssl_context, timeout=10) as response:
            return response.status == 200
    except Exception as e:
        print(f"Error deleting {path}/{item_id}: {e}")
        return False

def parse_firebase_data(data):
    if isinstance(data, dict):
        return [{'id': str(k), **v} for k, v in data.items() if isinstance(v, dict)]
    elif isinstance(data, list):
        return [{'id': str(i), **v} for i, v in enumerate(data) if v and isinstance(v, dict)]
    return []

# ==========================================
# Guards
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