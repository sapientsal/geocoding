#!/usr/bin/env python3
import requests
import time
import json
import os
import io
import csv
from datetime import datetime

# Get backend URL from frontend/.env
BACKEND_URL = "https://salespath-5.preview.emergentagent.com/api"

def test_enhanced_geocoding_robustness():
    """Test the enhanced geocoding robustness features"""
    print("\n🔍 Testing Enhanced Geocoding Robustness...")
    
    # Read the test file with a mix of valid and invalid addresses
    with open('/app/test_geocoding_robustness.csv', 'r') as f:
        csv_content = f.read()
    
    print(f"Loaded test file with addresses for robustness testing")
    
    # Create file-like object for upload
    files = {
        'file': ('test_geocoding_robustness.csv', csv_content, 'text/csv')
    }
    
    # Upload file
    print("Uploading file to test batch processing and error handling...")
    response = requests.post(f"{BACKEND_URL}/upload", files=files)
    
    if response.status_code != 200:
        print(f"❌ File upload failed with status code: {response.status_code}")
        print(f"Response: {response.text}")
        return None
    
    job_id = response.json().get("job_id")
    print(f"✅ File uploaded successfully. Job ID: {job_id}")
    
    # Monitor job progress with detailed logging
    max_attempts = 60  # Increased for large dataset
    polling_interval = 5
    consecutive_same_progress = 0
    last_processed = 0
    
    print("\nMonitoring job progress and checking for hanging issues...")
    for attempt in range(max_attempts):
        print(f"Polling job status (attempt {attempt+1}/{max_attempts})...")
        
        # Get job status
        response = requests.get(f"{BACKEND_URL}/job/{job_id}")
        
        if response.status_code != 200:
            print(f"❌ Failed to get job status. Status code: {response.status_code}")
            return None
        
        job_data = response.json()
        status = job_data.get("status")
        processed = job_data.get("processed_addresses", 0)
        geocoded = job_data.get("geocoded_addresses", 0)
        failed = job_data.get("failed_addresses", 0)
        total = job_data.get("total_addresses", 0)
        progress_message = job_data.get("progress_message", "")
        
        # Check for progress
        if processed == last_processed:
            consecutive_same_progress += 1
        else:
            consecutive_same_progress = 0
        
        last_processed = processed
        
        # Print detailed progress information
        print(f"Status: {status}")
        print(f"Processed: {processed}/{total} addresses ({job_data.get('progress_percentage', 0)}%)")
        print(f"Geocoded: {geocoded}, Failed: {failed}")
        if progress_message:
            print(f"Progress message: {progress_message}")
        
        # Check for hanging (no progress for 5 consecutive polls)
        if consecutive_same_progress >= 5 and processed > 0 and processed < total and status == "geocoding":
            print(f"⚠️ Possible hanging detected at address {processed}. Checking logs...")
            
            # Check logs to see what's happening
            logs_response = requests.get(f"{BACKEND_URL}/job/{job_id}/logs")
            if logs_response.status_code == 200:
                logs = logs_response.json().get("logs", [])
                if logs:
                    recent_logs = logs[-5:]  # Get 5 most recent logs
                    print("\nRecent logs:")
                    for log in recent_logs:
                        print(f"[{log.get('level')}] {log.get('message')} - Address: {log.get('address')}")
            
            # Continue monitoring to see if circuit breaker kicks in
        
        # Check if job is completed or failed
        if status == "completed":
            print(f"✅ Job completed successfully. Processed {processed}/{total} addresses.")
            print(f"Geocoded: {geocoded}, Failed: {failed}")
            
            # Verify the job didn't hang at addresses 1941 or 2350
            if processed == total:
                print("✅ Job processed all addresses without hanging")
            
            break
        elif status == "error":
            print(f"❌ Job failed with error: {job_data.get('error_message')}")
            return None
        
        # Wait before next polling attempt
        time.sleep(polling_interval)
    
    # Test logs endpoint
    print("\nTesting /api/job/{job_id}/logs endpoint...")
    logs_response = requests.get(f"{BACKEND_URL}/job/{job_id}/logs")
    
    if logs_response.status_code != 200:
        print(f"❌ Failed to get job logs. Status code: {logs_response.status_code}")
    else:
        logs = logs_response.json().get("logs", [])
        print(f"✅ Successfully retrieved {len(logs)} log entries")
        
        # Analyze logs for different levels
        log_levels = {}
        for log in logs:
            level = log.get("level", "UNKNOWN")
            log_levels[level] = log_levels.get(level, 0) + 1
        
        print("\nLog level distribution:")
        for level, count in log_levels.items():
            print(f"{level}: {count} entries")
        
        # Check for specific log patterns
        cache_hits = sum(1 for log in logs if "cache" in log.get("message", "").lower())
        retry_attempts = sum(1 for log in logs if "retry" in log.get("message", "").lower())
        backoff_mentions = sum(1 for log in logs if "backoff" in log.get("message", "").lower())
        batch_mentions = sum(1 for log in logs if "batch" in log.get("message", "").lower())
        
        print("\nSpecific log patterns:")
        print(f"Cache hits/mentions: {cache_hits}")
        print(f"Retry attempts: {retry_attempts}")
        print(f"Backoff mentions: {backoff_mentions}")
        print(f"Batch processing mentions: {batch_mentions}")
    
    # Get route data to verify all addresses were processed
    print("\nVerifying route data...")
    route_response = requests.get(f"{BACKEND_URL}/route/{job_id}")
    
    if route_response.status_code != 200:
        print(f"❌ Failed to get route data. Status code: {route_response.status_code}")
        return None
    
    route_data = route_response.json()
    addresses = route_data.get("addresses", [])
    optimized_addresses = route_data.get("optimized_addresses", [])
    
    if not addresses and not optimized_addresses:
        print("❌ No addresses found in route data")
        return None
    
    # Use whichever list is available
    address_list = addresses if addresses else optimized_addresses
    
    print(f"✅ Successfully retrieved {len(address_list)} addresses from route data")
    
    # Analyze geocoding success rate
    geocoded_count = sum(1 for addr in address_list if addr.get("geocoded", False))
    failed_count = len(address_list) - geocoded_count
    
    print(f"\nGeocoding results:")
    print(f"Total addresses: {len(address_list)}")
    print(f"Successfully geocoded: {geocoded_count} ({geocoded_count/len(address_list)*100:.1f}%)")
    print(f"Failed to geocode: {failed_count} ({failed_count/len(address_list)*100:.1f}%)")
    
    # Check for specific problematic addresses
    problem_addresses = ["1941 Random Street", "2350 Problem Avenue"]
    for problem_addr in problem_addresses:
        matching_addresses = [addr for addr in address_list if problem_addr in addr.get("original_address", "")]
        if matching_addresses:
            addr = matching_addresses[0]
            if addr.get("geocoded", False):
                print(f"✅ Successfully handled previously problematic address: {problem_addr}")
            else:
                print(f"ℹ️ Address {problem_addr} was not geocoded, but was properly handled without hanging")
    
    # Clean up - delete the job
    print("\nCleaning up - deleting test job...")
    delete_response = requests.delete(f"{BACKEND_URL}/job/{job_id}")
    
    if delete_response.status_code != 200:
        print(f"❌ Failed to delete job. Status code: {delete_response.status_code}")
    else:
        print("✅ Job deleted successfully")
    
    return job_id

if __name__ == "__main__":
    test_enhanced_geocoding_robustness()