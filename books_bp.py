import os  # Hantera filer
import json # Jobba med JSON
import re # Regex för att rensa text
from datetime import datetime # Hämta dagens datum
from urllib.parse import urljoin # Bygga kompletta URL:er

import requests # Skicka HTTP förfrågnignar
from bs4 import BeautifulSoup # Scraping / läsa HTML
from flask import Blueprint, jsonify, request # Flask API
import uuid  # Skapa unika ID:n

# Skapar blueprint för books API
books_bp = Blueprint("books_bp", __name__)

# Fil för att spara kategorier
URL_DICT_FILE = "url_dict.json"
# Bas-URL till sidan vi scrapar
BASE_URL = "https://books.toscrape.com/"
# Startkategori
START_URL = "https://books.toscrape.com/catalogue/category/books_1/index.html"

def today_stamp(): # Returnerar dagens datum i format YYMMDD
    return datetime.now().strftime("%y%m%d")

def fetch_category_hrefs(url): # Hämtar alla kategori länkar från sidan
    response = requests.get(url, timeout=10)
    soup = BeautifulSoup(response.text, "html.parser")

    ul_element = soup.find("ul", class_="nav nav-list")
    a_tags = ul_element.find_all("a")
    href_values = [a.get("href") for a in a_tags if a.get("href")]

    return href_values

def fetch_gbp_to_sek_rate(): # Hämtar aktuell växelkurs GBP --> SEK
    try:
        url = "https://www.x-rates.com/calculator/?from=GBP&to=SEK&amount=1"
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        el = soup.select_one(".ccOutputRslt")
        if not el:
            return None

        text = el.get_text(strip=True)
        number = "".join(re.findall(r"[\d.]+", text))
        return float(number) if number else None
    except Exception:
        return None

def create_url_dict(href_values): # Skapar dictionary med kategori + URL
    url_dict = {}

    for index, href in enumerate(href_values):
        if index == 0:
            continue  # hoppa över "Books"

        # bygg absolut URL korrekt 
        full_url = urljoin(START_URL, href)

        # plocka kategori från URL 
        parts = full_url.strip("/").split("/")
        cat_part = parts[-2]           
        category = cat_part.split("_")[0].lower().strip()

        url_dict[category] = full_url

    return url_dict

def ensure_url_dict(): 
    """
    # Cache: om url_dict.json finns -> läs
    # annars -> scrapa och spara
    """
    if os.path.exists(URL_DICT_FILE):
        with open(URL_DICT_FILE, "r", encoding="utf-8") as f:
            return json.load(f), "local_json_file"

    href_values = fetch_category_hrefs(START_URL)
    url_dict = create_url_dict(href_values)

    with open(URL_DICT_FILE, "w", encoding="utf-8") as f:
        json.dump(url_dict, f, ensure_ascii=False, indent=4)

    return url_dict, "live_web_scrape"

def clean_price(price_text): # Rensar pris-text och gör om till float
    price = "".join(re.findall(r"[\d.]+", price_text))
    return float(price) if price else 0.0

def scrape_books_first_page(category_url):
    """
    # Scrapar första sidan i vald kategori
    # Hämtar titel, pris och rating
    """
    response = requests.get(category_url, timeout=10)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    articles = soup.find_all("article", class_="product_pod")
    books = []

    for article in articles:
        title = article.h3.a["title"]
        price_text = article.find("p", class_="price_color").get_text(strip=True)
        price_gbp = clean_price(price_text)

        rating_tag = article.find("p", class_="star-rating")
        rating_classes = rating_tag.get("class", []) if rating_tag else []
        rating_map = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}
        rating = 0
        for k, v in rating_map.items():
            if k in rating_classes:
                rating = v
                break

        books.append({
            "title": title,
            "price_gbp": price_gbp,
            "rating": rating
        })

    return books

def books_cache_file(category): # Skapar filnamn baserat på kategori + dagens datum
    return f"{category}_{today_stamp()}.json"

def get_books_by_category(category):
    """
     # Hämtar böcker från cache om finns
     # Annars scrapar live och sparar
    """
    category = category.lower().strip()
    filename = books_cache_file(category)

    # Cache: om dagens fil finns så läser den och uppgraderar sen returnerar den
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)

        # upgrade: se till att id plus SEK finns även i gamla filer
        rate = data.get("gbp_to_sek_rate")
        if rate is None:
            rate = fetch_gbp_to_sek_rate() or 0.0
            data["gbp_to_sek_rate"] = rate

        changed = False
        for b in data.get("items", []):
            if "id" not in b:
                b["id"] = str(uuid.uuid4())
                changed = True
            if "price_sek" not in b:
                b["price_sek"] = round(float(b.get("price_gbp", 0.0)) * rate, 2) if rate else 0.0
                changed = True
            if "rating" not in b:
                b["rating"] = 0
                changed = True

        if changed:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)

        return data, "local_json_file"

    # Om ingen fil finns den får scrapa live, spara sen return
    url_dict, _ = ensure_url_dict()
    category_url = url_dict.get(category)

    if not category_url:
        return {"error": "Category not found"}, "error"

    books = scrape_books_first_page(category_url)

    rate = fetch_gbp_to_sek_rate()
    if rate is None:
        rate = 0.0

    for b in books:
        b["price_sek"] = round(b["price_gbp"] * rate, 2) if rate else 0.0
        b["id"] = str(uuid.uuid4())

    data = {
        "category": category,
        "date": today_stamp(),
        "gbp_to_sek_rate": rate,
        "count": len(books),
        "items": books
    }

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    return data, "live_web_scrape"

