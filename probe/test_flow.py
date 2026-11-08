"""Simple test script to simulate a full end-to-end API interaction
to verify the job lifecycle and data format.
"""
import requests
import time

BASE = "http://localhost:8000"

def test_flow():
    print("1. Resolve M51...")
    r = requests.post(f"{BASE}/api/resolve", json={"name": "M51"})
    if r.status_code != 200:
        print(f"Resolve failed: {r.status_code} {r.text}")
        return
    obj = r.json()
    ra, dec = obj["ra"], obj["dec"]
    print(f"-> {ra}, {dec}")

    print("2. Create Job...")
    r = requests.post(f"{BASE}/api/jobs", json={"ra": ra, "dec": dec, "stretch": "asinh"})
    job_id = r.json()["job_id"]
    print(f"-> {job_id}")

    print("3. Poll Job...")
    for _ in range(10):
        r = requests.get(f"{BASE}/api/jobs/{job_id}")
        job = r.json()
        print(f"-> {job['status']} ({job['progress']}/{job['total']})")
        if job["status"] == "completed":
            print(f"Done! {len(job['frames'])} frames.")
            return
        if job["status"] == "failed":
            print(f"Failed: {job['error']}")
            return
        time.sleep(2)

test_flow()
