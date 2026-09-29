"""Start the Bidhaa Market website.

    pip install -r requirements.txt
    python run.py

Then open http://127.0.0.1:5000 in your browser.
"""
from market import app

if __name__ == '__main__':
    app.run(debug=True)
