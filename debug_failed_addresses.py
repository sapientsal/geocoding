#!/usr/bin/env python3
import requests
import json
from pymongo import MongoClient
import os

# MongoDB connection
MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017/sales_routes')
client = MongoClient(MONGO_URL)
db = client['sales_routes']
addresses_collection = db['addresses']
routes_collection = db['routes']
upload_jobs_collection = db['upload_jobs']

BACKEND_URL = "https://f235ba44-72f5-4259-bbd8-67b1b9d8e1d9.preview.emergentagent.com/api"

def debug_helmstedt_job():
    """Debug the Helmstedt job data structure"""
    helmstedt_job_id = "dce58109-88ee-459c-b68d-baea39a64f76"
    
    print(f"🔍 Debugging Helmstedt job: {helmstedt_job_id}")
    print("=" * 80)
    
    # Check job in upload_jobs_collection
    print("📋 Checking upload_jobs_collection...")
    job = upload_jobs_collection.find_one({"id": helmstedt_job_id})
    if job:
        print(f"✅ Job found in upload_jobs_collection")
        print(f"  - Filename: {job.get('filename')}")
        print(f"  - Status: {job.get('status')}")
        print(f"  - Total addresses: {job.get('total_addresses')}")
        print(f"  - Processed addresses: {job.get('processed_addresses')}")
        print(f"  - Geocoded addresses: {job.get('geocoded_addresses')}")
        expected_failed = job.get('total_addresses', 0) - job.get('geocoded_addresses', 0)
        print(f"  - Expected failed addresses: {expected_failed}")
    else:
        print("❌ Job not found in upload_jobs_collection")
        return
    
    # Check routes_collection
    print("\n📋 Checking routes_collection...")
    route_data = routes_collection.find_one({"job_id": helmstedt_job_id})
    if route_data:
        print(f"✅ Route data found in routes_collection")
        print(f"  - Route ID: {route_data.get('_id')}")
        print(f"  - Job ID: {route_data.get('job_id')}")
        print(f"  - Keys in route data: {list(route_data.keys())}")
        
        # Check optimized_addresses
        optimized_addresses = route_data.get('optimized_addresses', [])
        print(f"  - Optimized addresses count: {len(optimized_addresses)}")
        
        if optimized_addresses:
            sample_addr = optimized_addresses[0]
            print(f"  - Sample address keys: {list(sample_addr.keys())}")
            print(f"  - Sample geocoded: {sample_addr.get('geocoded', 'N/A')}")
            
            # Count geocoded vs failed in optimized_addresses
            geocoded_count = sum(1 for addr in optimized_addresses if addr.get('geocoded', False))
            failed_count = len(optimized_addresses) - geocoded_count
            print(f"  - Manual count from optimized_addresses - Geocoded: {geocoded_count}, Failed: {failed_count}")
            
            # Show some failed addresses
            failed_addresses = [addr for addr in optimized_addresses if not addr.get('geocoded', False)]
            print(f"  - Failed addresses found: {len(failed_addresses)}")
            if failed_addresses:
                print(f"  - Sample failed addresses:")
                for i, addr in enumerate(failed_addresses[:5]):
                    original = addr.get('original_address', '')
                    error = addr.get('geocoding_error', addr.get('error', 'No error'))
                    print(f"    {i+1}. '{original}' - Error: {error}")
        else:
            print("  - No optimized_addresses found in route data")
            
        # Check if there are other address fields
        addresses = route_data.get('addresses', [])
        print(f"  - Addresses count: {len(addresses)}")
        
    else:
        print("❌ Route data not found in routes_collection")
    
    # Check addresses_collection as fallback
    print("\n📋 Checking addresses_collection...")
    addresses = list(addresses_collection.find({"job_id": helmstedt_job_id}))
    print(f"  - Addresses found in addresses_collection: {len(addresses)}")
    
    if addresses:
        sample_addr = addresses[0]
        print(f"  - Sample address keys: {list(sample_addr.keys())}")
        print(f"  - Sample geocoded: {sample_addr.get('geocoded', 'N/A')}")
        
        # Count geocoded vs failed in addresses_collection
        geocoded_count = sum(1 for addr in addresses if addr.get('geocoded', False))
        failed_count = len(addresses) - geocoded_count
        print(f"  - Manual count from addresses_collection - Geocoded: {geocoded_count}, Failed: {failed_count}")
        
        # Show some failed addresses
        failed_addresses = [addr for addr in addresses if not addr.get('geocoded', False)]
        print(f"  - Failed addresses found: {len(failed_addresses)}")
        if failed_addresses:
            print(f"  - Sample failed addresses:")
            for i, addr in enumerate(failed_addresses[:5]):
                original = addr.get('original_address', '')
                error = addr.get('geocoding_error', addr.get('error', 'No error'))
                print(f"    {i+1}. '{original}' - Error: {error}")

