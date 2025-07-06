from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pymongo import MongoClient
from typing import List, Optional, Dict, Any, Tuple
from pydantic import BaseModel
from datetime import datetime
from io import BytesIO
import pandas as pd
import requests
import time
import math
import uuid
import os
import json
import asyncio
import re
from concurrent.futures import ThreadPoolExecutor
import openpyxl
from openpyxl.styles import PatternFill, Font
from openpyxl.utils.dataframe import dataframe_to_rows

app = FastAPI(
    title="Sales Route Optimizer API",
    description="API for optimizing sales routes with geocoding and route optimization",
    version="1.0.0"
)

# Address cache for performance
address_cache = {}

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MongoDB connection with proper error handling
MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017/sales_routes')

try:
    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    # Test connection
    client.admin.command('ismaster')
    
    db = client['sales_routes']
    addresses_collection = db['addresses']
    routes_collection = db['routes']
    upload_jobs_collection = db['upload_jobs']
    
    print("✅ MongoDB connection successful")
except Exception as e:
    print(f"❌ MongoDB connection failed: {e}")
    print("⚠️ Using fallback configuration")
    
    # Fallback to basic connection without validation
    try:
        client = MongoClient(MONGO_URL)
        db = client['sales_routes']
        addresses_collection = db['addresses']
        routes_collection = db['routes']
        upload_jobs_collection = db['upload_jobs']
        print("✅ MongoDB fallback connection successful")
    except Exception as fallback_error:
        print(f"❌ MongoDB fallback also failed: {fallback_error}")
        raise

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler for better error responses"""
    import traceback
    
    error_id = str(uuid.uuid4())[:8]
    error_details = {
        "error_id": error_id,
        "error_type": type(exc).__name__,
        "message": str(exc),
        "path": str(request.url)
    }
    
    # Log the error
    print(f"❌ Error {error_id}: {type(exc).__name__} - {str(exc)}")
    print(f"📍 Path: {request.url}")
    
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "error_id": error_id}
        )
    
    # For unexpected errors, return 500
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Ein unerwarteter Fehler ist aufgetreten. Bitte versuchen Sie es später erneut.",
            "error_id": error_id,
            "error_type": type(exc).__name__
        }
    )

# Pydantic models
class Address(BaseModel):
    id: str
    original_address: str
    formatted_address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    geocoded: bool = False
    geocoding_error: Optional[str] = None

class Route(BaseModel):
    id: str
    job_id: str
    addresses: List[Address]
    optimized_order: List[int]
    total_distance: float
    created_at: datetime

class UploadJob(BaseModel):
    id: str
    filename: str
    status: str  # 'uploading', 'parsing', 'geocoding', 'optimizing', 'completed', 'error'
    total_addresses: int
    processed_addresses: int
    geocoded_addresses: int
    error_message: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None

def extract_house_number_parts(house_number_str) -> Tuple[int, str]:
    """Extract numeric and alphabetic parts from house number for proper sorting"""
    # Handle NaN, None, empty strings, etc.
    if house_number_str is None or pd.isna(house_number_str) or house_number_str == '' or str(house_number_str).strip() == '' or str(house_number_str).strip().lower() == 'nan':
        return 0, ''
    
    # Convert to string and strip whitespace
    house_str = str(house_number_str).strip()
    
    # Use regex to extract number and letter parts
    match = re.match(r'^(\d+)([A-Za-z]*).*', house_str)
    if match:
        try:
            number = int(match.group(1))
            letter = match.group(2).upper() if match.group(2) else ''
            return number, letter
        except ValueError:
            return 0, house_str
    else:
        # If no number found, try to extract any number
        numbers = re.findall(r'\d+', house_str)
        if numbers:
            try:
                return int(numbers[0]), ''
            except ValueError:
                return 0, house_str
        else:
            return 0, house_str

def calculate_distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> Optional[float]:
    """Calculate distance between two points in meters using Haversine formula"""
    if not all([lat1, lon1, lat2, lon2]):
        return None
    
    # Radius of Earth in meters
    R = 6371000
    
    # Convert to radians
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    
    # Haversine formula
    a = (math.sin(delta_lat/2) * math.sin(delta_lat/2) +
         math.cos(lat1_rad) * math.cos(lat2_rad) *
         math.sin(delta_lon/2) * math.sin(delta_lon/2))
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    
    return R * c

def sort_addresses_by_street_and_house_number(df, geocoded_data):
    """
    Sort addresses geo-based by street and house number numerically.
    Preserves all original columns exactly.
    """
    # Create a working copy with original index to preserve row relationships
    working_df = df.copy()
    working_df['original_index'] = working_df.index
    
    # Add geocoding data
    for i, geocoded in enumerate(geocoded_data):
        if i < len(working_df):
            working_df.loc[i, 'latitude'] = geocoded.get('latitude')
            working_df.loc[i, 'longitude'] = geocoded.get('longitude')
            working_df.loc[i, 'geocoded_address'] = geocoded.get('formatted_address', '')
            working_df.loc[i, 'street_from_geocoding'] = geocoded.get('street', '')
    
    # Detect address columns
    street_col = None
    house_num_col = None
    
    for col in working_df.columns:
        col_lower = col.lower().strip()
        if any(keyword in col_lower for keyword in ['projektname strasse', 'strasse', 'straße', 'street']):
            street_col = col
        elif any(keyword in col_lower for keyword in ['hausnummer', 'haus nummer', 'nummer', 'nr']):
            house_num_col = col
    
    if not street_col or not house_num_col:
        print("Warning: Could not detect street and house number columns for sorting")
        # Return original DataFrame with distance calculations
        distances = []
        for i in range(len(df)):
            if i < len(df) - 1:
                try:
                    current_lat = working_df.loc[i, 'latitude'] 
                    current_lon = working_df.loc[i, 'longitude']
                    next_lat = working_df.loc[i+1, 'latitude']
                    next_lon = working_df.loc[i+1, 'longitude']
                    
                    if (current_lat is not None and current_lon is not None and
                        next_lat is not None and next_lon is not None):
                        distance = calculate_distance_meters(current_lat, current_lon, next_lat, next_lon)
                        distances.append(round(distance) if distance else None)
                    else:
                        distances.append(None)
                except:
                    distances.append(None)
            else:
                distances.append(None)
        
        # Add distance column to original df
        result_df = df.copy()
        result_df['Entfernung_zur_naechsten_Adresse_m'] = distances
        result_df['Breitengrad'] = [geocoded_data[i].get('latitude') if i < len(geocoded_data) else None for i in range(len(result_df))]
        result_df['Laengengrad'] = [geocoded_data[i].get('longitude') if i < len(geocoded_data) else None for i in range(len(result_df))]
        result_df['Geocodierte_Adresse'] = [geocoded_data[i].get('formatted_address', '') if i < len(geocoded_data) else '' for i in range(len(result_df))]
        
        return result_df, distances
    
    # Clean and extract house number parts with proper error handling
    house_number_data = []
    for idx, value in working_df[house_num_col].items():
        try:
            numeric, letter = extract_house_number_parts(value)
            house_number_data.append((numeric, letter))
        except Exception as e:
            print(f"Error processing house number '{value}': {e}")
            house_number_data.append((0, ''))
    
    working_df['house_number_numeric'] = [data[0] for data in house_number_data]
    working_df['house_number_letter'] = [data[1] for data in house_number_data]
    
    # Clean street names for grouping - more conservative approach
    working_df['street_clean'] = working_df[street_col].astype(str).str.strip()
    
    # Remove project prefixes like "Worpswede " from street names - but be more careful
    def clean_street_name(street_name):
        if pd.isna(street_name) or str(street_name).strip() == '':
            return ''
        
        street = str(street_name).strip()
        
        # Remove specific project prefixes we know about
        if street.startswith('Worpswede '):
            street = street[10:].strip()
        
        # Remove other short numeric/code prefixes (but be conservative)
        # Only remove if it's a short code followed by space and actual street name
        parts = street.split()
        if len(parts) > 1 and len(parts[0]) <= 4 and parts[0].isalnum():
            # Check if the rest looks like a street name
            remaining = ' '.join(parts[1:])
            if any(char.isalpha() for char in remaining):
                street = remaining
        
        return street.strip()
    
    working_df['street_clean'] = working_df[street_col].apply(clean_street_name)
    
    # Debug: Print unique street names to verify grouping
    unique_streets = working_df['street_clean'].value_counts()
    print(f"Debug: Found {len(unique_streets)} unique streets:")
    for street, count in unique_streets.head(10).items():
        print(f"  - '{street}': {count} addresses")
    
    # Fill NaN values for sorting
    working_df['street_clean'] = working_df['street_clean'].fillna('')
    
    # Ensure numeric values are integers and not NaN
    working_df['house_number_numeric'] = working_df['house_number_numeric'].apply(
        lambda x: 0 if pd.isna(x) else int(x)
    )
    working_df['house_number_letter'] = working_df['house_number_letter'].fillna('')
    
    # Sort by street name (PRIMARY), then house number (SECONDARY), then letter (TERTIARY)
    try:
        # IMPORTANT FIX: We need to ensure the sorting is stable and properly groups streets
        # First, create a categorical variable for street names to ensure they stay together
        street_categories = pd.Categorical(working_df['street_clean'], 
                                          categories=sorted(working_df['street_clean'].unique()),
                                          ordered=True)
        working_df['street_category'] = street_categories
        
        # Now sort with the categorical street first
        working_df_sorted = working_df.sort_values([
            'street_category',        # PRIMARY: Group by street first (as categorical)
            'house_number_numeric',   # SECONDARY: Then by house number
            'house_number_letter'     # TERTIARY: Then by letter suffix
        ], na_position='last')
        
        print(f"Debug: Sorting completed. First 10 addresses after sorting:")
        for i in range(min(10, len(working_df_sorted))):
            row = working_df_sorted.iloc[i]
            print(f"  {i+1}. {row['street_clean']} {row['house_number_numeric']}{row['house_number_letter']}")
            
    except Exception as e:
        print(f"Error during sorting: {e}")
        # Fallback to original order
        working_df_sorted = working_df
    
    # Calculate distances to next address
    distances = []
    for i in range(len(working_df_sorted)):
        if i < len(working_df_sorted) - 1:
            try:
                current_row = working_df_sorted.iloc[i]
                next_row = working_df_sorted.iloc[i + 1]
                
                current_lat = current_row.get('latitude')
                current_lon = current_row.get('longitude')
                next_lat = next_row.get('latitude')
                next_lon = next_row.get('longitude')
                
                if (current_lat is not None and current_lon is not None and
                    next_lat is not None and next_lon is not None and
                    not pd.isna(current_lat) and not pd.isna(current_lon) and
                    not pd.isna(next_lat) and not pd.isna(next_lon)):
                    distance = calculate_distance_meters(current_lat, current_lon, next_lat, next_lon)
                    distances.append(round(distance) if distance else None)
                else:
                    distances.append(None)
            except Exception as e:
                print(f"Error calculating distance for row {i}: {e}")
                distances.append(None)
        else:
            distances.append(None)  # Last address has no next address
    
    # Get the original data in the new order but preserve ALL original columns
    try:
        original_indices = working_df_sorted['original_index'].tolist()
        sorted_df = df.iloc[original_indices].copy()
    except Exception as e:
        print(f"Error reordering original data: {e}")
        sorted_df = df.copy()
    
    # Add the distance column
    sorted_df['Entfernung_zur_naechsten_Adresse_m'] = distances
    
    # Add geocoding information as additional columns
    sorted_df['Breitengrad'] = working_df_sorted['latitude'].values if 'latitude' in working_df_sorted.columns else [None] * len(sorted_df)
    sorted_df['Laengengrad'] = working_df_sorted['longitude'].values if 'longitude' in working_df_sorted.columns else [None] * len(sorted_df)
    sorted_df['Geocodierte_Adresse'] = working_df_sorted['geocoded_address'].values if 'geocoded_address' in working_df_sorted.columns else [''] * len(sorted_df)
    
    return sorted_df, distances

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two points in kilometers using Haversine formula"""
    if not all([lat1, lon1, lat2, lon2]):
        return float('inf')
    
    # Radius of Earth in kilometers
    R = 6371
    
    # Convert to radians
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    
    # Haversine formula
    a = (math.sin(delta_lat/2) * math.sin(delta_lat/2) +
         math.cos(lat1_rad) * math.cos(lat2_rad) *
         math.sin(delta_lon/2) * math.sin(delta_lon/2))
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    
    return R * c

