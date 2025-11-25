#!/usr/bin/env python3
import requests
import time
import json
import sys

# Get backend URL from frontend/.env
BACKEND_URL = "https://salespath-5.preview.emergentagent.com/api"

def test_marker_filtering():
    """Test marker filtering optimization"""
    print("\n🔍 Testing marker filtering optimization...")
    
    # Get all jobs
    print("\nRetrieving all jobs...")
    response = requests.get(f"{BACKEND_URL}/jobs")
    
    if response.status_code == 200:
        jobs = response.json()
        if isinstance(jobs, dict) and "jobs" in jobs:
            jobs = jobs.get("jobs", [])
        elif not isinstance(jobs, list):
            print(f"❌ Unexpected response format: {type(jobs)}")
            return
        
        print(f"Retrieved {len(jobs)} jobs")
        
        # Find a completed job with a large number of addresses
        large_jobs = []
        for job in jobs:
            if job.get("status") == "completed" and job.get("total_addresses", 0) > 100:
                large_jobs.append(job)
        
        if large_jobs:
            print(f"Found {len(large_jobs)} large jobs")
            
            # Try each large job until we find one that works
            for large_job in large_jobs[:5]:  # Try up to 5 jobs
                job_id = large_job.get("id")
                total_addresses = large_job.get("total_addresses", 0)
                print(f"\nTrying job with ID: {job_id} and {total_addresses} addresses")
                
                # Test route endpoint
                print("Testing route data retrieval...")
                start_time = time.time()
                response = requests.get(f"{BACKEND_URL}/route/{job_id}")
                end_time = time.time()
                
                if response.status_code == 200:
                    route_data = response.json()
                    addresses = route_data.get("optimized_addresses", [])
                    print(f"Retrieved route with {len(addresses)} addresses in {end_time - start_time:.2f} seconds")
                    
                    # Check if all addresses have coordinates
                    addresses_with_coords = sum(1 for addr in addresses if addr.get("latitude") and addr.get("longitude"))
                    print(f"Addresses with coordinates: {addresses_with_coords}/{len(addresses)}")
                    
                    # Check if marker filtering is applied for large datasets
                    if len(addresses) >= 500:
                        print("\nLarge dataset detected (500+ addresses)")
                        print("Checking if marker filtering is applied...")
                        
                        # In the frontend, marker filtering would show only every nth marker
                        # We can simulate this by checking if the data structure supports this
                        if "optimized_order" in route_data:
                            print("✅ Optimized order is available for marker filtering")
                        else:
                            print("❌ Optimized order is not available for marker filtering")
                        
                        # Check if the data structure includes all necessary information for filtering
                        if all(addr.get("geocoded", False) for addr in addresses):
                            print("✅ All addresses have geocoding status for filtering")
                        else:
                            geocoded_count = sum(1 for addr in addresses if addr.get("geocoded", False))
                            print(f"❌ Only {geocoded_count}/{len(addresses)} addresses have geocoding status")
                    else:
                        print(f"\nDataset size ({len(addresses)}) is below the 500 threshold for marker filtering")
                    
                    # We found a working job, no need to try more
                    break
                else:
                    print(f"❌ Failed to retrieve route data. Status code: {response.status_code}")
        else:
            print("❌ No large completed jobs found")
    else:
        print(f"❌ Failed to retrieve jobs. Status code: {response.status_code}")

if __name__ == "__main__":
    test_marker_filtering()