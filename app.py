from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import datetime
import requests
import pytz
import threading
import time
import json
import random

# অ্যাপ এবং ডেটাবেস কনফিগারেশন
app = Flask(__name__)
app.config['SECRET_KEY'] = 'a-very-secret-key-that-you-should-change'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# ===== প্রধান অ্যাডমিন বট কনফিগারেশন =====
ADMIN_BOT_TOKEN = '7630074820:AAGFY7xSoDdHIb4GGLg6rKHRNCdVvlH6VVQ'  # Eikhane apnar main bot er token din
ADMIN_CHAT_ID = '7078198425'            # Eikhane apnar main chat ID din
TELEGRAM_GROUP_LINK = 'https://t.me/Autopay_SH'
APPROVAL_SECRET_TOKEN = 'some-random-secret-string-for-approval'
LAST_UPDATE_ID = 0

# ===== NEW: BIN নোটিফিকেশন পাঠানোর জন্য নতুন বট কনফিগারেশন =====
BIN_NOTIFIER_BOT_TOKEN = '7907318035:AAECzx1IFvn880rUfG_4rYpM0K09kYzgLHQ' # Eikhane apnar *notun* bot er token din
BIN_NOTIFIER_CHAT_ID = '7078198425'   # Eikhane je group/channel a BIN jabe tar ID din

