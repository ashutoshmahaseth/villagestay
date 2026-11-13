# VillageStay

A Flask web app that connects people who want to live in or experience village life with owners of empty or abandoned homes, including families who live abroad or in another state and cannot manage their house.

## Features
- Owner and guest accounts (hashed passwords)
- Owners list homes: rent, stay type (short experience or long-term), optional local caretaker
- Guests search by village or state and send booking requests
- Owners approve or reject requests
- Rent breakdown on every listing: 10% platform fee, optional 5% caretaker, rest to owner

## More features (v2)
- Photo upload, edit and delete listings
- Reviews and star ratings (only guests with an approved stay)
- Save homes to a wishlist, cancel bookings
- Owner dashboard with total earnings
- Admin panel (stats, verify listings). Default login: admin@villagestay.com / admin123 (change before real use)
- Search by village, state, stay type and maximum rent. Verified homes show first

## Run
```
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:5000

## Push to GitHub
```
git init
git add .
git commit -m "Initial commit: VillageStay"
git branch -M main
git remote add origin https://github.com/<your-username>/villagestay.git
git push -u origin main
```

## Future work
Photo upload, payments, reviews, Hindi/regional language support, caretaker accounts.
