#!/usr/bin/env python3
import sys
import os
import asyncio
import time
import random
from datetime import datetime

# Add the backend directory to the path so we can import the server module
sys.path.append('/app/backend')

# Import the geocoding function from server.py
from server import geocode_address_with_cache

async def test_geocoding_robustness():
    """Test the enhanced geocoding function with retry logic and exponential backoff"""
    print("\n🔍 Testing Enhanced Geocoding Robustness...")
    
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
    
    # Test valid addresses
    print("\nTesting valid addresses:")
    valid_results = []
    for address in valid_addresses:
        print(f"\nGeocoding: {address}")
        start_time = time.time()
        result = await geocode_address_with_cache(address)
        elapsed_time = time.time() - start_time
        
        valid_results.append({
            "address": address,
            "result": result,
            "elapsed_time": elapsed_time
        })
        
        if result.get('geocoded', False):
            print(f"✅ Successfully geocoded in {elapsed_time:.2f}s")
            print(f"   Latitude: {result.get('latitude')}")
            print(f"   Longitude: {result.get('longitude')}")
            print(f"   Formatted: {result.get('formatted_address')}")
        else:
            print(f"❌ Failed to geocode in {elapsed_time:.2f}s")
            print(f"   Error: {result.get('error')}")
        
        # Add a small delay between requests to avoid rate limiting
        await asyncio.sleep(1)
    
    # Test invalid addresses
    print("\nTesting invalid addresses:")
    invalid_results = []
    for address in invalid_addresses:
        print(f"\nGeocoding: {address}")
        start_time = time.time()
        result = await geocode_address_with_cache(address)
        elapsed_time = time.time() - start_time
        
        invalid_results.append({
            "address": address,
            "result": result,
            "elapsed_time": elapsed_time
        })
        
        if result.get('geocoded', False):
            print(f"❓ Unexpectedly geocoded in {elapsed_time:.2f}s")
            print(f"   Latitude: {result.get('latitude')}")
            print(f"   Longitude: {result.get('longitude')}")
            print(f"   Formatted: {result.get('formatted_address')}")
        else:
            print(f"✅ Correctly failed to geocode in {elapsed_time:.2f}s")
            print(f"   Error: {result.get('error')}")
        
        # Add a small delay between requests to avoid rate limiting
        await asyncio.sleep(1)
    
    # Test retry logic by simulating rate limiting
    print("\nTesting retry logic with rapid requests:")
    retry_results = []
    for i in range(5):
        address = random.choice(valid_addresses)
        print(f"\nRapid geocoding attempt {i+1}: {address}")
        start_time = time.time()
        result = await geocode_address_with_cache(address)
        elapsed_time = time.time() - start_time
        
        retry_results.append({
            "address": address,
            "result": result,
            "elapsed_time": elapsed_time
        })
        
        if result.get('geocoded', False):
            print(f"✅ Successfully geocoded in {elapsed_time:.2f}s")
            print(f"   Latitude: {result.get('latitude')}")
            print(f"   Longitude: {result.get('longitude')}")
            print(f"   Formatted: {result.get('formatted_address')}")
        else:
            print(f"❌ Failed to geocode in {elapsed_time:.2f}s")
            print(f"   Error: {result.get('error')}")
        
        # Don't add delay to test rate limiting handling
    
    # Calculate statistics
    valid_success_count = sum(1 for r in valid_results if r["result"].get("geocoded", False))
    valid_success_rate = valid_success_count / len(valid_results) * 100
    
    invalid_failure_count = sum(1 for r in invalid_results if not r["result"].get("geocoded", False))
    invalid_failure_rate = invalid_failure_count / len(invalid_results) * 100
    
    retry_success_count = sum(1 for r in retry_results if r["result"].get("geocoded", False))
    retry_success_rate = retry_success_count / len(retry_results) * 100
    
    avg_valid_time = sum(r["elapsed_time"] for r in valid_results) / len(valid_results)
    avg_invalid_time = sum(r["elapsed_time"] for r in invalid_results) / len(invalid_results)
    avg_retry_time = sum(r["elapsed_time"] for r in retry_results) / len(retry_results)
    
    # Print summary
    print("\n" + "=" * 80)
    print("📊 Test Summary:")
    print("=" * 80)
    print(f"Valid addresses: {valid_success_count}/{len(valid_results)} successful ({valid_success_rate:.1f}%)")
    print(f"Invalid addresses: {invalid_failure_count}/{len(invalid_results)} correctly failed ({invalid_failure_rate:.1f}%)")
    print(f"Retry logic: {retry_success_count}/{len(retry_results)} successful ({retry_success_rate:.1f}%)")
    print(f"Average time for valid addresses: {avg_valid_time:.2f}s")
    print(f"Average time for invalid addresses: {avg_invalid_time:.2f}s")
    print(f"Average time for retry tests: {avg_retry_time:.2f}s")
    
    # Test caching
    print("\nTesting caching functionality:")
    cached_address = valid_addresses[0]
    
    print(f"\nFirst request for: {cached_address}")
    start_time = time.time()
    first_result = await geocode_address_with_cache(cached_address)
    first_elapsed_time = time.time() - start_time
    
    print(f"✅ First request completed in {first_elapsed_time:.2f}s")
    
    print(f"\nSecond request (should use cache) for: {cached_address}")
    start_time = time.time()
    second_result = await geocode_address_with_cache(cached_address)
    second_elapsed_time = time.time() - start_time
    
    print(f"✅ Second request completed in {second_elapsed_time:.2f}s")
    
    if second_elapsed_time < first_elapsed_time:
        print(f"✅ Caching is working! Second request was {first_elapsed_time - second_elapsed_time:.2f}s faster")
    else:
        print(f"❌ Caching may not be working properly. Second request took {second_elapsed_time:.2f}s vs first {first_elapsed_time:.2f}s")
    
    # Overall assessment
    print("\n" + "=" * 80)
    print("🔍 Overall Assessment:")
    print("=" * 80)
    
    if valid_success_rate >= 70 and invalid_failure_rate >= 70 and retry_success_rate >= 60:
        print("✅ Enhanced geocoding is working properly with good success rates")
    else:
        print("❌ Enhanced geocoding has issues with success rates")
    
    if second_elapsed_time < first_elapsed_time:
        print("✅ Caching is working effectively")
    else:
        print("❌ Caching may not be working properly")
    
    print("=" * 80)

async def main():
    """Run all tests"""
    print("\n🚀 Starting Direct Geocoding Function Tests")
    print("=" * 80)
    
    await test_geocoding_robustness()

if __name__ == "__main__":
    asyncio.run(main())