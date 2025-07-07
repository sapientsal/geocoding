#!/usr/bin/env python3
import asyncio
import json
import os
import io
import csv
from datetime import datetime
import sys
import traceback

# Import the necessary functions from server.py
sys.path.append('/app/backend')
from server import (
    JobLogger, 
    geocode_address_with_cache, 
    address_cache,
    job_logs
)

async def test_geocoding_robustness():
    """Test the enhanced geocoding robustness features directly"""
    print("\n🔍 Testing Enhanced Geocoding Robustness...")
    
    # Create a test job ID and logger
    test_job_id = "test_geocoding_robustness"
    logger = JobLogger(test_job_id)
    
    # Read the test file with a mix of valid and invalid addresses
    addresses = []
    with open('/app/test_geocoding_robustness.csv', 'r') as f:
        reader = csv.reader(f)
        next(reader)  # Skip header
        for row in reader:
            if row:
                addresses.append(row[0].strip('"'))
    
    print(f"Loaded {len(addresses)} addresses for robustness testing")
    
    # Test batch processing (25 addresses per batch)
    batch_size = 25
    total_addresses = len(addresses)
    geocoded_data = []
    geocoded_count = 0
    failed_count = 0
    consecutive_failures = 0
    max_consecutive_failures = 50  # Circuit breaker threshold
    
    print(f"Starting geocoding of {total_addresses} addresses in batches of {batch_size}...")
    
    for batch_start in range(0, total_addresses, batch_size):
        batch_end = min(batch_start + batch_size, total_addresses)
        print(f"Processing batch {batch_start + 1}-{batch_end} of {total_addresses}")
        
        batch_geocoded = 0
        batch_failed = 0
        
        for i in range(batch_start, batch_end):
            address = addresses[i]
            
            try:
                print(f"Geocoding address {i+1}/{total_addresses}: {address}")
                logger.log("INFO", f"Starting geocoding for address {i+1}", i+1, address)
                
                # Test the geocoding function
                geocoded = await geocode_address_with_cache(address)
                
                # Log the result
                if geocoded.get('latitude') and geocoded.get('longitude'):
                    geocoded_count += 1
                    batch_geocoded += 1
                    consecutive_failures = 0
                    logger.log("INFO", f"Successfully geocoded", i+1, address)
                    print(f"✅ Successfully geocoded: {address}")
                else:
                    failed_count += 1
                    batch_failed += 1
                    consecutive_failures += 1
                    logger.log("WARNING", f"Failed to geocode: {geocoded.get('error', 'Unknown error')}", i+1, address)
                    print(f"❌ Failed to geocode: {address} - {geocoded.get('error', 'Unknown error')}")
                
                # Add to results
                geocoded_data.append(geocoded)
                
                # Test circuit breaker functionality
                if consecutive_failures >= max_consecutive_failures:
                    logger.log("CRITICAL", f"Circuit breaker activated after {consecutive_failures} consecutive failures", i+1, address)
                    print(f"⚠️ Circuit breaker activated after {consecutive_failures} consecutive failures")
                    break
                
                # Test rate limiting with adaptive delays
                if failed_count > 5 and (failed_count / max(i + 1, 1)) > 0.5:
                    # If failure rate is high, slow down
                    await asyncio.sleep(1.0)
                elif geocoded_count > 0 and (geocoded_count / max(i + 1, 1)) > 0.8:
                    # If success rate is high, speed up a bit
                    await asyncio.sleep(0.2)
                else:
                    # Normal rate
                    await asyncio.sleep(0.4)
                
            except Exception as e:
                print(f"Critical error processing address {i+1}: {address}")
                print(f"Error: {str(e)}")
                traceback.print_exc()
                
                logger.log("CRITICAL", f"Critical error: {str(e)}", i+1, address)
                
                geocoded_data.append({
                    'latitude': None,
                    'longitude': None,
                    'formatted_address': address,
                    'geocoded': False,
                    'error': str(e)
                })
                
                failed_count += 1
                batch_failed += 1
                consecutive_failures += 1
                
                # Continue processing even if one address fails
                continue
        
        # Check if circuit breaker was activated
        if consecutive_failures >= max_consecutive_failures:
            print(f"Circuit breaker stopped processing after {i+1} addresses")
            break
        
        print(f"Batch {batch_start + 1}-{batch_end} completed: {batch_geocoded} successful, {batch_failed} failed")
        
        # Small delay between batches
        if batch_end < total_addresses:
            print(f"Brief pause before next batch...")
            await asyncio.sleep(2.0)
    
    # Print final results
    print("\n=== Geocoding Results ===")
    print(f"Total addresses processed: {len(geocoded_data)}/{total_addresses}")
    print(f"Successfully geocoded: {geocoded_count} ({geocoded_count/len(geocoded_data)*100:.1f}%)")
    print(f"Failed to geocode: {failed_count} ({failed_count/len(geocoded_data)*100:.1f}%)")
    
    # Check cache effectiveness
    print(f"\nCache size: {len(address_cache)} entries")
    
    # Check logs
    print(f"\nLog entries: {len(logger.get_logs())}")
    log_levels = {}
    for log in logger.get_logs():
        level = log.get("level", "UNKNOWN")
        log_levels[level] = log_levels.get(level, 0) + 1
    
    print("\nLog level distribution:")
    for level, count in log_levels.items():
        print(f"{level}: {count} entries")
    
    # Check for specific problematic addresses
    problem_addresses = ["1941 Random Street", "2350 Problem Avenue"]
    for problem_addr in problem_addresses:
        matching_indices = [i for i, addr in enumerate(addresses) if problem_addr in addr]
        if matching_indices:
            idx = matching_indices[0]
            if idx < len(geocoded_data):
                result = geocoded_data[idx]
                if result.get('latitude') and result.get('longitude'):
                    print(f"✅ Successfully handled previously problematic address: {problem_addr}")
                else:
                    print(f"ℹ️ Address {problem_addr} was not geocoded, but was properly handled without hanging")
    
    return geocoded_data, logger.get_logs()

if __name__ == "__main__":
    asyncio.run(test_geocoding_robustness())