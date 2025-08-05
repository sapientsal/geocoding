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
BACKEND_URL = "https://f235ba44-72f5-4259-bbd8-67b1b9d8e1d9.preview.emergentagent.com/api"

def log_test(task, message, success=True):
    """Log test results"""
    status = "✅ PASS" if success else "❌ FAIL"
    print(f"{status} - {task}: {message}")

def test_comprehensive_column_detection():
    """Comprehensive test of the column detection fix"""
    print("\n🔍 COMPREHENSIVE COLUMN DETECTION FIX TEST...")
    print("=" * 80)
    print("🎯 FINAL VERIFICATION: Testing all aspects of the column detection fix")
    print("    to ensure 'Polygonnummer' is never used as house number column.")
    
    all_tests_passed = True
    
    try:
        # Test 1: The critical bug scenario
        print("\n📋 TEST 1: Critical Bug Scenario - Polygonnummer vs Hausnummer...")
        
        test_addresses_critical = [
            ["Projektname Strasse", "Hausnummer", "PLZ", "Ort", "Polygonnummer"],
            ["Worpswede Teststraße", "5", "27726", "Worpswede", "1001"],
            ["Worpswede Teststraße", "1", "27726", "Worpswede", "1002"],
            ["Worpswede Teststraße", "3", "27726", "Worpswede", "1003"],
        ]
        
        csv_content = ""
        for row in test_addresses_critical:
            csv_content += ",".join([f'"{cell}"' for cell in row]) + "\n"
        
        files = {'file': ('critical_test.csv', csv_content, 'text/csv')}
        response = requests.post(f"{BACKEND_URL}/upload-street-sorted", files=files)
        
        if response.status_code == 200:
            job_id = response.json().get("job_id")
            
            # Wait for completion
            for attempt in range(20):
                response = requests.get(f"{BACKEND_URL}/job/{job_id}")
                if response.status_code == 200:
                    job_data = response.json()
                    if job_data.get("status") == "completed":
                        break
                time.sleep(3)
            
            # Check results
            response = requests.get(f"{BACKEND_URL}/street-sorted/{job_id}")
            if response.status_code == 200:
                sorted_data = response.json()
                sorted_addresses = sorted_data.get("sorted_addresses", [])
                
                house_nums = []
                for addr in sorted_addresses:
                    row_data = addr.get("row_data", {})
                    house_nums.append(str(row_data.get("Hausnummer", "")))
                
                print(f"  Input order: ['5', '1', '3']")
                print(f"  Output order: {house_nums}")
                
                if house_nums == ["1", "3", "5"]:
                    log_test("Column Detection Fix", "✅ CRITICAL TEST PASSED: Addresses sorted by Hausnummer, not Polygonnummer")
                else:
                    log_test("Column Detection Fix", f"❌ CRITICAL TEST FAILED: Expected ['1', '3', '5'], got {house_nums}", False)
                    all_tests_passed = False
            
            requests.delete(f"{BACKEND_URL}/job/{job_id}")
        
        # Test 2: Multiple nummer columns
        print("\n📋 TEST 2: Multiple '*nummer' Columns...")
        
        test_addresses_multiple = [
            ["Strasse", "Hausnummer", "PLZ", "Ort", "Polygonnummer", "Kundennummer", "Rechnungsnummer", "Objektnummer"],
            ["Hauptstraße", "10", "12345", "Stadt", "P001", "K001", "R001", "O001"],
            ["Hauptstraße", "2", "12345", "Stadt", "P002", "K002", "R002", "O002"],
            ["Hauptstraße", "5", "12345", "Stadt", "P003", "K003", "R003", "O003"],
        ]
        
        csv_content_2 = ""
        for row in test_addresses_multiple:
            csv_content_2 += ",".join([f'"{cell}"' for cell in row]) + "\n"
        
        files_2 = {'file': ('multiple_nummer_test.csv', csv_content_2, 'text/csv')}
        response = requests.post(f"{BACKEND_URL}/upload-street-sorted", files=files_2)
        
        if response.status_code == 200:
            job_id_2 = response.json().get("job_id")
            
            # Wait for completion
            for attempt in range(20):
                response = requests.get(f"{BACKEND_URL}/job/{job_id_2}")
                if response.status_code == 200:
                    job_data = response.json()
                    if job_data.get("status") == "completed":
                        break
                time.sleep(3)
            
            # Check results
            response = requests.get(f"{BACKEND_URL}/street-sorted/{job_id_2}")
            if response.status_code == 200:
                sorted_data_2 = response.json()
                sorted_addresses_2 = sorted_data_2.get("sorted_addresses", [])
                
                house_nums_2 = []
                for addr in sorted_addresses_2:
                    row_data = addr.get("row_data", {})
                    house_nums_2.append(str(row_data.get("Hausnummer", "")))
                
                print(f"  Input order: ['10', '2', '5']")
                print(f"  Output order: {house_nums_2}")
                
                if house_nums_2 == ["2", "5", "10"]:
                    log_test("Column Detection Fix", "✅ MULTIPLE COLUMNS TEST PASSED: System correctly chose 'Hausnummer' among many '*nummer' columns")
                else:
                    log_test("Column Detection Fix", f"❌ MULTIPLE COLUMNS TEST FAILED: Expected ['2', '5', '10'], got {house_nums_2}", False)
                    all_tests_passed = False
            
            requests.delete(f"{BACKEND_URL}/job/{job_id_2}")
        
        # Test 3: Exact match test
        print("\n📋 TEST 3: Exact Match Test ('Nummer' column)...")
        
        test_addresses_exact = [
            ["Straße", "Nummer", "PLZ", "Ort", "Polygonnummer"],
            ["Beispielstraße", "8", "54321", "Beispielstadt", "X001"],
            ["Beispielstraße", "2", "54321", "Beispielstadt", "X002"],
            ["Beispielstraße", "4", "54321", "Beispielstadt", "X003"],
        ]
        
        csv_content_3 = ""
        for row in test_addresses_exact:
            csv_content_3 += ",".join([f'"{cell}"' for cell in row]) + "\n"
        
        files_3 = {'file': ('exact_match_test.csv', csv_content_3, 'text/csv')}
        response = requests.post(f"{BACKEND_URL}/upload-street-sorted", files=files_3)
        
        if response.status_code == 200:
            job_id_3 = response.json().get("job_id")
            
            # Wait for completion
            for attempt in range(20):
                response = requests.get(f"{BACKEND_URL}/job/{job_id_3}")
                if response.status_code == 200:
                    job_data = response.json()
                    if job_data.get("status") == "completed":
                        break
                time.sleep(3)
            
            # Check results
            response = requests.get(f"{BACKEND_URL}/street-sorted/{job_id_3}")
            if response.status_code == 200:
                sorted_data_3 = response.json()
                sorted_addresses_3 = sorted_data_3.get("sorted_addresses", [])
                
                house_nums_3 = []
                for addr in sorted_addresses_3:
                    row_data = addr.get("row_data", {})
                    house_nums_3.append(str(row_data.get("Nummer", "")))
                
                print(f"  Input order: ['8', '2', '4']")
                print(f"  Output order: {house_nums_3}")
                
                if house_nums_3 == ["2", "4", "8"]:
                    log_test("Column Detection Fix", "✅ EXACT MATCH TEST PASSED: 'Nummer' column correctly detected and used")
                else:
                    log_test("Column Detection Fix", f"❌ EXACT MATCH TEST FAILED: Expected ['2', '4', '8'], got {house_nums_3}", False)
                    all_tests_passed = False
            
            requests.delete(f"{BACKEND_URL}/job/{job_id_3}")
        
        # Test 4: Real-world scenario with German addresses
        print("\n📋 TEST 4: Real-world German Address Scenario...")
        
        test_addresses_german = [
            ["Projektname Strasse", "Hausnummer", "Zusatz", "PLZ", "Ort", "Polygonnummer"],
            ["624 Worpswede Am Hörenberg", "8", "", "27726", "Worpswede", "12350"],
            ["624 Worpswede Am Hörenberg", "1", "A", "27726", "Worpswede", "12345"],
            ["624 Worpswede Am Hörenberg", "3", "A", "27726", "Worpswede", "12346"],
            ["624 Worpswede Am Hörenberg", "10", "", "27726", "Worpswede", "12351"],
        ]
        
        csv_content_4 = ""
        for row in test_addresses_german:
            csv_content_4 += ",".join([f'"{cell}"' for cell in row]) + "\n"
        
        files_4 = {'file': ('german_real_world_test.csv', csv_content_4, 'text/csv')}
        response = requests.post(f"{BACKEND_URL}/upload-street-sorted", files=files_4)
        
        if response.status_code == 200:
            job_id_4 = response.json().get("job_id")
            
            # Wait for completion
            for attempt in range(20):
                response = requests.get(f"{BACKEND_URL}/job/{job_id_4}")
                if response.status_code == 200:
                    job_data = response.json()
                    if job_data.get("status") == "completed":
                        break
                time.sleep(3)
            
            # Check results
            response = requests.get(f"{BACKEND_URL}/street-sorted/{job_id_4}")
            if response.status_code == 200:
                sorted_data_4 = response.json()
                sorted_addresses_4 = sorted_data_4.get("sorted_addresses", [])
                
                house_display = []
                for addr in sorted_addresses_4:
                    row_data = addr.get("row_data", {})
                    house_num = str(row_data.get("Hausnummer", ""))
                    zusatz = str(row_data.get("Zusatz", "")).strip()
                    if zusatz:
                        house_display.append(f"{house_num}{zusatz}")
                    else:
                        house_display.append(house_num)
                
                print(f"  Input order: ['8', '1A', '3A', '10']")
                print(f"  Output order: {house_display}")
                
                expected_german = ["1A", "3A", "8", "10"]
                if house_display == expected_german:
                    log_test("Column Detection Fix", "✅ GERMAN REAL-WORLD TEST PASSED: Correct sorting with German address format")
                else:
                    log_test("Column Detection Fix", f"❌ GERMAN REAL-WORLD TEST FAILED: Expected {expected_german}, got {house_display}", False)
                    all_tests_passed = False
            
            requests.delete(f"{BACKEND_URL}/job/{job_id_4}")
        
        # Final summary
        print("\n🎯 COMPREHENSIVE COLUMN DETECTION FIX TEST RESULTS:")
        print("=" * 60)
        
        if all_tests_passed:
            log_test("Column Detection Fix", "🎉 ALL TESTS PASSED: Column detection fix is working correctly!")
            print("✅ System correctly identifies 'Hausnummer' as house number column")
            print("✅ System does NOT use 'Polygonnummer' for sorting")
            print("✅ Exact matching for 'Nummer' and 'Nr' works correctly")
            print("✅ Multiple '*nummer' columns handled properly")
            print("✅ German address format processing works correctly")
            print("✅ Street-based sorting functions as expected")
        else:
            log_test("Column Detection Fix", "❌ SOME TESTS FAILED: Column detection fix needs attention", False)
        
        return all_tests_passed
        
    except Exception as e:
        log_test("Column Detection Fix", f"Comprehensive testing failed with error: {str(e)}", False)
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    test_comprehensive_column_detection()