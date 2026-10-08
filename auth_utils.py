from werkzeug.security import check_password_hash
from firebase_utils import get_firebase_data, post_firebase_data

def get_all_users():
    """ดึงข้อมูลผู้ใช้ทั้งหมดจาก Firebase Realtime Database"""
    try:
        users = get_firebase_data('users')
        if isinstance(users, dict):
            return users
        elif isinstance(users, list):
            return {str(i): v for i, v in enumerate(users) if v is not None}
        return {}
    except Exception as e:
        print(f"System Error (get_all_users): {e}")
        return {}

def create_user(username, password, role):
    """บันทึกข้อมูลผู้ใช้ใหม่ลง Firebase"""
    payload = {
        "username": username,
        "password": password,
        "role": role,
        "is_active": True
    }
    res = post_firebase_data('users', payload)
    return bool(res and 'name' in res)

def validate_registration(username, password, role):
    if not isinstance(username, str) or not isinstance(password, str):
        return False, "ข้อมูลต้องเป็นตัวอักษร"
    if len(username) < 3 or len(password) < 4:
        return False, "ชื่อผู้ใช้ต้องมีอย่างน้อย 3 ตัวอักษร และรหัสผ่าน 4 ตัวอักษร"
    if not validate_role(role):
        return False, "สิทธิ์ผู้ใช้งานไม่ถูกต้องตามระบบ"
    return True, "ข้อมูลถูกต้อง"

def validate_role(role):
    valid_roles = ["admin", "staff", "customer"]
    return role in valid_roles

def check_credentials(username, password):
    users = get_all_users()
    if not isinstance(users, dict):
        return False, None

    for uid, info in users.items():
        if isinstance(info, dict) and info.get('username') == username:
            stored_password = info.get('password')
            if not stored_password:
                continue
            
            is_match = False
            try:
                is_match = check_password_hash(stored_password, password)
            except Exception:
                is_match = (stored_password == password)

            if is_match:
                user_info = dict(info)
                user_info['id'] = uid
                return True, user_info
    return False, None