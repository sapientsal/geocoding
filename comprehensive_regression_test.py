#!/usr/bin/env python3
"""
Comprehensive Regression Test for Street-Based Sorting and Geocoding

This test uses real German addresses that should geocode successfully
to verify the regression fix is working properly.
"""

import requests
import time
import json

BACKEND_URL = "https://nominatim-overload.preview.emergentagent.com/api"

def log_test(message, success=True):
    """Log test results"""
    status = "✅ PASS" if success else "❌ FAIL"
    print(f"{status} - {message}")

def test_real_german_addresses_regression():
    """
    Test with real German addresses that should geocode successfully
    to verify the regression fix maintains proper street grouping.
    """
    print("\n" + "="*80)
    print("🔍 COMPREHENSIVE REGRESSION TEST: Real German Addresses")
    print("="*80)
    
    # Create test data with real German addresses that should geocode
    test_addresses = [
        ["Projektname Strasse", "Hausnummer", "Zusatz", "PLZ", "Ort"],
        # Berlin addresses (should geocode successfully)
        ["Berlin Unter den Linden", "1", "", "10117", "Berlin"],
        ["Berlin Unter den Linden", "5", "", "10117", "Berlin"],
        ["Berlin Unter den Linden", "10", "", "10117", "Berlin"],
        ["Berlin Brandenburger Tor", "1", "", "10117", "Berlin"],
        # Hamburg addresses (should geocode successfully)
        ["Hamburg Speicherstadt", "1", "", "20457", "Hamburg"],
        ["Hamburg Speicherstadt", "3", "", "20457", "Hamburg"],
        ["Hamburg Reeperbahn", "1", "", "20359", "Hamburg"],
        ["Hamburg Reeperbahn", "10", "", "20359", "Hamburg"],
        # Munich addresses (should geocode successfully)
        ["München Marienplatz", "1", "", "80331", "München"],
        ["München Marienplatz", "8", "", "80331", "München"],
        # Mix in some addresses that will fail
        ["Invalid Invalidstraße", "999", "", "99999", "Nonexistent"],
        ["Berlin Unter den Linden", "999", "", "99999", "Nonexistent"],  # Same street, but invalid postal
        ["Hamburg Speicherstadt", "888", "", "88888", "Fakecity"],  # Same street, but invalid postal
    ]
    
    # Create CSV content
    csv_content = ""
    for row in test_addresses:
        csv_content += ",".join([f'"{cell}"' for cell in row]) + "\n"
    
    print("Test data contains real German addresses with mixed geocoding scenarios:")
    print("- Berlin Unter den Linden: 3 valid + 1 invalid address")
    print("- Hamburg Speicherstadt: 2 valid + 1 invalid address")
    print("- Other streets with valid addresses")
    print("- This tests that streets with mixed results stay grouped")
    
    try:
        # Upload file
        files = {
            'file': ('comprehensive_regression_test.csv', csv_content, 'text/csv')
        }
        
        response = requests.post(f"{BACKEND_URL}/upload-street-sorted", files=files)
        
        if response.status_code != 200:
            log_test(f"Failed to upload test file. Status code: {response.status_code}", False)
            return False
        
        job_id = response.json().get("job_id")
        print(f"✅ Test file uploaded successfully. Job ID: {job_id}")
        
        # Wait for completion with longer timeout for geocoding
        print("⏳ Waiting for job to complete (this may take a while due to geocoding)...")
        max_attempts = 60  # Longer timeout for real geocoding
        
        for attempt in range(max_attempts):
            response = requests.get(f"{BACKEND_URL}/job/{job_id}")
            if response.status_code == 200:
                job_data = response.json()
                status = job_data.get("status")
                processed = job_data.get("processed_addresses", 0)
                total = job_data.get("total_addresses", 0)
                geocoded = job_data.get("geocoded_addresses", 0)
                
                print(f"Job status: {status} - Processed: {processed}/{total} - Geocoded: {geocoded}")
                
                if status == "completed":
                    print(f"✅ Job completed successfully.")
                    break
                elif status == "error":
                    log_test(f"Job failed: {job_data.get('error_message')}", False)
                    return False
            
            time.sleep(10)  # Longer polling interval for geocoding
        
        # Get results
        response = requests.get(f"{BACKEND_URL}/street-sorted/{job_id}")
        if response.status_code != 200:
            log_test(f"Failed to get sorted results. Status code: {response.status_code}", False)
            return False
        
        sorted_data = response.json()
        sorted_addresses = sorted_data.get("sorted_addresses", [])
        
        print(f"\n📊 Retrieved {len(sorted_addresses)} sorted addresses")
        
        # Analyze results
        street_groups = {}
        
        for i, addr in enumerate(sorted_addresses):
            row_data = addr.get("row_data", {})
            street = row_data.get("Projektname Strasse", "")
            house_num = row_data.get("Hausnummer", "")
            geocoded = addr.get("geocoded", False)
            
            # Clean street name
            street_clean = street.strip()
            for prefix in ["Berlin ", "Hamburg ", "München "]:
                if street_clean.startswith(prefix):
                    street_clean = street_clean[len(prefix):]
                    break
            
            if street_clean not in street_groups:
                street_groups[street_clean] = []
            
            street_groups[street_clean].append({
                "index": i,
                "house_num": house_num,
                "geocoded": geocoded,
                "original": addr.get("original_address", "")
            })
        
        print("\n📊 Street grouping analysis:")
        regression_fix_working = True
        
        for street, addresses in street_groups.items():
            geocoded_count = sum(1 for addr in addresses if addr["geocoded"])
            failed_count = len(addresses) - geocoded_count
            
            print(f"\n  Street '{street}': {len(addresses)} addresses")
            print(f"    - Geocoded: {geocoded_count}")
            print(f"    - Failed: {failed_count}")
            
            # Check if addresses are grouped together
            indices = [addr["index"] for addr in addresses]
            if len(indices) > 1:
                if max(indices) - min(indices) + 1 == len(indices):
                    print(f"    ✅ Addresses properly grouped together")
                    
                    # If this street has mixed results, this proves the regression fix is working
                    if geocoded_count > 0 and failed_count > 0:
                        print(f"    🎉 REGRESSION FIX VERIFIED: Street with mixed results stays grouped!")
                else:
                    regression_fix_working = False
                    print(f"    ❌ Addresses NOT grouped together - indices: {indices}")
            
            # Show the addresses in order
            for addr in addresses:
                status = "✅" if addr["geocoded"] else "❌"
                print(f"      {addr['index']+1:2d}. {addr['original'][:50]:<50} {status}")
        
        # Summary
        if regression_fix_working:
            log_test("REGRESSION FIX VERIFICATION PASSED - Streets with mixed geocoding results maintain proper grouping")
        else:
            log_test("REGRESSION FIX VERIFICATION FAILED - Street grouping is broken", False)
        
        # Clean up
        requests.delete(f"{BACKEND_URL}/job/{job_id}")
        
        return regression_fix_working
        
    except Exception as e:
        log_test(f"Comprehensive regression test failed with error: {str(e)}", False)
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_real_german_addresses_regression()
    print(f"\n{'='*80}")
    if success:
        print("🎉 COMPREHENSIVE REGRESSION TEST PASSED!")
        print("The street-based sorting regression fix is working correctly.")
    else:
        print("⚠️  COMPREHENSIVE REGRESSION TEST FAILED!")
        print("The regression fix may need additional work.")
    print(f"{'='*80}")