#!/usr/bin/env python3
"""
Regression Test for Street-Based Sorting and Geocoding Functionality

This test specifically addresses the user-reported regression where:
1. Addresses are no longer being geocoded correctly
2. Street-based sorting is broken
3. House number sorting within streets is not working

The regression was caused by the Manual Review Interface fix that introduced
flawed logic in optimize_geographic_route() function.
"""

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

def log_test(message, success=True):
    """Log test results"""
    status = "✅ PASS" if success else "❌ FAIL"
    print(f"{status} - {message}")

def test_street_based_sorting_regression():
    """
    Test the regression fix for street-based sorting and geocoding functionality.
    
    This test verifies:
    1. Street-based sorting with mixed geocoding results (some successful, some failed)
    2. Addresses from the same street remain grouped together
    3. House numbers within each street are sorted numerically
    4. Failed addresses within a street don't cause the entire street to be separated
    """
    print("\n" + "="*80)
    print("🔍 REGRESSION TEST: Street-Based Sorting and Geocoding Functionality")
    print("="*80)
    print("Testing the fix for the user-reported regression where addresses were")
    print("no longer being geocoded correctly and street-based sorting was broken.")
    print("="*80)
    
    try:
        # Test 1: Street-Based Sorting with Mixed Results
        print("\n📋 TEST 1: Street-Based Sorting with Mixed Geocoding Results")
        print("-" * 60)
        
        # Load the regression test file
        with open('/app/street_sorting_regression_test.csv', 'r') as f:
            csv_content = f.read()
        
        print("Test data contains addresses from multiple streets with some that will fail geocoding:")
        print("- Bergstraße: 10, 10A, 12, 14, 16 (mostly valid)")
        print("- Am Hörenberg: 1A, 3A, 3C, 4, 7, 8, 10 (mostly valid)")
        print("- Hembergerstraße: 29A, 31 (valid)")
        print("- Auf der Heide: 49, 51 (valid)")
        print("- Invalid streets: Invalidstraße, Fakestraße, Teststraße (will fail)")
        
        # Upload file to street-sorted endpoint
        files = {
            'file': ('street_sorting_regression_test.csv', csv_content, 'text/csv')
        }
        
        response = requests.post(f"{BACKEND_URL}/upload-street-sorted", files=files)
        
        if response.status_code != 200:
            log_test(f"Failed to upload regression test file. Status code: {response.status_code}", False)
            return False
        
        job_id = response.json().get("job_id")
        print(f"✅ Test file uploaded successfully. Job ID: {job_id}")
        
        # Wait for job to complete
        print("⏳ Waiting for job to complete...")
        max_attempts = 30
        polling_interval = 5
        
        for attempt in range(max_attempts):
            response = requests.get(f"{BACKEND_URL}/job/{job_id}")
            
            if response.status_code != 200:
                log_test(f"Failed to get job status. Status code: {response.status_code}", False)
                return False
            
            job_data = response.json()
            status = job_data.get("status")
            
            print(f"Job status: {status} - Processed: {job_data.get('processed_addresses')}/{job_data.get('total_addresses')}")
            
            if status == "completed":
                print(f"✅ Job completed successfully.")
                break
            elif status == "error":
                log_test(f"Job failed with error: {job_data.get('error_message')}", False)
                return False
            
            time.sleep(polling_interval)
        
        # Get the sorted results
        print("\n📊 Analyzing sorted results...")
        response = requests.get(f"{BACKEND_URL}/street-sorted/{job_id}")
        
        if response.status_code != 200:
            log_test(f"Failed to get street-sorted data. Status code: {response.status_code}", False)
            return False
        
        sorted_data = response.json()
        sorted_addresses = sorted_data.get("sorted_addresses", [])
        
        if not sorted_addresses:
            log_test("No sorted addresses found in response", False)
            return False
        
        print(f"Retrieved {len(sorted_addresses)} sorted addresses")
        
        # Analyze the sorting results
        street_groups = {}
        address_order = []
        
        for i, addr in enumerate(sorted_addresses):
            row_data = addr.get("row_data", {})
            street = row_data.get("Projektname Strasse", "")
            house_num = row_data.get("Hausnummer", "")
            zusatz = row_data.get("Zusatz", "")
            geocoded = addr.get("geocoded", False)
            
            # Clean street name (remove project prefix)
            street_clean = street.replace("624 Worpswede ", "").strip()
            
            if street_clean not in street_groups:
                street_groups[street_clean] = []
            
            house_display = f"{house_num}{zusatz}" if zusatz else house_num
            
            street_groups[street_clean].append({
                "index": i,
                "house_num": house_num,
                "zusatz": zusatz,
                "house_display": house_display,
                "geocoded": geocoded,
                "original_address": addr.get("original_address", "")
            })
            
            address_order.append({
                "street": street_clean,
                "house_display": house_display,
                "geocoded": geocoded,
                "index": i
            })
        
        # Print the actual sorting results
        print("\n📊 Actual sorting results:")
        for addr in address_order:
            status_icon = "✅" if addr["geocoded"] else "❌"
            print(f"  {addr['index']+1:2d}. {addr['street']:<20} {addr['house_display']:<5} {status_icon}")
        
        # Test 1.1: Verify streets are grouped together
        print("\n🔍 TEST 1.1: Verifying street grouping...")
        street_grouping_correct = True
        
        for street, addresses in street_groups.items():
            if len(addresses) <= 1:
                continue
            
            indices = [addr["index"] for addr in addresses]
            min_idx, max_idx = min(indices), max(indices)
            
            # Check if all indices are consecutive
            if max_idx - min_idx + 1 != len(indices):
                street_grouping_correct = False
                log_test(f"Street '{street}' addresses are not grouped together. Indices: {indices}", False)
            else:
                # Check for mixed geocoding results within the street
                geocoded_count = sum(1 for addr in addresses if addr["geocoded"])
                failed_count = len(addresses) - geocoded_count
                
                if failed_count > 0:
                    print(f"  ✅ Street '{street}': {len(addresses)} addresses grouped together ({geocoded_count} geocoded, {failed_count} failed)")
                else:
                    print(f"  ✅ Street '{street}': {len(addresses)} addresses grouped together (all geocoded)")
        
        if street_grouping_correct:
            log_test("Street grouping test PASSED - All streets are properly grouped together despite mixed geocoding results")
        
        # Test 1.2: Verify house number sorting within streets
        print("\n🔍 TEST 1.2: Verifying house number sorting within streets...")
        house_sorting_correct = True
        
        for street, addresses in street_groups.items():
            if len(addresses) <= 1:
                continue
            
            # Extract house numbers in order
            house_numbers = []
            for addr in addresses:
                try:
                    num = int(addr["house_num"])
                    # Add decimal for letter suffixes to maintain proper order
                    if addr["zusatz"]:
                        if addr["zusatz"] == "A":
                            num += 0.1
                        elif addr["zusatz"] == "B":
                            num += 0.2
                        elif addr["zusatz"] == "C":
                            num += 0.3
                    house_numbers.append(num)
                except (ValueError, TypeError):
                    house_numbers.append(0)
            
            # Check if sorted
            if house_numbers != sorted(house_numbers):
                house_sorting_correct = False
                house_displays = [addr["house_display"] for addr in addresses]
                log_test(f"House numbers for '{street}' are not properly sorted. Found: {house_displays}", False)
            else:
                house_displays = [addr["house_display"] for addr in addresses]
                print(f"  ✅ Street '{street}': House numbers properly sorted: {house_displays}")
        
        if house_sorting_correct:
            log_test("House number sorting test PASSED - House numbers within each street are sorted numerically")
        
        # Test 1.3: Verify failed addresses don't break street grouping
        print("\n🔍 TEST 1.3: Verifying failed addresses don't break street grouping...")
        mixed_results_handled = True
        
        for street, addresses in street_groups.items():
            geocoded_count = sum(1 for addr in addresses if addr["geocoded"])
            failed_count = len(addresses) - geocoded_count
            
            if failed_count > 0 and geocoded_count > 0:
                # This street has mixed results - verify they're still grouped
                indices = [addr["index"] for addr in addresses]
                if max(indices) - min(indices) + 1 == len(indices):
                    print(f"  ✅ Street '{street}': Mixed results properly handled ({geocoded_count} success, {failed_count} failed)")
                else:
                    mixed_results_handled = False
                    log_test(f"Street '{street}' with mixed results is not properly grouped", False)
        
        if mixed_results_handled:
            log_test("Mixed geocoding results test PASSED - Failed addresses within streets don't break grouping")
        
        # Clean up
        requests.delete(f"{BACKEND_URL}/job/{job_id}")
        
        return street_grouping_correct and house_sorting_correct and mixed_results_handled
        
    except Exception as e:
        log_test(f"Street-based sorting regression test failed with error: {str(e)}", False)
        import traceback
        traceback.print_exc()
        return False

