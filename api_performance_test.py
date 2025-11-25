#!/usr/bin/env python3
import requests
import time
import json
import sys

# Get backend URL from frontend/.env
BACKEND_URL = "https://salespath-5.preview.emergentagent.com/api"

def test_api_performance():
    """Test API performance directly"""
    print("\n🔍 Testing API performance...")
    
    # Test jobs endpoint
    print("\nTesting /api/jobs endpoint...")
    start_time = time.time()
    response = requests.get(f"{BACKEND_URL}/jobs")
    end_time = time.time()
    
    if response.status_code == 200:
        jobs = response.json()
        if isinstance(jobs, dict) and "jobs" in jobs:
            jobs = jobs.get("jobs", [])
        print(f"✅ Retrieved {len(jobs)} jobs in {end_time - start_time:.2f} seconds")
        
        if jobs:
            # Get the most recent job
            job_id = jobs[0].get("id")
            print(f"Using job ID: {job_id}")
            
            # Test job status endpoint
            print("\nTesting /api/job/{job_id} endpoint...")
            start_time = time.time()
            response = requests.get(f"{BACKEND_URL}/job/{job_id}")
            end_time = time.time()
            
            if response.status_code == 200:
                job_data = response.json()
                print(f"✅ Retrieved job status in {end_time - start_time:.2f} seconds")
                print(f"Job status: {job_data.get('status')}")
                print(f"Processed addresses: {job_data.get('processed_addresses')}")
                print(f"Total addresses: {job_data.get('total_addresses')}")
            else:
                print(f"❌ Failed to retrieve job status. Status code: {response.status_code}")
            
            # Test route endpoint
            print("\nTesting /api/route/{job_id} endpoint...")
            start_time = time.time()
            response = requests.get(f"{BACKEND_URL}/route/{job_id}")
            end_time = time.time()
            
            if response.status_code == 200:
                route_data = response.json()
                addresses = route_data.get("optimized_addresses", [])
                print(f"✅ Retrieved route with {len(addresses)} addresses in {end_time - start_time:.2f} seconds")
                
                # Check if marker filtering is applied for large datasets
                if len(addresses) >= 500:
                    # Count markers with coordinates (which would be displayed on the map)
                    markers_with_coords = sum(1 for addr in addresses if addr.get("latitude") and addr.get("longitude"))
                    
                    # If marker filtering is working, we should see fewer markers than total addresses
                    if markers_with_coords < len(addresses):
                        print(f"✅ Marker filtering applied: {markers_with_coords} markers out of {len(addresses)} addresses")
                    else:
                        print(f"❌ Marker filtering not applied: All {len(addresses)} addresses have markers")
            else:
                print(f"❌ Failed to retrieve route data. Status code: {response.status_code}")
    else:
        print(f"❌ Failed to retrieve jobs. Status code: {response.status_code}")

if __name__ == "__main__":
    test_api_performance()