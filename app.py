from flask import Flask, render_template, request, redirect, session, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import qrcode, os
from datetime import datetime

# Initialize Flask App
app = Flask(__name__)

# Configuration
# Use environment variable for secret key in production, fallback for local dev
app.secret_key = os.environ.get('SECRET_KEY', 'your_super_secret_key_change_me_in_prod')

# Database Configuration (SQLite for local, PostgreSQL for Render deployment)
# Render automatically provides DATABASE_URL for PostgreSQL
# For local development, it will use db.sqlite3
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///db.sqlite3')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize SQLAlchemy
db = SQLAlchemy(app)


# -------------------- MODELS --------------------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    upi_id = db.Column(db.String(100), unique=True, nullable=False)

    # Relationships
    wallet = db.relationship('Wallet', backref='user', uselist=False, cascade='all, delete-orphan')

    def __repr__(self):
        return f"<User {self.email}>"


class Wallet(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False)
    balance = db.Column(db.Float, default=1000.0, nullable=False)

    def __repr__(self):
        return f"<Wallet UserID:{self.user_id} Balance:{self.balance}>"


class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_upi = db.Column(db.String(100), nullable=False)
    receiver_upi = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    description = db.Column(db.String(255), nullable=True)  # Added description field
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<Transaction {self.sender_upi} -> {self.receiver_upi} Amt:{self.amount}>"


# -------------------- QR GENERATION --------------------
def generate_qr(upi_id):
    """Generates a QR code for the given UPI ID and saves it to static/qrcodes/."""
    upi_url = f"upi://pay?pa={upi_id}&pn=WalletUser&cu=INR"  # Added currency code
    qr_dir = os.path.join(app.root_path, 'static', 'qrcodes')
    os.makedirs(qr_dir, exist_ok=True)  # Ensure the directory exists

    qr_filename = f'{upi_id}.png'
    path = os.path.join(qr_dir, qr_filename)

    # Only generate if the file doesn't exist to avoid redundant operations
    if not os.path.exists(path):
        img = qrcode.make(upi_url)
        img.save(path)

    # Return the path relative to the static folder for url_for
    return f'qrcodes/{qr_filename}'


# -------------------- ROUTES --------------------