def test_mixed_geocoding_scenarios():
    """
    Test specific mixed success/failure geocoding scenarios.
    
    This test verifies that streets with some successful and some failed
    addresses maintain proper grouping and sorting.
    """
    print("\n" + "="*80)
    print("🔍 TEST 2: Mixed Success/Failure Geocoding Scenarios")
    print("="*80)
    
    try:
        # Load the mixed geocoding test file
        with open('/app/mixed_geocoding_test.csv', 'r') as f:
            csv_content = f.read()
        
        print("Test data contains streets with intentionally mixed geocoding results:")
        print("- Each street has both valid and invalid addresses")
        print("- Invalid addresses use postal code 99999 and city 'Nonexistent'")
        print("- This tests the regression fix for mixed success/failure scenarios")
        
        # Upload file
        files = {
            'file': ('mixed_geocoding_test.csv', csv_content, 'text/csv')
        }
        
        response = requests.post(f"{BACKEND_URL}/upload-street-sorted", files=files)
        
        if response.status_code != 200:
            log_test(f"Failed to upload mixed geocoding test file. Status code: {response.status_code}", False)
            return False
        
        job_id = response.json().get("job_id")
        print(f"✅ Mixed geocoding test file uploaded. Job ID: {job_id}")
        
        # Wait for completion
        for attempt in range(30):
            response = requests.get(f"{BACKEND_URL}/job/{job_id}")
            if response.status_code == 200:
                job_data = response.json()
                if job_data.get("status") == "completed":
                    break
                elif job_data.get("status") == "error":
                    log_test(f"Job failed: {job_data.get('error_message')}", False)
                    return False
            time.sleep(5)
        
        # Analyze results
        response = requests.get(f"{BACKEND_URL}/street-sorted/{job_id}")
        if response.status_code != 200:
            log_test(f"Failed to get sorted results. Status code: {response.status_code}", False)
            return False
        
        sorted_data = response.json()
        sorted_addresses = sorted_data.get("sorted_addresses", [])
        
        # Group by street and analyze mixed results
        street_analysis = {}
        
        for addr in sorted_addresses:
            row_data = addr.get("row_data", {})
            street = row_data.get("Projektname Strasse", "").replace("624 Worpswede ", "").strip()
            geocoded = addr.get("geocoded", False)
            
            if street not in street_analysis:
                street_analysis[street] = {"total": 0, "geocoded": 0, "failed": 0, "addresses": []}
            
            street_analysis[street]["total"] += 1
            if geocoded:
                street_analysis[street]["geocoded"] += 1
            else:
                street_analysis[street]["failed"] += 1
            
            street_analysis[street]["addresses"].append({
                "house": row_data.get("Hausnummer", ""),
                "geocoded": geocoded
            })
        
        print("\n📊 Mixed geocoding analysis:")
        mixed_handling_correct = True
        
        for street, data in street_analysis.items():
            if data["failed"] > 0 and data["geocoded"] > 0:
                print(f"  Street '{street}': {data['geocoded']} geocoded, {data['failed']} failed")
                
                # Verify addresses are still grouped together
                street_indices = []
                for i, addr in enumerate(sorted_addresses):
                    row_data = addr.get("row_data", {})
                    addr_street = row_data.get("Projektname Strasse", "").replace("624 Worpswede ", "").strip()
                    if addr_street == street:
                        street_indices.append(i)
                
                # Check if indices are consecutive
                if len(street_indices) > 1:
                    if max(street_indices) - min(street_indices) + 1 == len(street_indices):
                        print(f"    ✅ Addresses properly grouped despite mixed results")
                    else:
                        mixed_handling_correct = False
                        log_test(f"Street '{street}' with mixed results is not properly grouped", False)
        
        if mixed_handling_correct:
            log_test("Mixed geocoding scenarios test PASSED - Streets with mixed results maintain proper grouping")
        
        # Clean up
        requests.delete(f"{BACKEND_URL}/job/{job_id}")
        
        return mixed_handling_correct
        
    except Exception as e:
        log_test(f"Mixed geocoding scenarios test failed with error: {str(e)}", False)
        return False

