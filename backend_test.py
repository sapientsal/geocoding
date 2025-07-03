#!/usr/bin/env python3
import requests
import time
import csv
import os
import io
import json
from datetime import datetime

# Get backend URL from frontend/.env
BACKEND_URL = "https://2049d7ff-f0bb-467d-8f1d-1060857b0d94.preview.emergentagent.com/api"

# Test results dictionary
test_results = {
    "Excel File Upload Processing": {"status": "Not tested", "details": []},
    "Address Geocoding with OpenStreetMap": {"status": "Not tested", "details": []},
    "Route Optimization Algorithm": {"status": "Not tested", "details": []},
    "Job Status Tracking": {"status": "Not tested", "details": []},
    "Database Operations": {"status": "Not tested", "details": []}
}

def log_test(task, message, success=True):
    """Log test results"""
    status = "✅ PASS" if success else "❌ FAIL"
    print(f"{status} - {task}: {message}")
    test_results[task]["details"].append({"status": status, "message": message})
    if not success and test_results[task]["status"] != "Failed":
        test_results[task]["status"] = "Failed"
    elif success and test_results[task]["status"] != "Failed":
        test_results[task]["status"] = "Passed"

def create_test_csv():
    """Create a test CSV file with real addresses"""
    print("\n🔍 Creating test CSV file with real addresses...")
    
    # Real addresses for testing
    addresses = [
        ["Address"],
        ["1600 Pennsylvania Avenue NW, Washington, DC 20500"],  # White House
        ["350 Fifth Avenue, New York, NY 10118"],               # Empire State Building
        ["1 Infinite Loop, Cupertino, CA 95014"],               # Apple HQ
        ["1600 Amphitheatre Parkway, Mountain View, CA 94043"], # Google HQ
        ["2800 E Observatory Rd, Los Angeles, CA 90027"]        # Griffith Observatory
    ]
    
    # Create CSV in memory
    csv_file = io.StringIO()
    writer = csv.writer(csv_file)
    for address in addresses:
        writer.writerow(address)
    
    csv_content = csv_file.getvalue()
    print(f"Created CSV with {len(addresses)-1} addresses")
    return csv_content

def test_health_check():
    """Test the health check endpoint"""
    print("\n🔍 Testing health check endpoint...")
    try:
        response = requests.get(f"{BACKEND_URL}/health")
        if response.status_code == 200:
            print("✅ Health check successful")
            return True
        else:
            print(f"❌ Health check failed with status code: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Health check failed with error: {str(e)}")
        return False

def test_file_upload():
    """Test file upload endpoint"""
    print("\n🔍 Testing Excel File Upload Processing...")
    
    # Create test CSV
    csv_content = create_test_csv()
    
    try:
        # Create file-like object for upload
        files = {
            'file': ('test_addresses.csv', csv_content, 'text/csv')
        }
        
        # Upload file
        response = requests.post(f"{BACKEND_URL}/upload", files=files)
        
        if response.status_code == 200:
            job_id = response.json().get("job_id")
            log_test("Excel File Upload Processing", f"File uploaded successfully. Job ID: {job_id}")
            return job_id
        else:
            log_test("Excel File Upload Processing", f"File upload failed with status code: {response.status_code}", False)
            print(f"Response: {response.text}")
            return None
    except Exception as e:
        log_test("Excel File Upload Processing", f"File upload failed with error: {str(e)}", False)
        return None

def test_job_status(job_id):
    """Test job status tracking"""
    print("\n🔍 Testing Job Status Tracking...")
    
    if not job_id:
        log_test("Job Status Tracking", "Cannot test job status without a valid job ID", False)
        return None
    
    try:
        max_attempts = 30  # Maximum number of polling attempts
        polling_interval = 5  # Seconds between polling attempts
        
        for attempt in range(max_attempts):
            print(f"Polling job status (attempt {attempt+1}/{max_attempts})...")
            response = requests.get(f"{BACKEND_URL}/job/{job_id}")
            
            if response.status_code != 200:
                log_test("Job Status Tracking", f"Failed to get job status. Status code: {response.status_code}", False)
                return None
            
            job_data = response.json()
            status = job_data.get("status")
            
            print(f"Current job status: {status}")
            print(f"Processed: {job_data.get('processed_addresses')}/{job_data.get('total_addresses')}")
            
            # Test geocoding progress
            if status in ["geocoding", "completed"] and job_data.get("geocoded_addresses", 0) > 0:
                log_test("Address Geocoding with OpenStreetMap", 
                         f"Geocoding successful. {job_data.get('geocoded_addresses')} of {job_data.get('total_addresses')} addresses geocoded.")
            
            # Check if job is completed or failed
            if status == "completed":
                log_test("Job Status Tracking", f"Job completed successfully. Processed {job_data.get('processed_addresses')} addresses.")
                return job_data
            elif status == "error":
                log_test("Job Status Tracking", f"Job failed with error: {job_data.get('error_message')}", False)
                return job_data
            
            # Wait before next polling attempt
            time.sleep(polling_interval)
        
        log_test("Job Status Tracking", f"Job did not complete within the expected time ({max_attempts * polling_interval} seconds)", False)
        return None
    except Exception as e:
        log_test("Job Status Tracking", f"Job status tracking failed with error: {str(e)}", False)
        return None

