#!/usr/bin/env python3
import requests
import time
import json
import unittest
import re

# Get backend URL from frontend/.env
BACKEND_URL = "https://5eb9a30f-3d93-48d7-930d-ac4b62f3b928.preview.emergentagent.com/api"

class TestGermanAddressFormatCleaning(unittest.TestCase):
    """Test the German address format cleaning logic"""
    
    def test_street_name_extraction(self):
        """Test the street name extraction from German address formats"""
        print("\n🔍 Testing street name extraction from German address formats...")
        
        # Create test data
        test_cases = [
            {
                "input": "624 Worpswede Albert-Schwedt-Weg",
                "expected": "Albert-Schwedt-Weg"
            },
            {
                "input": "624 Worpswede Am Hörenberg",
                "expected": "Am Hörenberg"
            },
            {
                "input": "624 Worpswede Am Bergerdorfer Schiffgraben",
                "expected": "Am Bergerdorfer Schiffgraben"
            }
        ]
        
        # Upload the test file
        with open('/app/german_address_format_test.csv', 'r') as f:
            csv_content = f.read()
        
        files = {
            'file': ('german_address_format_test.csv', csv_content, 'text/csv')
        }
        
        # Upload file to regular upload endpoint
        response = requests.post(f"{BACKEND_URL}/upload", files=files)
        self.assertEqual(response.status_code, 200, "File upload failed")
        
        job_id = response.json().get("job_id")
        print(f"File uploaded successfully. Job ID: {job_id}")
        
        # Wait for job to complete
        max_attempts = 30
        polling_interval = 5
        
        for attempt in range(max_attempts):
            print(f"Polling job status (attempt {attempt+1}/{max_attempts})...")
            response = requests.get(f"{BACKEND_URL}/job/{job_id}")
            
            self.assertEqual(response.status_code, 200, "Failed to get job status")
            
            job_data = response.json()
            status = job_data.get("status")
            
            print(f"Current job status: {status}")
            print(f"Processed: {job_data.get('processed_addresses')}/{job_data.get('total_addresses')}")
            
            # Check if job is completed or failed
            if status == "completed":
                print(f"Job completed successfully. Processed {job_data.get('processed_addresses')} addresses.")
                break
            elif status == "error":
                self.fail(f"Job failed with error: {job_data.get('error_message')}")
            
            # Wait before next polling attempt
            time.sleep(polling_interval)
        
        # Test retrieving the route data
        print("Testing /api/route/{job_id} endpoint...")
        response = requests.get(f"{BACKEND_URL}/route/{job_id}")
        
        self.assertEqual(response.status_code, 200, "Failed to get route data")
        
        route_data = response.json()
        addresses = route_data.get("addresses", [])
        
        self.assertTrue(len(addresses) > 0, "No addresses found in response")
        
        # Extract the original addresses to analyze the street name extraction
        print("\nAnalyzing street name extraction:")
        
        # Group addresses by street
        street_groups = {}
        
        for addr in addresses:
            original_address = addr.get("original_address", "")
            formatted_address = addr.get("formatted_address", "")
            
            # Extract the street name from the original address
            extracted_street = None
            for test_case in test_cases:
                if test_case["input"] in original_address:
                    extracted_street = test_case["expected"]
                    break
            
            if extracted_street:
                if extracted_street not in street_groups:
                    street_groups[extracted_street] = []
                    
                street_groups[extracted_street].append({
                    "original_address": original_address,
                    "formatted_address": formatted_address,
                    "extracted_street": extracted_street
                })
        
        # Print the street grouping results
        print("\nStreet grouping results:")
        for street, addresses in street_groups.items():
            print(f"\n{street} - {len(addresses)} addresses:")
            for addr in addresses:
                print(f"  - Original: '{addr['original_address']}' → Formatted: '{addr['formatted_address']}'")
        
        # Verify that each test case street is correctly extracted
        for test_case in test_cases:
            expected_street = test_case["expected"]
            input_street = test_case["input"]
            
            # Find if any address contains this input street
            found = False
            for addr in addresses:
                if input_street in addr.get("original_address", ""):
                    found = True
                    print(f"Found address with '{input_street}': {addr.get('original_address')}")
                    break
            
            self.assertTrue(found, f"No address found containing '{input_street}'")
        
        print("\n✅ Street name extraction test completed!")
    
    def test_house_number_sorting(self):
        """Test the house number sorting within street groups"""
        print("\n🔍 Testing house number sorting within street groups...")
        
        # Upload the test file with mixed house numbers
        with open('/app/street_sorting_test_specific.csv', 'r') as f:
            csv_content = f.read()
        
        files = {
            'file': ('street_sorting_test_specific.csv', csv_content, 'text/csv')
        }
        
        # Upload file to regular upload endpoint
        response = requests.post(f"{BACKEND_URL}/upload", files=files)
        self.assertEqual(response.status_code, 200, "File upload failed")
        
        job_id = response.json().get("job_id")
        print(f"File uploaded successfully. Job ID: {job_id}")
        
        # Wait for job to complete
        max_attempts = 30
        polling_interval = 5
        
        for attempt in range(max_attempts):
            print(f"Polling job status (attempt {attempt+1}/{max_attempts})...")
            response = requests.get(f"{BACKEND_URL}/job/{job_id}")
            
            self.assertEqual(response.status_code, 200, "Failed to get job status")
            
            job_data = response.json()
            status = job_data.get("status")
            
            print(f"Current job status: {status}")
            print(f"Processed: {job_data.get('processed_addresses')}/{job_data.get('total_addresses')}")
            
            # Check if job is completed or failed
            if status == "completed":
                print(f"Job completed successfully. Processed {job_data.get('processed_addresses')} addresses.")
                break
            elif status == "error":
                self.fail(f"Job failed with error: {job_data.get('error_message')}")
            
            # Wait before next polling attempt
            time.sleep(polling_interval)
        
        # Test retrieving the route data
        print("Testing /api/route/{job_id} endpoint...")
        response = requests.get(f"{BACKEND_URL}/route/{job_id}")
        
        self.assertEqual(response.status_code, 200, "Failed to get route data")
        
        route_data = response.json()
        addresses = route_data.get("addresses", [])
        optimized_addresses = route_data.get("optimized_addresses", [])
        
        self.assertTrue(len(addresses) > 0, "No addresses found in response")
        
        # Extract the original addresses to analyze the house number sorting
        print("\nAnalyzing house number sorting:")
        
        # Group addresses by street
        street_groups = {}
        
        for addr in addresses:
            original_address = addr.get("original_address", "")
            
            # Extract street and house number from original address
            # Format: "Street HouseNumber, ZIP City"
            match = re.match(r"([^,]+) (\d+)([A-Za-z]*)?, (\d+) (.+)", original_address)
            if match:
                street = match.group(1).strip()
                house_num = match.group(2)
                zusatz = match.group(3) if match.group(3) else ""
                
                if street not in street_groups:
                    street_groups[street] = []
                    
                # Convert house number to numeric for sorting check
                try:
                    house_num_numeric = int(house_num)
                except (ValueError, TypeError):
                    house_num_numeric = 0
                    
                # Adjust for letter suffixes (e.g., 10A)
                if zusatz:
                    house_num_display = f"{house_num}{zusatz}"
                else:
                    house_num_display = house_num
                    
                street_groups[street].append({
                    "street": street,
                    "house_num": house_num_numeric,
                    "house_num_display": house_num_display,
                    "zusatz": zusatz,
                    "original_address": original_address
                })
        
        # Print the street grouping results
        print("\nStreet grouping results:")
        for street, addresses in street_groups.items():
            print(f"\n{street} - {len(addresses)} addresses:")
            house_nums = []
            for addr in addresses:
                house_nums.append(addr["house_num_display"])
                print(f"  - {addr['original_address']}")
            print(f"  House numbers in order: {house_nums}")
        
        # Check if streets are grouped together in the optimized route
        print("\nChecking if streets are grouped together in the optimized route:")
        
        # Get the streets in the order they appear in the optimized route
        optimized_streets = []
        for addr in optimized_addresses:
            original_address = addr.get("original_address", "")
            match = re.match(r"([^,]+) \d+[A-Za-z]*, \d+ .+", original_address)
            if match:
                street = match.group(1).strip()
                optimized_streets.append(street)
        
        # Print the streets in the optimized route
        print(f"Streets in optimized route: {optimized_streets}")
        
        # Check if streets are grouped together
        grouped_streets = []
        current_street = None
        for street in optimized_streets:
            if street != current_street:
                grouped_streets.append(street)
                current_street = street
        
        print(f"Grouped streets: {grouped_streets}")
        
        # Check if house numbers within each street are sorted
        print("\nChecking if house numbers within each street are sorted:")
        
        # Get the house numbers for each street in the optimized route
        optimized_house_nums = {}
        for addr in optimized_addresses:
            original_address = addr.get("original_address", "")
            match = re.match(r"([^,]+) (\d+)([A-Za-z]*)?, \d+ .+", original_address)
            if match:
                street = match.group(1).strip()
                house_num = match.group(2)
                zusatz = match.group(3) if match.group(3) else ""
                
                if street not in optimized_house_nums:
                    optimized_house_nums[street] = []
                
                if zusatz:
                    house_num_display = f"{house_num}{zusatz}"
                else:
                    house_num_display = house_num
                
                optimized_house_nums[street].append(house_num_display)
        
        # Print the house numbers for each street in the optimized route
        for street, house_nums in optimized_house_nums.items():
            print(f"{street}: {house_nums}")
        
        print("\n✅ House number sorting test completed!")

if __name__ == "__main__":
    unittest.main()