@app.route('/')
def index():
    """Renders the home page."""
    return render_template('index.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    """Handles user registration."""
    if 'user_id' in session:  # If already logged in, redirect to dashboard
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        name = request.form['name'].strip()
        email = request.form['email'].strip().lower()
        password = request.form['password']

        if not name or not email or not password:
            flash('All fields are required.', 'error')
            return redirect(url_for('register'))

        if '@' not in email:
            flash('Please enter a valid email address.', 'error')
            return redirect(url_for('register'))

        # Check if email already registered
        if User.query.filter_by(email=email).first():
            flash('Email already registered. Please use a different email or log in.', 'error')
            return redirect(url_for('register'))

        # Generate UPI ID
        upi_id_base = email.split('@')[0]
        # Basic check for uniqueness, could be more robust
        unique_upi_id = f"{upi_id_base}@mockupi"
        counter = 1
        while User.query.filter_by(upi_id=unique_upi_id).first():
            unique_upi_id = f"{upi_id_base}{counter}@mockupi"
            counter += 1

        hashed_password = generate_password_hash(password)

        # Create user and wallet
        user = User(name=name, email=email, password=hashed_password, upi_id=unique_upi_id)
        db.session.add(user)
        db.session.commit()  # Commit user first to get user.id

        wallet = Wallet(user_id=user.id, balance=1000.0)  # Initial balance
        db.session.add(wallet)
        db.session.commit()

        # Generate QR code for the new user
        generate_qr(unique_upi_id)

        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Handles user login."""
    if 'user_id' in session:  # If already logged in, redirect to dashboard
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']

        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            flash(f'Welcome back, {user.name}!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid email or password. Please try again.', 'error')

    return render_template('login.html')


@app.route('/dashboard')
def dashboard():
    """Displays user dashboard with wallet balance and QR code."""
    if 'user_id' not in session:
        flash('Please log in to view your dashboard.', 'error')
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])
    if not user:  # Should not happen if session['user_id'] is valid
        session.clear()
        flash('User not found. Please log in again.', 'error')
        return redirect(url_for('login'))

    wallet = Wallet.query.filter_by(user_id=user.id).first()
    if not wallet:  # Should not happen if registration works correctly
        flash('Wallet not found for your account. Please contact support.', 'error')
        # Potentially create a wallet here or log an error
        return redirect(url_for('logout'))

    qr_static_path = generate_qr(user.upi_id)  # Generate QR code if it doesn't exist

    return render_template('dashboard.html', user=user, wallet=wallet, qr_path=qr_static_path)


@app.route('/transfer', methods=['POST'])
def transfer():
    """Handles peer-to-peer fund transfer."""
    if 'user_id' not in session:
        flash('Please log in to make a transfer.', 'error')
        return redirect(url_for('login'))

    sender_user = User.query.get(session['user_id'])
    sender_wallet = Wallet.query.filter_by(user_id=sender_user.id).first()

    receiver_upi = request.form.get('recipient_upi_id', '').strip().lower()
    amount_str = request.form.get('amount', '').strip()
    description = request.form.get('description', '').strip()

    # Input validation
    if not receiver_upi or not amount_str:
        flash('Recipient UPI ID and Amount are required.', 'error')
        return redirect(url_for('dashboard'))

    try:
        amount = float(amount_str)
        if amount <= 0:
            flash('Amount must be positive.', 'error')
            return redirect(url_for('dashboard'))
    except ValueError:
        flash('Invalid amount. Please enter a numerical value.', 'error')
        return redirect(url_for('dashboard'))

    if receiver_upi == sender_user.upi_id:
        flash("You cannot send money to yourself.", "error")
        return redirect(url_for('dashboard'))

    receiver_user = User.query.filter_by(upi_id=receiver_upi).first()

    if not receiver_user:
        flash(f'Recipient UPI ID "{receiver_upi}" not found.', 'error')
        return redirect(url_for('dashboard'))

    receiver_wallet = Wallet.query.filter_by(user_id=receiver_user.id).first()
    if not receiver_wallet:
        # This case should ideally not happen if every user has a wallet
        flash('Recipient wallet not found. Please contact support.', 'error')
        return redirect(url_for('dashboard'))

    if sender_wallet.balance < amount:
        flash('Insufficient balance to complete the transaction.', 'error')
        return redirect(url_for('dashboard'))

    # Perform the transaction within a database session
    try:
        sender_wallet.balance -= amount
        receiver_wallet.balance += amount

        # Create transaction record
        txn = Transaction(
            sender_upi=sender_user.upi_id,
            receiver_upi=receiver_upi,
            amount=amount,
            description=description if description else "UPI Transfer"
        )
        db.session.add(txn)
        db.session.commit()
        flash(f'Successfully sent ₹{amount:.2f} to {receiver_upi}.', 'success')
    except Exception as e:
        db.session.rollback()  # Rollback changes if anything goes wrong
        flash(f'An error occurred during transfer: {e}', 'error')

    return redirect(url_for('dashboard'))


@app.route('/history')
def history():
    """Displays the user's transaction history."""
    if 'user_id' not in session:
        flash('Please log in to view your transaction history.', 'error')
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])
    if not user:
        session.clear()
        flash('User not found. Please log in again.', 'error')
        return redirect(url_for('login'))

    # Fetch transactions where the current user is either sender or receiver
    transactions = Transaction.query.filter(
        (Transaction.sender_upi == user.upi_id) |
        (Transaction.receiver_upi == user.upi_id)
    ).order_by(Transaction.timestamp.desc()).all()  # Order by newest first

    return render_template('history.html', transactions=transactions, user=user)


@app.route('/logout')
def logout():
    """Logs the user out."""
    session.clear()  # Clears all session data
    flash('You have been successfully logged out.', 'success')
    return redirect(url_for('index'))


# -------------------- DATABASE INITIALIZATION --------------------
# This block ensures tables are created when the app runs locally
# For production deployment on Render with PostgreSQL, you'd typically
# run `db.create_all()` once via a Render build command or shell.
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)  # debug=True for local development