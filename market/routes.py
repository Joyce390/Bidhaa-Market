import time
import os
import uuid
import random
import logging
from functools import wraps
from flask import abort
from io import BytesIO
import pdfkit
from itsdangerous import URLSafeTimedSerializer
from flask_mail import Message
from market.utils import send_reset_email
from flask import make_response, render_template, redirect, url_for, flash, request, jsonify, session,  current_app, send_file, Response
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from PIL import Image
from flask import current_app as app
from market import db, bcrypt
from datetime import datetime
from market.mpesa import MpesaAPI
from market.models import User, Wallet, Item, Order, Sale, OwnedItem, Transaction, Notification
from market.forms import RegisterForm, LoginForm, SellItemForm, AddItemForm, PurchaseForm, PurchaseItemForm, ItemForm, EditItemForm, EditProfileForm, AdminSettingsForm
from market.decorators import admin_required  


def get_transaction_by_id(receipt_id):
    return Transaction.query.get(receipt_id)


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function



def admin_required(func):
    @wraps(func)
    def decorated_view(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash("❌ Admin access required!", category='danger')
            return redirect(url_for('admin_login'))
        return func(*args, **kwargs)
    return decorated_view



ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    """Check if the file has a valid extension."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def generate_barcode():
    """Generates a unique 12-digit barcode."""
    return str(random.randint(100000000000, 999999999999))  # 12-digit unique number



@app.route('/')
@app.route('/home')
def home_page():
    return render_template('home.html')


@app.route('/seller_dashboard')
@login_required
def seller_dashboard():
    items = Item.query.filter_by(seller_id=current_user.id).all()

    orders = Order.query.filter_by(seller_id=current_user.id).all()

    total_sales = db.session.query(db.func.sum(Order.total_price)).filter_by(seller_id=current_user.id).scalar() or 0.0

    notifications = Notification.query.filter_by(seller_id=current_user.id).order_by(Notification.date_created.desc()).limit(10).all()

    Notification.query.filter_by(seller_id=current_user.id, status='unread').update({'status': 'read'})
    db.session.commit()

    return render_template(
        'seller_dashboard.html',
        items=items,
        orders=orders,
        total_sales=total_sales,
        notifications=notifications
    )


@app.route('/seller/orders')
def seller_orders():
    orders = Order.query.filter_by(seller_id=current_user.id).all()  # Get orders for the seller
    return render_template('seller_orders.html', orders=orders)



@app.route('/seller_wallet', methods=['GET', 'POST'])
@login_required
def seller_wallet():
    # Fetch the seller's wallet
    seller_wallet = Wallet.query.filter_by(user_id=current_user.id).first()

    if not seller_wallet:
        flash("You don't have a wallet yet!", "warning")
        return redirect(url_for('seller_dashboard'))  # Redirect if no wallet exists

    if request.method == 'POST':
        withdraw_amount = float(request.form.get('withdraw_amount'))
        
        if withdraw_amount <= 0:
            flash("Invalid withdrawal amount!", 'danger')
        elif seller_wallet.balance >= withdraw_amount:
            seller_wallet.balance -= withdraw_amount
            db.session.commit()
            flash(f"Successfully withdrew KES {withdraw_amount} from your wallet.", 'success')
        else:
            flash("Insufficient funds to withdraw.", 'danger')

    return render_template('seller_wallet.html', seller_wallet=seller_wallet)



@app.route('/market', defaults={'category': 'All'}, methods=['GET', 'POST'])
@app.route('/market/<category>', methods=['GET', 'POST'])
@login_required
def market_page(category):
    purchase_form = PurchaseItemForm()

    if request.method == "POST":
        purchased_item_id = request.form.get('purchased_item_id')
        if not purchased_item_id:
            flash(" No item selected for purchase!", category='danger')
            return redirect(url_for('market_page', category=category))

        p_item_object = Item.query.get(purchased_item_id)
        if not p_item_object:
            flash(" Item not found!", category='danger')
            return redirect(url_for('market_page', category=category))

        if current_user.wallet and current_user.wallet.withdraw(p_item_object.price):
            p_item_object.owner = current_user.id  
            db.session.commit()
            flash(f" You purchased {p_item_object.name} for {p_item_object.price}!", category='success')
        else:
            flash(f" Insufficient balance to buy {p_item_object.name}", category='danger')

        return redirect(url_for('market_page', category=category))

    # Fetch items with seller details
    if category == "All":
        items = Item.query.filter(Item.seller_id.isnot(None)).all()
    else:
        items = Item.query.filter(Item.seller_id.isnot(None), Item.category == category).all()

    seller_ids = list({item.seller_id for item in items})  # Unique seller IDs
    sellers = {seller.id: seller for seller in User.query.filter(User.id.in_(seller_ids)).all()}

    return render_template(
        'market.html',
        items=items,
        purchase_form=purchase_form,
        selected_category=category,
        sellers=sellers 
    )




@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        user_to_create = User(
            username=form.username.data,
            email=form.email.data,
            phone=form.phone.data,  
            password=form.password1.data  
        )
        db.session.add(user_to_create)
        db.session.commit()
        return redirect(url_for('market_page', category='All'))  
    if form.errors != {}:
        for err_msg in form.errors.values():
            flash(f'There was an error with creating a user: {err_msg}', category='danger')
    return render_template('register.html', form=form)



@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        attempted_user = User.query.filter_by(username=form.username.data).first()
        if attempted_user and attempted_user.check_password(attempted_password=form.password.data):
            login_user(attempted_user)
            flash(f'Successfully logged in as: {attempted_user.username}', category='success')

            if attempted_user.is_admin:
                return redirect(url_for('admin_dashboard'))
            else:
                return redirect(url_for('market_page', category='All')) 

        else:
            flash('Username and password do not match! Please try again.', category='danger')
    return render_template('login.html', form=form)

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()
        if user:
            token = user.get_reset_token()
            reset_url = url_for('reset_password', token=token, _external=True)
            send_reset_email(user.email, reset_url)
            flash('Check your email for the password reset link.', 'info')
        else:
            flash('No account found with that email.', 'danger')
    return render_template('forgot_password.html')

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    user = User.verify_reset_token(token)
    if not user:
        flash('Invalid or expired token', 'danger')
        return redirect(url_for('forgot_password'))
    
    if request.method == 'POST':
        new_password = request.form.get('password')
        user.password_hash = generate_password_hash(new_password)
        db.session.commit()
        flash('Your password has been updated!', 'success')
        return redirect(url_for('login'))

    return render_template('reset_password.html', token=token)



@app.route('/search_items', methods=['GET'])
def search_items():
    query = request.args.get('query', '')
    items = Item.query.filter(Item.name.ilike(f"%{query}%")).all()
    purchase_form = PurchaseForm()
    return render_template('market.html', items=items, query=query, purchase_form=purchase_form)


@app.route('/wallet', methods=['GET', 'POST'])
@login_required
def wallet_page():
    if request.method == 'POST':
        amount = request.form.get('amount', type=float)
        if amount and amount > 0:
            current_user.wallet_balance += amount
            db.session.commit()
            flash("Wallet topped up successfully!", "success")
        else:
            flash("Invalid amount!", "danger")

    return render_template('wallet.html', wallet_balance=current_user.wallet_balance)




@app.route('/customer_dashboard')
@login_required
def customer_dashboard():
    return render_template('customer_dashboard.html', user=current_user)


from sqlalchemy.orm import joinedload

@app.route('/customer/orders')
@login_required
def customer_orders():
    # Get the current user's orders
    orders = Order.query.filter_by(user_id=current_user.id).all()
    
    # Print for debugging
    print(f"Found {len(orders)} orders for user {current_user.username}")
    
    # Render the template with the orders
    return render_template('customer_orders.html', orders=orders)



@app.route('/logout')
def logout():
    logout_user()
    session.pop('user_id', None) 
    session.clear() 
    flash("You have been logged out.", "info")
    return redirect(url_for('home_page'))



@app.route('/edit_item/<int:item_id>', methods=['GET', 'POST'])
@login_required
def edit_item(item_id):
    item = Item.query.get_or_404(item_id)
    
    form = EditItemForm(obj=item)
    
    if form.validate_on_submit():
        # Handle image upload if a new image is provided
        image_file = request.files.get('image')  
        if image_file:
            if allowed_file(image_file.filename):
                filename = secure_filename(image_file.filename)
                # Save the image file to the uploads folder
                image_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                item.image = filename  # Update the image field in the database
            else:
                flash('Invalid file type. Only JPG, PNG, and GIF files are allowed.', 'danger')
                return redirect(request.url)

        # Update item fields
        item.name = form.name.data
        item.price = form.price.data
        item.category = form.category.data
        item.description = form.description.data
        
        try:
            db.session.commit() 
            flash('Item updated successfully!', 'success')
            return redirect(url_for('seller_dashboard')) 
        except Exception as e:
            db.session.rollback() 
            flash('Error updating item.', 'danger')
            logging.error(f"Error: {e}")
            return redirect(request.url) 

    return render_template('edit_item.html', form=form, item=item) 


@app.route('/delete_item/<int:item_id>', methods=['POST'])
@login_required
def delete_item(item_id):
    item = Item.query.get(item_id)

    if not item:
        flash("Item not found!", "danger")
        return redirect(url_for('seller_dashboard'))  

    if item.seller_id != current_user.id:
        flash("You are not authorized to delete this item!", "danger")
        return redirect(url_for('seller_dashboard'))

    # Delete all related orders for this item
    Order.query.filter_by(item_id=item_id).delete()

    # Delete all sales records linked to this item
    Sale.query.filter_by(item_id=item_id).delete()

    # Delete the item itself
    db.session.delete(item)
    db.session.commit()

    flash("Item and all related data deleted successfully!", "success")
    return redirect(url_for('seller_dashboard'))




@app.route('/add_item', methods=['GET', 'POST'])
@login_required
def add_item():
    form = AddItemForm()
    if form.validate_on_submit():
        logging.debug("Form is valid!")
        image_file = request.files['image']
        filename = None
        if image_file and allowed_file(image_file.filename):
            filename = secure_filename(image_file.filename)
            image_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            logging.debug(f"Image saved as {filename}")
        else:
            logging.error("Invalid image file or no file uploaded!")

        barcode = generate_barcode()
        logging.debug(f"Generated barcode: {barcode}")

        new_item = Item(
            name=form.name.data,
            price=form.price.data,
            category=form.category.data,
            description=form.description.data,
            barcode=barcode,  
            image=filename,
            seller_id=current_user.id  
        )

        try:
            db.session.add(new_item)
            db.session.commit()
            flash('Item added successfully!', 'success')
            logging.debug("Item added successfully to the database!")
            return redirect(url_for('seller_dashboard'))
        except Exception as e:
            logging.error(f"Error adding item to database: {e}")
            flash("An error occurred while adding the item. Please try again.", "danger")
            return redirect(url_for('seller_dashboard'))

    else:
        # Log form validation errors
        logging.debug("Form is invalid!")
        for field, errors in form.errors.items():
            for error in errors:
                logging.error(f"Error in field {field}: {error}")

    return render_template('add_item.html', form=form)


@app.route('/seller_listed_items')
@login_required
def seller_listed_items():
    if not hasattr(current_user, 'is_seller') or not current_user.is_seller:
        flash("Unauthorized access!", "danger")
        return redirect(url_for('market'))

    items = Item.query.filter_by(seller_id=current_user.id).all()
    return render_template('seller_dashboard.html', items=items)

@app.route('/purchase/<int:item_id>', methods=['POST'])
@login_required
def purchase_item(item_id):
    item = Item.query.get_or_404(item_id)

    # Ensure the item is verified before purchase
    if not item.verified:
        flash("This item has not been verified and cannot be purchased.", "danger")
        return redirect(url_for('market_page'))

    # Ensure the seller exists
    seller = User.query.get(item.seller_id)
    if not seller:
        flash("Seller not found.", "danger")
        return redirect(url_for('market_page'))

    # Check if the item is already sold
    if item.sold:
        flash("This item has already been sold.", "danger")
        return redirect(url_for('market_page'))

    # Ensure buyer has enough balance
    buyer_wallet = Wallet.query.filter_by(user_id=current_user.id).first()
    if not buyer_wallet:
        # If buyer doesn't have a wallet, create one
        buyer_wallet = Wallet(user_id=current_user.id, balance=0)
        db.session.add(buyer_wallet)

    if buyer_wallet.balance < item.price:
        flash("Insufficient funds!", "danger")
        return redirect(url_for('market_page'))

    # Deduct money from buyer's wallet
    buyer_wallet.balance -= item.price

    # Ensure the seller has a wallet
    seller_wallet = Wallet.query.filter_by(user_id=seller.id).first()
    if not seller_wallet:
        # If seller doesn't have a wallet, create one
        seller_wallet = Wallet(user_id=seller.id, balance=0)
        db.session.add(seller_wallet)

    # Add money to seller's wallet
    seller_wallet.balance += item.price

    # Mark the item as sold
    item.sold = True

    # Create a new order
    new_order = Order(
        user_id=current_user.id,  # Buyer
        seller_id=seller.id,      # Seller
        item_id=item.id,
        total_price=item.price,
        shipping_status="Pending"  # Initial status
    )
    db.session.add(new_order)

    # Create a new owned item record
    owned_item = OwnedItem(
        owner_id=current_user.id,
        item_id=item.id,
        order_id=new_order.id  # This will be assigned after session.flush()
    )
    
    # We need to flush the session to get the order ID
    db.session.flush()
    
    # Now assign the order ID to the owned item
    owned_item.order_id = new_order.id
    db.session.add(owned_item)

    # Create a sale record
    sale = Sale(
        seller_id=seller.id,
        item_id=item.id,
        amount=item.price
    )
    db.session.add(sale)

    # Record the transaction
    transaction = Transaction(
        buyer_id=current_user.id,
        seller_id=seller.id,
        item_id=item.id,
        amount=item.price,
        status='Completed'
    )
    db.session.add(transaction)

    db.session.commit()
    flash(f"Congratulations! You purchased {item.name}.", "success")

    notification_message = f"A buyer has purchased your item: {item.name}. Please process shipping."
    new_notification = Notification(seller_id=seller.id, message=notification_message)
    
    db.session.add(new_notification)
    db.session.commit()

    flash('Item purchased successfully! The seller has been notified.', 'success')

    return redirect(url_for('customer_orders'))





@app.route('/order/<int:order_id>')
@login_required
def order_details(order_id):
    order = Order.query.get_or_404(order_id)
    
    # Ensure only the seller can view the order details
    if order.seller_id != current_user.id:
        return redirect(url_for('seller_dashboard'))

    return render_template('order_details.html', order=order)



@app.route('/cancel_order/<int:order_id>', methods=['POST'])
@login_required
def cancel_order(order_id):
    order = Order.query.get_or_404(order_id)

    # Ensure the order belongs to the logged-in user
    if order.user_id != current_user.id:
        flash("You are not authorized to cancel this order!", "danger")
        return redirect(url_for('customer_orders'))

    wallet = Wallet.query.filter_by(user_id=current_user.id).first()
    if wallet:
        wallet.balance += order.item.price  
        db.session.commit()

    db.session.delete(order)
    db.session.commit()

    flash("Order canceled and refunded successfully!", "success")
    return redirect(url_for('customer_orders'))



@app.route('/checkout', methods=['POST'])
@login_required
def checkout():
    item = Item.query.get(request.form.get('item_id'))
    if item and current_user.wallet_balance >= item.price:
        current_user.wallet_balance -= item.price  
        order = Order(
            buyer_id=current_user.id,
            seller_id=item.seller_id,  
            item_id=item.id,
            price=item.price
        )
        db.session.add(order)
        db.session.commit()
        flash("Purchase successful!", "success")
        return redirect(url_for('customer_orders'))
    flash("Insufficient funds or item not found.", "danger")
    return redirect(url_for('marketplace'))


@app.route('/submit_shipping_all', methods=['POST'])
@login_required
def submit_shipping_all():
    form_data = request.form

    shipping_town = form_data.get('global_town', '').strip()
    shipping_apartment = form_data.get('global_apartment', '').strip()
    shipping_phone = form_data.get('global_phone', '').strip()

    if not shipping_town or not shipping_apartment or not shipping_phone:
        flash('Please fill in all shipping details.', 'danger')
        return redirect(url_for('customer_orders'))

    orders = Order.query.filter_by(user_id=current_user.id).all()
    for order in orders:
        order.shipping_town = shipping_town
        order.shipping_apartment = shipping_apartment
        order.shipping_phone = shipping_phone
        order.shipping_status = "Processing" 

    db.session.commit()  

    flash('Shipping information updated successfully!', 'success')
    return redirect(url_for('customer_orders'))




 
@app.route('/become_seller', methods=['POST'])
@login_required
def become_seller():
    existing_seller = Seller.query.filter_by(user_id=current_user.id).first()
    
    if existing_seller:
        flash(" You are already a seller!", "danger")
        return redirect(url_for('market_page'))

    store_name = request.form.get('store_name')
    if not store_name:
        flash("Store name is required!", "danger")
        return redirect(url_for('market_page'))

    seller = Seller(user_id=current_user.id, store_name=store_name)
    db.session.add(seller)
    db.session.commit()

    flash(f"🎉 You are now a seller with the store '{store_name}'!", "success")
    return redirect(url_for('seller_dashboard'))

@app.route('/withdraw', methods=['POST'])
@login_required
def withdraw():
    amount = float(request.form.get('withdraw_amount'))
    mpesa_number = request.form.get('mpesa_number')
    
    wallet = Wallet.query.filter_by(user_id=current_user.id).first()
    
    if wallet and wallet.balance >= amount:
        wallet.balance -= amount  # Deduct from wallet

        # Log withdrawal as a transaction
        withdrawal = Transaction(
            seller_id=current_user.id,
            amount=amount,
            type="withdrawal",
            mpesa_number=mpesa_number  
        )
        db.session.add(withdrawal)
        db.session.commit()

        flash(f'Withdrawal of KES {amount} successful! Money sent to {mpesa_number}.', 'success')
    else:
        flash('Insufficient balance!', 'danger')

    return redirect(url_for('seller_dashboard'))



@app.route('/deposit', methods=['POST'])
@login_required
def deposit():
    data = request.get_json()
    phone = data.get('phone')
    amount = data.get('amount')

    if not phone or not amount:
        return jsonify({'error': 'Phone and amount are required'}), 400

    response = {"message": "STK Push sent successfully"}

    current_user.wallet.balance += amount
    db.session.commit()

    return jsonify(response)

@app.route('/transactions')
@login_required
def transactions():
    user_transactions = Transaction.query.filter(
        (Transaction.buyer_id == current_user.id) | (Transaction.seller_id == current_user.id)
    ).order_by(Transaction.date.desc()).all()

    return render_template('transactions.html', transactions=user_transactions)


    
@app.route('/top_up', methods=['POST'])
@login_required
def top_up():
    amount = request.form.get('amount')

    if not amount:
        flash("Amount is required!", "danger")
        return redirect(url_for('wallet_page'))

    try:
        amount = float(amount)
        if amount <= 0:
            flash("Invalid amount!", "danger")
            return redirect(url_for('wallet_page'))

        wallet = Wallet.query.filter_by(user_id=current_user.id).first()
        if not wallet:
            wallet = Wallet(user_id=current_user.id, balance=0)
            db.session.add(wallet)
            db.session.commit()

        wallet.deposit(amount)
        flash(f"Wallet topped up with KES {amount}!", "success")
    except ValueError:
        flash("Invalid input!", "danger")

    return redirect(url_for('wallet_page'))



@app.route('/verify_payment', methods=['POST'])
def verify_payment():
    phone = request.form.get('phone')
    transaction_code = request.form.get('transaction_code')
    amount = request.form.get('amount')

    print("Received Data:", phone, transaction_code, amount) 

    if not phone or not transaction_code or not amount:
        return jsonify({'error': 'Missing fields'}), 400

    phone = phone.replace(" ", "").replace("-", "")

    if phone.startswith("254"):  
        short_phone = phone[-9:]  
    elif phone.startswith("07"):
        short_phone = phone[1:]  
    else:
        short_phone = phone

    print(f"Searching for: {phone} OR {short_phone}")  

    user = User.query.filter(
        (User.phone == phone) | (User.phone == short_phone)
    ).first()

    if user:
        print(f"User found: {user.username} with phone {user.phone}")  
    else:
        print("User not found in database.") 
        return jsonify({'error': 'User not found'}), 404

    if not user.wallet:
        print(f"Creating wallet for {user.username}")
        user.wallet = Wallet(user_id=user.id, balance=0.0)  
        db.session.add(user.wallet)
        db.session.commit()

    user.wallet.balance += float(amount)
    db.session.commit()

    return jsonify({'message': 'Payment verified and wallet updated'})



    
@app.route('/mpesa/callback', methods=['POST'])
def mpesa_callback():
    data = request.get_json()

    if data.get("ResponseCode") == "0":
        print("Payment successful!")
    else:
        print(f"Payment failed: {data.get('ResponseDescription')}")
    
    return jsonify({"status": "success"}), 200

@app.route('/edit_profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    form = EditProfileForm()
    if form.validate_on_submit():
        current_user.phone = form.phone.data  # Update the phone field
        db.session.commit()
        flash("✅ Profile updated!", category='success')
        return redirect(url_for('seller_dashboard'))  
    return render_template('edit_profile.html', form=form)

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if current_user.is_authenticated and current_user.is_admin:
        return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password, password) and user.is_admin:
            login_user(user)
            flash("✅ Admin logged in successfully!", category="success")
            return redirect(url_for('admin_dashboard'))
        else:
            flash("❌ Invalid admin credentials!", category="danger")

    return render_template('admin_login.html')


@app.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        flash('Unauthorized Access!', category='danger')
        return redirect(url_for('market_page'))
    
    users = User.query.all()
    sellers = User.query.filter_by(is_seller=True).all()
    items = Item.query.all()
    transactions = Transaction.query.all()

    return render_template('admin_dashboard.html', users=users, sellers=sellers, items=items, transactions=transactions)

@app.route('/admin/profile')
@login_required
def admin_profile():
    return render_template('admin_profile.html')


@app.route('/admin/settings')
@login_required
def admin_settings():
    return render_template('admin_settings.html')



@app.route('/admin/users')
@login_required
@admin_required
def manage_users():
    users = User.query.all()
    return render_template('admin_users.html', users=users)


@app.route('/admin/items')
@login_required
@admin_required
def manage_items():
    items = Item.query.all()
    return render_template('admin_items.html', items=items)

@app.route('/admin/transactions')
@login_required
@admin_required
def manage_transactions():
    transactions = Transaction.query.all()
    return render_template('admin_transactions.html', transactions=transactions)

@app.route('/manage_sellers')
def manage_sellers():
    sellers = User.query.filter_by(role='seller').all()  # Adjust according to your model
    return render_template('manage_sellers.html', sellers=sellers)


@app.route('/admin/delete_user/<int:user_id>')
@login_required
def delete_user(user_id):
    user = User.query.get(user_id)
    if not user:
        flash('User not found', 'danger')
        return redirect(url_for('admin_dashboard'))

    Item.query.filter_by(seller_id=user.id).delete()

    db.session.delete(user)
    db.session.commit()
    flash('User deleted successfully', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin_delete_item/<int:item_id>', methods=['POST'])
@login_required
def admin_delete_item(item_id):
    item = Item.query.get(item_id)

    if not item:
        flash("Item not found!", "danger")
        return redirect(url_for('manage_items'))  

   
    orders_with_item = db.session.query(Order.query.filter_by(item_id=item_id).exists()).scalar()
    if orders_with_item:
        flash("Cannot delete item as it has been ordered!", "warning")
        return redirect(url_for('manage_items'))

    db.session.delete(item)
    db.session.commit()
    flash("Item deleted successfully!", "success")

    return redirect(url_for('manage_items'))  




@app.route('/receipt/<int:transaction_id>')
@login_required
def receipt(transaction_id):
    transaction = Transaction.query.get_or_404(transaction_id)
    if transaction.buyer_id != current_user.id and transaction.seller_id != current_user.id:
        flash("You don't have permission to view this receipt.", "danger")
        return redirect(url_for('index'))

    return render_template('receipt.html', transaction=transaction)



@app.route('/order/<int:order_id>/start_shipping', methods=['POST'])
@login_required
def start_shipping(order_id):
    order = Order.query.get_or_404(order_id)

    if order.seller_id != current_user.id:
        flash("You cannot modify this order.", "danger")
        return redirect(url_for('seller_orders'))

    order.shipping_status = 'Shipping in Process'
    db.session.commit()

    flash(f"Shipping for the order of {order.item.name} is now in process.", "success")
    return redirect(url_for('seller_orders'))


@app.route('/mark_order_as_shipping/<int:order_id>', methods=['POST'])
def mark_order_as_shipping(order_id):
    order = Order.query.get(order_id)
    if order:
        order.shipping_status = 'Shipping in Process'
        db.session.commit()
    return redirect(url_for('seller_orders'))


@app.route('/mark_order_as_shipped/<int:order_id>', methods=['POST'])
def mark_order_as_shipped(order_id):
    order = Order.query.get(order_id)
    if order:
        order.shipping_status = 'Shipped'
        db.session.commit()
    return redirect(url_for('seller_orders'))


@app.route('/delete_order/<int:order_id>', methods=['POST'])
@login_required
def delete_order(order_id):
    order = Order.query.get(order_id)
    
    if order and order.customer_id == current_user.id:
        if order.shipping_status == "Shipped":
            db.session.delete(order)
            db.session.commit()
            flash("Order deleted successfully!", "success")
        else:
            flash("You can only delete shipped orders.", "warning")
    else:
        flash("Order not found or unauthorized action.", "danger")

    return redirect(url_for('customer_orders'))



@app.route('/verify_item/<int:item_id>', methods=['POST'])
@login_required
@admin_required
def verify_item(item_id):
    item = Item.query.get_or_404(item_id)

    if item.verified:
        flash("Item is already verified!", "info")
    else:
        item.verified = True
        db.session.commit()
        flash(f"Item '{item.name}' has been verified!", "success")

    return redirect(request.referrer or url_for('admin_dashboard')) 




@app.route('/admin/setting', methods=['GET', 'POST'])
@login_required
def admin_setting():
    form = AdminSettingsForm()
    if form.validate_on_submit():
        
        settings.site_name = form.site_name.data
        settings.site_email = form.site_email.data
        settings.site_phone = form.site_phone.data
        settings.max_users = form.max_users.data
        settings.enable_registration = form.enable_registration.data
        settings.transaction_fee = form.transaction_fee.data
        settings.payment_gateway = form.payment_gateway.data
        settings.theme_color = form.theme_color.data
# Commit to DB
        flash('Settings saved successfully', 'success')
        return redirect(url_for('admin_setting'))
    return render_template('admin_setting.html', form=form)


@app.route('/generate_receipt/<int:receipt_id>')
def generate_receipt(receipt_id):
    transaction = get_transaction_by_id(receipt_id)  
    
    if not transaction:
        return "Transaction not found", 404
    
    rendered_html = render_template('receipt.html', transaction=transaction)

    path_to_wkhtmltopdf = r"C:\Program Files (x86)\wkhtmltopdf\bin\wkhtmltopdf.exe"  
    config = pdfkit.configuration(wkhtmltopdf=path_to_wkhtmltopdf)

    options = {
        'no-images': '',
        'enable-local-file-access': '',  
    }

    try:
        pdf = pdfkit.from_string(rendered_html, False, configuration=config, options=options)
        
        return Response(
            pdf, 
            content_type='application/pdf', 
            headers={'Content-Disposition': 'attachment;filename=receipt.pdf'}
        )
    except Exception as e:
        return f"An error occurred: {e}"




@app.route('/download_receipt/<int:transaction_id>')
@login_required
def download_receipt(transaction_id):
    transaction = Transaction.query.get_or_404(transaction_id)

    if transaction.buyer_id != current_user.id and transaction.seller_id != current_user.id:
        flash("You don't have permission to download this receipt.", "danger")
        return redirect(url_for('index'))

    rendered = render_template('receipt.html', transaction=transaction)

    pdf = weasyprint.HTML(string=rendered).write_pdf()

    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=receipt_{transaction.id}.pdf'

    return response

@app.route('/generate_report', methods=['GET'])
@login_required
def generate_report():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    # Fetch users and items
    users = User.query.all()
    items = Item.query.all()
    
    query = Transaction.query
    if start_date and end_date:
        query = query.filter(Transaction.date >= start_date, Transaction.date <= end_date)
    
    transactions = query.all()
    
    total_sales = sum(t.amount for t in transactions)
    num_transactions = len(transactions)

    top_items = (
        db.session.query(Item.name, db.func.count(Transaction.id))
        .join(Transaction, Transaction.item_id == Item.id)
        .group_by(Item.name)
        .order_by(db.func.count(Transaction.id).desc())
        .limit(5)
        .all()
    )

    top_buyers = (
        db.session.query(User.username, db.func.count(Transaction.id))
        .join(Transaction, Transaction.buyer_id == User.id)
        .group_by(User.username)
        .order_by(db.func.count(Transaction.id).desc())
        .limit(5)
        .all()
    )

    rendered_html = render_template(
        'report.html', 
        users=users, 
        items=items, 
        transactions=transactions, 
        total_sales=total_sales, 
        num_transactions=num_transactions, 
        top_items=top_items, 
        top_buyers=top_buyers, 
        start_date=start_date, 
        end_date=end_date
    )

    config = pdfkit.configuration(wkhtmltopdf=r'C:\Program Files (x86)\wkhtmltopdf\bin\wkhtmltopdf.exe')
    pdf = pdfkit.from_string(rendered_html, False, configuration=config)

    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = 'inline; filename=report.pdf'
    
    return response




