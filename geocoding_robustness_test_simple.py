#!/usr/bin/env python3
import requests
import time
import csv
import os
import io
import json
import random
from datetime import datetime

# Get backend URL from frontend/.env
BACKEND_URL = "https://95a8d55d-d4d3-4544-aea7-981b1e115401.preview.emergentagent.com/api"

def create_test_csv_with_mixed_addresses(num_valid=15, num_invalid=5):
    """Create a test CSV file with a mix of valid and invalid addresses"""
    print(f"\n🔍 Creating test CSV with {num_valid} valid and {num_invalid} invalid addresses...")
    
    # Valid addresses for testing
    valid_addresses = [
        # US addresses
        "1600 Pennsylvania Avenue NW, Washington, DC 20500",  # White House
        "350 Fifth Avenue, New York, NY 10118",               # Empire State Building
        "1 Infinite Loop, Cupertino, CA 95014",               # Apple HQ
        "1600 Amphitheatre Parkway, Mountain View, CA 94043", # Google HQ
        "2800 E Observatory Rd, Los Angeles, CA 90027",       # Griffith Observatory
        
        # German addresses
        "Brandenburger Tor, 10117 Berlin, Germany",
        "Marienplatz 8, 80331 München, Germany",
        "Kölner Dom, 50667 Köln, Germany",
        "Am Hörenberg 8, 27726 Worpswede, Germany",
        "Hembergerstraße 29 A, 27726 Worpswede, Germany"
    ]
    
    # Invalid addresses for testing
    invalid_addresses = [
        "123 Nonexistent Street, Faketown, XY 99999",
        "456 Invalid Avenue, Nowhere Land, ZZ 00000",
        "789 Made Up Road, Imaginary City, QQ 11111",
        "Fehlerstraße 404, 00000 Nichtexistiert, Germany",
        "Ungültige Straße 123, 99999 Fantasiestadt, Germany"
    ]
    
    # Create a list of addresses with more valid than invalid
    addresses = []
    
    # Add valid addresses (with repetition if needed)
    for i in range(num_valid):
        addresses.append(random.choice(valid_addresses))
    
    # Add invalid addresses (with repetition if needed)
    for i in range(num_invalid):
        addresses.append(random.choice(invalid_addresses))
    
    # Shuffle the addresses to mix valid and invalid
    random.shuffle(addresses)
    
    # Create CSV in memory
    csv_file = io.StringIO()
    writer = csv.writer(csv_file)
    writer.writerow(["Address"])  # Header
    for address in addresses:
        writer.writerow([address])
    
    csv_content = csv_file.getvalue()
    print(f"Created CSV with {len(addresses)} addresses ({num_valid} valid, {num_invalid} invalid)")
    return csv_content

def test_geocoding_robustness():
    """Test the enhanced geocoding function with retry logic and exponential backoff"""
    print("\n🔍 Testing Enhanced Geocoding Robustness...")
    
    # Create test CSV with mixed valid and invalid addresses
    csv_content = create_test_csv_with_mixed_addresses(15, 5)
    
    try:
        # Create file-like object for upload
        files = {
            'file': ('mixed_addresses.csv', csv_content, 'text/csv')
        }
        
        # Upload file
        print("Uploading file with mixed addresses...")
        response = requests.post(f"{BACKEND_URL}/upload", files=files)
        
        if response.status_code == 200:
            job_id = response.json().get("job_id")
            print(f"✅ File uploaded successfully. Job ID: {job_id}")
            
            # Monitor job progress with detailed statistics
            max_attempts = 30
            polling_interval = 5
            
            print("\nMonitoring job progress with detailed statistics...")
            for attempt in range(max_attempts):
                print(f"Polling job status (attempt {attempt+1}/{max_attempts})...")
                response = requests.get(f"{BACKEND_URL}/job/{job_id}")
                
                if response.status_code != 200:
                    print(f"❌ Failed to get job status. Status code: {response.status_code}")
                    return False
                
                job_data = response.json()
                status = job_data.get("status")
                
                # Calculate progress percentage
                total = job_data.get("total_addresses", 0)
                processed = job_data.get("processed_addresses", 0)
                geocoded = job_data.get("geocoded_addresses", 0)
                
                progress_percentage = (processed / total * 100) if total > 0 else 0
                success_rate = (geocoded / processed * 100) if processed > 0 else 0
                
                print(f"Status: {status}")
                print(f"Progress: {processed}/{total} ({progress_percentage:.1f}%)")
                print(f"Geocoded: {geocoded}/{processed} ({success_rate:.1f}% success rate)")
                
                # Check if job is completed or failed
                if status == "completed":
                    print(f"✅ Job completed successfully after {attempt+1} polling attempts.")
                    
                    # Verify the results
                    response = requests.get(f"{BACKEND_URL}/route/{job_id}")
                    if response.status_code == 200:
                        route_data = response.json()
                        addresses = route_data.get("addresses", [])
                        
                        # Count successful and failed geocoding
                        geocoded_count = sum(1 for addr in addresses if addr.get("geocoded", False))
                        failed_count = sum(1 for addr in addresses if not addr.get("geocoded", False))
                        
                        print(f"\nResults:")
                        print(f"Total addresses: {len(addresses)}")
                        print(f"Successfully geocoded: {geocoded_count} ({geocoded_count/len(addresses)*100:.1f}%)")
                        print(f"Failed to geocode: {failed_count} ({failed_count/len(addresses)*100:.1f}%)")
                        
                        # Check if we have a reasonable success rate (should be around 75% given our test data)
                        if geocoded_count >= len(addresses) * 0.7:
                            print("✅ Geocoding success rate is reasonable (>= 70%)")
                            
                            # Check for error handling in failed addresses
                            if failed_count > 0:
                                print("\nSample of failed addresses with error messages:")
                                failed_addresses = [addr for addr in addresses if not addr.get("geocoded", False)]
                                for i, addr in enumerate(failed_addresses[:3]):  # Show up to 3 examples
                                    print(f"{i+1}. '{addr.get('original_address')}' - Error: {addr.get('geocoding_error')}")
                                
                                # Verify that error messages are present
                                if all(addr.get("geocoding_error") for addr in failed_addresses):
                                    print("✅ Error messages are properly recorded for failed addresses")
                                else:
                                    print("❌ Some failed addresses are missing error messages")
                            
                            return True
                        else:
                            print(f"❌ Geocoding success rate is too low: {geocoded_count/len(addresses)*100:.1f}%")
                            return False
                    else:
                        print(f"❌ Failed to get route data. Status code: {response.status_code}")
                        return False
                
                elif status == "error":
                    print(f"❌ Job failed with error: {job_data.get('error_message')}")
                    return False
                
                # Wait before next polling attempt
                time.sleep(polling_interval)
            
            print(f"❌ Job did not complete within the expected time ({max_attempts * polling_interval} seconds)")
            return False
        else:
            print(f"❌ File upload failed with status code: {response.status_code}")
            print(f"Response: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Test failed with error: {str(e)}")
        return False