# ---------------- ROUTES ----------------

@books_bp.route("/") # Start route som visar info om API
def home():
    return jsonify({
        "message": "BooksToScrape API (Blueprint) running",
        "endpoints": [
            "/api/v1/categories",
            "/api/v1/categories/<category>",
            "/api/v1/books/<category>"
        ]
    })


@books_bp.route("/categories") # Hämtar alla kategorier
def categories():
    try:
        url_dict, source = ensure_url_dict()
        return jsonify({"source": source, "count": len(url_dict), "categories": url_dict})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@books_bp.route("/categories/<category>") # Hämtar URL för en specifik kategori
def category_url(category):
    url_dict, _ = ensure_url_dict()
    key = category.lower().strip()

    if key not in url_dict:
        return jsonify({"error": "Category not found"}), 404

    return jsonify({
        "category": key,
        "url": url_dict[key]
    })


@books_bp.route("/books/<category>") # Hämtar alla böcker i en kategori
# (från cache eller live scrape)
def books(category):
    try:
        data, source = get_books_by_category(category)
        if source == "error":
            return jsonify(data), 404
        data["source"] = source
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@books_bp.route("/books/<category>", methods=["POST"]) # Skapar en ny bok i cache-filen
def create_book(category):
    category = category.lower().strip()
    filename = books_cache_file(category)

    if not os.path.exists(filename):
        return jsonify({"error": "No cache file for today. Call GET /api/v1/books/<category> first."}), 404

    payload = request.get_json(force=True)
    title = payload.get("title")
    price_gbp = payload.get("price_gbp")
    rating = int(payload.get("rating", 0))

    if not title or price_gbp is None:
        return jsonify({"error": "title and price_gbp are required"}), 400

    with open(filename, "r", encoding="utf-8") as f:
        data = json.load(f)

    rate = float(data.get("gbp_to_sek_rate", 0.0))
    new_book = {
        "id": str(uuid.uuid4()),
        "title": str(title),
        "price_gbp": float(price_gbp),
        "rating": rating,
        "price_sek": round(float(price_gbp) * rate, 2) if rate else 0.0
    }

    data["items"].append(new_book)
    data["count"] = len(data["items"])

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    return jsonify(new_book), 201

@books_bp.route("/books/<category>/<book_id>", methods=["GET"]) # Hämtar en bok via ID
def get_book_by_id(category, book_id):
    category = category.lower().strip()
    filename = books_cache_file(category)

    if not os.path.exists(filename):
        return jsonify({"error": "No cache file for today. Call GET /api/v1/books/<category> first."}), 404

    with open(filename, "r", encoding="utf-8") as f:
        data = json.load(f)

    for b in data.get("items", []):
        if b.get("id") == book_id:
            return jsonify(b)

    return jsonify({"error": "Book not found"}), 404

@books_bp.route("/books/<category>/<book_id>", methods=["PUT"]) # Uppdaterar en bok via ID
def update_book(category, book_id):
    category = category.lower().strip()
    filename = books_cache_file(category)

    if not os.path.exists(filename):
        return jsonify({"error": "No cache file for today. Call GET /api/v1/books/<category> first."}), 404

    payload = request.get_json(force=True)

    with open(filename, "r", encoding="utf-8") as f:
        data = json.load(f)

    rate = float(data.get("gbp_to_sek_rate", 0.0))

    for b in data.get("items", []):
        if b.get("id") == book_id:
            if "title" in payload:
                b["title"] = str(payload["title"])
            if "price_gbp" in payload:
                b["price_gbp"] = float(payload["price_gbp"])
                b["price_sek"] = round(b["price_gbp"] * rate, 2) if rate else b.get("price_sek", 0.0)
            if "rating" in payload:
                b["rating"] = int(payload["rating"])

            with open(filename, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)

            return jsonify(b)

    return jsonify({"error": "Book not found"}), 404

@books_bp.route("/books/<category>/<book_id>", methods=["DELETE"]) # Tar bort en bok via ID
def delete_book(category, book_id):
    category = category.lower().strip()
    filename = books_cache_file(category)

    if not os.path.exists(filename):
        return jsonify({"error": "No cache file for today. Call GET /api/v1/books/<category> first."}), 404

    with open(filename, "r", encoding="utf-8") as f:
        data = json.load(f)

    before = len(data.get("items", []))
    data["items"] = [b for b in data.get("items", []) if b.get("id") != book_id]

    if len(data["items"]) == before:
        return jsonify({"error": "Book not found"}), 404

    data["count"] = len(data["items"])

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    return jsonify({"deleted": book_id})