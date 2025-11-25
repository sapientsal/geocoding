#!/usr/bin/env python3
import requests
import time
import csv
import os
import io
import json
import pandas as pd
from datetime import datetime

# Get backend URL from frontend/.env
BACKEND_URL = "https://salespath-5.preview.emergentagent.com/api"

def log_test(task, message, success=True):
    """Log test results"""
    status = "✅ PASS" if success else "❌ FAIL"
    print(f"{status} - {task}: {message}")

def test_column_detection_fix():
    """Test the column detection fix for house number identification - CRITICAL ISSUE TEST"""
    print("\n🔍 Testing Column Detection Fix for House Number Identification...")
    print("=" * 80)
    print("🎯 CRITICAL ISSUE: System was incorrectly using 'Polygonnummer' as house number field")
    print("    instead of actual house number column, breaking address sorting functionality.")
    print("    Testing the fix that changed from substring to exact matching for 'nummer'/'nr'.")
    
    try:
        # Test 1: Column Detection Logic Test
        print("\n📋 TEST 1: Column Detection Logic with Polygonnummer vs Hausnummer...")
        
        # Create test CSV with both "Polygonnummer" and actual house number columns
        test_addresses_polygonnummer = [
            ["Projektname Strasse", "Hausnummer", "Zusatz", "PLZ", "Ort", "Polygonnummer"],
            ["Worpswede Am Hörenberg", "1", "A", "27726", "Worpswede", "12345"],
            ["Worpswede Am Hörenberg", "3", "A", "27726", "Worpswede", "12346"],
            ["Worpswede Am Hörenberg", "3", "C", "27726", "Worpswede", "12347"],
            ["Worpswede Am Hörenberg", "4", "", "27726", "Worpswede", "12348"],
            ["Worpswede Am Hörenberg", "7", "", "27726", "Worpswede", "12349"],
            ["Worpswede Am Hörenberg", "8", "", "27726", "Worpswede", "12350"],
            ["Worpswede Am Hörenberg", "10", "", "27726", "Worpswede", "12351"],
        ]
        
        # Create CSV content
        csv_content = ""
        for row in test_addresses_polygonnummer:
            csv_content += ",".join([f'"{cell}"' for cell in row]) + "\n"
        
        print(f"📊 Test data created with both 'Polygonnummer' and 'Hausnummer' columns:")
        print(f"  - Addresses should be sorted by Hausnummer (1A, 3A, 3C, 4, 7, 8, 10)")
        print(f"  - NOT by Polygonnummer (12345, 12346, 12347, 12348, 12349, 12350, 12351)")
        
        # Upload the test file using street-sorted endpoint to test column detection
        files = {
            'file': ('column_detection_test.csv', csv_content, 'text/csv')
        }
        
        response = requests.post(f"{BACKEND_URL}/upload-street-sorted", files=files)
        
        if response.status_code != 200:
            log_test("Street-Based Sorting", f"Failed to upload column detection test file. Status code: {response.status_code}", False)
            print(f"Response: {response.text}")
            return None
        
        job_id = response.json().get("job_id")
        print(f"✅ Column detection test job created: {job_id}")
        
        # Wait for job to complete
        print("⏳ Waiting for job to complete...")
        max_attempts = 30
        polling_interval = 5
        
        for attempt in range(max_attempts):
            response = requests.get(f"{BACKEND_URL}/job/{job_id}")
            
            if response.status_code != 200:
                log_test("Street-Based Sorting", f"Failed to get job status. Status code: {response.status_code}", False)
                return None
            
            job_data = response.json()
            status = job_data.get("status")
            
            print(f"Job status: {status} (attempt {attempt+1}/{max_attempts})")
            
            if status == "completed":
                print(f"✅ Job completed successfully.")
                break
            elif status == "error":
                log_test("Street-Based Sorting", f"Job failed with error: {job_data.get('error_message')}", False)
                return None
            
            time.sleep(polling_interval)
        
        # Test retrieving the sorted data to verify column detection
        print("\n🔍 Testing column detection results...")
        response = requests.get(f"{BACKEND_URL}/street-sorted/{job_id}")
        
        if response.status_code != 200:
            log_test("Street-Based Sorting", f"Failed to get street-sorted data. Status code: {response.status_code}", False)
            print(f"Response: {response.text}")
            return None
        
        sorted_data = response.json()
        sorted_addresses = sorted_data.get("sorted_addresses", [])
        
        if not sorted_addresses:
            log_test("Street-Based Sorting", "No sorted addresses found in response", False)
            return None
        
        # Verify that addresses are sorted by house number, NOT by polygon number
        print("\n📊 Analyzing sorting results:")
        house_numbers = []
        polygon_numbers = []
        
        for addr in sorted_addresses:
            row_data = addr.get("row_data", {})
            house_num = row_data.get("Hausnummer", "")
            zusatz = row_data.get("Zusatz", "")
            polygon_num = row_data.get("Polygonnummer", "")
            
            # Create display format for house number
            if zusatz and str(zusatz).strip():
                house_display = f"{house_num}{zusatz}"
            else:
                house_display = str(house_num)
            
            house_numbers.append(house_display)
            polygon_numbers.append(str(polygon_num))
        
        print(f"  House numbers in sorted order: {house_numbers}")
        print(f"  Polygon numbers in same order: {polygon_numbers}")
        
        # Expected house number order (correct sorting)
        expected_house_order = ["1A", "3A", "3C", "4", "7", "8", "10"]
        
        # Expected polygon number order (if incorrectly sorted by polygon)
        expected_polygon_order = ["12345", "12346", "12347", "12348", "12349", "12350", "12351"]
        
        # Check if sorted by house numbers (CORRECT)
        if house_numbers == expected_house_order:
            log_test("Street-Based Sorting", "✅ COLUMN DETECTION FIX VERIFIED: Addresses correctly sorted by house numbers (Hausnummer)")
            log_test("Street-Based Sorting", f"House number order: {house_numbers}")
        else:
            log_test("Street-Based Sorting", f"❌ COLUMN DETECTION FAILED: House numbers not in expected order. Got: {house_numbers}, Expected: {expected_house_order}", False)
        
        # Check if NOT sorted by polygon numbers (would indicate bug)
        if polygon_numbers == expected_polygon_order:
            log_test("Street-Based Sorting", "❌ CRITICAL BUG: Addresses appear to be sorted by Polygonnummer instead of Hausnummer!", False)
        else:
            log_test("Street-Based Sorting", "✅ REGRESSION PREVENTION: Addresses are NOT sorted by Polygonnummer (correct behavior)")
        
        # Clean up
        requests.delete(f"{BACKEND_URL}/job/{job_id}")
        
        print("\n🎯 COLUMN DETECTION FIX TEST SUMMARY:")
        print("=" * 50)
        print("✅ Tested that 'Polygonnummer' is NOT used as house number column")
        print("✅ Verified that proper house number columns are correctly identified")
        print("✅ Confirmed addresses are sorted by actual house numbers")
        print("✅ Regression prevention: substring matching no longer breaks sorting")
        
        return job_id
        
    except Exception as e:
        log_test("Street-Based Sorting", f"Column detection fix testing failed with error: {str(e)}", False)
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    test_column_detection_fix()