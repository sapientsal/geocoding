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
BACKEND_URL = "https://nominatim-overload.preview.emergentagent.com/api"

def log_test(task, message, success=True):
    """Log test results"""
    status = "✅ PASS" if success else "❌ FAIL"
    print(f"{status} - {task}: {message}")

def test_final_verification():
    """Final verification of the column detection fix"""
    print("\n🔍 FINAL VERIFICATION OF COLUMN DETECTION FIX...")
    print("=" * 80)
    print("🎯 CRITICAL ISSUE RESOLVED: Verifying that 'Polygonnummer' is no longer")
    print("    incorrectly matched as house number column, fixing address sorting.")
    
    try:
        # The most important test: Polygonnummer vs Hausnummer
        print("\n📋 FINAL TEST: Polygonnummer vs Hausnummer Column Detection...")
        
        test_addresses = [
            ["Projektname Strasse", "Hausnummer", "PLZ", "Ort", "Polygonnummer"],
            ["Worpswede Teststraße", "10", "27726", "Worpswede", "1001"],  # House 10, Polygon 1001
            ["Worpswede Teststraße", "2", "27726", "Worpswede", "1002"],   # House 2, Polygon 1002
            ["Worpswede Teststraße", "5", "27726", "Worpswede", "1003"],   # House 5, Polygon 1003
            ["Worpswede Teststraße", "1", "27726", "Worpswede", "1004"],   # House 1, Polygon 1004
        ]
        
        csv_content = ""
        for row in test_addresses:
            csv_content += ",".join([f'"{cell}"' for cell in row]) + "\n"
        
        print(f"📊 Test scenario:")
        print(f"  - Input has both 'Hausnummer' and 'Polygonnummer' columns")
        print(f"  - House numbers in input order: [10, 2, 5, 1]")
        print(f"  - Polygon numbers in input order: [1001, 1002, 1003, 1004]")
        print(f"  - CORRECT result (sorted by house): [1, 2, 5, 10]")
        print(f"  - WRONG result (sorted by polygon): [10, 2, 5, 1] (unchanged)")
        
        files = {'file': ('final_verification.csv', csv_content, 'text/csv')}
        response = requests.post(f"{BACKEND_URL}/upload-street-sorted", files=files)
        
        if response.status_code != 200:
            log_test("Column Detection Fix", f"Failed to upload test file. Status code: {response.status_code}", False)
            return False
        
        job_id = response.json().get("job_id")
        print(f"✅ Test job created: {job_id}")
        
        # Wait for completion
        for attempt in range(20):
            response = requests.get(f"{BACKEND_URL}/job/{job_id}")
            if response.status_code == 200:
                job_data = response.json()
                if job_data.get("status") == "completed":
                    break
            time.sleep(3)
        
        # Get results
        response = requests.get(f"{BACKEND_URL}/street-sorted/{job_id}")
        if response.status_code != 200:
            log_test("Column Detection Fix", f"Failed to get results. Status code: {response.status_code}", False)
            return False
        
        sorted_data = response.json()
        sorted_addresses = sorted_data.get("sorted_addresses", [])
        
        if not sorted_addresses:
            log_test("Column Detection Fix", "No sorted addresses found", False)
            return False
        
        # Extract house numbers from results
        house_numbers = []
        for addr in sorted_addresses:
            row_data = addr.get("row_data", {})
            house_num = row_data.get("Hausnummer", "")
            house_numbers.append(str(house_num))
        
        print(f"\n📊 RESULTS:")
        print(f"  Input order: [10, 2, 5, 1]")
        print(f"  Output order: {house_numbers}")
        
        # Check if correctly sorted by house numbers
        expected_order = ["1", "2", "5", "10"]
        input_order = ["10", "2", "5", "1"]
        
        if house_numbers == expected_order:
            log_test("Column Detection Fix", "🎉 COLUMN DETECTION FIX VERIFIED: Addresses correctly sorted by house numbers!")
            log_test("Column Detection Fix", "✅ System correctly identified 'Hausnummer' as house number column")
            log_test("Column Detection Fix", "✅ System did NOT use 'Polygonnummer' for sorting")
            log_test("Column Detection Fix", "✅ Address sorting is now working correctly")
            success = True
        elif house_numbers == input_order:
            log_test("Column Detection Fix", "❌ CRITICAL BUG STILL EXISTS: Addresses not sorted (may be using Polygonnummer)", False)
            success = False
        else:
            log_test("Column Detection Fix", f"❌ UNEXPECTED SORTING: Got {house_numbers}, expected {expected_order}", False)
            success = False
        
        # Clean up
        requests.delete(f"{BACKEND_URL}/job/{job_id}")
        
        print("\n🎯 FINAL VERIFICATION SUMMARY:")
        print("=" * 50)
        
        if success:
            print("🎉 COLUMN DETECTION FIX IS WORKING CORRECTLY!")
            print("✅ The system no longer incorrectly matches 'Polygonnummer' as house number")
            print("✅ Proper house number columns are correctly identified")
            print("✅ Addresses are now sorted by actual house numbers")
            print("✅ The fix prevents regression with substring matching")
            print("✅ Street-based sorting functionality is restored")
        else:
            print("❌ COLUMN DETECTION FIX NEEDS ATTENTION")
            print("❌ The system may still be using incorrect columns for sorting")
        
        return success
        
    except Exception as e:
        log_test("Column Detection Fix", f"Final verification failed with error: {str(e)}", False)
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    test_final_verification()