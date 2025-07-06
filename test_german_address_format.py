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
        
        # Upload file to street-sorted endpoint
        response = requests.post(f"{BACKEND_URL}/upload-street-sorted", files=files)
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
        
        # Test retrieving the sorted data
        print("Testing /api/street-sorted/{job_id} endpoint...")
        response = requests.get(f"{BACKEND_URL}/street-sorted/{job_id}")
        
        self.assertEqual(response.status_code, 200, "Failed to get street-sorted data")
        
        sorted_data = response.json()
        sorted_addresses = sorted_data.get("sorted_addresses", [])
        
        self.assertTrue(len(sorted_addresses) > 0, "No sorted addresses found in response")
        
        # Extract the original row data to analyze the street name extraction
        print("\nAnalyzing street name extraction:")
        
        # Group addresses by street
        street_groups = {}
        
        for addr in sorted_addresses:
            row_data = addr.get("row_data", {})
            if not row_data:
                continue
                
            original_street = row_data.get("Projektname Strasse", "")
            
            # Extract the street name from the original street
            extracted_street = None
            for test_case in test_cases:
                if original_street == test_case["input"]:
                    extracted_street = test_case["expected"]
                    break
            
            if extracted_street not in street_groups:
                street_groups[extracted_street] = []
                
            street_groups[extracted_street].append({
                "original_street": original_street,
                "extracted_street": extracted_street
            })
        
        # Print the street grouping results
        print("\nStreet grouping results:")
        for street, addresses in street_groups.items():
            print(f"\n{street} - {len(addresses)} addresses:")
            for addr in addresses:
                print(f"  - Original: '{addr['original_street']}' → Extracted: '{addr['extracted_street']}'")
        
        # Verify that each test case street is correctly extracted and grouped
        for test_case in test_cases:
            expected_street = test_case["expected"]
            self.assertIn(expected_street, street_groups, f"Street '{expected_street}' not found in grouped results")
            
            # Verify that all addresses with this street are grouped together
            for addr in street_groups[expected_street]:
                self.assertEqual(addr["extracted_street"], expected_street, 
                                f"Street extraction failed. Expected: '{expected_street}', Got: '{addr['extracted_street']}'")
        
        print("\n✅ All street name extractions passed!")
    
    def test_house_number_sorting(self):
        """Test the house number sorting within street groups"""
        print("\n🔍 Testing house number sorting within street groups...")
        
        # Upload the test file with mixed house numbers
        with open('/app/street_sorting_test_specific.csv', 'r') as f:
            csv_content = f.read()
        
        files = {
            'file': ('street_sorting_test_specific.csv', csv_content, 'text/csv')
        }
        
        # Upload file to street-sorted endpoint
        response = requests.post(f"{BACKEND_URL}/upload-street-sorted", files=files)
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
        
        # Test retrieving the sorted data
        print("Testing /api/street-sorted/{job_id} endpoint...")
        response = requests.get(f"{BACKEND_URL}/street-sorted/{job_id}")
        
        self.assertEqual(response.status_code, 200, "Failed to get street-sorted data")
        
        sorted_data = response.json()
        sorted_addresses = sorted_data.get("sorted_addresses", [])
        
        self.assertTrue(len(sorted_addresses) > 0, "No sorted addresses found in response")
        
        # Extract the original row data to analyze the house number sorting
        print("\nAnalyzing house number sorting:")
        
        # Group addresses by street
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
                "zusatz": zusatz
            })
        
        # Print the street grouping results
        print("\nStreet grouping results:")
        for street, addresses in street_groups.items():
            print(f"\n{street} - {len(addresses)} addresses:")
            house_nums = []
            for addr in addresses:
                house_nums.append(addr["house_num_display"])
                print(f"  - {addr['street']} {addr['house_num_display']}")
            print(f"  House numbers in order: {house_nums}")
        
        # Expected order for each street
        expected_orders = {
            "Am Hörenberg": ["1A", "3A", "3C", "4", "7", "8", "10"],
            "Albert-Schwedt-Weg": ["1", "2", "3", "5", "12"],
            "Am Bergerdorfer Schiffgraben": ["30", "34", "50", "64"]
        }
        
        # Verify that house numbers are sorted correctly within each street
        for street, expected_order in expected_orders.items():
            if street not in street_groups:
                self.fail(f"Street '{street}' not found in grouped results")
                continue
                
            # Get house numbers in the order they appear in the sorted list
            house_nums = []
            for addr in street_groups[street]:
                house_nums.append(addr["house_num_display"])
            
            print(f"\nHouse numbers for {street}: {house_nums}")
            print(f"Expected order: {expected_order}")
            
            # Check if house numbers match expected order
            self.assertEqual(house_nums, expected_order, 
                            f"House numbers for '{street}' are not in expected order. Found: {house_nums}, Expected: {expected_order}")
        
        print("\n✅ All house number sorting tests passed!")

if __name__ == "__main__":
    unittest.main()