def test_german_address_format_processing():
    """
    Test German address format processing with the specific format mentioned in the review.
    
    Tests addresses with format: "Projektname Strasse", "Hausnummer", "PLZ", "Ort"
    """
    print("\n" + "="*80)
    print("🔍 TEST 3: German Address Format Processing")
    print("="*80)
    
    try:
        # Create test data with the exact format mentioned in the review
        test_addresses = [
            ["Projektname Strasse", "Hausnummer", "Zusatz", "PLZ", "Ort"],
            ["624 Worpswede Bergstraße", "10", "", "27726", "Worpswede"],
            ["624 Worpswede Bergstraße", "12", "", "27726", "Worpswede"],
            ["624 Worpswede Bergstraße", "14", "", "27726", "Worpswede"],
            ["624 Worpswede Bergstraße", "10", "A", "27726", "Worpswede"],
            ["624 Worpswede Bergstraße", "10", "B", "27726", "Worpswede"],
            ["624 Worpswede Am Hörenberg", "8", "", "27726", "Worpswede"],
            ["624 Worpswede Am Hörenberg", "10", "", "27726", "Worpswede"],
        ]
        
        # Create CSV content
        csv_content = ""
        for row in test_addresses:
            csv_content += ",".join([f'"{cell}"' for cell in row]) + "\n"
        
        print("Test data uses the exact German address format:")
        print("- 'Projektname Strasse' column with project code and city prefix")
        print("- 'Hausnummer' column with house numbers")
        print("- 'Zusatz' column with letter suffixes (A, B, etc.)")
        print("- 'PLZ' and 'Ort' columns for postal code and city")
        
        # Upload file
        files = {
            'file': ('german_format_test.csv', csv_content, 'text/csv')
        }
        
        response = requests.post(f"{BACKEND_URL}/upload-street-sorted", files=files)
        
        if response.status_code != 200:
            log_test(f"Failed to upload German format test file. Status code: {response.status_code}", False)
            return False
        
        job_id = response.json().get("job_id")
        print(f"✅ German format test file uploaded. Job ID: {job_id}")
        
        # Wait for completion
        for attempt in range(30):
            response = requests.get(f"{BACKEND_URL}/job/{job_id}")
            if response.status_code == 200:
                job_data = response.json()
                if job_data.get("status") == "completed":
                    break
                elif job_data.get("status") == "error":
                    log_test(f"Job failed: {job_data.get('error_message')}", False)
                    return False
            time.sleep(5)
        
        # Analyze address combination and geocoding
        response = requests.get(f"{BACKEND_URL}/street-sorted/{job_id}")
        if response.status_code != 200:
            log_test(f"Failed to get sorted results. Status code: {response.status_code}", False)
            return False
        
        sorted_data = response.json()
        sorted_addresses = sorted_data.get("sorted_addresses", [])
        
        print("\n📊 German address format processing results:")
        format_processing_correct = True
        
        for addr in sorted_addresses:
            original = addr.get("original_address", "")
            geocoded = addr.get("geocoded", False)
            row_data = addr.get("row_data", {})
            
            # Check if address was properly combined
            expected_parts = [
                "Bergstraße" in original or "Am Hörenberg" in original,
                "27726" in original,
                "Worpswede" in original
            ]
            
            if all(expected_parts):
                status = "✅ Geocoded" if geocoded else "❌ Failed"
                print(f"  {status}: {original}")
            else:
                format_processing_correct = False
                log_test(f"Address not properly combined: {original}", False)
        
        # Test house number extraction and sorting
        bergstrasse_addresses = []
        for addr in sorted_addresses:
            row_data = addr.get("row_data", {})
            street = row_data.get("Projektname Strasse", "")
            if "Bergstraße" in street:
                house_num = row_data.get("Hausnummer", "")
                zusatz = row_data.get("Zusatz", "")
                house_display = f"{house_num}{zusatz}" if zusatz else house_num
                bergstrasse_addresses.append(house_display)
        
        expected_order = ["10", "10A", "10B", "12", "14"]
        if bergstrasse_addresses == expected_order:
            log_test("House number extraction and sorting PASSED - Bergstraße addresses in correct order: " + str(bergstrasse_addresses))
        else:
            format_processing_correct = False
            log_test(f"House number sorting incorrect. Expected: {expected_order}, Got: {bergstrasse_addresses}", False)
        
        if format_processing_correct:
            log_test("German address format processing test PASSED - Addresses properly combined and sorted")
        
        # Clean up
        requests.delete(f"{BACKEND_URL}/job/{job_id}")
        
        return format_processing_correct
        
    except Exception as e:
        log_test(f"German address format processing test failed with error: {str(e)}", False)
        return False