def debug_new_test_job():
    """Create a new test job and debug its data structure"""
    print("\n🔍 Creating new test job for debugging...")
    print("=" * 80)
    
    # Create a test job with some addresses that will fail
    test_addresses = [
        ['Projektname Strasse', 'Hausnummer', 'Zusatz', 'PLZ', 'Ort'],
        ['Worpswede Am Hörenberg', '8', '', '27726', 'Worpswede'],  # Valid
        ['', '12', '', '27726', 'Worpswede'],  # Invalid - empty street
        ['Worpswede Invalidstraße', '999', '', '99999', 'Nonexistent'],  # Invalid location
    ]
    
    # Create CSV content
    csv_content = ''
    for row in test_addresses:
        csv_content += ','.join([f'"{cell}"' for cell in row]) + '\n'
    
    print('Creating test job...')
    files = {
        'file': ('debug_test.csv', csv_content, 'text/csv')
    }
    
    response = requests.post(f'{BACKEND_URL}/upload', files=files)
    if response.status_code != 200:
        print(f'Upload failed: {response.status_code} - {response.text}')
        return
    
    job_id = response.json().get('job_id')
    print(f'Created job: {job_id}')
    
    # Wait for completion
    import time
    print('Waiting for job completion...')
    for i in range(20):
        response = requests.get(f'{BACKEND_URL}/job/{job_id}')
        if response.status_code == 200:
            job_data = response.json()
            status = job_data.get('status')
            print(f'Status: {status}, Processed: {job_data.get("processed_addresses")}/{job_data.get("total_addresses")}, Geocoded: {job_data.get("geocoded_addresses")}')
            if status == 'completed':
                break
        time.sleep(3)
    
    # Now debug the data structure
    print(f"\n📋 Debugging test job data structure: {job_id}")
    
    # Check routes_collection
    route_data = routes_collection.find_one({"job_id": job_id})
    if route_data:
        print(f"✅ Route data found")
        print(f"  - Keys: {list(route_data.keys())}")
        
        optimized_addresses = route_data.get('optimized_addresses', [])
        print(f"  - Optimized addresses: {len(optimized_addresses)}")
        
        if optimized_addresses:
            for i, addr in enumerate(optimized_addresses):
                geocoded = addr.get('geocoded', False)
                original = addr.get('original_address', '')
                error = addr.get('geocoding_error', addr.get('error', 'No error'))
                print(f"    {i+1}. '{original}' - Geocoded: {geocoded}, Error: {error}")
    else:
        print("❌ No route data found")
    
    # Check addresses_collection
    addresses = list(addresses_collection.find({"job_id": job_id}))
    print(f"  - Addresses in addresses_collection: {len(addresses)}")
    
    if addresses:
        for i, addr in enumerate(addresses):
            geocoded = addr.get('geocoded', False)
            original = addr.get('original_address', '')
            error = addr.get('geocoding_error', addr.get('error', 'No error'))
            print(f"    {i+1}. '{original}' - Geocoded: {geocoded}, Error: {error}")
    
    # Test the failed addresses endpoint
    print(f"\n📋 Testing failed addresses endpoint for test job...")
    response = requests.get(f'{BACKEND_URL}/job/{job_id}/failed-addresses')
    print(f'Status: {response.status_code}')
    if response.status_code == 200:
        data = response.json()
        print(f'Failed addresses count: {data.get("statistics", {}).get("failed_geocoding", 0)}')
        print(f'Total addresses: {data.get("statistics", {}).get("total_addresses", 0)}')
        failed_list = data.get('failed_addresses', [])
        print(f'Failed addresses list length: {len(failed_list)}')
    else:
        print(f'Error: {response.text}')
    
    # Clean up
    requests.delete(f'{BACKEND_URL}/job/{job_id}')

if __name__ == "__main__":
    debug_helmstedt_job()
    debug_new_test_job()