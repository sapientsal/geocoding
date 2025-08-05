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
BACKEND_URL = "https://f235ba44-72f5-4259-bbd8-67b1b9d8e1d9.preview.emergentagent.com/api"

def create_large_dataset(num_addresses=2000):
    """Create a large dataset with the specified number of addresses"""
    print(f"\n🔍 Creating large dataset with {num_addresses} addresses...")
    
    # Base addresses to use (real addresses)
    base_addresses = [
        "1600 Pennsylvania Avenue NW, Washington, DC 20500",  # White House
        "350 Fifth Avenue, New York, NY 10118",               # Empire State Building
        "1 Infinite Loop, Cupertino, CA 95014",               # Apple HQ
        "1600 Amphitheatre Parkway, Mountain View, CA 94043", # Google HQ
        "2800 E Observatory Rd, Los Angeles, CA 90027",       # Griffith Observatory
        "151 3rd St, San Francisco, CA 94103",                # SF MOMA
        "1 Telegraph Hill Blvd, San Francisco, CA 94133",     # Coit Tower
        "900 Exposition Blvd, Los Angeles, CA 90007",         # Natural History Museum
        "111 S Grand Ave, Los Angeles, CA 90012",             # Walt Disney Concert Hall
        "100 Universal City Plaza, Universal City, CA 91608"  # Universal Studios
    ]
    
    # German addresses
    german_addresses = [
        "Unter den Linden 77, 10117 Berlin",
        "Brandenburger Tor, 10117 Berlin",
        "Kurfürstendamm 216, 10719 Berlin",
        "Friedrichstraße 43-45, 10969 Berlin",
        "Alexanderplatz 1, 10178 Berlin",
        "Potsdamer Platz 1, 10785 Berlin",
        "Schloßstraße 1, 14059 Berlin",
        "Frankfurter Allee 110, 10247 Berlin",
        "Karl-Marx-Allee 33, 10178 Berlin",
        "Prenzlauer Allee 242, 10405 Berlin"
    ]
    
    # Combine all base addresses
    all_base_addresses = base_addresses + german_addresses
    
    # Generate addresses by adding variations to base addresses
    addresses = []
    addresses.append(["Address"])  # Header row
    
    for i in range(num_addresses):
        base_address = random.choice(all_base_addresses)
        
        # Add some variation to make each address unique
        # This ensures we don't just have duplicates which might be cached
        if random.random() < 0.7:  # 70% of addresses are variations
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
            # Sometimes use the original address
            addresses.append([base_address])
    
    # Create CSV in memory
    csv_file = io.StringIO()
    writer = csv.writer(csv_file)
    for address in addresses:
        writer.writerow(address)
    
    csv_content = csv_file.getvalue()
    print(f"Created CSV with {len(addresses)-1} addresses")
    return csv_content

def test_large_dataset_performance(num_addresses=2000):
    """Test application performance with a large dataset"""
    print(f"\n🔍 Testing performance with {num_addresses} addresses...")
    
    # Create large dataset
    csv_content = create_large_dataset(num_addresses)
    
    # Measure upload time
    print("\nTesting file upload performance...")
    upload_start_time = time.time()
    
    files = {
        'file': (f'large_dataset_{num_addresses}.csv', csv_content, 'text/csv')
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
            max_attempts = 60  # Maximum number of polling attempts (5 minutes)
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
                    
                    # Test map loading performance
                    test_map_loading_performance(job_id)
                    
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

def test_map_loading_performance(job_id):
    """Test map loading performance by measuring API response time"""
    print("\nTesting map data loading performance...")
    
    if not job_id:
        print("Cannot test map loading without a valid job ID")
        return
    
    try:
        # Measure route data loading time
        route_start_time = time.time()
        response = requests.get(f"{BACKEND_URL}/route/{job_id}")
        route_end_time = time.time()
        
        route_duration = route_end_time - route_start_time
        print(f"Route data loading time: {route_duration:.2f} seconds")
        
        if response.status_code != 200:
            print(f"Failed to get route data. Status code: {response.status_code}")
            return
        
        route_data = response.json()
        
        # Check if we have a valid route
        optimized_addresses = route_data.get("optimized_addresses", [])
        total_addresses = len(optimized_addresses)
        
        print(f"Retrieved {total_addresses} addresses in the route")
        
        # Check if marker filtering is applied for large datasets
        if total_addresses >= 500:
            # Count markers with coordinates (which would be displayed on the map)
            markers_with_coords = sum(1 for addr in optimized_addresses if addr.get("latitude") and addr.get("longitude"))
            
            # If marker filtering is working, we should see fewer markers than total addresses
            if markers_with_coords < total_addresses:
                print(f"✅ Marker filtering applied: {markers_with_coords} markers out of {total_addresses} addresses")
            else:
                print(f"❌ Marker filtering not applied: All {total_addresses} addresses have markers")
        
    except Exception as e:
        print(f"Map loading test failed with error: {str(e)}")

if __name__ == "__main__":
    # Get number of addresses from command line argument, default to 2000
    num_addresses = 2000
    if len(sys.argv) > 1:
        try:
            num_addresses = int(sys.argv[1])
        except ValueError:
            print(f"Invalid number of addresses: {sys.argv[1]}. Using default: 2000")
    
    test_large_dataset_performance(num_addresses)