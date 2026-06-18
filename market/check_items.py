from market import db
from market.models import Item

items = Item.query.all()

if items:
    for item in items:
        print(f"Item: {item.name}, Price: {item.price}, Category: {item.category}")
else:
    print("No items found in the database.")