def optimize_geographic_route(df, geocoded_data, addresses_to_geocode):
    """
    Optimize route geographically for door-to-door sales
    - Groups nearby addresses by geographic proximity  
    - Creates logical walking/driving routes
    - Calculates exact distances between consecutive stops
    """
    print("Starting geographic route optimization for door-to-door sales...")
    
    # Create working dataframe with geocoded data
    working_df = df.copy()
    working_df['original_address'] = addresses_to_geocode
    
    # Add geocoded coordinates
    for i, geocoded in enumerate(geocoded_data):
        if i < len(working_df):
            working_df.loc[i, 'latitude'] = geocoded.get('latitude')
            working_df.loc[i, 'longitude'] = geocoded.get('longitude')
            working_df.loc[i, 'formatted_address'] = geocoded.get('formatted_address', '')
    
    # Filter addresses that have valid coordinates
    valid_addresses = working_df.dropna(subset=['latitude', 'longitude']).copy()
    invalid_addresses = working_df[working_df['latitude'].isna() | working_df['longitude'].isna()].copy()
    
    if len(valid_addresses) == 0:
        print("No valid geocoded addresses for optimization")
        working_df['distance_to_next_m'] = None
        return working_df, 0
    
    print(f"Optimizing route for {len(valid_addresses)} valid addresses...")
    
    # Simple geographic optimization using nearest neighbor approach
    # Start from the first address
    route_order = []
    remaining_indices = list(valid_addresses.index)
    current_index = remaining_indices[0]
    remaining_indices.remove(current_index)
    route_order.append(current_index)
    
    # Build route by always going to nearest unvisited address
    while remaining_indices:
        current_lat = valid_addresses.loc[current_index, 'latitude']
        current_lon = valid_addresses.loc[current_index, 'longitude']
        
        min_distance = float('inf')
        next_index = None
        
        for candidate_index in remaining_indices:
            candidate_lat = valid_addresses.loc[candidate_index, 'latitude']
            candidate_lon = valid_addresses.loc[candidate_index, 'longitude']
            
            distance = calculate_distance_meters(current_lat, current_lon, candidate_lat, candidate_lon)
            if distance < min_distance:
                min_distance = distance
                next_index = candidate_index
        
        if next_index is not None:
            route_order.append(next_index)
            remaining_indices.remove(next_index)
            current_index = next_index
    
    # Create optimized dataframe
    optimized_valid = valid_addresses.loc[route_order].copy()
    
    # Calculate distances between consecutive addresses
    distances = []
    total_distance = 0
    
    for i in range(len(optimized_valid)):
        if i < len(optimized_valid) - 1:
            current_row = optimized_valid.iloc[i]
            next_row = optimized_valid.iloc[i + 1]
            
            distance = calculate_distance_meters(
                current_row['latitude'], current_row['longitude'],
                next_row['latitude'], next_row['longitude']
            )
            distances.append(round(distance) if distance else 0)
            total_distance += distance if distance else 0
        else:
            distances.append(None)  # Last address has no next address
    
    optimized_valid['distance_to_next_m'] = distances
    
    # Add invalid addresses at the end
    if len(invalid_addresses) > 0:
        invalid_addresses['distance_to_next_m'] = None
        optimized_df = pd.concat([optimized_valid, invalid_addresses], ignore_index=True)
    else:
        optimized_df = optimized_valid
    
    print(f"Route optimization completed. Total distance: {total_distance/1000:.2f} km")
    
    return optimized_df, total_distance
def calculate_distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> Optional[float]:
    """Calculate distance between two points in meters using Haversine formula"""
    if not all([lat1, lon1, lat2, lon2]):
        return None
    
    # Radius of Earth in meters
    R = 6371000
    
    # Convert to radians
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    
    # Haversine formula
    a = (math.sin(delta_lat/2) * math.sin(delta_lat/2) +
         math.cos(lat1_rad) * math.cos(lat2_rad) *
         math.sin(delta_lon/2) * math.sin(delta_lon/2))
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    
    return R * c

async def geocode_address_with_cache(address: str) -> dict:
    """Geocode an address with caching and retry logic for performance"""
    try:
        # Check cache first
        if address in address_cache:
            cached_result = address_cache[address]
            return {
                'latitude': cached_result['lat'],
                'longitude': cached_result['lon'],
                'formatted_address': cached_result['formatted'],
                'error': cached_result['error']
            }
        
        # Reduced delay for better performance (0.3 seconds instead of 0.5)
        await asyncio.sleep(0.3)
        
        url = "https://nominatim.openstreetmap.org/search"
        params = {
            'q': address,
            'format': 'json',
            'limit': 1,
            'addressdetails': 1,
            'accept-language': 'de,en'  # Prefer German results
        }
        
        headers = {
            'User-Agent': 'SalesRouteOptimizer/1.0 (Enterprise)',
            'Accept': 'application/json'
        }
        
        # Retry logic for better reliability
        max_retries = 2
        error_msg = None
        
        for attempt in range(max_retries + 1):
            try:
                response = requests.get(url, params=params, headers=headers, timeout=15)
                response.raise_for_status()
                
                data = response.json()
                
                if data:
                    result = data[0]
                    lat = float(result['lat'])
                    lon = float(result['lon'])
                    formatted_address = result.get('display_name', address)
                    
                    # Enhanced cache with metadata
                    address_cache[address] = {
                        'lat': lat,
                        'lon': lon,
                        'formatted': formatted_address,
                        'error': None,
                        'cached_at': datetime.now(),
                        'source': 'nominatim'
                    }
                    
                    return {
                        'latitude': lat,
                        'longitude': lon,
                        'formatted_address': formatted_address,
                        'error': None
                    }
                else:
                    error_msg = f"No geocoding results found for: {address}"
                    break
                    
            except requests.exceptions.Timeout:
                if attempt < max_retries:
                    await asyncio.sleep(1)  # Wait before retry
                    continue
                error_msg = f"Geocoding timeout after {max_retries + 1} attempts: {address}"
                break
            except requests.exceptions.RequestException as e:
                if attempt < max_retries:
                    await asyncio.sleep(1)
                    continue
                error_msg = f"Geocoding API error after {max_retries + 1} attempts: {str(e)}"
                break
        
        # Cache negative results to avoid repeated failed requests
        address_cache[address] = {
            'lat': None,
            'lon': None,
            'formatted': None,
            'error': error_msg,
            'cached_at': datetime.now()
        }
        return {
            'latitude': None,
            'longitude': None,
            'formatted_address': None,
            'error': error_msg
        }
            
    except Exception as e:
        error_msg = f"Geocoding error: {str(e)}"
        return {
            'latitude': None,
            'longitude': None,
            'formatted_address': None,
            'error': error_msg
        }

