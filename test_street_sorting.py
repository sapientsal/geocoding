#!/usr/bin/env python3
import requests
import time
import csv
import os
import io
import json
from datetime import datetime

# Get backend URL from frontend/.env
BACKEND_URL = "https://salespath-5.preview.emergentagent.com/api"

def test_street_based_sorting():
    """Test street-based sorting with specific test cases"""
    print("\n🔍 Testing Street-Based Sorting with Specific Test Cases...")
    
    try:
        # Read the specific street sorting test addresses file
        with open('/app/street_sorting_test_specific.csv', 'r') as f:
            csv_content = f.read()
        
        print(f"Loaded specific street sorting test addresses file:")
        print(csv_content)
        
        # Create file-like object for upload
        files = {
            'file': ('street_sorting_test_specific.csv', csv_content, 'text/csv')
        }
        
        # Upload file to upload endpoint
        response = requests.post(f"{BACKEND_URL}/upload", files=files)
        
        if response.status_code == 200:
            job_id = response.json().get("job_id")
            print(f"✅ File uploaded successfully. Job ID: {job_id}")
            
            # Wait for job to complete
            max_attempts = 30
            polling_interval = 5
            
            for attempt in range(max_attempts):
                print(f"Polling job status (attempt {attempt+1}/{max_attempts})...")
                response = requests.get(f"{BACKEND_URL}/job/{job_id}")
                
                if response.status_code != 200:
                    print(f"❌ Failed to get job status. Status code: {response.status_code}")
                    return None
                
                job_data = response.json()
                status = job_data.get("status")
                
                print(f"Current job status: {status}")
                print(f"Processed: {job_data.get('processed_addresses')}/{job_data.get('total_addresses')}")
                
                # Check if job is completed or failed
                if status == "completed":
                    print(f"✅ Job completed successfully. Processed {job_data.get('processed_addresses')} addresses.")
                    break
                elif status == "error":
                    print(f"❌ Job failed with error: {job_data.get('error_message')}")
                    return None
                
                # Wait before next polling attempt
                time.sleep(polling_interval)
            
            # Test retrieving the street-sorted data
            print("Testing /api/street-sorted/{job_id} endpoint...")
            response = requests.get(f"{BACKEND_URL}/street-sorted/{job_id}")
            
            if response.status_code != 200:
                print(f"❌ Failed to get route data. Status code: {response.status_code}")
                print(f"Response: {response.text}")
                return None
            
            route_data = response.json()
            addresses = route_data.get("addresses", [])
            optimized_addresses = route_data.get("optimized_addresses", [])
            
            if not addresses:
                print("❌ No addresses found in route data")
                return None
            
            print(f"✅ Successfully retrieved {len(addresses)} addresses and {len(optimized_addresses)} optimized addresses")
            
            # Print all addresses to see the actual format
            print("\nAll addresses in original order:")
            for i, addr in enumerate(addresses):
                original_address = addr.get("original_address", "")
                print(f"{i+1}. {original_address}")
            
            print("\nAll addresses in optimized order:")
            for i, addr in enumerate(optimized_addresses):
                original_address = addr.get("original_address", "")
                print(f"{i+1}. {original_address}")
            
            # Group addresses by street
            street_groups = {}
            
            for addr in optimized_addresses:
                # Extract street name from address
                original_address = addr.get("original_address", "")
                parts = original_address.split(',')[0].strip().split()
                
                # Determine street name (everything except the last part which is the house number)
                if len(parts) > 1:
                    street_name = ' '.join(parts[:-1])
                    house_num = parts[-1]
                else:
                    street_name = original_address
                    house_num = ""
                
                if street_name not in street_groups:
                    street_groups[street_name] = []
                
                street_groups[street_name].append({
                    "address": original_address,
                    "house_num": house_num
                })
            
            # Print the street grouping results
            print("\nStreet grouping results:")
            for street, addresses in street_groups.items():
                print(f"\n{street} - {len(addresses)} addresses:")
                for addr in addresses:
                    print(f"  - {addr['address']}")
            
            # Check if streets are grouped together
            consecutive_indices = True
            for street, addresses in street_groups.items():
                if len(addresses) <= 1:
                    continue
                
                # Get the indices in the original sorted list
                indices = [i for i, addr in enumerate(optimized_addresses) 
                          if addr.get("original_address", "").startswith(street)]
                
                # Check if indices are consecutive
                if max(indices) - min(indices) + 1 != len(indices):
                    consecutive_indices = False
                    print(f"❌ Street '{street}' addresses are not consecutive in the sorted list. Indices: {indices}")
            
            if consecutive_indices:
                print("✅ All streets are properly grouped together")
            
            return job_id
        else:
            print(f"❌ File upload failed with status code: {response.status_code}")
            print(f"Response: {response.text}")
            return None
    except Exception as e:
        print(f"❌ Street-based sorting testing failed with error: {str(e)}")
        return None

if __name__ == "__main__":
    test_street_based_sorting()