def test_batch_processing():
    """Test batch processing with a smaller dataset"""
    print("\n🔍 Testing Batch Processing...")
    
    # Create a dataset with 50 addresses (batch size)
    csv_content = create_test_csv_with_mixed_addresses(40, 10)
    
    try:
        # Create file-like object for upload
        files = {
            'file': ('batch_test.csv', csv_content, 'text/csv')
        }
        
        # Upload file
        print("Uploading batch test file...")
        start_time = time.time()
        response = requests.post(f"{BACKEND_URL}/upload", files=files)
        
        if response.status_code == 200:
            job_id = response.json().get("job_id")
            print(f"✅ Batch test file uploaded successfully. Job ID: {job_id}")
            
            # Monitor processing
            max_attempts = 30
            polling_interval = 5
            
            print("\nMonitoring batch processing progress...")
            last_processed = 0
            
            for attempt in range(max_attempts):
                print(f"Polling job status (attempt {attempt+1}/{max_attempts})...")
                response = requests.get(f"{BACKEND_URL}/job/{job_id}")
                
                if response.status_code != 200:
                    print(f"❌ Failed to get job status. Status code: {response.status_code}")
                    return False
                
                job_data = response.json()
                status = job_data.get("status")
                
                # Calculate progress statistics
                total = job_data.get("total_addresses", 0)
                processed = job_data.get("processed_addresses", 0)
                geocoded = job_data.get("geocoded_addresses", 0)
                
                # Calculate processing rate
                if attempt > 0:
                    addresses_since_last_check = processed - last_processed
                    if addresses_since_last_check > 0:
                        print(f"Processed {addresses_since_last_check} addresses since last check")
                
                last_processed = processed
                
                progress_percentage = (processed / total * 100) if total > 0 else 0
                success_rate = (geocoded / processed * 100) if processed > 0 else 0
                
                print(f"Status: {status}")
                print(f"Progress: {processed}/{total} ({progress_percentage:.1f}%)")
                print(f"Geocoded: {geocoded}/{processed} ({success_rate:.1f}% success rate)")
                
                # Check if job is completed or failed
                if status == "completed":
                    elapsed_time = time.time() - start_time
                    print(f"✅ Job completed successfully in {elapsed_time:.1f} seconds")
                    
                    # Verify the results
                    response = requests.get(f"{BACKEND_URL}/route/{job_id}")
                    if response.status_code == 200:
                        route_data = response.json()
                        addresses = route_data.get("addresses", [])
                        
                        # Verify that all addresses were processed
                        if len(addresses) == total:
                            print(f"✅ All {total} addresses were processed")
                            return True
                        else:
                            print(f"❌ Not all addresses were processed. Expected: {total}, Actual: {len(addresses)}")
                            return False
                    else:
                        print(f"❌ Failed to get route data. Status code: {response.status_code}")
                        return False
                
                elif status == "error":
                    print(f"❌ Job failed with error: {job_data.get('error_message')}")
                    return False
                
                # Wait before next polling attempt
                time.sleep(polling_interval)
            
            print(f"❌ Job did not complete within the expected time ({max_attempts * polling_interval} seconds)")
            return False
        else:
            print(f"❌ File upload failed with status code: {response.status_code}")
            print(f"Response: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Test failed with error: {str(e)}")
        return False