def geocode_address_cached(address: str) -> tuple:
    """Geocode an address with caching for performance"""
    try:
        # Check cache first
        if address in address_cache:
            cached_result = address_cache[address]
            return cached_result['lat'], cached_result['lon'], cached_result['formatted'], cached_result['error']
        
        # Add reduced delay for better performance (0.5 seconds instead of 1)
        time.sleep(0.5)
        
        url = "https://nominatim.openstreetmap.org/search"
        params = {
            'q': address,
            'format': 'json',
            'limit': 1,
            'addressdetails': 1
        }
        
        headers = {
            'User-Agent': 'SalesRouteOptimizer/1.0'
        }
        
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        if data:
            result = data[0]
            lat = float(result['lat'])
            lon = float(result['lon'])
            formatted_address = result.get('display_name', address)
            
            # Cache the result
            address_cache[address] = {
                'lat': lat,
                'lon': lon,
                'formatted': formatted_address,
                'error': None
            }
            
            return lat, lon, formatted_address, None
        else:
            error_msg = f"No results found for address: {address}"
            address_cache[address] = {
                'lat': None,
                'lon': None,
                'formatted': None,
                'error': error_msg
            }
            return None, None, None, error_msg
            
    except requests.exceptions.RequestException as e:
        error_msg = f"Geocoding API error: {str(e)}"
        return None, None, None, error_msg
    except Exception as e:
        error_msg = f"Geocoding error: {str(e)}"
        return None, None, None, error_msg
def geocode_address(address: str) -> tuple:
    """Geocode an address with caching and retry logic for performance"""
    try:
        # Check cache first
        if address in address_cache:
            cached_result = address_cache[address]
            return cached_result['lat'], cached_result['lon'], cached_result['formatted'], cached_result['error']
        
        # Reduced delay for better performance (0.3 seconds instead of 0.5)
        time.sleep(0.3)
        
        url = "https://nominatim.openstreetmap.org/search"
        params = {
            'q': address,
            'format': 'json',
            'limit': 1,
            'addressdetails': 1,
            'accept-language': 'de,en'  # Prefer German results
        }
        
        headers = {
            'User-Agent': 'SalesRouteOptimizer/1.0 (Enterprise)',
            'Accept': 'application/json'
        }
        
        # Retry logic for better reliability
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                response = requests.get(url, params=params, headers=headers, timeout=15)
                response.raise_for_status()
                
                data = response.json()
                
                if data:
                    result = data[0]
                    lat = float(result['lat'])
                    lon = float(result['lon'])
                    formatted_address = result.get('display_name', address)
                    
                    # Enhanced cache with metadata
                    address_cache[address] = {
                        'lat': lat,
                        'lon': lon,
                        'formatted': formatted_address,
                        'error': None,
                        'cached_at': datetime.now(),
                        'source': 'nominatim'
                    }
                    
                    return lat, lon, formatted_address, None
                else:
                    error_msg = f"No geocoding results found for: {address}"
                    break
                    
            except requests.exceptions.Timeout:
                if attempt < max_retries:
                    time.sleep(1)  # Wait before retry
                    continue
                error_msg = f"Geocoding timeout after {max_retries + 1} attempts: {address}"
                break
            except requests.exceptions.RequestException as e:
                if attempt < max_retries:
                    time.sleep(1)
                    continue
                error_msg = f"Geocoding API error after {max_retries + 1} attempts: {str(e)}"
                break
        
        # Cache negative results to avoid repeated failed requests
        address_cache[address] = {
            'lat': None,
            'lon': None,
            'formatted': None,
            'error': error_msg,
            'cached_at': datetime.now()
        }
        return None, None, None, error_msg
            
    except Exception as e:
        error_msg = f"Geocoding error: {str(e)}"
        return None, None, None, error_msg

def optimize_route_improved(addresses: List[Address]) -> List[int]:
    """Advanced route optimization using Nearest Neighbor + 2-opt improvement"""
    if len(addresses) <= 1:
        return [0] if addresses else []
    
    # Filter only geocoded addresses
    geocoded_addresses = [addr for addr in addresses if addr.geocoded and addr.latitude and addr.longitude]
    
    if len(geocoded_addresses) <= 1:
        return [0] if geocoded_addresses else []
    
    # Create address index mapping
    address_map = {addr.id: i for i, addr in enumerate(addresses)}
    geocoded_indices = [address_map[addr.id] for addr in geocoded_addresses]
    
    # Step 1: Create initial route using nearest neighbor
    initial_route = nearest_neighbor_route(geocoded_addresses)
    
    # Step 2: Improve route using 2-opt algorithm
    if len(geocoded_addresses) <= 500:
        # For smaller datasets, use 2-opt improvement
        improved_route = two_opt_improvement(geocoded_addresses, initial_route)
    else:
        # For very large datasets, use clustering + 2-opt
        improved_route = cluster_based_optimization(geocoded_addresses, geocoded_indices)
    
    # Convert back to original indices
    optimized_indices = [geocoded_indices[i] for i in improved_route]
    return optimized_indices

def calculate_cluster_center(cluster: List[Address]) -> tuple:
    """Calculate geographic center of a cluster"""
    if not cluster:
        return (0, 0)
    
    avg_lat = sum(addr.latitude for addr in cluster) / len(cluster)
    avg_lon = sum(addr.longitude for addr in cluster) / len(cluster)
    return (avg_lat, avg_lon)

def nearest_neighbor_route(addresses: List[Address]) -> List[int]:
    """Optimized nearest neighbor algorithm"""
    n = len(addresses)
    if n <= 1:
        return list(range(n))
    
    # Try multiple starting points for better results
    best_route = None
    best_distance = float('inf')
    
    # Test different starting points (up to 5 for performance)
    start_points = min(5, n)
    for start in range(start_points):
        route = []
        unvisited = set(range(n))
        current = start
        route.append(current)
        unvisited.remove(current)
        total_distance = 0
        
        while unvisited:
            nearest_distance = float('inf')
            nearest_index = None
            
            current_addr = addresses[current]
            
            for next_index in unvisited:
                next_addr = addresses[next_index]
                distance = haversine_distance(
                    current_addr.latitude, current_addr.longitude,
                    next_addr.latitude, next_addr.longitude
                )
                
                if distance < nearest_distance:
                    nearest_distance = distance
                    nearest_index = next_index
            
            if nearest_index is not None:
                route.append(nearest_index)
                unvisited.remove(nearest_index)
                total_distance += nearest_distance
                current = nearest_index
        
        if total_distance < best_distance:
            best_distance = total_distance
            best_route = route
    
    return best_route if best_route else list(range(n))

def two_opt_improvement(addresses: List[Address], route: List[int]) -> List[int]:
    """2-opt algorithm to improve route efficiency"""
    def calculate_route_distance(addresses: List[Address], route: List[int]) -> float:
        total_distance = 0
        for i in range(len(route)):
            current = addresses[route[i]]
            next_addr = addresses[route[(i + 1) % len(route)]]
            total_distance += haversine_distance(
                current.latitude, current.longitude,
                next_addr.latitude, next_addr.longitude
            )
        return total_distance
    
    def two_opt_swap(route: List[int], i: int, j: int) -> List[int]:
        new_route = route[:i] + route[i:j+1][::-1] + route[j+1:]
        return new_route
    
    best_route = route[:]
    best_distance = calculate_route_distance(addresses, best_route)
    improved = True
    iterations = 0
    max_iterations = min(100, len(route) * 2)  # Limit iterations for performance
    
    while improved and iterations < max_iterations:
        improved = False
        iterations += 1
        
        for i in range(1, len(route) - 1):
            for j in range(i + 1, len(route)):
                if j - i == 1:
                    continue  # Skip adjacent edges
                
                new_route = two_opt_swap(best_route, i, j)
                new_distance = calculate_route_distance(addresses, new_route)
                
                if new_distance < best_distance:
                    best_route = new_route
                    best_distance = new_distance
                    improved = True
                    break
            
            if improved:
                break
    
    return best_route

def create_geographic_clusters_kmeans(addresses: List[Address], k: int) -> List[List[Address]]:
    """Improved K-means clustering for geographic data"""
    if k >= len(addresses):
        return [[addr] for addr in addresses]
    
    # Initialize centers using k-means++ method for better distribution
    centers = []
    centers.append(addresses[0])  # First center is random
    
    # Choose remaining centers with weighted probability
    for _ in range(1, k):
        distances = []
        for addr in addresses:
            min_dist = min(
                haversine_distance(addr.latitude, addr.longitude, center.latitude, center.longitude)
                for center in centers
            )
            distances.append(min_dist * min_dist)  # Square for better distribution
        
        # Choose next center with probability proportional to squared distance
        total_dist = sum(distances)
        if total_dist > 0:
            rand_val = total_dist * (len(centers) / k)  # Deterministic for consistency
            cumulative = 0
            for i, dist in enumerate(distances):
                cumulative += dist
                if cumulative >= rand_val:
                    centers.append(addresses[i])
                    break
        else:
            centers.append(addresses[len(centers)])
    
    # Assign addresses to clusters
    clusters = [[] for _ in range(k)]
    for addr in addresses:
        min_distance = float('inf')
        closest_cluster = 0
        
        for i, center in enumerate(centers):
            distance = haversine_distance(
                addr.latitude, addr.longitude,
                center.latitude, center.longitude
            )
            if distance < min_distance:
                min_distance = distance
                closest_cluster = i
        
        clusters[closest_cluster].append(addr)
    
    # Remove empty clusters
    return [cluster for cluster in clusters if cluster]

