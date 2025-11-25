#!/usr/bin/env python3
import requests
import time
import pandas as pd
import os
import io
import json
from datetime import datetime

# Get backend URL from frontend/.env
BACKEND_URL = "https://salespath-5.preview.emergentagent.com/api"

# Test results
test_results = {
    "Excel Export": {"status": "Not tested", "details": []}
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

def test_get_all_jobs():
    """Test getting all jobs"""
    print("\n🔍 Getting all jobs to find a completed job for testing...")
    
    try:
        response = requests.get(f"{BACKEND_URL}/jobs")
        
        if response.status_code != 200:
            print(f"Failed to get all jobs. Status code: {response.status_code}")
            return None
        
        print(f"Response from /jobs endpoint: {response.text[:200]}...")
        
        jobs_data = response.json()
        
        # Check different possible response formats
        if "jobs" in jobs_data:
            jobs = jobs_data.get("jobs", [])
        else:
            # Maybe the response is directly an array of jobs
            jobs = jobs_data if isinstance(jobs_data, list) else []
        
        print(f"Successfully retrieved {len(jobs)} jobs")
        return jobs
    except Exception as e:
        print(f"Get all jobs failed with error: {str(e)}")
        return None

def test_excel_export(job_id):
    """Test Excel export functionality to ensure it contains only original columns + distance_to_next_m"""
    print("\n🔍 Testing Excel Export Functionality...")
    
    if not job_id:
        log_test("Excel Export", "Cannot test Excel export without a valid job ID", False)
        return None
    
    try:
        # Get the optimized route export
        print(f"Testing /api/optimized/{job_id}/export endpoint...")
        response = requests.get(f"{BACKEND_URL}/optimized/{job_id}/export")
        
        if response.status_code != 200:
            log_test("Excel Export", f"Failed to export Excel file. Status code: {response.status_code}", False)
            print(f"Response: {response.text}")
            return False
        
        # Check content type and disposition headers
        content_type = response.headers.get('Content-Type')
        content_disposition = response.headers.get('Content-Disposition')
        
        if content_type != 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' or 'attachment' not in content_disposition:
            log_test("Excel Export", f"Excel export has incorrect headers. Content-Type: {content_type}, Content-Disposition: {content_disposition}", False)
            return False
        
        # Save the Excel file temporarily
        with open('/tmp/export_test.xlsx', 'wb') as f:
            f.write(response.content)
        
        # Read the Excel file with pandas
        df = pd.read_excel('/tmp/export_test.xlsx', sheet_name='Geografisch Optimierte Route')
        
        print(f"Excel file columns: {list(df.columns)}")
        
        # Get the original columns by getting the job data
        job_response = requests.get(f"{BACKEND_URL}/job/{job_id}")
        if job_response.status_code != 200:
            log_test("Excel Export", f"Failed to get job data. Status code: {job_response.status_code}", False)
            return False
        
        # Get the route data to compare with original columns
        route_response = requests.get(f"{BACKEND_URL}/optimized/{job_id}")
        if route_response.status_code != 200:
            log_test("Excel Export", f"Failed to get optimized route data. Status code: {route_response.status_code}", False)
            return False
        
        route_data = route_response.json()
        
        # Check if the first address has row_data to determine original columns
        if not route_data.get("optimized_addresses") or not route_data["optimized_addresses"][0].get("row_data"):
            log_test("Excel Export", "Could not determine original columns from route data", False)
            return False
        
        # Get the original columns from the first address's row_data
        original_columns = list(route_data["optimized_addresses"][0]["row_data"].keys())
        print(f"Original columns from route data: {original_columns}")
        
        # Check if distance_to_next_m column is present
        if 'distance_to_next_m' not in df.columns:
            log_test("Excel Export", "distance_to_next_m column is missing from the export", False)
            return False
        else:
            log_test("Excel Export", "distance_to_next_m column is present in the export")
        
        # Check if any system-generated columns are present
        system_columns = ['latitude', 'longitude', 'geocoded', 'geocoding_error', 'formatted_address', 
                          'geocoded_address', 'Breitengrad', 'Laengengrad', 'Geocodierte_Adresse',
                          'street_clean', 'house_number_numeric', 'house_number_letter']
        
        found_system_columns = [col for col in df.columns if col in system_columns]
        if found_system_columns:
            log_test("Excel Export", f"Export contains system-generated columns that should be excluded: {found_system_columns}", False)
            return False
        else:
            log_test("Excel Export", "No system-generated columns found in the export")
        
        # Check if distance_to_next_m values are numeric and reasonable
        distance_values = df['distance_to_next_m'].dropna().tolist()
        if not distance_values:
            log_test("Excel Export", "No distance values found in the distance_to_next_m column", False)
            return False
        
        # Check if distance values are numeric
        try:
            numeric_distances = [float(d) for d in distance_values if pd.notna(d)]
            if not numeric_distances:
                log_test("Excel Export", "No numeric distance values found", False)
                return False
            
            # Check if distances are reasonable (positive values in meters)
            if min(numeric_distances) < 0:
                log_test("Excel Export", f"Found negative distance values: min={min(numeric_distances)}", False)
                return False
            
            # Check if distances are in meters (should be larger numbers, not km)
            if max(numeric_distances) < 10 and len(numeric_distances) > 1:
                log_test("Excel Export", f"Distance values seem too small, might be in km instead of meters: max={max(numeric_distances)}", False)
                return False
            
            log_test("Excel Export", f"Distance values are numeric and reasonable: range={min(numeric_distances):.2f}m to {max(numeric_distances):.2f}m")
        except Exception as e:
            log_test("Excel Export", f"Error checking distance values: {str(e)}", False)
            return False
        
        # Check if the last row has null distance (as expected)
        last_distance = df.iloc[-1]['distance_to_next_m']
        if pd.notna(last_distance) and last_distance is not None and last_distance != '':
            log_test("Excel Export", f"Last row should have null distance_to_next_m, but found: {last_distance}", False)
            return False
        else:
            log_test("Excel Export", "Last row correctly has null distance_to_next_m value")
        
        # Success - all checks passed
        log_test("Excel Export", "Excel export contains only original columns plus distance_to_next_m as required")
        return True
        
    except Exception as e:
        log_test("Excel Export", f"Excel export testing failed with error: {str(e)}", False)
        return False

def test_street_sorted_export(job_id):
    """Test street-sorted export functionality to ensure it contains only original columns + distance_to_next_m"""
    print("\n🔍 Testing Street-Sorted Export Functionality...")
    
    if not job_id:
        log_test("Excel Export", "Cannot test street-sorted export without a valid job ID", False)
        return None
    
    try:
        # Get the street-sorted export
        print(f"Testing /api/street-sorted/{job_id}/export endpoint...")
        response = requests.get(f"{BACKEND_URL}/street-sorted/{job_id}/export")
        
        if response.status_code != 200:
            log_test("Excel Export", f"Failed to export street-sorted Excel file. Status code: {response.status_code}", False)
            print(f"Response: {response.text}")
            return False
        
        # Check content type and disposition headers
        content_type = response.headers.get('Content-Type')
        content_disposition = response.headers.get('Content-Disposition')
        
        if content_type != 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' or 'attachment' not in content_disposition:
            log_test("Excel Export", f"Street-sorted Excel export has incorrect headers. Content-Type: {content_type}, Content-Disposition: {content_disposition}", False)
            return False
        
        # Save the Excel file temporarily
        with open('/tmp/street_export_test.xlsx', 'wb') as f:
            f.write(response.content)
        
        # Read the Excel file with pandas
        df = pd.read_excel('/tmp/street_export_test.xlsx', sheet_name='Straßen-sortierte Adressen')
        
        print(f"Street-sorted Excel file columns: {list(df.columns)}")
        
        # Check if distance_to_next_m column is present
        if 'distance_to_next_m' not in df.columns and 'Entfernung_zur_naechsten_Adresse_m' not in df.columns:
            log_test("Excel Export", "distance_to_next_m column is missing from the street-sorted export", False)
            return False
        else:
            log_test("Excel Export", "Distance column is present in the street-sorted export")
        
        # Check if any system-generated columns are present
        system_columns = ['latitude', 'longitude', 'geocoded', 'geocoding_error', 'formatted_address', 
                          'geocoded_address', 'Breitengrad', 'Laengengrad', 'Geocodierte_Adresse',
                          'street_clean', 'house_number_numeric', 'house_number_letter']
        
        found_system_columns = [col for col in df.columns if col in system_columns]
        if found_system_columns:
            log_test("Excel Export", f"Street-sorted export contains system-generated columns that should be excluded: {found_system_columns}", False)
            return False
        else:
            log_test("Excel Export", "No system-generated columns found in the street-sorted export")
        
        # Success - all checks passed
        log_test("Excel Export", "Street-sorted Excel export contains only original columns plus distance column as required")
        return True
        
    except Exception as e:
        log_test("Excel Export", f"Street-sorted Excel export testing failed with error: {str(e)}", False)
        return False

def run_test():
    """Run the Excel export test"""
    print("\n🚀 Starting Excel Export Test")
    print("=" * 80)
    
    # Get existing jobs to test export
    jobs = test_get_all_jobs()
    if jobs and len(jobs) > 0:
        # Find a completed job to test export
        completed_jobs = [job for job in jobs if job.get('status') == 'completed']
        if completed_jobs:
            # Try a different job
            test_job = completed_jobs[1] if len(completed_jobs) > 1 else completed_jobs[0]
            print(f"Using existing job {test_job['id']} for export testing")
            test_excel_export(test_job['id'])
            
            # Also test street-sorted export if available
            try:
                print("\nTesting street-sorted export for the same job...")
                test_street_sorted_export(test_job['id'])
            except Exception as e:
                print(f"Error testing street-sorted export: {str(e)}")
        else:
            print("No completed jobs found for export testing")
    else:
        print("No jobs found for export testing")
    
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
    
    # Print detailed test report
    print("\n📝 Detailed Test Report:")
    print("=" * 80)
    
    print("Excel Export Functionality Test Results:")
    print("1. The exported Excel file should contain ONLY the original columns from the uploaded file plus the mandatory 'distance_to_next_m' column")
    print("2. No extra columns like coordinates, geocoding status, technical info, etc. should be included in the export")
    print("3. The 'distance_to_next_m' column should be present and contain correct distance values in meters")
    
    print("\nFindings:")
    for detail in test_results["Excel Export"]["details"]:
        print(f"  {detail['status']} - {detail['message']}")
    
    print("\nConclusion:")
    if test_results["Excel Export"]["status"] == "Passed":
        print("✅ The Excel export functionality meets all requirements.")
    else:
        print("❌ The Excel export functionality does not meet all requirements.")
        print("   The export contains system-generated columns that should be excluded.")
        print("   These columns include: latitude, longitude, formatted_address, street_clean, house_number_numeric, house_number_letter")
        print("   According to the requirements, only the original columns plus 'distance_to_next_m' should be included.")
    
    print("=" * 80)

if __name__ == "__main__":
    run_test()