def test_job_status_details():
    """Test enhanced job status information"""
    print("\n🔍 Testing Enhanced Job Status Information...")
    
    # Create test CSV with mixed valid and invalid addresses
    csv_content = create_test_csv_with_mixed_addresses(15, 5)
    
    try:
        # Create file-like object for upload
        files = {
            'file': ('status_test.csv', csv_content, 'text/csv')
        }
        
        # Upload file
        print("Uploading file for status testing...")
        response = requests.post(f"{BACKEND_URL}/upload", files=files)
        
        if response.status_code == 200:
            job_id = response.json().get("job_id")
            print(f"✅ File uploaded successfully. Job ID: {job_id}")
            
            # Check for enhanced status information
            print("\nChecking for enhanced status information...")
            time.sleep(5)  # Wait a bit for processing to start
            
            response = requests.get(f"{BACKEND_URL}/job/{job_id}")
            
            if response.status_code != 200:
                print(f"❌ Failed to get job status. Status code: {response.status_code}")
                return False
            
            job_data = response.json()
            
            # Check for required status fields
            required_fields = ["status", "total_addresses", "processed_addresses", "geocoded_addresses"]
            missing_fields = [field for field in required_fields if field not in job_data]
            
            if missing_fields:
                print(f"❌ Job status is missing required fields: {', '.join(missing_fields)}")
                return False
            
            print("✅ Job status contains all required fields")
            
            # Calculate and display derived metrics
            total = job_data.get("total_addresses", 0)
            processed = job_data.get("processed_addresses", 0)
            geocoded = job_data.get("geocoded_addresses", 0)
            
            progress_percentage = (processed / total * 100) if total > 0 else 0
            success_rate = (geocoded / processed * 100) if processed > 0 else 0
            
            print(f"Progress percentage: {progress_percentage:.1f}%")
            print(f"Success rate: {success_rate:.1f}%")
            
            # Wait for job to complete to check final status
            max_attempts = 30
            polling_interval = 5
            
            for attempt in range(max_attempts):
                print(f"Polling job status (attempt {attempt+1}/{max_attempts})...")
                response = requests.get(f"{BACKEND_URL}/job/{job_id}")
                
                if response.status_code != 200:
                    print(f"❌ Failed to get job status. Status code: {response.status_code}")
                    return False
                
                job_data = response.json()
                status = job_data.get("status")
                
                if status == "completed":
                    print(f"✅ Job completed successfully")
                    
                    # Check final status information
                    final_processed = job_data.get("processed_addresses", 0)
                    final_geocoded = job_data.get("geocoded_addresses", 0)
                    final_success_rate = (final_geocoded / final_processed * 100) if final_processed > 0 else 0
                    
                    print(f"Final status:")
                    print(f"Total addresses: {job_data.get('total_addresses')}")
                    print(f"Processed addresses: {final_processed}")
                    print(f"Geocoded addresses: {final_geocoded}")
                    print(f"Success rate: {final_success_rate:.1f}%")
                    
                    # Verify that the success rate is reasonable
                    if 65 <= final_success_rate <= 100:
                        print("✅ Final success rate is reasonable")
                        return True
                    else:
                        print(f"❌ Final success rate is outside expected range: {final_success_rate:.1f}%")
                        return False
                
                elif status == "error":
                    print(f"❌ Job failed with error: {job_data.get('error_message')}")
                    return False
                
                # Wait before next polling attempt
                time.sleep(polling_interval)
            
            print(f"❌ Job did not complete within the expected time")
            return False
        else:
            print(f"❌ File upload failed with status code: {response.status_code}")
            print(f"Response: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Test failed with error: {str(e)}")
        return False

def run_all_tests():
    """Run all geocoding robustness tests"""
    print("\n🚀 Starting Enhanced Geocoding Robustness Tests")
    print("=" * 80)
    
    # Test results
    results = {
        "Geocoding Robustness": test_geocoding_robustness(),
        "Batch Processing": test_batch_processing(),
        "Job Status Details": test_job_status_details()
    }
    
    # Print summary
    print("\n" + "=" * 80)
    print("📊 Test Summary:")
    print("=" * 80)
    
    all_passed = True
    for test_name, result in results.items():
        status = "PASSED" if result else "FAILED"
        if not result:
            all_passed = False
        print(f"{'✅' if result else '❌'} {test_name}: {status}")
    
    print("=" * 80)
    print(f"Overall result: {'✅ ALL TESTS PASSED' if all_passed else '❌ SOME TESTS FAILED'}")
    print("=" * 80)

if __name__ == "__main__":
    run_all_tests()