def run_regression_tests():
    """Run all regression tests for the street-based sorting fix"""
    print("\n" + "="*100)
    print("🚀 RUNNING REGRESSION TESTS FOR STREET-BASED SORTING AND GEOCODING FIX")
    print("="*100)
    print("These tests verify that the regression fix restores proper functionality:")
    print("1. Street-based sorting with mixed geocoding results")
    print("2. Mixed success/failure geocoding scenarios")
    print("3. German address format processing")
    print("="*100)
    
    results = {
        "street_sorting_regression": False,
        "mixed_geocoding": False,
        "german_format": False
    }
    
    # Run all tests
    results["street_sorting_regression"] = test_street_based_sorting_regression()
    results["mixed_geocoding"] = test_mixed_geocoding_scenarios()
    results["german_format"] = test_german_address_format_processing()
    
    # Summary
    print("\n" + "="*100)
    print("📊 REGRESSION TEST RESULTS SUMMARY")
    print("="*100)
    
    passed_tests = sum(1 for result in results.values() if result)
    total_tests = len(results)
    
    for test_name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{status} - {test_name.replace('_', ' ').title()}")
    
    print(f"\nOverall Result: {passed_tests}/{total_tests} tests passed")
    
    if passed_tests == total_tests:
        print("🎉 ALL REGRESSION TESTS PASSED - The street-based sorting fix is working correctly!")
        return True
    else:
        print("⚠️  SOME REGRESSION TESTS FAILED - The fix may need additional work")
        return False

if __name__ == "__main__":
    success = run_regression_tests()
    exit(0 if success else 1)