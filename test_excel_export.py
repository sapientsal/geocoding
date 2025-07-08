#!/usr/bin/env python3
import requests
import pandas as pd
import io
import json
import os
import time

# Get backend URL from frontend/.env
BACKEND_URL = "https://95a8d55d-d4d3-4544-aea7-981b1e115401.preview.emergentagent.com/api"

def test_excel_export():
    """Test Excel export functionality to verify system-generated columns are filtered out"""
    print("\n🔍 Testing Excel Export Functionality...")
    
    # First, get a list of completed jobs
    try:
        response = requests.get(f"{BACKEND_URL}/jobs")
        if response.status_code != 200:
            print(f"❌ Failed to get jobs. Status code: {response.status_code}")
            return
        
        jobs = response.json().get("jobs", [])
        completed_jobs = [job for job in jobs if job.get("status") == "completed"]
        
        if not completed_jobs:
            print("❌ No completed jobs found for testing export functionality")
            return
        
        # Use the most recent completed job
        job_id = completed_jobs[0]["id"]
        print(f"✅ Found completed job for testing: {job_id}")
        
        # Test optimized route export
        print("\n🔍 Testing /api/optimized/{job_id}/export endpoint...")
        response = requests.get(f"{BACKEND_URL}/optimized/{job_id}/export")
        
        if response.status_code != 200:
            print(f"❌ Failed to export optimized route. Status code: {response.status_code}")
            print(f"Response: {response.text}")
        else:
            # Check if the response is an Excel file
            content_type = response.headers.get('Content-Type')
            if content_type == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':
                # Save the Excel file temporarily
                with open('temp_export.xlsx', 'wb') as f:
                    f.write(response.content)
                
                # Read the Excel file to check its contents
                df = pd.read_excel('temp_export.xlsx')
                
                # Check for system-generated columns
                system_columns = [
                    'latitude', 'longitude', 'geocoded', 'geocoding_error', 'formatted_address',
                    'street_clean', 'house_number_numeric', 'house_number_letter',
                    'Breitengrad', 'Laengengrad', 'Geocodierte_Adresse', 'Formatierte_Adresse',
                    'Longitude', 'Latitude', 'Geocodiert', 'Geocoding_Fehler'
                ]
                
                found_system_columns = [col for col in df.columns if col in system_columns]
                
                if found_system_columns:
                    print(f"❌ System-generated columns found in export: {found_system_columns}")
                else:
                    print("✅ No system-generated columns found in export")
                
                # Check if distance_to_next_m column is present
                if 'distance_to_next_m' in df.columns:
                    print("✅ distance_to_next_m column is present")
                    
                    # Check if distance values are correct (non-null for all rows except the last)
                    null_distances = df['distance_to_next_m'].iloc[:-1].isna().sum()
                    if null_distances > 0:
                        print(f"❌ Found {null_distances} null distance values (excluding last row)")
                    else:
                        print("✅ All distance values are present (excluding last row)")
                else:
                    print("❌ distance_to_next_m column is missing")
                
                # Print all columns for verification
                print(f"\nColumns in export: {list(df.columns)}")
                
                # Clean up
                os.remove('temp_export.xlsx')
            else:
                print(f"❌ Response is not an Excel file. Content-Type: {content_type}")
        
        # Test street-sorted export if endpoint exists
        print("\n🔍 Testing /api/street-sorted/{job_id}/export endpoint...")
        response = requests.get(f"{BACKEND_URL}/street-sorted/{job_id}/export")
        
        if response.status_code != 200:
            print(f"❌ Failed to export street-sorted route. Status code: {response.status_code}")
            print(f"Response: {response.text}")
        else:
            # Check if the response is an Excel file
            content_type = response.headers.get('Content-Type')
            if content_type == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':
                # Save the Excel file temporarily
                with open('temp_street_export.xlsx', 'wb') as f:
                    f.write(response.content)
                
                # Read the Excel file to check its contents
                df = pd.read_excel('temp_street_export.xlsx')
                
                # Check for system-generated columns
                system_columns = [
                    'latitude', 'longitude', 'geocoded', 'geocoding_error', 'formatted_address',
                    'street_clean', 'house_number_numeric', 'house_number_letter',
                    'Breitengrad', 'Laengengrad', 'Geocodierte_Adresse', 'Formatierte_Adresse',
                    'Longitude', 'Latitude', 'Geocodiert', 'Geocoding_Fehler'
                ]
                
                found_system_columns = [col for col in df.columns if col in system_columns]
                
                if found_system_columns:
                    print(f"❌ System-generated columns found in street-sorted export: {found_system_columns}")
                else:
                    print("✅ No system-generated columns found in street-sorted export")
                
                # Check if distance_to_next_m column is present
                if 'distance_to_next_m' in df.columns:
                    print("✅ distance_to_next_m column is present in street-sorted export")
                    
                    # Check if distance values are correct (non-null for all rows except the last)
                    null_distances = df['distance_to_next_m'].iloc[:-1].isna().sum()
                    if null_distances > 0:
                        print(f"❌ Found {null_distances} null distance values in street-sorted export (excluding last row)")
                    else:
                        print("✅ All distance values are present in street-sorted export (excluding last row)")
                else:
                    print("❌ distance_to_next_m column is missing in street-sorted export")
                
                # Print all columns for verification
                print(f"\nColumns in street-sorted export: {list(df.columns)}")
                
                # Clean up
                os.remove('temp_street_export.xlsx')
            else:
                print(f"❌ Response is not an Excel file. Content-Type: {content_type}")
        
        # Test route export (original endpoint)
        print("\n🔍 Testing /api/route/{job_id}/export endpoint...")
        response = requests.get(f"{BACKEND_URL}/route/{job_id}/export")
        
        if response.status_code != 200:
            print(f"❌ Failed to export route. Status code: {response.status_code}")
            print(f"Response: {response.text}")
        else:
            # Check if the response is an Excel file
            content_type = response.headers.get('Content-Type')
            if content_type == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':
                # Save the Excel file temporarily
                with open('temp_route_export.xlsx', 'wb') as f:
                    f.write(response.content)
                
                # Read the Excel file to check its contents
                df = pd.read_excel('temp_route_export.xlsx')
                
                # Check for system-generated columns
                system_columns = [
                    'latitude', 'longitude', 'geocoded', 'geocoding_error', 'formatted_address',
                    'street_clean', 'house_number_numeric', 'house_number_letter',
                    'Breitengrad', 'Laengengrad', 'Geocodierte_Adresse', 'Formatierte_Adresse',
                    'Longitude', 'Latitude', 'Geocodiert', 'Geocoding_Fehler'
                ]
                
                found_system_columns = [col for col in df.columns if col in system_columns]
                
                if found_system_columns:
                    print(f"❌ System-generated columns found in route export: {found_system_columns}")
                else:
                    print("✅ No system-generated columns found in route export")
                
                # Check if distance_to_next_m column is present
                if 'distance_to_next_m' in df.columns:
                    print("✅ distance_to_next_m column is present in route export")
                else:
                    print("❌ distance_to_next_m column is missing in route export")
                
                # Print all columns for verification
                print(f"\nColumns in route export: {list(df.columns)}")
                
                # Clean up
                os.remove('temp_route_export.xlsx')
            else:
                print(f"❌ Response is not an Excel file. Content-Type: {content_type}")
    
    except Exception as e:
        print(f"❌ Error testing Excel export: {str(e)}")

if __name__ == "__main__":
    test_excel_export()