import time
import os
import uuid
import random
import logging
import csv
import io
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
from market.models import User, Wallet, Item, Order, Sale, OwnedItem, Transaction, Notification
from market.forms import RegisterForm, LoginForm, SellItemForm, AddItemForm, PurchaseForm, PurchaseItemForm, ItemForm, EditItemForm, EditProfileForm, AdminSettingsForm
from market.decorators import admin_required  


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
    items = Item.query.filter_by(seller_id=current_user.id).order_by(Item.id.desc()).all()

    orders = Order.query.filter_by(seller_id=current_user.id).order_by(Order.order_date.desc()).all()
    active_orders = [o for o in orders if o.shipping_status not in ('Delivered',)]

    # Buyers pay on delivery, so only delivered orders count as sales
    total_sales = db.session.query(db.func.sum(Order.total_price)).filter_by(seller_id=current_user.id, shipping_status='Delivered').scalar() or 0.0

    stats = {
        'total_sales': total_sales,
        'orders_to_ship': sum(1 for o in orders if o.shipping_status in ('Pending', 'Processing', 'Shipping in Process')),
        'awaiting_delivery': sum(1 for o in orders if o.shipping_status == 'Shipped'),
        'delivered': sum(1 for o in orders if o.shipping_status == 'Delivered'),
        'live_items': sum(1 for i in items if i.verified and not i.sold),
        'hidden_items': sum(1 for i in items if not i.verified and not i.sold),
        'sold_items': sum(1 for i in items if i.sold),
    }

    notifications = Notification.query.filter_by(seller_id=current_user.id).order_by(Notification.date_created.desc()).limit(10).all()
    # Remember which ones are new before marking them read, so the page can highlight them
    unread_ids = {n.id for n in notifications if n.status == 'unread'}

    Notification.query.filter_by(seller_id=current_user.id, status='unread').update({'status': 'read'})
    db.session.commit()

    return render_template(
        'seller_dashboard.html',
        items=items,
        active_orders=active_orders[:5],
        stats=stats,
        notifications=notifications,
        unread_ids=unread_ids
    )


@app.route('/seller/orders')
@login_required
def seller_orders():
    orders = Order.query.filter_by(seller_id=current_user.id).all()  # Get orders for the seller
    return render_template('seller_orders.html', orders=orders)



