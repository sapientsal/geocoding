#!/usr/bin/env python3
import requests
import time
import csv
import os
import io
import json
from datetime import datetime

# Get backend URL from frontend/.env
BACKEND_URL = "https://5eb9a30f-3d93-48d7-930d-ac4b62f3b928.preview.emergentagent.com/api"

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
                print(f"❌ Failed to get street-sorted data. Status code: {response.status_code}")
                print(f"Response: {response.text}")
                return None
            
            sorted_data = response.json()
            sorted_addresses = sorted_data.get("sorted_addresses", [])
            
            if not sorted_addresses:
                print("❌ No sorted addresses found in response")
                return None
            
            print(f"✅ Successfully retrieved {len(sorted_addresses)} sorted addresses")
            
            # Print all addresses to see the actual format
            print("\nAll addresses in sorted order:")
            for i, addr in enumerate(sorted_addresses):
                original_address = addr.get("original_address", "")
                print(f"{i+1}. {original_address}")
            
            # Extract the original row data to analyze the sorting
            print("\nAnalyzing original row data for sorting:")
            street_groups = {}
            
            for addr in sorted_addresses:
                row_data = addr.get("row_data", {})
                if not row_data:
                    continue
                    
                street = row_data.get("Projektname Strasse", "")
                house_num = row_data.get("Hausnummer", "")
                zusatz = row_data.get("Zusatz", "")
                
                if street not in street_groups:
                    street_groups[street] = []
                    
                # Convert house number to numeric for sorting check
                try:
                    house_num_numeric = int(house_num)
                except (ValueError, TypeError):
                    house_num_numeric = 0
                    
                # Adjust for letter suffixes (e.g., 10A)
                if zusatz and str(zusatz).strip():
                    house_num_display = f"{house_num}{zusatz}"
                else:
                    house_num_display = house_num
                    
                street_groups[street].append({
                    "street": street,
                    "house_num": house_num_numeric,
                    "house_num_display": house_num_display,
                    "zusatz": zusatz,
                    "index": len(street_groups[street])
                })
            
            # Print the street grouping results
            print("\nStreet grouping results:")
            for street, addresses in street_groups.items():
                print(f"\n{street} - {len(addresses)} addresses:")
                for addr in addresses:
                    print(f"  - {addr['street']} {addr['house_num_display']}")
            
            # Check if streets are grouped together
            consecutive_indices = True
            for street, addresses in street_groups.items():
                if len(addresses) <= 1:
                    continue
                    
                # Get the indices in the original sorted list
                indices = [i for i, addr in enumerate(sorted_addresses) 
                          if addr.get("row_data", {}).get("Projektname Strasse") == street]
                
                # Check if indices are consecutive
                if max(indices) - min(indices) + 1 != len(indices):
                    consecutive_indices = False
                    print(f"❌ Street '{street}' addresses are not consecutive in the sorted list. Indices: {indices}")
            
            if consecutive_indices:
                print("✅ All streets are properly grouped together")
            
            # Check if house numbers are sorted within each street
            house_numbers_sorted = True
            
            # Expected order for each street
            expected_orders = {
                "Am Hörenberg": ["1A", "3A", "3C", "4", "7", "8", "10"],
                "Albert-Schwedt-Weg": ["1", "2", "3", "5", "12"],
                "Am Bergerdorfer Schiffgraben": ["30", "34", "50", "64"]
            }
            
            for street, addresses in street_groups.items():
                if len(addresses) <= 1:
                    continue
                
                # Get house numbers in the order they appear in the sorted list
                house_nums = []
                for i, addr in enumerate(sorted_addresses):
                    row_data = addr.get("row_data", {})
                    if row_data.get("Projektname Strasse") == street:
                        house_num = row_data.get("Hausnummer", "")
                        zusatz = row_data.get("Zusatz", "")
                        if zusatz and str(zusatz).strip():
                            house_nums.append(f"{house_num}{zusatz}")
                        else:
                            house_nums.append(f"{house_num}")
                
                print(f"\nHouse numbers for {street}: {house_nums}")
                
                # Check against expected order if available
                if street in expected_orders:
                    expected = expected_orders[street]
                    if house_nums != expected:
                        house_numbers_sorted = False
                        print(f"❌ House numbers for '{street}' are not in expected order. Found: {house_nums}, Expected: {expected}")
                    else:
                        print(f"✅ House numbers for '{street}' are correctly sorted: {house_nums}")
            
            if house_numbers_sorted:
                print("✅ House numbers within each street are properly sorted numerically")
            
            # Verify distance calculations
            has_distances = True
            for addr in sorted_addresses[:-1]:
                if "distance_to_next" not in addr and "Entfernung_zur_naechsten_Adresse_m" not in addr.get("row_data", {}):
                    has_distances = False
                    break
                    
            if has_distances:
                print("✅ Distance calculations are present for all addresses")
            else:
                print("❌ Distance calculations are missing for some addresses")
            
            # Test Excel export functionality
            print("Testing /api/street-sorted/{job_id}/export endpoint...")
            response = requests.get(f"{BACKEND_URL}/street-sorted/{job_id}/export")
            
            if response.status_code != 200:
                print(f"❌ Failed to export Excel file. Status code: {response.status_code}")
                print(f"Response: {response.text}")
            else:
                content_type = response.headers.get('Content-Type')
                content_disposition = response.headers.get('Content-Disposition')
                
                if content_type == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' and 'attachment' in content_disposition:
                    print("✅ Excel export functionality works correctly")
                else:
                    print(f"❌ Excel export has incorrect headers. Content-Type: {content_type}, Content-Disposition: {content_disposition}")
            
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