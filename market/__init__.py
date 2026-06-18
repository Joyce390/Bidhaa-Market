import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_mail import Mail 
from market.config import Config

db = SQLAlchemy()
bcrypt = Bcrypt()
login_manager = LoginManager()
migrate = Migrate()
mail = Mail()  

def create_app():
    """Factory function to create and configure the Flask app."""
    app = Flask(__name__)
    app.config.from_object(Config)  

    
    db.init_app(app)
    bcrypt.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    mail.init_app(app)  

    
    login_manager.login_view = "login"
    login_manager.login_message_category = "info"

    from market.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))  

    with app.app_context():
        from market import routes  

    return app

app = create_app()
