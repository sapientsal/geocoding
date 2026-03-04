#!/usr/bin/env python3
import requests
import time
import csv
import os
import io
import json
import pandas as pd
from datetime import datetime
import random
import sys

# Get backend URL from frontend/.env
BACKEND_URL = "https://nominatim-overload.preview.emergentagent.com/api"

def create_test_dataset(num_addresses=100):
    """Create a test dataset with the specified number of addresses"""
    print(f"\n🔍 Creating test dataset with {num_addresses} addresses...")
    
    # Base addresses to use (real addresses)
    base_addresses = [
        "1600 Pennsylvania Avenue NW, Washington, DC 20500",  # White House
        "350 Fifth Avenue, New York, NY 10118",               # Empire State Building
        "1 Infinite Loop, Cupertino, CA 95014",               # Apple HQ
        "1600 Amphitheatre Parkway, Mountain View, CA 94043", # Google HQ
        "2800 E Observatory Rd, Los Angeles, CA 90027"        # Griffith Observatory
    ]
    
    # Generate addresses by adding variations to base addresses
    addresses = []
    addresses.append(["Address"])  # Header row
    
    for i in range(num_addresses):
        base_address = base_addresses[i % len(base_addresses)]
        
        # Add some variation to make each address unique
        if i > len(base_addresses):
            parts = base_address.split(',')
            street_parts = parts[0].split(' ')
            
            # Modify the street number slightly
            if len(street_parts) > 1 and street_parts[0].isdigit():
                street_num = int(street_parts[0])
                # Add a small random offset to the street number
                offset = random.randint(-100, 100)
                new_num = max(1, street_num + offset)
                street_parts[0] = str(new_num)
                parts[0] = ' '.join(street_parts)
                
            modified_address = ','.join(parts)
            addresses.append([modified_address])
        else:
            # Use the original address for the first few
            addresses.append([base_address])
    
    # Create CSV in memory
    csv_file = io.StringIO()
    writer = csv.writer(csv_file)
    for address in addresses:
        writer.writerow(address)
    
    csv_content = csv_file.getvalue()
    print(f"Created CSV with {len(addresses)-1} addresses")
    return csv_content

def test_backend_performance(num_addresses=100):
    """Test backend performance with the specified number of addresses"""
    print(f"\n🔍 Testing backend performance with {num_addresses} addresses...")
    
    # Create test dataset
    csv_content = create_test_dataset(num_addresses)
    
    # Measure upload time
    print("\nTesting file upload performance...")
    upload_start_time = time.time()
    
    files = {
        'file': (f'test_dataset_{num_addresses}.csv', csv_content, 'text/csv')
    }
    
    try:
        # Upload file
        response = requests.post(f"{BACKEND_URL}/upload", files=files)
        
        upload_end_time = time.time()
        upload_duration = upload_end_time - upload_start_time
        
        print(f"Upload time: {upload_duration:.2f} seconds")
        
        if response.status_code == 200:
            job_id = response.json().get("job_id")
            print(f"File uploaded successfully. Job ID: {job_id}")
            
            # Monitor processing time
            print("\nMonitoring processing performance...")
            max_attempts = 30  # Maximum number of polling attempts
            polling_interval = 5  # Seconds between polling attempts
            
            processing_start_time = time.time()
            last_status = None
            status_timestamps = {}
            
            for attempt in range(max_attempts):
                print(f"Polling job status (attempt {attempt+1}/{max_attempts})...")
                response = requests.get(f"{BACKEND_URL}/job/{job_id}")
                
                if response.status_code != 200:
                    print(f"Failed to get job status. Status code: {response.status_code}")
                    break
                
                job_data = response.json()
                status = job_data.get("status")
                
                # Record timestamp for each new status
                if status != last_status:
                    status_timestamps[status] = time.time()
                    if last_status:
                        duration = status_timestamps[status] - status_timestamps[last_status]
                        print(f"Phase '{last_status}' took {duration:.2f} seconds")
                    last_status = status
                
                print(f"Current job status: {status}")
                print(f"Processed: {job_data.get('processed_addresses', 0)}/{job_data.get('total_addresses', 0)}")
                print(f"Geocoded: {job_data.get('geocoded_addresses', 0)}/{job_data.get('total_addresses', 0)}")
                
                # Check if job is completed or failed
                if status == "completed":
                    processing_end_time = time.time()
                    processing_duration = processing_end_time - processing_start_time
                    print(f"\n✅ Job completed successfully in {processing_duration:.2f} seconds")
                    print(f"Processed {job_data.get('processed_addresses')} addresses")
                    print(f"Geocoded {job_data.get('geocoded_addresses')} addresses")
                    
                    # Print duration of each phase
                    for i, (phase, timestamp) in enumerate(status_timestamps.items()):
                        if i > 0:
                            prev_phase = list(status_timestamps.keys())[i-1]
                            duration = timestamp - status_timestamps[prev_phase]
                            print(f"Phase '{prev_phase}' took {duration:.2f} seconds")
                    
                    # Test route data retrieval performance
                    print("\nTesting route data retrieval performance...")
                    route_start_time = time.time()
                    response = requests.get(f"{BACKEND_URL}/route/{job_id}")
                    route_end_time = time.time()
                    
                    route_duration = route_end_time - route_start_time
                    print(f"Route data retrieval time: {route_duration:.2f} seconds")
                    
                    if response.status_code == 200:
                        route_data = response.json()
                        addresses = route_data.get("optimized_addresses", [])
                        print(f"Retrieved {len(addresses)} addresses in the route")
                    else:
                        print(f"Failed to retrieve route data. Status code: {response.status_code}")
                    
                    return job_id
                elif status == "error":
                    print(f"\n❌ Job failed with error: {job_data.get('error_message')}")
                    return None
                
                # Wait before next polling attempt
                time.sleep(polling_interval)
            
            print(f"\n⚠️ Job did not complete within the expected time ({max_attempts * polling_interval} seconds)")
            return job_id
        else:
            print(f"\n❌ File upload failed with status code: {response.status_code}")
            print(f"Response: {response.text}")
            return None
    except Exception as e:
        print(f"\n❌ Test failed with error: {str(e)}")
        return None

if __name__ == "__main__":
    # Get number of addresses from command line argument, default to 100
    num_addresses = 100
    if len(sys.argv) > 1:
        try:
            num_addresses = int(sys.argv[1])
        except ValueError:
            print(f"Invalid number of addresses: {sys.argv[1]}. Using default: 100")
    
    test_backend_performance(num_addresses)