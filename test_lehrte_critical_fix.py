#!/usr/bin/env python3
"""
CRITICAL GEOCODING FIX TEST for Penliste Lehrte 1 DGN.xlsx
Tests the fix where system was using 'Teilort' (Aligse) instead of 'Ort' (Lehrte)
"""
import requests
import time
import pandas as pd

BACKEND_URL = "https://nominatim-overload.preview.emergentagent.com/api"

def test_critical_geocoding_fix():
    """Test the critical geocoding fix with Lehrte sample data"""
    print("🔍 Testing CRITICAL GEOCODING FIX for Lehrte addresses")
    print("=" * 80)
    print("🎯 ISSUE: System was using 'Teilort' (Aligse) instead of 'Ort' (Lehrte)")
    print("🎯 EXPECTED: Addresses should use 'Lehrte' and have >70% success rate")
    
    try:
        # Load the sample CSV
        with open('/app/lehrte_sample.csv', 'rb') as f:
            file_content = f.read()
        
        print(f"✅ Loaded sample file: {len(file_content)} bytes")
        
        # Test street-sorted endpoint
        files = {
            'file': ('lehrte_sample.csv', file_content, 'text/csv')
        }
        
        response = requests.post(f"{BACKEND_URL}/upload-street-sorted", files=files)
        
        if response.status_code != 200:
            print(f"❌ Upload failed: {response.status_code}")
            print(f"Response: {response.text}")
            return False
        
        job_id = response.json().get("job_id")
        print(f"✅ Job created: {job_id}")
        
        # Monitor job progress
        print("⏳ Monitoring job progress...")
        for attempt in range(30):
            response = requests.get(f"{BACKEND_URL}/job/{job_id}")
            
            if response.status_code != 200:
                print(f"❌ Status check failed: {response.status_code}")
                return False
            
            job_data = response.json()
            status = job_data.get("status")
            total = job_data.get("total_addresses", 0)
            processed = job_data.get("processed_addresses", 0)
            geocoded = job_data.get("geocoded_addresses", 0)
            
            print(f"Status: {status}, Processed: {processed}/{total}, Geocoded: {geocoded}")
            
            if status == "completed":
                success_rate = (geocoded / total) * 100 if total > 0 else 0
                print(f"🎯 FINAL SUCCESS RATE: {success_rate:.1f}%")
                
                if success_rate > 70:
                    print("✅ SUCCESS: Geocoding rate > 70% (fix working!)")
                else:
                    print(f"❌ FAILED: Geocoding rate {success_rate:.1f}% < 70%")
                
                break
            elif status == "error":
                print(f"❌ Job failed: {job_data.get('error_message')}")
                return False
            
            time.sleep(5)
        
        # Check address construction
        print("\n🔍 Checking address construction...")
        response = requests.get(f"{BACKEND_URL}/street-sorted/{job_id}")
        
        if response.status_code == 200:
            sorted_data = response.json()
            sorted_addresses = sorted_data.get("sorted_addresses", [])
            
            if sorted_addresses:
                print(f"✅ Retrieved {len(sorted_addresses)} addresses")
                
                # Check first 5 addresses
                uses_lehrte = 0
                uses_aligse = 0
                
                for i, addr in enumerate(sorted_addresses[:5]):
                    original = addr.get("original_address", "")
                    print(f"  {i+1}. {original}")
                    
                    if "Lehrte" in original:
                        uses_lehrte += 1
                        print(f"      ✅ Uses 'Lehrte' (correct)")
                    if "Aligse" in original:
                        uses_aligse += 1
                        print(f"      ❌ Uses 'Aligse' (incorrect)")
                
                print(f"\n📊 Results: {uses_lehrte}/5 use 'Lehrte', {uses_aligse}/5 use 'Aligse'")
                
                if uses_lehrte >= 4 and uses_aligse == 0:
                    print("✅ COLUMN DETECTION FIX VERIFIED: Uses 'Ort' not 'Teilort'")
                    success = True
                else:
                    print("❌ COLUMN DETECTION FAILED: Still using wrong column")
                    success = False
            else:
                print("❌ No addresses returned")
                success = False
        else:
            print(f"❌ Failed to get sorted data: {response.status_code}")
            success = False
        
        # Clean up
        requests.delete(f"{BACKEND_URL}/job/{job_id}")
        
        return success
        
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_critical_geocoding_fix()
    if success:
        print("\n🎉 CRITICAL GEOCODING FIX TEST PASSED!")
    else:
        print("\n💥 CRITICAL GEOCODING FIX TEST FAILED!")