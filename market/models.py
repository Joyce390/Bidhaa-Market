from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from itsdangerous import URLSafeTimedSerializer
from flask import current_app
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from market import db

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(30), unique=True, nullable=False)
    email = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(60), nullable=False)
    phone = db.Column(db.String(20), unique=True, nullable=True)
    role = db.Column(db.String(10), default="both")  
    is_admin = db.Column(db.Boolean, default=False)
    wallet_balance = db.Column(db.Float, nullable=False, default=0.0) 
    created_at = db.Column(db.DateTime, default=datetime.utcnow)  


    wallet = db.relationship('Wallet', back_populates='user', uselist=False)
    seller_items = db.relationship('Item', back_populates='seller', lazy=True)
    owned_items = db.relationship('OwnedItem', back_populates='owner', lazy=True)
    orders = db.relationship('Order', foreign_keys='Order.user_id', back_populates='user', lazy=True)
    sales = db.relationship('Sale', back_populates='seller', lazy=True)
    sold_orders = db.relationship('Order', foreign_keys='Order.seller_id', back_populates='seller', lazy=True)

    def can_purchase(self, item_price):
        return self.wallet_balance is not None and self.wallet_balance >= item_price

    def get_reset_token(self, expires_sec=1800):
        s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
        return s.dumps(self.email, salt='password-reset')

    @staticmethod
    def verify_reset_token(token):
        s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
        try:
            email = s.loads(token, salt='password-reset', max_age=1800)
        except:
            return None
        return User.query.filter_by(email=email).first()

    @property
    def password(self):
        raise AttributeError("Password is not readable!")

    @password.setter
    def password(self, plain_text_password):
        self.password_hash = generate_password_hash(plain_text_password)

    def check_password(self, attempted_password):
        return check_password_hash(self.password_hash, attempted_password)

    @property
    def is_seller(self):
        return self.role in ["seller", "both"]

    def is_buyer(self):
        return self.role in ['buyer', 'both']


class Wallet(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, unique=True)
    balance = db.Column(db.Float, default=0.0)
    user = db.relationship('User', back_populates='wallet')

    def deposit(self, amount):
        if amount > 0:
            self.balance += amount
            db.session.commit()
            return True
        return False

    def withdraw(self, amount):
        if amount > 0 and self.balance >= amount:
            self.balance -= amount
            db.session.commit()
            return True
        return False


class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    buyer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    seller_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey('item.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='Pending') 

    buyer = db.relationship('User', foreign_keys=[buyer_id])
    seller = db.relationship('User', foreign_keys=[seller_id])
    item = db.relationship('Item')

    def __repr__(self):
        return f"<Transaction {self.id}: Buyer {self.buyer_id} -> Seller {self.seller_id}, Amount: {self.amount}>"

class Item(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    barcode = db.Column(db.String(12), nullable=False, unique=True)
    image = db.Column(db.String(255), nullable=True)
    verified = db.Column(db.Boolean, default=False)
    sold = db.Column(db.Boolean, default=False)  

    seller_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    seller = db.relationship('User', back_populates='seller_items')

    orders = db.relationship('Order', back_populates='item', lazy=True)
    sales = db.relationship('Sale', back_populates='item', lazy=True)


class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    seller_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey('item.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    sale_date = db.Column(db.DateTime, default=datetime.utcnow)

    seller = db.relationship('User', foreign_keys=[seller_id], back_populates='sales')
    item = db.relationship('Item', back_populates='sales')

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)  
    seller_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)  
    item_id = db.Column(db.Integer, db.ForeignKey('item.id'), nullable=False)
    order_date = db.Column(db.DateTime, default=datetime.utcnow)
    total_price = db.Column(db.Float, nullable=False)
    shipping_status = db.Column(db.String(20), default="Pending")

    shipping_town = db.Column(db.String(100))
    shipping_apartment = db.Column(db.String(100))
    shipping_phone = db.Column(db.String(15))
    delivery_notes = db.Column(db.String(255))
    delivery_lat = db.Column(db.Float)
    delivery_lng = db.Column(db.Float)

    user = db.relationship('User', foreign_keys=[user_id], back_populates='orders') 
    seller = db.relationship('User', foreign_keys=[seller_id], back_populates='sold_orders') 
    item = db.relationship('Item', back_populates='orders')  

    owned_items = db.relationship('OwnedItem', back_populates='order', uselist=False)

    def __repr__(self):
        return f"<Order {self.id} - {self.item.name} - {self.user.username}>"

class OwnedItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey('item.id'), nullable=False)
    purchase_date = db.Column(db.DateTime, default=datetime.utcnow)

    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)

    owner = db.relationship('User', back_populates='owned_items')
    item = db.relationship('Item')
    order = db.relationship('Order', back_populates='owned_items')  

    def __repr__(self):
        return f"<OwnedItem {self.id} - {self.item.name} - {self.owner.username}>"


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    seller_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.String(255), nullable=False)
    date_created = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='unread')  

    def __repr__(self):
        return f'<Notification {self.message}>'
