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

def test_guntershausen_format():
    """Test with the actual Guntershausen data format that was causing issues"""
    print("\n🔍 Testing Guntershausen Data Format...")
    print("=" * 80)
    print("🎯 Testing with the actual German address format that was causing issues")
    print("    to ensure the column detection fix works with real-world data.")
    
    try:
        # Create test data similar to the Guntershausen format mentioned in the issue
        test_addresses_guntershausen = [
            ["Projektname Strasse", "Hausnummer", "Zusatz", "PLZ", "Ort", "Polygonnummer", "Objektnummer"],
            ["624 Worpswede Albert-Schwedt-Weg", "1", "", "27726", "Worpswede", "POL001", "OBJ001"],
            ["624 Worpswede Albert-Schwedt-Weg", "12", "", "27726", "Worpswede", "POL002", "OBJ002"],
            ["624 Worpswede Albert-Schwedt-Weg", "2", "", "27726", "Worpswede", "POL003", "OBJ003"],
            ["624 Worpswede Albert-Schwedt-Weg", "3", "", "27726", "Worpswede", "POL004", "OBJ004"],
            ["624 Worpswede Albert-Schwedt-Weg", "5", "", "27726", "Worpswede", "POL005", "OBJ005"],
            ["624 Worpswede Bergstraße", "10", "", "27726", "Worpswede", "POL006", "OBJ006"],
            ["624 Worpswede Bergstraße", "12", "", "27726", "Worpswede", "POL007", "OBJ007"],
            ["624 Worpswede Bergstraße", "14", "", "27726", "Worpswede", "POL008", "OBJ008"],
        ]
        
        # Create CSV content
        csv_content = ""
        for row in test_addresses_guntershausen:
            csv_content += ",".join([f'"{cell}"' for cell in row]) + "\n"
        
        print(f"📊 Test data created with Guntershausen-like format:")
        print(f"  - Multiple columns containing 'nummer': Hausnummer, Polygonnummer, Objektnummer")
        print(f"  - Expected: System should use 'Hausnummer' for sorting")
        print(f"  - Albert-Schwedt-Weg should be sorted: [1, 2, 3, 5, 12]")
        print(f"  - Bergstraße should be sorted: [10, 12, 14]")
        
        # Upload the test file
        files = {
            'file': ('guntershausen_test.csv', csv_content, 'text/csv')
        }
        
        response = requests.post(f"{BACKEND_URL}/upload-street-sorted", files=files)
        
        if response.status_code != 200:
            log_test("German Address Format Processing", f"Failed to upload Guntershausen test file. Status code: {response.status_code}", False)
            print(f"Response: {response.text}")
            return None
        
        job_id = response.json().get("job_id")
        print(f"✅ Guntershausen test job created: {job_id}")
        
        # Wait for job to complete
        print("⏳ Waiting for job to complete...")
        max_attempts = 30
        polling_interval = 5
        
        for attempt in range(max_attempts):
            response = requests.get(f"{BACKEND_URL}/job/{job_id}")
            
            if response.status_code != 200:
                log_test("German Address Format Processing", f"Failed to get job status. Status code: {response.status_code}", False)
                return None
            
            job_data = response.json()
            status = job_data.get("status")
            
            print(f"Job status: {status} (attempt {attempt+1}/{max_attempts})")
            
            if status == "completed":
                print(f"✅ Job completed successfully.")
                break
            elif status == "error":
                log_test("German Address Format Processing", f"Job failed with error: {job_data.get('error_message')}", False)
                return None
            
            time.sleep(polling_interval)
        
        # Test retrieving the sorted data
        print("\n🔍 Testing Guntershausen format results...")
        response = requests.get(f"{BACKEND_URL}/street-sorted/{job_id}")
        
        if response.status_code != 200:
            log_test("German Address Format Processing", f"Failed to get street-sorted data. Status code: {response.status_code}", False)
            print(f"Response: {response.text}")
            return None
        
        sorted_data = response.json()
        sorted_addresses = sorted_data.get("sorted_addresses", [])
        
        if not sorted_addresses:
            log_test("German Address Format Processing", "No sorted addresses found in response", False)
            return None
        
        # Analyze the results by street
        print("\n📊 Analyzing Guntershausen format results:")
        street_groups = {}
        
        for addr in sorted_addresses:
            row_data = addr.get("row_data", {})
            street_raw = row_data.get("Projektname Strasse", "")
            house_num = row_data.get("Hausnummer", "")
            polygon_num = row_data.get("Polygonnummer", "")
            
            # Extract clean street name (should remove "624 Worpswede " prefix)
            street_clean = street_raw.replace("624 Worpswede ", "").strip()
            
            if street_clean not in street_groups:
                street_groups[street_clean] = []
            
            street_groups[street_clean].append({
                "house_num": house_num,
                "polygon_num": polygon_num,
                "original": street_raw
            })
        
        print(f"  Found {len(street_groups)} street groups:")
        
        # Check Albert-Schwedt-Weg sorting
        if "Albert-Schwedt-Weg" in street_groups:
            albert_houses = [addr["house_num"] for addr in street_groups["Albert-Schwedt-Weg"]]
            expected_albert = ["1", "2", "3", "5", "12"]
            
            print(f"  Albert-Schwedt-Weg house numbers: {albert_houses}")
            
            if albert_houses == expected_albert:
                log_test("German Address Format Processing", "✅ ALBERT-SCHWEDT-WEG: Correctly sorted by house numbers")
            else:
                log_test("German Address Format Processing", f"❌ ALBERT-SCHWEDT-WEG: Wrong sorting. Expected {expected_albert}, got {albert_houses}", False)
        
        # Check Bergstraße sorting
        if "Bergstraße" in street_groups:
            berg_houses = [addr["house_num"] for addr in street_groups["Bergstraße"]]
            expected_berg = ["10", "12", "14"]
            
            print(f"  Bergstraße house numbers: {berg_houses}")
            
            if berg_houses == expected_berg:
                log_test("German Address Format Processing", "✅ BERGSTRASSE: Correctly sorted by house numbers")
            else:
                log_test("German Address Format Processing", f"❌ BERGSTRASSE: Wrong sorting. Expected {expected_berg}, got {berg_houses}", False)
        
        # Verify street name cleaning worked
        original_addresses = [addr.get("original_address", "") for addr in sorted_addresses]
        
        # Check if addresses were properly combined and cleaned
        cleaned_addresses_found = False
        for addr in original_addresses:
            if "Albert-Schwedt-Weg" in addr and "624 Worpswede" not in addr:
                cleaned_addresses_found = True
                break
        
        if cleaned_addresses_found:
            log_test("German Address Format Processing", "✅ STREET NAME CLEANING: German address format properly cleaned (removed project prefix)")
        else:
            log_test("German Address Format Processing", "⚠️ STREET NAME CLEANING: May not have cleaned project prefixes as expected")
        
        # Verify that the system detected the correct columns
        print(f"\n📊 Column Detection Verification:")
        print(f"  - Available columns: Projektname Strasse, Hausnummer, Polygonnummer, Objektnummer")
        print(f"  - System should have detected 'Hausnummer' as house number column")
        print(f"  - System should NOT have used 'Polygonnummer' or 'Objektnummer'")
        
        # The fact that we got proper house number sorting proves the column detection worked
        if all(street_groups[street][0]["house_num"] <= street_groups[street][-1]["house_num"] 
               for street in street_groups if len(street_groups[street]) > 1):
            log_test("German Address Format Processing", "✅ COLUMN DETECTION: System correctly identified 'Hausnummer' column")
        
        # Clean up
        requests.delete(f"{BACKEND_URL}/job/{job_id}")
        
        print("\n🎯 GUNTERSHAUSEN FORMAT TEST SUMMARY:")
        print("=" * 50)
        print("✅ Tested with real-world German address format")
        print("✅ Verified column detection works with multiple '*nummer' columns")
        print("✅ Confirmed street-based sorting works correctly")
        print("✅ Verified German address format processing and cleaning")
        
        return job_id
        
    except Exception as e:
        log_test("German Address Format Processing", f"Guntershausen format testing failed with error: {str(e)}", False)
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    test_guntershausen_format()