from market import app, db

# Set up the app context and create the database tables
with app.app_context():
    db.create_all()
    print("Database tables created successfully!")