def nearest_neighbor_cluster_order(cluster_centers: List[tuple]) -> List[int]:
    """Optimize cluster visiting order using nearest neighbor"""
    if len(cluster_centers) <= 1:
        return list(range(len(cluster_centers)))
    
    unvisited = set(range(len(cluster_centers)))
    route = []
    current = 0  # Start with first cluster
    route.append(current)
    unvisited.remove(current)
    
    while unvisited:
        min_distance = float('inf')
        nearest = None
        current_center = cluster_centers[current]
        
        for next_idx in unvisited:
            next_center = cluster_centers[next_idx]
            distance = haversine_distance(
                current_center[0], current_center[1],
                next_center[0], next_center[1]
            )
            
            if distance < min_distance:
                min_distance = distance
                nearest = next_idx
        
        if nearest is not None:
            route.append(nearest)
            unvisited.remove(nearest)
            current = nearest
    
    return route

def cluster_based_optimization(addresses: List[Address], geocoded_indices: List[int]) -> List[int]:
    """Advanced clustering-based optimization for very large datasets"""
    # For very large datasets, use geographic clustering
    num_clusters = min(10, max(2, len(addresses) // 100))
    clusters = create_geographic_clusters_kmeans(addresses, num_clusters)
    
    route = []
    
    # Calculate cluster centers and optimize cluster order
    cluster_centers = [calculate_cluster_center(cluster) for cluster in clusters]
    cluster_order = nearest_neighbor_cluster_order(cluster_centers)
    
    # Optimize route within each cluster using 2-opt
    for cluster_idx in cluster_order:
        cluster = clusters[cluster_idx]
        if len(cluster) > 1:
            cluster_route = nearest_neighbor_route(cluster)
            if len(cluster) <= 50:  # Only use 2-opt for smaller clusters
                cluster_route = two_opt_improvement(cluster, cluster_route)
            
            # Convert cluster indices back to global indices
            global_indices = [addresses.index(cluster[i]) for i in cluster_route]
            route.extend(global_indices)
        elif len(cluster) == 1:
            route.append(addresses.index(cluster[0]))
    
    return route

async def process_upload_job(job_id: str, file_content: bytes, filename: str):
    """Background task to process uploaded file with enhanced error handling and performance"""
    try:
        # Update job status
        upload_jobs_collection.update_one(
            {"id": job_id},
            {"$set": {"status": "parsing"}}
        )
        
        # Parse Excel file with better error handling
        try:
            if filename.endswith('.csv'):
                df = pd.read_csv(BytesIO(file_content), encoding='utf-8')
            else:
                # Try multiple engines for Excel files
                try:
                    df = pd.read_excel(BytesIO(file_content), engine='openpyxl')
                except Exception:
                    df = pd.read_excel(BytesIO(file_content), engine='xlrd')
        except UnicodeDecodeError:
            # Try different encodings for CSV
            for encoding in ['latin-1', 'iso-8859-1', 'cp1252']:
                try:
                    df = pd.read_csv(BytesIO(file_content), encoding=encoding)
                    break
                except:
                    continue
            else:
                raise ValueError("Datei-Encoding konnte nicht erkannt werden. Bitte speichern Sie die Datei als UTF-8.")
        except Exception as e:
            upload_jobs_collection.update_one(
                {"id": job_id},
                {"$set": {"status": "error", "error_message": f"Datei konnte nicht gelesen werden: {str(e)}"}}
            )
            return
        
        # Detect specific Excel format with German column names
        street_col = None
        house_num_col = None
        zusatz_col = None
        plz_col = None
        ort_col = None
        
        # Map specific German column names to address components
        for col in df.columns:
            col_lower = col.lower().strip()
            if any(keyword in col_lower for keyword in ['projektname strasse', 'strasse', 'straße', 'street']):
                street_col = col
            elif any(keyword in col_lower for keyword in ['hausnummer', 'haus nummer', 'nummer', 'nr']):
                house_num_col = col
            elif any(keyword in col_lower for keyword in ['zusatz', 'zusätze']):
                zusatz_col = col
            elif any(keyword in col_lower for keyword in ['plz', 'postleitzahl', 'postal']):
                plz_col = col
            elif any(keyword in col_lower for keyword in ['ort', 'stadt', 'city', 'location']):
                ort_col = col
        
        # Check if we have German format (separate columns)
        has_german_format = street_col and house_num_col and plz_col and ort_col
        
        print(f"Detected columns: Street={street_col}, House={house_num_col}, PLZ={plz_col}, Ort={ort_col}, Zusatz={zusatz_col}")
        print(f"German format detected: {has_german_format}")
        
        # Find single address column as fallback
        address_column = None
        if not has_german_format:
            for col in df.columns:
                col_lower = col.lower()
                if any(keyword in col_lower for keyword in ['address', 'adresse', 'street', 'location', 'addr']):
                    address_column = col
                    break
            
            if address_column is None:
                # Use first column if no address column found
                address_column = df.columns[0]
        
        addresses = []
        total_addresses = len(df)
        
        # Update job with total count
        upload_jobs_collection.update_one(
            {"id": job_id},
            {"$set": {"total_addresses": total_addresses, "status": "geocoding"}}
        )
        
        # Process addresses
        for index, row in df.iterrows():
            # Build complete address based on format
            if has_german_format:
                # German format: combine separate columns
                street = str(row[street_col]).strip() if street_col else ""
                house_num = str(row[house_num_col]).strip() if house_num_col else ""
                zusatz = str(row[zusatz_col]).strip() if zusatz_col else ""
                plz = str(row[plz_col]).strip() if plz_col else ""
                ort = str(row[ort_col]).strip() if ort_col else ""
                
                # Skip empty rows
                if not street or not ort or street.lower() == 'nan' or ort.lower() == 'nan':
                    continue
                
                # Combine into full address
                address_parts = []
                
                # Street name from "Projektname Strasse" column
                street_clean = street.replace("Worpswede ", "").strip()
                
                # Combine street with house number and zusatz
                street_part = street_clean
                if house_num and house_num.lower() != 'nan':
                    street_part += f" {house_num}"
                    if zusatz and zusatz.lower() != 'nan':
                        street_part += f" {zusatz}"
                
                address_parts.append(street_part)
                
                # Add PLZ and Ort
                if plz and plz.lower() != 'nan':
                    if ort:
                        address_parts.append(f"{plz} {ort}")
                    else:
                        address_parts.append(plz)
                elif ort:
                    address_parts.append(ort)
                
                address_text = ", ".join(address_parts)
                print(f"Combined address: {address_text}")
            else:
                # Single address column format
                address_text = str(row[address_column]).strip()
                if not address_text or address_text.lower() == 'nan':
                    continue
            
            address_id = str(uuid.uuid4())
            
            # Geocode address with caching
            lat, lon, formatted_addr, error = geocode_address(address_text)
            
            address = {
                "id": address_id,
                "job_id": job_id,
                "original_address": address_text,
                "formatted_address": formatted_addr,
                "latitude": lat,
                "longitude": lon,
                "geocoded": lat is not None and lon is not None,
                "geocoding_error": error,
                # ALLE ursprünglichen Excel-Daten speichern
                "original_row_data": {col: str(row[col]) if pd.notna(row[col]) else "" for col in df.columns},
                "original_row_index": index
            }
            
            addresses.append(address)
            
            # Update progress
            upload_jobs_collection.update_one(
                {"id": job_id},
                {"$set": {
                    "processed_addresses": len(addresses),
                    "geocoded_addresses": len([a for a in addresses if a["geocoded"]])
                }}
            )
        
        # Save addresses to database
        if addresses:
            addresses_collection.insert_many(addresses)
        
        # Update job status to optimizing
        upload_jobs_collection.update_one(
            {"id": job_id},
            {"$set": {"status": "optimizing"}}
        )
        
        # Create Address objects for optimization
        address_objects = [Address(**addr) for addr in addresses]
        
        # Optimize route
        optimized_order = optimize_route_improved(address_objects)
        
        # Calculate total distance
        total_distance = 0
        if len(optimized_order) > 1:
            for i in range(len(optimized_order) - 1):
                current = address_objects[optimized_order[i]]
                next_addr = address_objects[optimized_order[i + 1]]
                
                if current.geocoded and next_addr.geocoded:
                    distance = haversine_distance(
                        current.latitude, current.longitude,
                        next_addr.latitude, next_addr.longitude
                    )
                    total_distance += distance
        
        # Save route
        route = {
            "id": str(uuid.uuid4()),
            "job_id": job_id,
            "optimized_order": optimized_order,
            "total_distance": total_distance,
            "created_at": datetime.now()
        }
        
        routes_collection.insert_one(route)
        
        # Update job as completed
        upload_jobs_collection.update_one(
            {"id": job_id},
            {"$set": {
                "status": "completed",
                "completed_at": datetime.now()
            }}
        )
        
    except Exception as e:
        # Update job with error
        upload_jobs_collection.update_one(
            {"id": job_id},
            {"$set": {
                "status": "error",
                "error_message": str(e)
            }}
        )

@app.post("/api/preview")
async def preview_file(file: UploadFile = File(...)):
    """Preview Excel file structure before processing"""
    
    # Validate file type
    if not file.filename.endswith(('.xlsx', '.xls', '.csv')):
        raise HTTPException(status_code=400, detail="Only Excel (.xlsx, .xls) and CSV files are supported")
    
    try:
        # Read file content
        file_content = await file.read()
        
        # Parse Excel file - READ ALL ROWS for preview
        if file.filename.endswith('.csv'):
            df = pd.read_csv(BytesIO(file_content))  # Alle Zeilen lesen
        else:
            df = pd.read_excel(BytesIO(file_content))  # Alle Zeilen lesen
        
        # Clean DataFrame - replace NaN/Infinity values
        df = df.fillna("")
        df = df.replace([float('inf'), -float('inf')], "")
        
        # Convert all columns to string to avoid JSON serialization issues
        for col in df.columns:
            df[col] = df[col].astype(str)
        
        # Detect columns
        street_col = None
        house_num_col = None
        zusatz_col = None
        plz_col = None
        ort_col = None
        
        for col in df.columns:
            col_lower = col.lower().strip()
            if any(keyword in col_lower for keyword in ['projektname strasse', 'strasse', 'straße', 'street']):
                street_col = col
            elif any(keyword in col_lower for keyword in ['hausnummer', 'haus nummer', 'nummer', 'nr']):
                house_num_col = col
            elif any(keyword in col_lower for keyword in ['zusatz', 'zusätze']):
                zusatz_col = col
            elif any(keyword in col_lower for keyword in ['plz', 'postleitzahl', 'postal']):
                plz_col = col
            elif any(keyword in col_lower for keyword in ['ort', 'stadt', 'city', 'location']):
                ort_col = col
        
        has_german_format = street_col and house_num_col and plz_col and ort_col
        
        # Generate preview addresses - show ALL addresses, not just first 5
        preview_addresses = []
        for index, row in df.iterrows():
            if has_german_format:
                street = str(row[street_col]).strip() if street_col else ""
                house_num = str(row[house_num_col]).strip() if house_num_col else ""
                zusatz = str(row[zusatz_col]).strip() if zusatz_col else ""
                plz = str(row[plz_col]).strip() if plz_col else ""
                ort = str(row[ort_col]).strip() if ort_col else ""
                
                if street and ort and street.lower() not in ['nan', ''] and ort.lower() not in ['nan', '']:
                    street_clean = street.replace("Worpswede ", "").strip()
                    street_part = street_clean
                    if house_num and house_num.lower() not in ['nan', '']:
                        street_part += f" {house_num}"
                        if zusatz and zusatz.lower() not in ['nan', '']:
                            street_part += f" {zusatz}"
                    
                    if plz and plz.lower() not in ['nan', '']:
                        combined_address = f"{street_part}, {plz} {ort}"
                    else:
                        combined_address = f"{street_part}, {ort}"
                    
                    preview_addresses.append({
                        "index": index + 1,
                        "address": combined_address,
                        "original_parts": {
                            "street": street_clean,
                            "house_number": house_num,
                            "zusatz": zusatz,
                            "plz": plz,
                            "ort": ort
                        }
                    })
        
        # Clean sample data for JSON serialization
        sample_data = df.head(5).to_dict('records')
        
        # Ensure all values in sample_data are JSON serializable
        for record in sample_data:
            for key, value in record.items():
                if pd.isna(value) or value in [float('inf'), -float('inf')]:
                    record[key] = ""
                else:
                    record[key] = str(value)
        
        return {
            "filename": file.filename,
            "total_rows": int(len(df)),
            "columns": list(df.columns),
            "detected_format": "German (separate columns)" if has_german_format else "Single address column",
            "detected_columns": {
                "street": street_col,
                "house_number": house_num_col,
                "zusatz": zusatz_col,
                "plz": plz_col,
                "ort": ort_col
            },
            "preview_addresses": preview_addresses,
            "sample_data": sample_data
        }
        
    except Exception as e:
        print(f"Preview error: {str(e)}")
        raise HTTPException(status_code=400, detail=f"File preview error: {str(e)}")

async def process_street_sorted_job(job_id: str, file_content: bytes, filename: str):
    """Background task to process uploaded file with street-based sorting"""
    try:
        # Update job status
        upload_jobs_collection.update_one(
            {"id": job_id},
            {"$set": {"status": "parsing"}}
        )
        
        # Parse file
        try:
            if filename.endswith('.csv'):
                df = pd.read_csv(BytesIO(file_content), encoding='utf-8')
            else:
                try:
                    df = pd.read_excel(BytesIO(file_content), engine='openpyxl')
                except Exception:
                    df = pd.read_excel(BytesIO(file_content), engine='xlrd')
        except UnicodeDecodeError:
            for encoding in ['latin-1', 'iso-8859-1', 'cp1252']:
                try:
                    df = pd.read_csv(BytesIO(file_content), encoding=encoding)
                    break
                except:
                    continue
            else:
                raise ValueError("Datei-Encoding konnte nicht erkannt werden.")
        except Exception as e:
            upload_jobs_collection.update_one(
                {"id": job_id},
                {"$set": {"status": "error", "error_message": f"Datei konnte nicht gelesen werden: {str(e)}"}}
            )
            return
        
        # Detect address format and create address list
        street_col = house_num_col = zusatz_col = plz_col = ort_col = None
        
        for col in df.columns:
            col_lower = col.lower().strip()
            if any(keyword in col_lower for keyword in ['projektname strasse', 'strasse', 'straße', 'street']):
                street_col = col
            elif any(keyword in col_lower for keyword in ['hausnummer', 'haus nummer', 'nummer', 'nr']):
                house_num_col = col
            elif any(keyword in col_lower for keyword in ['zusatz', 'zusätze']):
                zusatz_col = col
            elif any(keyword in col_lower for keyword in ['plz', 'postleitzahl', 'postal']):
                plz_col = col
            elif any(keyword in col_lower for keyword in ['ort', 'stadt', 'city', 'location']):
                ort_col = col
        
        has_german_format = street_col and house_num_col and plz_col and ort_col
        
        # Create address strings for geocoding
        addresses_to_geocode = []
        if has_german_format:
            for idx, row in df.iterrows():
                street = str(row[street_col]).strip() if pd.notna(row[street_col]) else ""
                house_num = str(row[house_num_col]).strip() if pd.notna(row[house_num_col]) else ""
                zusatz = str(row[zusatz_col]).strip() if zusatz_col and pd.notna(row[zusatz_col]) else ""
                plz = str(row[plz_col]).strip() if pd.notna(row[plz_col]) else ""
                ort = str(row[ort_col]).strip() if pd.notna(row[ort_col]) else ""
                
                # Clean street name - remove project prefixes
                if street.startswith('Worpswede '):
                    street = street[10:].strip()
                elif ' ' in street and len(street.split()[0]) < 4:
                    # Remove short prefixes that might be project codes
                    parts = street.split()
                    if parts[0].isalnum() and len(parts) > 1:
                        street = ' '.join(parts[1:])
                
                # Combine address parts
                if zusatz and zusatz != 'nan':
                    address = f"{street} {house_num} {zusatz}, {plz} {ort}"
                else:
                    address = f"{street} {house_num}, {plz} {ort}"
                
                addresses_to_geocode.append(address.strip())
        else:
            # Look for single address column
            address_column = None
            for col in df.columns:
                if any(keyword in col.lower() for keyword in ['address', 'adresse', 'addr']):
                    address_column = col
                    break
            
            if not address_column:
                upload_jobs_collection.update_one(
                    {"id": job_id},
                    {"$set": {"status": "error", "error_message": "Keine Adress-Spalten gefunden"}}
                )
                return
            
            addresses_to_geocode = df[address_column].astype(str).tolist()
        
        # Update status and counts
        total_addresses = len(addresses_to_geocode)
        upload_jobs_collection.update_one(
            {"id": job_id},
            {"$set": {
                "status": "geocoding",
                "total_addresses": total_addresses,
                "processed_addresses": 0,
                "geocoded_addresses": 0
            }}
        )
        
        # Geocode all addresses
        geocoded_data = []
        geocoded_count = 0
        
        for i, address in enumerate(addresses_to_geocode):
            try:
                print(f"Geocoding address {i+1}/{total_addresses}: {address}")
                geocoded = await geocode_address_with_cache(address)
                
                # Extract street name from geocoded result if available
                street_name = ""
                if geocoded.get('formatted_address'):
                    # Try to extract street name from formatted address
                    parts = geocoded.get('formatted_address', '').split(',')
                    if parts and len(parts) > 0:
                        street_part = parts[0].strip()
                        # Extract just the street name without the number
                        street_words = street_part.split()
                        if len(street_words) > 1 and any(c.isdigit() for c in street_words[-1]):
                            street_name = ' '.join(street_words[:-1])
                        else:
                            street_name = street_part
                
                # Add street name to geocoded data
                geocoded['street'] = street_name
                
                geocoded_data.append(geocoded)
                if geocoded.get('latitude') and geocoded.get('longitude'):
                    geocoded_count += 1
                    print(f"✅ Successfully geocoded: {address}")
                else:
                    print(f"❌ Failed to geocode: {address} - {geocoded.get('error', 'Unknown error')}")
                
                # Update progress
                upload_jobs_collection.update_one(
                    {"id": job_id},
                    {"$set": {
                        "processed_addresses": i + 1,
                        "geocoded_addresses": geocoded_count
                    }}
                )
                
                # Rate limiting
                await asyncio.sleep(0.5)  # Increased delay for better success rate
                
            except Exception as e:
                print(f"Geocoding error for address {address}: {e}")
                geocoded_data.append({})
        
        # Sort addresses by street and house number
        upload_jobs_collection.update_one(
            {"id": job_id},
            {"$set": {"status": "sorting"}}
        )
        
        # IMPROVED SORTING IMPLEMENTATION
        # Create a working copy with original index to preserve row relationships
        working_df = df.copy()
        working_df['original_index'] = working_df.index
        
        # Add geocoding data
        for i, geocoded in enumerate(geocoded_data):
            if i < len(working_df):
                working_df.loc[i, 'latitude'] = geocoded.get('latitude')
                working_df.loc[i, 'longitude'] = geocoded.get('longitude')
                working_df.loc[i, 'geocoded_address'] = geocoded.get('formatted_address', '')
                working_df.loc[i, 'street_from_geocoding'] = geocoded.get('street', '')
        
        # Detect address columns
        if has_german_format:
            # Clean street names for grouping
            working_df['street_clean'] = working_df[street_col].astype(str).str.strip()
            
            # Remove project prefixes like "Worpswede " from street names
            def clean_street_name(street_name):
                if pd.isna(street_name) or str(street_name).strip() == '':
                    return ''
                
                street = str(street_name).strip()
                
                # Remove specific project prefixes we know about
                if street.startswith('Worpswede '):
                    street = street[10:].strip()
                
                # Remove other short numeric/code prefixes
                parts = street.split()
                if len(parts) > 1 and len(parts[0]) <= 4 and parts[0].isalnum():
                    # Check if the rest looks like a street name
                    remaining = ' '.join(parts[1:])
                    if any(char.isalpha() for char in remaining):
                        street = remaining
                
                return street.strip()
            
            working_df['street_clean'] = working_df[street_col].apply(clean_street_name)
            
            # Extract house number parts for sorting
            def extract_house_number_parts(value):
                if pd.isna(value) or str(value).strip() == '':
                    return (0, '')
                
                house_str = str(value).strip()
                match = re.match(r'^(\d+)([A-Za-z]*).*', house_str)
                if match:
                    try:
                        number = int(match.group(1))
                        letter = match.group(2).upper() if match.group(2) else ''
                        return (number, letter)
                    except ValueError:
                        return (0, house_str)
                else:
                    numbers = re.findall(r'\d+', house_str)
                    if numbers:
                        try:
                            return (int(numbers[0]), '')
                        except ValueError:
                            return (0, house_str)
                    else:
                        return (0, house_str)
            
            # Process house numbers
            working_df['house_number_numeric'] = 0
            working_df['house_number_letter'] = ''
            
            for idx, row in working_df.iterrows():
                try:
                    house_num = row[house_num_col] if pd.notna(row[house_num_col]) else 0
                    numeric, letter = extract_house_number_parts(house_num)
                    working_df.loc[idx, 'house_number_numeric'] = numeric
                    working_df.loc[idx, 'house_number_letter'] = letter
                    
                    # Handle letter suffix for sorting (e.g., 10A should come after 10)
                    if zusatz_col and pd.notna(row[zusatz_col]) and row[zusatz_col]:
                        working_df.loc[idx, 'house_number_letter'] = str(row[zusatz_col]).strip()
                except Exception as e:
                    print(f"Error processing house number: {e}")
            
            # Ensure numeric values are integers
            working_df['house_number_numeric'] = working_df['house_number_numeric'].fillna(0).astype(int)
            working_df['house_number_letter'] = working_df['house_number_letter'].fillna('')
            
            # Group by street and sort by house number
            try:
                # First, create a categorical variable for street names to ensure they stay together
                unique_streets = sorted(working_df['street_clean'].unique())
                street_categories = pd.Categorical(working_df['street_clean'], 
                                                categories=unique_streets,
                                                ordered=True)
                working_df['street_category'] = street_categories
                
                # Sort by street first, then house number
                working_df_sorted = working_df.sort_values(
                    ['street_category', 'house_number_numeric', 'house_number_letter'],
                    na_position='last'
                )
                
                # Debug output
                print("Sorted addresses:")
                for i in range(min(10, len(working_df_sorted))):
                    row = working_df_sorted.iloc[i]
                    print(f"{i+1}. {row['street_clean']} {row['house_number_numeric']}{row['house_number_letter']}")
                
                # Get the original indices in the new order
                original_indices = working_df_sorted['original_index'].tolist()
                sorted_df = df.iloc[original_indices].copy()
                
                # Calculate distances between consecutive addresses
                distances = []
                for i in range(len(working_df_sorted)):
                    if i < len(working_df_sorted) - 1:
                        current_row = working_df_sorted.iloc[i]
                        next_row = working_df_sorted.iloc[i + 1]
                        
                        current_lat = current_row.get('latitude')
                        current_lon = current_row.get('longitude')
                        next_lat = next_row.get('latitude')
                        next_lon = next_row.get('longitude')
                        
                        if (current_lat is not None and current_lon is not None and
                            next_lat is not None and next_lon is not None and
                            not pd.isna(current_lat) and not pd.isna(current_lon) and
                            not pd.isna(next_lat) and not pd.isna(next_lon)):
                            distance = calculate_distance_meters(current_lat, current_lon, next_lat, next_lon)
                            distances.append(round(distance) if distance else None)
                        else:
                            distances.append(None)
                    else:
                        distances.append(None)  # Last address has no next address
                
                # Add distance and geocoding columns to the sorted DataFrame
                sorted_df['Entfernung_zur_naechsten_Adresse_m'] = distances
                sorted_df['Breitengrad'] = working_df_sorted['latitude'].values
                sorted_df['Laengengrad'] = working_df_sorted['longitude'].values
                sorted_df['Geocodierte_Adresse'] = working_df_sorted['geocoded_address'].values
                
            except Exception as e:
                print(f"Error during sorting: {e}")
                # Fallback to original order
                sorted_df = df.copy()
                distances = [None] * len(sorted_df)
                sorted_df['Entfernung_zur_naechsten_Adresse_m'] = distances
                sorted_df['Breitengrad'] = working_df['latitude'].values if 'latitude' in working_df.columns else [None] * len(sorted_df)
                sorted_df['Laengengrad'] = working_df['longitude'].values if 'longitude' in working_df.columns else [None] * len(sorted_df)
                sorted_df['Geocodierte_Adresse'] = working_df['geocoded_address'].values if 'geocoded_address' in working_df.columns else [''] * len(sorted_df)
        else:
            # If we don't have German format, just use the original order
            sorted_df = df.copy()
            distances = [None] * len(sorted_df)
            sorted_df['Entfernung_zur_naechsten_Adresse_m'] = distances
            sorted_df['Breitengrad'] = [geocoded_data[i].get('latitude') if i < len(geocoded_data) else None for i in range(len(sorted_df))]
            sorted_df['Laengengrad'] = [geocoded_data[i].get('longitude') if i < len(geocoded_data) else None for i in range(len(sorted_df))]
            sorted_df['Geocodierte_Adresse'] = [geocoded_data[i].get('formatted_address', '') if i < len(geocoded_data) else '' for i in range(len(sorted_df))]
        
        # Store results in database
        sorted_addresses = []
        for idx, row in sorted_df.iterrows():
            # Find the corresponding geocoded data for this row
            original_idx = idx
            geocoded_info = geocoded_data[original_idx] if original_idx < len(geocoded_data) else {}
            
            # Convert any NaN or infinity values to None for JSON serialization
            row_dict = {}
            for k, v in row.to_dict().items():
                if isinstance(v, float) and (pd.isna(v) or math.isinf(v)):
                    row_dict[k] = None
                else:
                    row_dict[k] = v
            
            address_data = {
                "id": str(uuid.uuid4()),
                "original_address": addresses_to_geocode[original_idx] if original_idx < len(addresses_to_geocode) else "",
                "latitude": geocoded_info.get('latitude'),
                "longitude": geocoded_info.get('longitude'),
                "formatted_address": geocoded_info.get('formatted_address', ''),
                "geocoded": bool(geocoded_info.get('latitude') and geocoded_info.get('longitude')),
                "distance_to_next": None if pd.isna(row.get('Entfernung_zur_naechsten_Adresse_m')) else row.get('Entfernung_zur_naechsten_Adresse_m'),
                "row_data": row_dict  # Store all original data with NaN values converted to None
            }
            sorted_addresses.append(address_data)
        
        # Store in database
        route_data = {
            "job_id": job_id,
            "sorted_addresses": sorted_addresses,
            "total_distance": sum(d for d in distances if d is not None),
            "created_at": datetime.utcnow(),
            "sorting_type": "street_based"
        }
        
        routes_collection.insert_one(route_data)
        
        # Update job as completed
        upload_jobs_collection.update_one(
            {"id": job_id},
            {"$set": {
                "status": "completed",
                "geocoded_addresses": geocoded_count,
                "completed_at": datetime.utcnow()
            }}
        )
        
        print(f"Street-sorted job {job_id} completed successfully with {geocoded_count}/{total_addresses} geocoded addresses")
        
    except Exception as e:
        print(f"Error in street sorting job {job_id}: {e}")
        upload_jobs_collection.update_one(
            {"id": job_id},
            {"$set": {
                "status": "error",
                "error_message": str(e)
            }}
        )

# New endpoint for street-based sorting
@app.post("/api/upload-street-sorted")
async def upload_file_street_sorted(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """Upload file for street-based address sorting"""
    if not file.filename.lower().endswith(('.xlsx', '.xls', '.csv')):
        raise HTTPException(status_code=400, detail="Nur Excel (.xlsx, .xls) und CSV Dateien sind erlaubt")
    
    try:
        file_content = await file.read()
        
        # Create job
        job_id = str(uuid.uuid4())
        job_data = {
            "id": job_id,
            "filename": file.filename,
            "status": "uploading",
            "created_at": datetime.utcnow(),
            "total_addresses": 0,
            "processed_addresses": 0,
            "geocoded_addresses": 0,
            "sorting_type": "street_based"
        }
        
        upload_jobs_collection.insert_one(job_data)
        
        # Start background processing
        background_tasks.add_task(process_street_sorted_job, job_id, file_content, file.filename)
        
        return {"job_id": job_id, "status": "uploading", "message": "Datei wird für Straßen-Sortierung verarbeitet"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler beim Upload: {str(e)}")

# New endpoint for street-sorted export
@app.get("/api/street-sorted/{job_id}/export")
async def export_street_sorted_route(job_id: str):
    """Export street-sorted addresses as Excel file"""
    try:
        # Get route data from database
        route_data = routes_collection.find_one({"job_id": job_id, "sorting_type": "street_based"})
        if not route_data:
            raise HTTPException(status_code=404, detail="Street-sorted route not found")
        
        # Get job info
        job = upload_jobs_collection.find_one({"id": job_id})
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        
        # Prepare data for Excel export
        addresses = route_data['sorted_addresses']
        
        # Create DataFrame from sorted addresses preserving all original columns
        rows = []
        for addr in addresses:
            row_data = addr.get('row_data', {})
            rows.append(row_data)
        
        df = pd.DataFrame(rows)
        
        # Create Excel file with enhanced formatting
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            # Main sheet with sorted addresses
            df.to_excel(writer, sheet_name='Straßen-sortierte Adressen', index=False)
            
            # Get workbook and worksheet
            workbook = writer.book
            worksheet = writer.sheets['Straßen-sortierte Adressen']
            
            # Style header row
            header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
            header_font = Font(color="FFFFFF", bold=True)
            
            for cell in worksheet[1]:
                cell.fill = header_fill
                cell.font = header_font
            
            # Auto-adjust column widths
            for column in worksheet.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = min(max_length + 2, 50)
                worksheet.column_dimensions[column_letter].width = adjusted_width
            
            # Summary sheet
            summary_data = {
                'Datei': [job['filename']],
                'Verarbeitungsdatum': [job['created_at'].strftime('%d.%m.%Y %H:%M:%S')],
                'Gesamte Adressen': [len(addresses)],
                'Erfolgreich geocodiert': [sum(1 for addr in addresses if addr.get('geocoded', False))],
                'Sortierung': ['Nach Straße und Hausnummer'],
                'Gesamtstrecke (m)': [route_data.get('total_distance', 0)]
            }
            
            summary_df = pd.DataFrame(summary_data)
            summary_df.to_excel(writer, sheet_name='Zusammenfassung', index=False)
            
            # Style summary sheet
            summary_ws = writer.sheets['Zusammenfassung']
            for cell in summary_ws[1]:
                cell.fill = header_fill
                cell.font = header_font
            
            for column in summary_ws.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = min(max_length + 2, 50)
                summary_ws.column_dimensions[column_letter].width = adjusted_width
        
        output.seek(0)
        
        # Prepare filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"straßen_sortiert_{timestamp}.xlsx"
        
        return StreamingResponse(
            BytesIO(output.read()),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except Exception as e:
        print(f"Error exporting street-sorted route: {e}")
        raise HTTPException(status_code=500, detail=f"Fehler beim Excel-Export: {str(e)}")

@app.get("/api/street-sorted/{job_id}")
async def get_street_sorted_route(job_id: str):
    """Get street-sorted route data"""
    try:
        route_data = routes_collection.find_one({"job_id": job_id, "sorting_type": "street_based"})
        if not route_data:
            raise HTTPException(status_code=404, detail="Street-sorted route not found")
        
        # Convert MongoDB ObjectId to string
        route_data["_id"] = str(route_data["_id"])
        
        # Handle NaN and infinity values for JSON serialization
        def clean_for_json(obj):
            if isinstance(obj, dict):
                return {k: clean_for_json(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [clean_for_json(item) for item in obj]
            elif isinstance(obj, float):
                # Replace NaN and infinity with None
                if math.isnan(obj) or math.isinf(obj):
                    return None
                return obj
            else:
                return obj
        
        # Clean the data for JSON serialization
        cleaned_data = clean_for_json(route_data)
        
        return cleaned_data
        
    except Exception as e:
        print(f"Error fetching street-sorted route: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching street-sorted route: {str(e)}")

@app.post("/api/upload")
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...)
):
    """Upload and process Excel file with addresses"""
    
    # Validate file type
    if not file.filename.endswith(('.xlsx', '.xls', '.csv')):
        raise HTTPException(status_code=400, detail="Only Excel (.xlsx, .xls) and CSV files are supported")
    
    # Read file content
    file_content = await file.read()
    
    # Create job
    job_id = str(uuid.uuid4())
    job = {
        "id": job_id,
        "filename": file.filename,
        "status": "uploading",
        "total_addresses": 0,
        "processed_addresses": 0,
        "geocoded_addresses": 0,
        "error_message": None,
        "created_at": datetime.now(),
        "completed_at": None
    }
    
    upload_jobs_collection.insert_one(job)
    
    # Start background processing
    background_tasks.add_task(process_upload_job, job_id, file_content, file.filename)
    
    return {"job_id": job_id, "message": "File uploaded successfully, processing started"}

@app.get("/api/job/{job_id}")
async def get_job_status(job_id: str):
    """Get job status and progress"""
    job = upload_jobs_collection.find_one({"id": job_id})
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Convert MongoDB document to dict and handle datetime
    job_data = {
        "id": job["id"],
        "filename": job["filename"],
        "status": job["status"],
        "total_addresses": job["total_addresses"],
        "processed_addresses": job["processed_addresses"],
        "geocoded_addresses": job["geocoded_addresses"],
        "error_message": job.get("error_message"),
        "created_at": job["created_at"].isoformat() if job["created_at"] else None,
        "completed_at": job["completed_at"].isoformat() if job.get("completed_at") else None,
        "sorting_type": job.get("sorting_type", "route_optimization")  # Add sorting_type
    }
    
    return job_data

@app.get("/api/route/{job_id}/export")
async def export_route_excel(job_id: str):
    """Export optimized route as Excel file with all original columns"""
    from fastapi.responses import StreamingResponse
    
    # Check if job exists and is completed
    job = upload_jobs_collection.find_one({"id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job["status"] != "completed":
        raise HTTPException(status_code=400, detail="Job is not completed yet")
    
    # Get route and addresses
    route = routes_collection.find_one({"job_id": job_id})
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    
    addresses = list(addresses_collection.find({"job_id": job_id}))
    
    # Create Excel workbook with original data structure
    try:
        wb = openpyxl.Workbook()
        
        # Remove default sheet
        wb.remove(wb.active)
        
        # Get original column structure from first address
        original_columns = []
        if addresses and addresses[0].get("original_row_data"):
            original_columns = list(addresses[0]["original_row_data"].keys())
        
        # Create optimized route sheet with ALL original columns
        ws_route = wb.create_sheet("Geosortierte Route")
        
        # Define styles
        header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        header_font = Font(color="FFFFFF", bold=True)
        success_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
        error_fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
        
        # Headers: New order column + ALL original columns + geocoding info
        route_headers = ["Neue_Reihenfolge"] + original_columns + [
            "Formatierte_Adresse", "Breitengrad", "Längengrad", "Geocodiert", "Geocoding_Fehler"
        ]
        
        # Write headers
        for col, header in enumerate(route_headers, 1):
            cell = ws_route.cell(row=1, column=col, value=header)
            cell.fill = header_fill
            cell.font = header_font
        
        # Write optimized data with ALL original columns
        for order_index, addr_index in enumerate(route["optimized_order"]):
            if addr_index < len(addresses):
                addr = addresses[addr_index]
                row_idx = order_index + 2
                
                # New order number
                ws_route.cell(row=row_idx, column=1, value=order_index + 1)
                
                # ALL original Excel columns
                if addr.get("original_row_data"):
                    for col_idx, col_name in enumerate(original_columns, 2):
                        original_value = addr["original_row_data"].get(col_name, "")
                        ws_route.cell(row=row_idx, column=col_idx, value=original_value)
                
                # Geocoding information
                geo_start_col = len(original_columns) + 2
                ws_route.cell(row=row_idx, column=geo_start_col, value=addr.get("formatted_address", ""))
                ws_route.cell(row=row_idx, column=geo_start_col + 1, value=addr.get("latitude", ""))
                ws_route.cell(row=row_idx, column=geo_start_col + 2, value=addr.get("longitude", ""))
                ws_route.cell(row=row_idx, column=geo_start_col + 3, value="Ja" if addr.get("geocoded") else "Nein")
                ws_route.cell(row=row_idx, column=geo_start_col + 4, value=addr.get("geocoding_error", ""))
                
                # Apply styling based on geocoding status
                fill_color = success_fill if addr.get("geocoded") else error_fill
                for col in range(1, len(route_headers) + 1):
                    ws_route.cell(row=row_idx, column=col).fill = fill_color
        
        # Auto-adjust column widths
        for column in ws_route.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 50)
            ws_route.column_dimensions[column_letter].width = adjusted_width
        
        # Create summary sheet
        ws_summary = wb.create_sheet("Zusammenfassung")
        ws_summary.cell(row=1, column=1, value="🚀 Sales Route Optimizer - Zusammenfassung").font = Font(bold=True, size=16)
        
        summary_data = [
            ("", ""),
            ("📄 Datei-Informationen:", ""),
            ("Dateiname:", job["filename"]),
            ("Upload-Datum:", job["created_at"].strftime("%d.%m.%Y %H:%M:%S") if job.get("created_at") else ""),
            ("Fertigstellung:", job["completed_at"].strftime("%d.%m.%Y %H:%M:%S") if job.get("completed_at") else ""),
            ("", ""),
            ("📊 Verarbeitungs-Statistiken:", ""),
            ("Gesamtanzahl Adressen:", str(job["total_addresses"])),
            ("Verarbeitete Adressen:", str(job["processed_addresses"])),
            ("Erfolgreich geocodiert:", str(job["geocoded_addresses"])),
            ("Geocoding-Erfolgsrate:", f"{(job['geocoded_addresses']/job['total_addresses']*100):.1f}%" if job["total_addresses"] > 0 else "0%"),
            ("", ""),
            ("🗺️ Route-Optimierung:", ""),
            ("Gesamtdistanz:", f"{route['total_distance']:.2f} km"),
            ("Optimierungsmethode:", "Nearest Neighbor + 2-opt Verbesserung"),
            ("Anzahl Stopps in Route:", str(len(route["optimized_order"]))),
            ("", ""),
            ("📈 Performance-Verbesserung:", ""),
            ("Geschätzte Zeitersparnis:", "20-40% gegenüber unoptimierter Route"),
            ("Geschätzte Kraftstoffersparnis:", "15-30% durch optimierte Distanzen"),
            ("", ""),
            ("ℹ️ Hinweise:", ""),
            ("Reihenfolge basiert auf:", "Geografische Distanzen zwischen Adressen"),
            ("Algorithmus:", "Nearest Neighbor mit 2-opt Verbesserung"),
            ("Cache-Optimierung:", "Bereits geocodierte Adressen werden wiederverwendet"),
            ("", ""),
            ("📧 Support:", "Bei Fragen wenden Sie sich an Ihren Administrator"),
            ("🕐 Erstellt am:", datetime.now().strftime("%d.%m.%Y %H:%M:%S"))
        ]
        
        for row_idx, (label, value) in enumerate(summary_data, 1):
            if label:
                ws_summary.cell(row=row_idx, column=1, value=label).font = Font(bold=True)
                ws_summary.cell(row=row_idx, column=2, value=value)
        
        # Set column widths for summary
        ws_summary.column_dimensions['A'].width = 35
        ws_summary.column_dimensions['B'].width = 40
        
        # Create distance matrix sheet (for analysis)
        ws_distances = wb.create_sheet("Distanz-Analyse")
        ws_distances.cell(row=1, column=1, value="Distanz-Analyse zwischen Adressen").font = Font(bold=True, size=14)
        ws_distances.cell(row=3, column=1, value="Reihenfolge").font = Font(bold=True)
        ws_distances.cell(row=3, column=2, value="Von Adresse").font = Font(bold=True)
        ws_distances.cell(row=3, column=3, value="Zu Adresse").font = Font(bold=True)
        ws_distances.cell(row=3, column=4, value="Distanz (km)").font = Font(bold=True)
        
        # Calculate distances between consecutive addresses in optimized route
        total_calc_distance = 0
        for i in range(len(route["optimized_order"]) - 1):
            current_idx = route["optimized_order"][i]
            next_idx = route["optimized_order"][i + 1]
            
            if current_idx < len(addresses) and next_idx < len(addresses):
                current_addr = addresses[current_idx]
                next_addr = addresses[next_idx]
                
                if (current_addr.get("geocoded") and next_addr.get("geocoded") and 
                    current_addr.get("latitude") and current_addr.get("longitude") and
                    next_addr.get("latitude") and next_addr.get("longitude")):
                    
                    distance = haversine_distance(
                        current_addr["latitude"], current_addr["longitude"],
                        next_addr["latitude"], next_addr["longitude"]
                    )
                    total_calc_distance += distance
                    
                    row = i + 4
                    ws_distances.cell(row=row, column=1, value=i + 1)
                    ws_distances.cell(row=row, column=2, value=current_addr["original_address"])
                    ws_distances.cell(row=row, column=3, value=next_addr["original_address"])
                    ws_distances.cell(row=row, column=4, value=f"{distance:.2f}")
        
        # Add total
        final_row = len(route["optimized_order"]) + 4
        ws_distances.cell(row=final_row, column=3, value="GESAMT:").font = Font(bold=True)
        ws_distances.cell(row=final_row, column=4, value=f"{total_calc_distance:.2f}").font = Font(bold=True)
        
        # Auto-adjust column widths for distance sheet
        for column in ws_distances.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 60)
            ws_distances.column_dimensions[column_letter].width = adjusted_width
        
        # Save to BytesIO
        excel_buffer = BytesIO()
        wb.save(excel_buffer)
        excel_buffer.seek(0)
        
        # Create filename with German format
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"Optimierte_Route_{job['filename'].split('.')[0]}_{timestamp}.xlsx"
        
        return StreamingResponse(
            BytesIO(excel_buffer.getvalue()),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except Exception as e:
        print(f"Excel export error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Excel export error: {str(e)}")

@app.get("/api/route/{job_id}")
async def get_route(job_id: str):
    """Get optimized route for a job"""
    
    # Check if job exists and is completed
    job = upload_jobs_collection.find_one({"id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job["status"] != "completed":
        raise HTTPException(status_code=400, detail="Job is not completed yet")
    
    # Get route
    route = routes_collection.find_one({"job_id": job_id})
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    
    # Get addresses
    addresses = list(addresses_collection.find({"job_id": job_id}))
    
    # Convert to proper format
    address_objects = []
    for addr in addresses:
        address_objects.append({
            "id": addr["id"],
            "original_address": addr["original_address"],
            "formatted_address": addr.get("formatted_address"),
            "latitude": addr.get("latitude"),
            "longitude": addr.get("longitude"),
            "geocoded": addr.get("geocoded", False),
            "geocoding_error": addr.get("geocoding_error")
        })
    
    # Create ordered addresses based on optimized route
    optimized_addresses = []
    for index in route["optimized_order"]:
        if index < len(address_objects):
            optimized_addresses.append(address_objects[index])
    
    return {
        "id": route["id"],
        "job_id": job_id,
        "addresses": address_objects,
        "optimized_addresses": optimized_addresses,
        "total_distance": route["total_distance"],
        "created_at": route["created_at"].isoformat()
    }

@app.get("/api/jobs")
async def get_jobs():
    """Get all upload jobs"""
    jobs = list(upload_jobs_collection.find().sort("created_at", -1))
    
    # Convert to proper format
    job_list = []
    for job in jobs:
        job_data = {
            "id": job["id"],
            "filename": job["filename"],
            "status": job["status"],
            "total_addresses": job["total_addresses"],
            "processed_addresses": job["processed_addresses"],
            "geocoded_addresses": job["geocoded_addresses"],
            "error_message": job.get("error_message"),
            "created_at": job["created_at"].isoformat() if job["created_at"] else None,
            "completed_at": job["completed_at"].isoformat() if job.get("completed_at") else None,
            "sorting_type": job.get("sorting_type", "route_optimization")  # Add sorting_type
        }
        job_list.append(job_data)
    
    return job_list

@app.delete("/api/job/{job_id}")
async def delete_job(job_id: str):
    """Delete a job and its associated data"""
    
    # Delete addresses
    addresses_collection.delete_many({"job_id": job_id})
    
    # Delete route
    routes_collection.delete_many({"job_id": job_id})
    
    # Delete job
    result = upload_jobs_collection.delete_one({"id": job_id})
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return {"message": "Job deleted successfully"}

@app.get("/api/cache/stats")
async def get_cache_stats():
    """Get geocoding cache statistics for performance monitoring"""
    cache_size = len(address_cache)
    
    # Count successful vs failed entries
    successful = sum(1 for entry in address_cache.values() if entry['lat'] is not None)
    failed = cache_size - successful
    
    # Calculate cache hit rate (estimated)
    total_requests = successful + failed
    hit_rate = (successful / total_requests * 100) if total_requests > 0 else 0
    
    return {
        "cache_size": cache_size,
        "successful_geocodes": successful,
        "failed_geocodes": failed,
        "estimated_hit_rate": f"{hit_rate:.1f}%",
        "memory_usage_estimate": f"{cache_size * 0.5:.1f}KB"  # Rough estimate
    }

@app.delete("/api/cache/clear")
async def clear_geocoding_cache():
    """Clear geocoding cache (admin function)"""
    global address_cache
    old_size = len(address_cache)
    address_cache.clear()
    
    return {
        "message": f"Cache cleared successfully. Removed {old_size} entries.",
        "new_cache_size": 0
    }
    """Health check endpoint"""
    return {"status": "healthy", "message": "Sales Route Optimizer API is running"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)