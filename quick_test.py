# quick_test.py -- run manually, not part of the app
from services.website_processing import extract_from_website

records = extract_from_website("https://iitj.ac.in")
print(f"Extracted {len(records)} records")
for r in records[:3]:
    print("---")
    print("URL:", r["source_url"])
    print("Title:", r["source"])
    print("Text preview:", r["text"][:200])