def test_route_optimization(job_id):
    """Test route optimization algorithm"""
    print("\n🔍 Testing Route Optimization Algorithm...")
    
    if not job_id:
        log_test("Route Optimization Algorithm", "Cannot test route optimization without a valid job ID", False)
        return None
    
    try:
        response = requests.get(f"{BACKEND_URL}/route/{job_id}")
        
        if response.status_code != 200:
            log_test("Route Optimization Algorithm", f"Failed to get route. Status code: {response.status_code}", False)
            return None
        
        route_data = response.json()
        
        # Verify route data structure
        if "optimized_addresses" not in route_data:
            log_test("Route Optimization Algorithm", "Route data does not contain optimized_addresses", False)
            return None
        
        optimized_addresses = route_data.get("optimized_addresses", [])
        total_distance = route_data.get("total_distance", 0)
        
        # Check if we have a valid route
        if len(optimized_addresses) < 2:
            log_test("Route Optimization Algorithm", f"Not enough addresses were geocoded successfully. Only {len(optimized_addresses)} valid addresses.", False)
            return None
        
        # Verify that the route contains geocoded addresses
        geocoded_count = sum(1 for addr in optimized_addresses if addr.get("geocoded", False))
        
        if geocoded_count != len(optimized_addresses):
            log_test("Route Optimization Algorithm", f"Not all addresses in the route were geocoded. {geocoded_count}/{len(optimized_addresses)} geocoded.", False)
        else:
            log_test("Route Optimization Algorithm", f"Route optimization successful. {len(optimized_addresses)} addresses in optimized route. Total distance: {total_distance:.2f} km")
        
        # Verify that the route makes sense (each point should be close to the previous one)
        valid_route = True
        for i in range(len(optimized_addresses) - 1):
            current = optimized_addresses[i]
            next_addr = optimized_addresses[i + 1]
            
            # Skip validation if addresses don't have coordinates
            if not (current.get("latitude") and current.get("longitude") and 
                    next_addr.get("latitude") and next_addr.get("longitude")):
                continue
            
            # We can't fully validate the nearest neighbor algorithm here,
            # but we can check that the route contains valid coordinates
            if (not isinstance(current.get("latitude"), (int, float)) or 
                not isinstance(current.get("longitude"), (int, float)) or
                not isinstance(next_addr.get("latitude"), (int, float)) or
                not isinstance(next_addr.get("longitude"), (int, float))):
                valid_route = False
                break
        
        if valid_route:
            log_test("Route Optimization Algorithm", "Route coordinates validation passed")
        else:
            log_test("Route Optimization Algorithm", "Route contains invalid coordinates", False)
        
        return route_data
    except Exception as e:
        log_test("Route Optimization Algorithm", f"Route optimization testing failed with error: {str(e)}", False)
        return None

def test_get_all_jobs():
    """Test getting all jobs"""
    print("\n🔍 Testing Database Operations - Get All Jobs...")
    
    try:
        response = requests.get(f"{BACKEND_URL}/jobs")
        
        if response.status_code != 200:
            log_test("Database Operations", f"Failed to get all jobs. Status code: {response.status_code}", False)
            return None
        
        jobs_data = response.json()
        
        if "jobs" not in jobs_data:
            log_test("Database Operations", "Jobs data does not contain 'jobs' key", False)
            return None
        
        jobs = jobs_data.get("jobs", [])
        log_test("Database Operations", f"Successfully retrieved {len(jobs)} jobs")
        return jobs
    except Exception as e:
        log_test("Database Operations", f"Get all jobs failed with error: {str(e)}", False)
        return None

def test_delete_job(job_id):
    """Test job deletion"""
    print("\n🔍 Testing Database Operations - Delete Job...")
    
    if not job_id:
        log_test("Database Operations", "Cannot test job deletion without a valid job ID", False)
        return False
    
    try:
        response = requests.delete(f"{BACKEND_URL}/job/{job_id}")
        
        if response.status_code != 200:
            log_test("Database Operations", f"Failed to delete job. Status code: {response.status_code}", False)
            return False
        
        # Verify job was deleted by trying to get it
        verify_response = requests.get(f"{BACKEND_URL}/job/{job_id}")
        
        if verify_response.status_code == 404:
            log_test("Database Operations", f"Job {job_id} was successfully deleted")
            return True
        else:
            log_test("Database Operations", f"Job deletion verification failed. Expected 404, got {verify_response.status_code}", False)
            return False
    except Exception as e:
        log_test("Database Operations", f"Job deletion failed with error: {str(e)}", False)
        return False

def run_all_tests():
    """Run all tests in sequence"""
    print("\n🚀 Starting Sales Route Optimization Backend API Tests")
    print("=" * 80)
    
    # Check if API is healthy
    if not test_health_check():
        print("\n❌ API health check failed. Aborting tests.")
        return
    
    # Test file upload
    job_id = test_file_upload()
    
    if job_id:
        # Test job status tracking and wait for completion
        job_data = test_job_status(job_id)
        
        if job_data and job_data.get("status") == "completed":
            # Test route optimization
            route_data = test_route_optimization(job_id)
            
            # Test getting all jobs
            jobs = test_get_all_jobs()
            
            # Test job deletion
            test_delete_job(job_id)
    
    # Print summary
    print("\n" + "=" * 80)
    print("📊 Test Summary:")
    print("=" * 80)
    
    for task, result in test_results.items():
        status = result["status"]
        if status == "Passed":
            print(f"✅ {task}: PASSED")
        elif status == "Failed":
            print(f"❌ {task}: FAILED")
        else:
            print(f"⚠️ {task}: {status}")
    
    print("=" * 80)

if __name__ == "__main__":
    run_all_tests()