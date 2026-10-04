from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash

# 1. นำเข้าฟังก์ชันจาก auth_utils
from auth_utils import (
    get_all_users, 
    create_user, 
    validate_registration, 
    check_credentials
)

# 2. นำเข้า Blueprints จากแต่ละระบบ
from staff_utils import staff_bp
from admin_routes import admin_bp
from customer_routes import customer_bp

app = Flask(__name__)
app.secret_key = 'restaurant_super_secret'

# ลงทะเบียน Blueprints สำหรับ Admin, Staff และ Customer
app.register_blueprint(admin_bp)
app.register_blueprint(staff_bp)
app.register_blueprint(customer_bp)

# ==========================================
# AUTHENTICATION & HOME ROUTES
# ==========================================
@app.route('/')
def home():
    if 'username' in session:
        role = session.get('role')
        if role == 'admin':
            return redirect(url_for('admin.admin_dashboard'))
        elif role == 'staff':
            return redirect(url_for('staff.staff_orders'))
        else:
            return redirect(url_for('customer.customer_dashboard'))
    return redirect(url_for('signin'))

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        try:
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '').strip()
            role = 'customer' 

            users = get_all_users() or {}
            is_duplicate = any(info.get('username') == username for uid, info in users.items() if isinstance(info, dict))
            if is_duplicate:
                flash("ชื่อผู้ใช้นี้มีในระบบแล้ว", "error")
                return redirect(url_for('signup'))

            is_valid, msg = validate_registration(username, password, role)
            if not is_valid:
                flash(msg, "error")
                return redirect(url_for('signup'))

            hashed_password = generate_password_hash(password)
            if create_user(username, hashed_password, role):
                flash("สมัครสมาชิกสำเร็จ! กรุณาเข้าสู่ระบบ", "success")
                return redirect(url_for('signin'))
            else:
                flash("ไม่สามารถเชื่อมต่อฐานข้อมูล Firebase ได้ กรุณาลองใหม่อีกครั้ง", "error")
                return redirect(url_for('signup'))
                
        except Exception as e:
            flash(f"เกิดข้อผิดพลาดของระบบ: {str(e)}", "error")
            return redirect(url_for('signup'))

    return render_template('signup.html')

@app.route('/signin', methods=['GET', 'POST'])
def signin():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        is_valid, user_info = check_credentials(username, password)
        if is_valid:
            if not user_info.get('is_active', True):
                flash("บัญชีของคุณถูกระงับการใช้งาน กรุณาติดต่อผู้ดูแลระบบ", "error")
                return render_template('signin.html')

            session['username'] = user_info['username']
            session['role'] = user_info['role']
            session['user_id'] = user_info.get('id', '')
            
            role = user_info['role']
            if role == 'admin':
                return redirect(url_for('admin.admin_dashboard'))
            elif role == 'staff':
                return redirect(url_for('staff.staff_orders'))
            else:
                return redirect(url_for('customer.customer_dashboard'))
        else:
            flash("ชื่อผู้ใช้งานหรือรหัสผ่านไม่ถูกต้อง", "error")

    return render_template('signin.html')

@app.route('/signout')
def signout():
    session.clear()
    return redirect(url_for('signin'))

if __name__ == '__main__':
    app.run(debug=True)