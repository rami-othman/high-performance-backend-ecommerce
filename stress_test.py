import threading
import requests
import time

BASE_URL = "http://localhost:8000"

ENDPOINTS = [
    "/api/products/",
    "/api/orders/",
]

results = {
    "success": 0,
    "fail": 0
}

def hit_api():
    try:
        url = BASE_URL + ENDPOINTS[0]
        r = requests.get(url, timeout=5)

        if r.status_code == 200:
            results["success"] += 1
        else:
            results["fail"] += 1

    except:
        results["fail"] += 1


threads = []

start = time.time()

# 🔥 100 users simulation
for i in range(500):
    t = threading.Thread(target=hit_api)
    threads.append(t)
    t.start()

for t in threads:
    t.join()

end = time.time()

print("\n===== STRESS TEST RESULT =====")
print(f"Total Users: 500")
print(f"Success: {results['success']}")
print(f"Failed: {results['fail']}")
print(f"Time Taken: {end - start:.2f} seconds")