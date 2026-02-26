from flask import Flask
from books_bp import books_bp

app = Flask(__name__)

# Viktigt: url_prefix gör att alla routes blir /api/v1/...
app.register_blueprint(books_bp, url_prefix="/api/v1")

if __name__ == "__main__":
    app.run(debug=True)