# ডেটাবেস মডেল
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    telegram_username = db.Column(db.String(80), nullable=True)
    password_hash = db.Column(db.String(120), nullable=False)
    is_approved = db.Column(db.Boolean, default=False, nullable=False)
    expiry_date = db.Column(db.DateTime, nullable=True)
    is_blocked = db.Column(db.Boolean, default=False, nullable=False)
    requested_duration = db.Column(db.Integer, nullable=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# কার্ড জেনারেট করার ফাংশন
def luhn_checksum(card_number):
    def digits_of(n): return [int(d) for d in str(n)]
    digits = digits_of(card_number)
    odd = digits[-1::-2]
    even = digits[-2::-2]
    checksum = sum(odd)
    for d in even:
        checksum += sum(digits_of(d*2))
    return checksum % 10

def generate_card_number(bin_prefix, length=16):
    num_to_generate = length - len(bin_prefix) - 1
    while True:
        num = bin_prefix + ''.join([str(random.randint(0,9)) for _ in range(num_to_generate)])
        for d in range(10):
            card = num + str(d)
            if luhn_checksum(card) == 0:
                return card
    return None

def generate_card(bin_prefix, date_mode, month, year, cvv, quantity):
    generated_cards = []
    quantity = min(quantity, 10000)
    for _ in range(quantity):
        card_number = generate_card_number(bin_prefix)
        if card_number:
            if date_mode == 'random':
                exp_month = str(random.randint(1, 12)).zfill(2)
                exp_year = str(random.randint(datetime.datetime.now().year + 1, datetime.datetime.now().year + 5))
            else:
                exp_month = str(month).zfill(2) if month else str(random.randint(1, 12)).zfill(2)
                exp_year = str(year)[-2:] if year else str(random.randint(datetime.datetime.now().year % 100 + 1, datetime.datetime.now().year % 100 + 5))
            card_cvv = str(cvv) if cvv else str(random.randint(100, 999))
            generated_cards.append({"number": card_number, "month": exp_month, "year": exp_year, "cvv": card_cvv})
    return generated_cards

# টেলিগ্রাম ফাংশন
def send_telegram_message(bot_token, chat_id, text):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    params = {'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'}
    try:
        requests.get(url, params=params)
    except Exception as e:
        print(f"Failed to send telegram message: {e}")

def send_approval_request_to_telegram(user):
    message = (f"New user registration:\n\nUsername: `{user.username}`\nEmail: `{user.email}`\nTelegram: `@{user.telegram_username}`\nRequested Duration: *{user.requested_duration} days*\n\nPlease approve for a specific duration:")
    approval_buttons = [{"text": f"Approve {d} Days", "url": url_for('approve_user', user_id=user.id, days=d, token=APPROVAL_SECRET_TOKEN, _external=True)} for d in [1, 3, 7, 30]]
    keyboard = {"inline_keyboard": [approval_buttons[:2], approval_buttons[2:]]}; params = {'chat_id': ADMIN_CHAT_ID, 'text': message, 'reply_markup': json.dumps(keyboard), 'parse_mode': 'Markdown'}
    url = f"https://api.telegram.org/bot{ADMIN_BOT_TOKEN}/sendMessage"; requests.get(url, params=params)

def send_login_notification_to_telegram(user, ip_address):
    dhaka_tz = pytz.timezone("Asia/Dhaka"); login_time = datetime.datetime.now(dhaka_tz).strftime('%Y-%m-%d %I:%M:%S %p')
    message = (f"User Logged In\n\nUsername: `{user.username}`\nIP Address: `{ip_address}`\nTime: `{login_time}`")
    send_telegram_message(ADMIN_BOT_TOKEN, ADMIN_CHAT_ID, message)

# ===== NEW: BIN নোটিফিকেশন পাঠানোর নতুন ফাংশন =====
def send_bin_to_telegram(user, used_bin, quantity):
    dhaka_tz = pytz.timezone("Asia/Dhaka")
    current_time = datetime.datetime.now(dhaka_tz).strftime('%Y-%m-%d %I:%M:%S %p')
    
    message = (
        f"💳 BIN Used\n\n"
        f"User: `{user.username}`\n"
        f"BIN: `{used_bin}`\n"
        f"Quantity: `{quantity}`\n"
        f"Time: `{current_time}`"
    )
    # নতুন বট এবং চ্যাট আইডি ব্যবহার করা হচ্ছে
    send_telegram_message(BIN_NOTIFIER_BOT_TOKEN, BIN_NOTIFIER_CHAT_ID, message)

# রুট এবং অন্যান্য ফাংশন
@app.route('/', methods=['GET', 'POST'])
@login_required
def index():
    if not current_user.is_approved or current_user.is_blocked or (current_user.expiry_date and current_user.expiry_date < datetime.datetime.now()):
        logout_user(); flash('Your account is inactive or expired. Please contact admin.', 'danger'); return redirect(url_for('login'))
    card_list = []
    if request.method == 'POST':
        bin_prefix = request.form.get('bin', '453590'); date_mode = request.form.get('date_mode', 'random'); month = request.form.get('month'); year = request.form.get('year'); cvv = request.form.get('cvv'); quantity = int(request.form.get('quantity', 10))
        if not bin_prefix: bin_prefix = '453590'
        
        # ===== NEW: BIN নোটিফিকেশন পাঠানোর ফাংশন কল করা হচ্ছে =====
        send_bin_to_telegram(current_user, bin_prefix, quantity)
        
        card_list = generate_card(bin_prefix, date_mode, month, year, cvv, quantity)
    return render_template('index.html', card_list=card_list, form_data=request.form, telegram_link=TELEGRAM_GROUP_LINK)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated: return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username'); password = request.form.get('password'); user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            if user.is_blocked: flash('Your account has been blocked.', 'danger')
            elif not user.is_approved: flash(f'Your account is pending approval. Please join our Telegram group.', 'warning')
            elif user.expiry_date and user.expiry_date < datetime.datetime.now(): flash('Your subscription has expired. Please contact admin.', 'danger')
            else: 
                login_user(user)
                ip_addr = request.remote_addr
                send_login_notification_to_telegram(user, ip_addr)
                return redirect(url_for('index'))
        else: flash('Invalid username or password.', 'danger')
    return render_template('login.html', telegram_link=TELEGRAM_GROUP_LINK)

# (বাকি কোড আগের মতোই থাকবে)
@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated: return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username'); email = request.form.get('email'); telegram_username = request.form.get('telegram_username'); password = request.form.get('password'); requested_duration = request.form.get('duration')
        if User.query.filter_by(username=username).first(): flash('Username already exists.', 'danger')
        elif User.query.filter_by(email=email).first(): flash('Email address already registered.', 'danger')
        else:
            new_user = User(username=username, email=email, telegram_username=telegram_username, requested_duration=requested_duration); new_user.set_password(password); db.session.add(new_user); db.session.commit()
            send_approval_request_to_telegram(new_user)
            flash('Registration successful! Please wait for admin approval.', 'success'); return redirect(url_for('login'))
    return render_template('register.html')
@app.route('/account', methods=['GET', 'POST'])
@login_required
def account():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'change_password':
            old_password = request.form.get('old_password'); new_password = request.form.get('new_password')
            if current_user.check_password(old_password): current_user.set_password(new_password); db.session.commit(); flash('Password updated successfully!', 'success')
            else: flash('Incorrect old password.', 'danger')
        elif action == 'change_email':
            new_email = request.form.get('new_email')
            if User.query.filter_by(email=new_email).first() and current_user.email != new_email: flash('Email address already in use.', 'danger')
            else: current_user.email = new_email; db.session.commit(); flash('Email updated successfully!', 'success')
        return redirect(url_for('account'))
    return render_template('account.html')
@app.route('/logout')
@login_required
def logout(): logout_user(); return redirect(url_for('login'))
@app.route('/approve_user')
def approve_user():
    user_id = request.args.get('user_id'); token = request.args.get('token'); days = request.args.get('days', type=int)
    if token != APPROVAL_SECRET_TOKEN: return "Invalid token.", 403
    if not days: return "Duration not specified.", 400
    user_to_approve = User.query.get(user_id)
    if user_to_approve:
        user_to_approve.is_approved = True; user_to_approve.expiry_date = datetime.datetime.now() + datetime.timedelta(days=days); db.session.commit()
        send_telegram_message(ADMIN_BOT_TOKEN, ADMIN_CHAT_ID, f"User `{user_to_approve.username}` has been approved with *{days} days* validity.")
        return f"User '{user_to_approve.username}' has been approved for {days} days!"
    else: return "User not found.", 404
def handle_bot_command(message):
    with app.app_context():
        command_text = message.get('text', ''); parts = command_text.split(); command = parts[0]
        if command == '/list':
            users = User.query.all();
            if not users: send_telegram_message(ADMIN_BOT_TOKEN, ADMIN_CHAT_ID, "No users found."); return
            user_list_text = "📜 *User List:*\n\n";
            for user in users:
                status = "🟢 Approved" if user.is_approved else "🟡 Pending";
                if user.is_blocked: status = "🔴 Blocked"
                expiry_text = "Never"
                if user.expiry_date:
                    if user.expiry_date < datetime.datetime.now(): status = "⚪ Expired"
                    expiry_text = user.expiry_date.strftime('%Y-%m-%d')
                user_list_text += f"- `{user.username}` | {status} | Expires: {expiry_text}\n"
            send_telegram_message(ADMIN_BOT_TOKEN, ADMIN_CHAT_ID, user_list_text)
        elif command == '/extend' and len(parts) == 3:
            username = parts[1]; days = int(parts[2]); user = User.query.filter_by(username=username).first()
            if user:
                if user.expiry_date and user.expiry_date > datetime.datetime.now(): user.expiry_date += datetime.timedelta(days=days)
                else: user.expiry_date = datetime.datetime.now() + datetime.timedelta(days=days)
                db.session.commit(); send_telegram_message(ADMIN_BOT_TOKEN, ADMIN_CHAT_ID, f"✅ Validity for `{username}` extended by {days} days. New expiry: {user.expiry_date.strftime('%Y-%m-%d')}")
            else: send_telegram_message(ADMIN_BOT_TOKEN, ADMIN_CHAT_ID, f"❌ User `{username}` not found.")
        elif command == '/block' and len(parts) == 2:
            username = parts[1]; user = User.query.filter_by(username=username).first()
            if user: user.is_blocked = True; db.session.commit(); send_telegram_message(ADMIN_BOT_TOKEN, ADMIN_CHAT_ID, f"🔴 User `{username}` has been blocked.")
            else: send_telegram_message(ADMIN_BOT_TOKEN, ADMIN_CHAT_ID, f"❌ User `{username}` not found.")
        elif command == '/unblock' and len(parts) == 2:
            username = parts[1]; user = User.query.filter_by(username=username).first()
            if user: user.is_blocked = False; db.session.commit(); send_telegram_message(ADMIN_BOT_TOKEN, ADMIN_CHAT_ID, f"🟢 User `{username}` has been unblocked.")
            else: send_telegram_message(ADMIN_BOT_TOKEN, ADMIN_CHAT_ID, f"❌ User `{username}` not found.")
def poll_telegram_bot():
    global LAST_UPDATE_ID; print("Bot polling started...");
    while True:
        try:
            url = f"https://api.telegram.org/bot{ADMIN_BOT_TOKEN}/getUpdates"; params = {'offset': LAST_UPDATE_ID + 1, 'timeout': 30}; response = requests.get(url, params=params).json()
            if response.get('result'):
                for update in response['result']:
                    LAST_UPDATE_ID = update['update_id']
                    if 'message' in update and 'text' in update['message']: handle_bot_command(update['message'])
            time.sleep(2)
        except Exception as e: print(f"Error in polling: {e}"); time.sleep(10)
def set_bot_commands():
    commands = [{"command": "list", "description": "List all registered users"}, {"command": "extend", "description": "/extend <user> <days>"}, {"command": "block", "description": "/block <user>"}, {"command": "unblock", "description": "/unblock <user>"}]
    url = f"https://api.telegram.org/bot{ADMIN_BOT_TOKEN}/setMyCommands"
    try:
        response = requests.post(url, json={'commands': commands}); print("Bot commands set successfully" if response.ok else "Failed to set bot commands")
    except Exception as e: print(f"Error setting bot commands: {e}")
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        set_bot_commands()
    polling_thread = threading.Thread(target=poll_telegram_bot, daemon=True)
    polling_thread.start()
    app.run(debug=False, port=5001)

