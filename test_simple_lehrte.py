#!/usr/bin/env python3
"""
Simple test for the critical geocoding fix
"""
import requests
import time
import json

BACKEND_URL = "http://localhost:8001/api"

def test_simple():
    print("🔍 Testing Critical Geocoding Fix - Simple Test")
    print("=" * 60)
    
    # Create a simple CSV with the Lehrte format
    csv_content = '''PLZ,Ort,Teilort,Straße,Hnr,Zusatz
31275,Lehrte,Aligse,Burgdorfer Straße,118,
31275,Lehrte,Aligse,Ulmenallee,9,
31275,Lehrte,Aligse,Ulmenallee,6,
31275,Lehrte,Aligse,Ulmenallee,3,
31275,Lehrte,Aligse,Ulmenallee,11,'''
    
    print("📊 Test data:")
    print("- 5 addresses from Lehrte")
    print("- Ort: 'Lehrte' (main city)")
    print("- Teilort: 'Aligse' (sub-locality)")
    print("- Expected: System should use 'Lehrte' not 'Aligse'")
    
    try:
        # Upload file
        files = {
            'file': ('lehrte_test.csv', csv_content, 'text/csv')
        }
        
        print("\n⏳ Uploading file...")
        response = requests.post(f"{BACKEND_URL}/upload-street-sorted", files=files, timeout=30)
        
        if response.status_code != 200:
            print(f"❌ Upload failed: {response.status_code}")
            print(f"Response: {response.text}")
            return False
        
        job_id = response.json().get("job_id")
        print(f"✅ Job created: {job_id}")
        
        # Wait for completion (shorter timeout)
        print("⏳ Waiting for completion...")
        for attempt in range(20):  # 2 minutes max
            try:
                response = requests.get(f"{BACKEND_URL}/job/{job_id}", timeout=10)
                
                if response.status_code != 200:
                    print(f"❌ Status check failed: {response.status_code}")
                    return False
                
                job_data = response.json()
                status = job_data.get("status")
                total = job_data.get("total_addresses", 0)
                geocoded = job_data.get("geocoded_addresses", 0)
                
                print(f"  Attempt {attempt+1}: {status}, Geocoded: {geocoded}/{total}")
                
                if status == "completed":
                    success_rate = (geocoded / total) * 100 if total > 0 else 0
                    print(f"🎯 SUCCESS RATE: {success_rate:.1f}%")
                    
                    # Check addresses
                    print("\n🔍 Checking address construction...")
                    response = requests.get(f"{BACKEND_URL}/street-sorted/{job_id}", timeout=10)
                    
                    if response.status_code == 200:
                        data = response.json()
                        addresses = data.get("sorted_addresses", [])
                        
                        uses_lehrte = 0
                        uses_aligse = 0
                        
                        for addr in addresses:
                            original = addr.get("original_address", "")
                            if "Lehrte" in original:
                                uses_lehrte += 1
                            if "Aligse" in original:
                                uses_aligse += 1
                        
                        print(f"📊 Results:")
                        print(f"  - Uses 'Lehrte': {uses_lehrte}/{len(addresses)}")
                        print(f"  - Uses 'Aligse': {uses_aligse}/{len(addresses)}")
                        
                        if uses_lehrte > 0 and uses_aligse == 0:
                            print("✅ CRITICAL FIX VERIFIED: Uses 'Ort' not 'Teilort'")
                            result = True
                        else:
                            print("❌ CRITICAL FIX FAILED: Still using wrong column")
                            result = False
                    else:
                        print(f"❌ Failed to get addresses: {response.status_code}")
                        result = False
                    
                    # Clean up
                    try:
                        requests.delete(f"{BACKEND_URL}/job/{job_id}", timeout=5)
                    except:
                        pass
                    
                    return result
                    
                elif status == "error":
                    print(f"❌ Job failed: {job_data.get('error_message')}")
                    return False
                
                time.sleep(6)  # Wait 6 seconds between checks
                
            except requests.exceptions.Timeout:
                print(f"  Attempt {attempt+1}: Timeout, retrying...")
                continue
            except Exception as e:
                print(f"  Attempt {attempt+1}: Error - {e}")
                continue
        
        print("❌ Test timed out")
        return False
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False

if __name__ == "__main__":
    success = test_simple()
    print("\n" + "=" * 60)
    if success:
        print("🎉 CRITICAL GEOCODING FIX TEST PASSED!")
    else:
        print("💥 CRITICAL GEOCODING FIX TEST FAILED!")
    print("=" * 60)