@app.route('/market', defaults={'category': 'All'})
@app.route('/market/<category>')
@login_required
def market_page(category):
    query = request.args.get('q', '').strip()

    # Only items buyers can actually order: not hidden by an admin and not sold yet
    items = Item.query.filter(Item.verified.is_(True), Item.sold.is_(False))
    if category != "All":
        items = items.filter(Item.category == category)
    if query:
        items = items.filter(Item.name.ilike(f"%{query}%") | Item.description.ilike(f"%{query}%"))
    items = items.order_by(Item.id.desc()).all()

    categories = ['All', 'Fashion', 'Electronics', 'Sports', 'Tools']

    return render_template(
        'market.html',
        items=items,
        selected_category=category,
        categories=categories,
        query=query
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
        login_user(user_to_create)
        flash(f'Welcome to Bidhaa Market, {user_to_create.username}! Your account can buy and sell.', category='success')
        return redirect(url_for('market_page', category='All'))
    # Field errors are shown next to each field on the form
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
    # Search lives on the market page now
    return redirect(url_for('market_page', category='All', q=request.args.get('query', '')))


@app.route('/customer_dashboard')
@login_required
def customer_dashboard():
    orders = Order.query.filter_by(user_id=current_user.id).order_by(Order.order_date.desc()).all()
    delivered = [o for o in orders if o.shipping_status == 'Delivered']
    on_the_way = [o for o in orders if o.shipping_status != 'Delivered']

    stats = {
        'bought': len(delivered),
        'on_the_way': len(on_the_way),
        'total_spent': sum(o.total_price for o in delivered),
        'to_pay': sum(o.total_price for o in on_the_way),
        # Every account can also sell
        'selling': Item.query.filter_by(seller_id=current_user.id, sold=False).count(),
    }

    return render_template('customer_dashboard.html', orders=orders, stats=stats)


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
            seller_id=current_user.id,
            verified=True  # New items go live straight away; admins can hide them later
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
    # The listed items live on the seller dashboard
    return redirect(url_for('seller_dashboard', _anchor='listed-items'))

@app.route('/purchase/<int:item_id>', methods=['GET', 'POST'])
@login_required
def purchase_item(item_id):
    """Checkout: the buyer fills in where to deliver (and pins it on a map), then pays on delivery."""
    item = Item.query.get_or_404(item_id)

    # Items hidden by an admin can't be bought
    if not item.verified:
        flash("This item is not available right now.", "danger")
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

    if item.seller_id == current_user.id:
        flash("You cannot buy your own item.", "danger")
        return redirect(url_for('market_page'))

    # Prefill the form from the buyer's last order so repeat buyers don't retype their address
    last_order = Order.query.filter_by(user_id=current_user.id).order_by(Order.order_date.desc()).first()
    delivery = {
        'town': last_order.shipping_town if last_order else '',
        'apartment': last_order.shipping_apartment if last_order else '',
        'phone': (last_order.shipping_phone if last_order else None) or current_user.phone or '',
        'notes': '',
        'lat': last_order.delivery_lat if last_order else None,
        'lng': last_order.delivery_lng if last_order else None,
    }

    if request.method == 'GET':
        return render_template('checkout.html', item=item, delivery=delivery)

    delivery = {
        'town': request.form.get('town', '').strip(),
        'apartment': request.form.get('apartment', '').strip(),
        'phone': request.form.get('phone', '').strip(),
        'notes': request.form.get('notes', '').strip()[:255],
        'lat': request.form.get('lat', type=float),
        'lng': request.form.get('lng', type=float),
    }

    if not delivery['town'] or not delivery['apartment'] or not delivery['phone']:
        flash("Please fill in your town, apartment/building and phone number.", "danger")
        return render_template('checkout.html', item=item, delivery=delivery)

    if (delivery['lat'] is None or delivery['lng'] is None
            or not -90 <= delivery['lat'] <= 90 or not -180 <= delivery['lng'] <= 180):
        flash("Please pin your delivery location on the map.", "danger")
        return render_template('checkout.html', item=item, delivery=delivery)

    # Payment is made on delivery, so no money moves here - just reserve the item
    item.sold = True

    # Create a new order
    new_order = Order(
        user_id=current_user.id,  # Buyer
        seller_id=seller.id,      # Seller
        item_id=item.id,
        total_price=item.price,
        shipping_status="Processing",  # Delivery details are known, seller can start shipping
        shipping_town=delivery['town'],
        shipping_apartment=delivery['apartment'],
        shipping_phone=delivery['phone'],
        delivery_notes=delivery['notes'] or None,
        delivery_lat=delivery['lat'],
        delivery_lng=delivery['lng']
    )
    db.session.add(new_order)

    # We need to flush the session to get the order ID
    db.session.flush()

    owned_item = OwnedItem(
        owner_id=current_user.id,
        item_id=item.id,
        order_id=new_order.id
    )
    db.session.add(owned_item)

    notification_message = f"A buyer has ordered your item: {item.name}. Payment is on delivery. Please process shipping."
    db.session.add(Notification(seller_id=seller.id, message=notification_message))

    db.session.commit()

    flash(f"Order placed for {item.name}! You will pay Ksh {item.price} on delivery.", "success")

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

    if order.shipping_status in ('Shipped', 'Delivered'):
        flash("This order has already been shipped and can no longer be canceled.", "warning")
        return redirect(url_for('customer_orders'))

    # Nothing was paid yet (payment is on delivery), so just release the item back to the market
    order.item.sold = False
    OwnedItem.query.filter_by(order_id=order.id).delete()
    db.session.delete(order)
    db.session.commit()

    flash("Order canceled successfully!", "success")
    return redirect(url_for('customer_orders'))



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

        if user and user.check_password(password) and user.is_admin:
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
    sellers = User.query.filter(User.role.in_(['seller', 'both'])).all()
    items = Item.query.all()
    hidden_items = Item.query.filter_by(verified=False, sold=False).count()
    # Newest listings, so the admin can spot and hide anything inappropriate
    latest_items = Item.query.filter_by(sold=False).order_by(Item.id.desc()).limit(8).all()

    orders = Order.query.order_by(Order.order_date.desc()).all()
    order_stats = {
        'total': len(orders),
        'in_progress': sum(1 for o in orders if o.shipping_status != 'Delivered'),
        'delivered': sum(1 for o in orders if o.shipping_status == 'Delivered'),
        'delivered_value': sum(o.total_price for o in orders if o.shipping_status == 'Delivered'),
    }

    # Top sellers by value of delivered (paid) orders
    top_sellers = (
        db.session.query(User.username, db.func.count(Order.id), db.func.sum(Order.total_price))
        .join(Order, Order.seller_id == User.id)
        .filter(Order.shipping_status == 'Delivered')
        .group_by(User.username)
        .order_by(db.func.sum(Order.total_price).desc())
        .limit(5)
        .all()
    )
    new_users = User.query.order_by(User.id.desc()).limit(5).all()

    return render_template('admin_dashboard.html', users=users, sellers=sellers, items=items,
                           hidden_items=hidden_items, latest_items=latest_items, recent_orders=orders[:8], order_stats=order_stats,
                           top_sellers=top_sellers, new_users=new_users)

@app.route('/admin/users')
@login_required
@admin_required
def manage_users():
    q = request.args.get('q', '').strip()
    query = User.query
    if q:
        query = query.filter(User.username.ilike(f"%{q}%") | User.email.ilike(f"%{q}%") | User.phone.ilike(f"%{q}%"))
    users = query.order_by(User.id.desc()).all()

    # Per-user activity so the admin can see who buys and who sells
    items_listed = dict(db.session.query(Item.seller_id, db.func.count(Item.id)).group_by(Item.seller_id).all())
    orders_placed = dict(db.session.query(Order.user_id, db.func.count(Order.id)).group_by(Order.user_id).all())
    orders_received = dict(db.session.query(Order.seller_id, db.func.count(Order.id)).group_by(Order.seller_id).all())

    return render_template('admin_users.html', users=users, q=q, items_listed=items_listed,
                           orders_placed=orders_placed, orders_received=orders_received)


@app.route('/admin/users/<int:user_id>/toggle_admin', methods=['POST'])
@login_required
@admin_required
def toggle_admin(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("You can't remove your own admin access.", "warning")
    else:
        user.is_admin = not user.is_admin
        db.session.commit()
        flash(f"{user.username} is {'now an admin' if user.is_admin else 'no longer an admin'}.", "success")
    return redirect(request.referrer or url_for('manage_users'))


@app.route('/admin/users/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)

    if user.id == current_user.id:
        flash("You can't delete your own account.", "warning")
        return redirect(url_for('manage_users'))

    # Keep order history intact: users who have bought or sold can't be deleted
    has_orders = Order.query.filter((Order.user_id == user.id) | (Order.seller_id == user.id)).first()
    if has_orders:
        flash(f"{user.username} has orders on record and can't be deleted.", "warning")
        return redirect(url_for('manage_users'))

    for item in Item.query.filter_by(seller_id=user.id).all():
        Sale.query.filter_by(item_id=item.id).delete()
        db.session.delete(item)
    Notification.query.filter_by(seller_id=user.id).delete()
    Wallet.query.filter_by(user_id=user.id).delete()
    db.session.delete(user)
    db.session.commit()
    flash(f"User {user.username} deleted.", "success")
    return redirect(url_for('manage_users'))


@app.route('/admin/items')
@login_required
@admin_required
def manage_items():
    status = request.args.get('status', 'All')
    q = request.args.get('q', '').strip()
    query = Item.query
    if status == 'Hidden':
        query = query.filter(Item.verified.is_(False), Item.sold.is_(False))
    elif status == 'Live':
        query = query.filter(Item.verified.is_(True), Item.sold.is_(False))
    elif status == 'Sold':
        query = query.filter(Item.sold.is_(True))
    if q:
        query = query.filter(Item.name.ilike(f"%{q}%"))
    items = query.order_by(Item.id.desc()).all()
    return render_template('admin_items.html', items=items, status=status, q=q)


@app.route('/admin/items/<int:item_id>/unverify', methods=['POST'])
@login_required
@admin_required
def unverify_item(item_id):
    """Hide an item from the market (e.g. after a complaint). It can be shown again later."""
    item = Item.query.get_or_404(item_id)
    item.verified = False
    db.session.add(Notification(seller_id=item.seller_id,
                                message=f"Your item '{item.name}' was hidden from the market by an admin. Contact support if you think this is a mistake."))
    db.session.commit()
    flash(f"'{item.name}' is now hidden from the market.", "info")
    return redirect(request.referrer or url_for('manage_items'))


@app.route('/admin/orders')
@login_required
@admin_required
def manage_orders():
    # Buyers pay on delivery, so orders (not transactions) are the record of what was bought
    status = request.args.get('status', 'All')
    q = request.args.get('q', '').strip()
    query = Order.query
    if status == 'In progress':
        query = query.filter(Order.shipping_status != 'Delivered')
    elif status == 'Delivered':
        query = query.filter(Order.shipping_status == 'Delivered')
    orders = query.order_by(Order.order_date.desc()).all()
    if q:
        ql = q.lower()
        orders = [o for o in orders if ql in o.item.name.lower() or ql in o.user.username.lower()
                  or ql in o.seller.username.lower() or ql in (o.shipping_town or '').lower()]
    return render_template('admin_orders.html', orders=orders, status=status, q=q)


@app.route('/admin/orders/<int:order_id>/cancel', methods=['POST'])
@login_required
@admin_required
def admin_cancel_order(order_id):
    order = Order.query.get_or_404(order_id)
    if order.shipping_status == 'Delivered':
        flash("Delivered orders can't be cancelled.", "warning")
        return redirect(request.referrer or url_for('manage_orders'))

    # Nothing has been paid yet, so cancelling just puts the item back on the market
    order.item.sold = False
    db.session.add(Notification(seller_id=order.seller_id,
                                message=f"The order for '{order.item.name}' was cancelled by an admin. The item is back on the market."))
    OwnedItem.query.filter_by(order_id=order.id).delete()
    db.session.delete(order)
    db.session.commit()
    flash("Order cancelled and the item is back on the market.", "success")
    return redirect(request.referrer or url_for('manage_orders'))


@app.route('/admin/export/<string:dataset>.csv')
@login_required
@admin_required
def admin_export(dataset):
    """Download users, items or orders as a CSV file (opens in Excel / Google Sheets)."""
    def fmt_date(d):
        return d.strftime('%Y-%m-%d %H:%M') if d else ''

    if dataset == 'users':
        header = ['ID', 'Username', 'Email', 'Phone', 'Admin', 'Joined', 'Items listed', 'Orders placed', 'Orders received']
        items_listed = dict(db.session.query(Item.seller_id, db.func.count(Item.id)).group_by(Item.seller_id).all())
        orders_placed = dict(db.session.query(Order.user_id, db.func.count(Order.id)).group_by(Order.user_id).all())
        orders_received = dict(db.session.query(Order.seller_id, db.func.count(Order.id)).group_by(Order.seller_id).all())
        rows = [[u.id, u.username, u.email, u.phone or '', 'Yes' if u.is_admin else 'No', fmt_date(u.created_at),
                 items_listed.get(u.id, 0), orders_placed.get(u.id, 0), orders_received.get(u.id, 0)]
                for u in User.query.order_by(User.id).all()]
    elif dataset == 'items':
        header = ['ID', 'Name', 'Category', 'Price (Ksh)', 'Status', 'Seller', 'Barcode', 'Description']
        rows = [[i.id, i.name, i.category, i.price,
                 'Sold' if i.sold else ('Live' if i.verified else 'Hidden'),
                 i.seller.username if i.seller else '', i.barcode, i.description]
                for i in Item.query.order_by(Item.id).all()]
    elif dataset == 'orders':
        header = ['ID', 'Date', 'Item', 'Buyer', 'Seller', 'Amount (Ksh)', 'Status', 'Paid', 'Town',
                  'Apartment/Building', 'Phone', 'Directions', 'Latitude', 'Longitude']
        rows = [[o.id, fmt_date(o.order_date), o.item.name, o.user.username, o.seller.username, o.total_price,
                 o.shipping_status, 'Yes (on delivery)' if o.shipping_status == 'Delivered' else 'No',
                 o.shipping_town or '', o.shipping_apartment or '', o.shipping_phone or '', o.delivery_notes or '',
                 o.delivery_lat if o.delivery_lat is not None else '', o.delivery_lng if o.delivery_lng is not None else '']
                for o in Order.query.order_by(Order.order_date.desc()).all()]
    else:
        abort(404)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)

    filename = f"bidhaa_{dataset}_{datetime.now().strftime('%Y-%m-%d')}.csv"
    # The BOM makes Excel open the file as UTF-8
    return Response('﻿' + buffer.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename={filename}'})


@app.route('/admin_delete_item/<int:item_id>', methods=['POST'])
@login_required
@admin_required
def admin_delete_item(item_id):
    item = Item.query.get(item_id)

    if not item:
        flash("Item not found!", "danger")
        return redirect(url_for('manage_items'))

    orders_with_item = db.session.query(Order.query.filter_by(item_id=item_id).exists()).scalar()
    if orders_with_item:
        flash("Cannot delete item as it has been ordered!", "warning")
        return redirect(url_for('manage_items'))

    Sale.query.filter_by(item_id=item_id).delete()
    db.session.delete(item)
    db.session.commit()
    flash("Item deleted successfully!", "success")

    return redirect(request.referrer or url_for('manage_items'))


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
@login_required
def mark_order_as_shipping(order_id):
    order = Order.query.get(order_id)
    if order and order.seller_id == current_user.id:
        order.shipping_status = 'Shipping in Process'
        db.session.commit()
    return redirect(url_for('seller_orders'))


@app.route('/mark_order_as_shipped/<int:order_id>', methods=['POST'])
@login_required
def mark_order_as_shipped(order_id):
    order = Order.query.get(order_id)
    if order and order.seller_id == current_user.id:
        order.shipping_status = 'Shipped'
        db.session.commit()
    return redirect(url_for('seller_orders'))


@app.route('/mark_order_as_delivered/<int:order_id>', methods=['POST'])
@login_required
def mark_order_as_delivered(order_id):
    """Seller confirms the item was delivered and the buyer paid on delivery."""
    order = Order.query.get(order_id)
    if order and order.seller_id == current_user.id and order.shipping_status == 'Shipped':
        order.shipping_status = 'Delivered'
        db.session.commit()
        flash(f"Order for {order.item.name} marked as delivered and paid.", "success")
    return redirect(url_for('seller_orders'))


@app.route('/delete_order/<int:order_id>', methods=['POST'])
@login_required
def delete_order(order_id):
    order = Order.query.get(order_id)

    if order and order.user_id == current_user.id:
        if order.shipping_status == "Delivered":
            OwnedItem.query.filter_by(order_id=order.id).delete()
            db.session.delete(order)
            db.session.commit()
            flash("Order deleted successfully!", "success")
        else:
            flash("You can only delete delivered orders.", "warning")
    else:
        flash("Order not found or unauthorized action.", "danger")

    return redirect(url_for('customer_orders'))



@app.route('/verify_item/<int:item_id>', methods=['POST'])
@login_required
@admin_required
def verify_item(item_id):
    item = Item.query.get_or_404(item_id)

    # "Verify" now means "show on the market again" after an admin hid the item
    if item.verified:
        flash("Item is already on the market.", "info")
    else:
        item.verified = True
        db.session.add(Notification(seller_id=item.seller_id,
                                    message=f"Good news! Your item '{item.name}' is back on the market."))
        db.session.commit()
        flash(f"'{item.name}' is back on the market.", "success")

    return redirect(request.referrer or url_for('admin_dashboard')) 


@app.route('/generate_report', methods=['GET'])
@login_required
@admin_required
def generate_report():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    # Fetch users and items
    users = User.query.all()
    items = Item.query.all()
    
    # Buyers pay on delivery, so the report is built from orders rather than transactions
    query = Order.query
    if start_date and end_date:
        query = query.filter(Order.order_date >= start_date, Order.order_date <= end_date)
    
    orders = query.order_by(Order.order_date.desc()).all()
    
    total_sales = sum(o.total_price for o in orders if o.shipping_status == 'Delivered')
    num_orders = len(orders)

    top_items = (
        db.session.query(Item.name, db.func.count(Order.id))
        .join(Order, Order.item_id == Item.id)
        .group_by(Item.name)
        .order_by(db.func.count(Order.id).desc())
        .limit(5)
        .all()
    )

    top_buyers = (
        db.session.query(User.username, db.func.count(Order.id))
        .join(Order, Order.user_id == User.id)
        .group_by(User.username)
        .order_by(db.func.count(Order.id).desc())
        .limit(5)
        .all()
    )

    rendered_html = render_template(
        'report.html', 
        users=users, 
        items=items, 
        orders=orders, 
        total_sales=total_sales, 
        num_orders=num_orders, 
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


