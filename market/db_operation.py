from market import app, db, Item

# Add a new item to the database
def add_item(name, price, description, barcode):
    try:
        with app.app_context():
            # Check for existing barcode
            if Item.query.filter_by(barcode=barcode).first():
                print(f"Item with barcode {barcode} already exists!")
                return

            # Create and add the new item
            item = Item(name=name, price=price, description=description, barcode=barcode)
            db.session.add(item)
            db.session.commit()
            print(f"Added item: {item.name}")
    except Exception as e:
        print(f"Error adding item: {e}")

# Fetch all items from the database
def get_all_items():
    try:
        with app.app_context():
            return Item.query.all()
    except Exception as e:
        print(f"Error fetching items: {e}")
        return []

if __name__ == "__main__":
    # Example usage
    print("Fetching existing items...")
    items = get_all_items()
    for item in items:
        print(f"{item.name} - {item.barcode} - {item.price}")

    print("\nAdding a new item...")
    add_item(name="Laptop", price=600, description="A new laptop", barcode="123456789012")
    add_item(name="Keyboard", price=100, description="Mechanical keyboard", barcode="987654321098")
    add_item(name="Chain", price= 100, description="Lighting ability",barcode="980094345677")

