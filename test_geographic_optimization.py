#!/usr/bin/env python3
"""
Test geographic optimization endpoint with Lehrte data
"""
import requests
import time

BACKEND_URL = "http://localhost:8001/api"

def test_geographic_optimization():
    print("🔍 Testing Geographic Optimization Endpoint")
    print("=" * 60)
    
    # Same test data
    csv_content = '''PLZ,Ort,Teilort,Straße,Hnr,Zusatz
31275,Lehrte,Aligse,Burgdorfer Straße,118,
31275,Lehrte,Aligse,Ulmenallee,9,
31275,Lehrte,Aligse,Ulmenallee,6,
31275,Lehrte,Aligse,Ulmenallee,3,
31275,Lehrte,Aligse,Ulmenallee,11,'''
    
    try:
        # Upload to geographic optimization endpoint
        files = {
            'file': ('lehrte_geo_test.csv', csv_content, 'text/csv')
        }
        
        print("⏳ Uploading to /api/upload endpoint...")
        response = requests.post(f"{BACKEND_URL}/upload", files=files, timeout=30)
        
        if response.status_code != 200:
            print(f"❌ Upload failed: {response.status_code}")
            return False
        
        job_id = response.json().get("job_id")
        print(f"✅ Job created: {job_id}")
        
        # Wait for completion
        for attempt in range(15):
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
                    
                    # Test routes endpoint
                    print("\n🔍 Testing routes endpoint...")
                    response = requests.get(f"{BACKEND_URL}/route/{job_id}", timeout=10)
                    
                    if response.status_code == 200:
                        route_data = response.json()
                        addresses = route_data.get("addresses", [])
                        optimized_addresses = route_data.get("optimized_addresses", [])
                        
                        print(f"✅ Routes endpoint working:")
                        print(f"  - Total addresses: {len(addresses)}")
                        print(f"  - Optimized addresses: {len(optimized_addresses)}")
                        
                        # Check for coordinates
                        coords_count = sum(1 for addr in optimized_addresses 
                                         if addr.get("latitude") is not None and addr.get("longitude") is not None)
                        
                        print(f"  - Addresses with coordinates: {coords_count}")
                        
                        if coords_count > 0:
                            print("✅ ROUTES ENDPOINT: Has lat/lon coordinates")
                            result = True
                        else:
                            print("❌ ROUTES ENDPOINT: No coordinates found")
                            result = False
                    else:
                        print(f"❌ Routes endpoint failed: {response.status_code}")
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
                
                time.sleep(6)
                
            except Exception as e:
                print(f"  Attempt {attempt+1}: Error - {e}")
                continue
        
        print("❌ Test timed out")
        return False
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False

if __name__ == "__main__":
    success = test_geographic_optimization()
    print("\n" + "=" * 60)
    if success:
        print("🎉 GEOGRAPHIC OPTIMIZATION TEST PASSED!")
    else:
        print("💥 GEOGRAPHIC OPTIMIZATION TEST FAILED!")
    print("=" * 60)