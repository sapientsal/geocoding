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
import aiohttp
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
import openpyxl
from openpyxl.styles import PatternFill, Font
import signal
import threading
import traceback
from openpyxl.utils.dataframe import dataframe_to_rows

def clean_numeric_string(value) -> str:
    """
    CRITICAL FIX: Convert numeric values to clean strings without .0 decimal points
    
    Problem: Excel stores numbers as floats (31275.0, 118.0), and str() keeps the .0
    This breaks geocoding because "31275.0 Lehrte" is invalid for OpenStreetMap
    
    Solution: Convert floats to ints before string conversion
    
    Examples:
        31275.0 -> "31275"  (not "31275.0")
        118.0 -> "118"      (not "118.0")
        "9 b" -> "9 b"      (strings unchanged)
    """
    if pd.isna(value) or value is None:
        return ""
    
    # If it's a numeric type (int or float)
    if isinstance(value, (int, float)):
        # Check if it's a whole number (no decimal part)
        if float(value).is_integer():
            # Convert to int to remove .0
            return str(int(value))
        else:
            # Keep decimal if it's not a whole number
            return str(value)
    
    # For strings and other types, just convert to string
    return str(value).strip()

def clean_dataframe_for_excel(df: pd.DataFrame) -> pd.DataFrame:
    """
    CRITICAL FIX: Clean DataFrame before Excel export to prevent NaTType errors
    
    Problem: NaT (Not a Time) datetime values cause "NaTType does not support utcoffset" error
    when writing to Excel via pandas.to_excel()
    
    Solution: Replace all NaT values in datetime columns with None before export
    
    Args:
        df: DataFrame to clean
        
    Returns:
        Cleaned DataFrame with NaT values replaced by None
    """
    df_clean = df.copy()
    
    # Clean datetime columns
    for col in df_clean.columns:
        if pd.api.types.is_datetime64_any_dtype(df_clean[col]):
            # Replace NaT with None (which Excel can handle)
            df_clean[col] = df_clean[col].apply(lambda x: None if pd.isna(x) else x)
    
    return df_clean

def apply_percentage_formatting(worksheet, df: pd.DataFrame, sheet_name: str = None):
    """
    CRITICAL FIX: Apply Excel percentage formatting to columns with '%' in their name
    
    Problem: Columns like "Penetration % aktuell" contain decimal values (0.5, 1.0)
    which should be displayed as percentages (50%, 100%) in Excel
    
    Solution: Automatically detect columns with '%' in the name and apply Excel's
    native percentage formatting
    
    Args:
        worksheet: openpyxl worksheet object
        df: DataFrame that was exported (to get column names)
        sheet_name: Optional sheet name for logging
        
    Returns:
        Modified worksheet with percentage formatting applied
    """
    from openpyxl.styles import numbers
    
    # Find all columns with '%' in the name
    percentage_columns = [col for col in df.columns if '%' in str(col)]
    
    if not percentage_columns:
        return worksheet
    
    # Get column indices (1-based for Excel)
    column_indices = []
    for pct_col in percentage_columns:
        try:
            col_idx = df.columns.get_loc(pct_col) + 1  # +1 because Excel is 1-indexed
            column_indices.append((col_idx, pct_col))
        except KeyError:
            continue
    
    # Apply percentage formatting to these columns
    for col_idx, col_name in column_indices:
        # Get the Excel column letter
        from openpyxl.utils import get_column_letter
        col_letter = get_column_letter(col_idx)
        
        # Apply formatting to all cells in this column (skip header row)
        for row in range(2, worksheet.max_row + 1):
            cell = worksheet[f'{col_letter}{row}']
            if cell.value is not None and isinstance(cell.value, (int, float)):
                # Apply percentage format: 0.5 → 50.0%, 1 → 100.0%
                cell.number_format = '0.0%'
    
    return worksheet


app = FastAPI(
    title="Sales Route Optimizer API",
    description="API for optimizing sales routes with geocoding and route optimization",
    version="1.0.0"
)


@app.on_event("startup")
async def on_startup():
    """On startup, mark any orphaned in-progress jobs as errored (server was killed mid-run)."""
    try:
        upload_jobs_collection.update_many(
            {"status": {"$in": ["parsing", "geocoding", "sorting", "optimizing"]}},
            {"$set": {
                "status": "error",
                "error_message": "Server wurde neu gestartet – Job abgebrochen. Bitte Datei erneut hochladen."
            }}
        )
        print("✅ Startup: Orphaned jobs cleaned up")
    except Exception as e:
        print(f"⚠️ Startup cleanup failed: {e}")

# Global variables for caching and monitoring
address_cache = {}
active_jobs = {}
job_logs = {}

# Multi-API geocoding configuration
LOCATIONIQ_KEY = os.environ.get('LOCATIONIQ_KEY', '')
GEOAPIFY_KEY = os.environ.get('GEOAPIFY_KEY', '')
OPENCAGE_KEY = os.environ.get('OPENCAGE_KEY', '')

# API health tracker: per-API cooldown (unix timestamp until which it's blocked)
api_cooldown = {
    'photon': 0,
    'locationiq': 0,
    'geoapify': 0,
    'opencage': 0,
    'nominatim': 0,
}

# Job singleton lock: only one geocoding job runs at a time
_geocoding_job_lock = asyncio.Lock()

class JobLogger:
    """Centralized logging for jobs with frontend visibility"""
    
    def __init__(self, job_id):
        self.job_id = job_id
        self.logs = []
        self.start_time = datetime.utcnow()
        
    def log(self, level, message, address_index=None, address=None):
        """Add a log entry"""
        timestamp = datetime.utcnow()
        log_entry = {
            "timestamp": timestamp.isoformat(),
            "level": level,  # INFO, WARNING, ERROR, CRITICAL
            "message": message,
            "address_index": address_index,
            "address": address,
            "elapsed_time": (timestamp - self.start_time).total_seconds()
        }
        self.logs.append(log_entry)
        
        # Keep only last 1000 log entries to prevent memory issues
        if len(self.logs) > 1000:
            self.logs = self.logs[-1000:]
        
        # Update job logs in global storage
        job_logs[self.job_id] = self.logs
        
        print(f"[{level}] Job {self.job_id}: {message}")
        
    def get_logs(self):
        """Get all logs for this job"""
        return self.logs
    
    def get_recent_logs(self, count=50):
        """Get recent logs"""
        return self.logs[-count:] if self.logs else []

def cleanup_job_monitoring(job_id):
    """Clean up job monitoring resources"""
    if job_id in active_jobs:
        del active_jobs[job_id]
    if job_id in job_logs:
        # Keep logs for 24 hours for debugging
        # In production, you might want to move this to a persistent storage
        pass

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
    # Database collections
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
    ort_col = None
    teilort_col = None
    
    for col in working_df.columns:
        col_lower = col.lower().strip()
        if any(keyword in col_lower for keyword in ['projektname strasse', 'strasse', 'straße', 'street']):
            street_col = col
        elif any(keyword in col_lower for keyword in ['hausnummer', 'haus nummer', 'haus-nummer']) or (col_lower == 'nummer' or col_lower == 'nr' or col_lower == 'nr.' or col_lower == 'hnr' or col_lower == 'number'):
            house_num_col = col
        elif any(keyword in col_lower for keyword in ['ort', 'stadt', 'city', 'location', 'municipality']) and 'teil' not in col_lower:
            # Only match "Ort" columns, not "Teilort"
            ort_col = col
        elif any(keyword in col_lower for keyword in ['teilort', 'stadtteil', 'ortsteil', 'district']):
            # Keep Teilort separate for potential future use
            teilort_col = col
    
    # CRITICAL FIX: For geocoding, prefer "Ort" (main city) over "Teilort" (sub-locality)
    # "Teilort" alone often fails geocoding (e.g., "Aligse" without "Lehrte")
    # Use "Ort" if available, otherwise fall back to "Teilort"
    if not ort_col and teilort_col:
        ort_col = teilort_col
    
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
        # Only strip codes containing digits – NEVER German words like "Vor", "Am", "Alte"
        parts = street.split()
        if len(parts) > 1 and len(parts[0]) <= 4 and parts[0].isalnum() and any(c.isdigit() for c in parts[0]):
            # Check if the rest looks like a street name
            remaining = ' '.join(parts[1:])
            if any(char.isalpha() for char in remaining):
                street = remaining
        
        return street.strip()
    
    working_df['street_clean'] = working_df[street_col].apply(clean_street_name)
    
    # CRITICAL FIX: Create street_city_key for proper grouping
    # This ensures that same street names in different cities are treated as separate streets
    # Include Ortsteil so identical street names in different Ortsteilen stay separate
    def create_street_city_key(row):
        street = str(row['street_clean']).strip()
        city = str(row.get(ort_col, '')).strip() if ort_col else ''
        ot = str(row.get(teilort_col, '')).strip() if teilort_col else ''
        
        if street == '' or street == 'nan':
            return ''
        
        if ot and ot.lower() not in ('', 'nan', 'null', 'none') and ot != city:
            return f"{street}, {ot}, {city}" if city and city != 'nan' else f"{street}, {ot}"
        # Create unique key: "Straße, Stadt"
        if city and city != '' and city != 'nan':
            return f"{street}, {city}"
        else:
            return street
    
    working_df['street_city_key'] = working_df.apply(create_street_city_key, axis=1)
    
    # Debug: Print unique street-city combinations to verify grouping
    unique_streets = working_df['street_city_key'].value_counts()
    print(f"Debug: Found {len(unique_streets)} unique streets:")
    for street, count in unique_streets.head(10).items():
        print(f"  - '{street}': {count} addresses")
    
    # Fill NaN values for sorting
    working_df['street_clean'] = working_df['street_clean'].fillna('')
    working_df['street_city_key'] = working_df['street_city_key'].fillna('')
    
    # Ensure numeric values are integers and not NaN
    working_df['house_number_numeric'] = working_df['house_number_numeric'].apply(
        lambda x: 0 if pd.isna(x) else int(x)
    )
    working_df['house_number_letter'] = working_df['house_number_letter'].fillna('')
    
    # Sort by street+city (PRIMARY), then house number (SECONDARY), then letter (TERTIARY)
    try:
        # CRITICAL FIX: Create categorical variable for street_city_key to ensure proper grouping
        # This ensures that "Weidenweg, Peitz" and "Weidenweg, Turnow-Preilack" are separate groups
        street_city_categories = pd.Categorical(working_df['street_city_key'], 
                                               categories=sorted(working_df['street_city_key'].unique()),
                                               ordered=True)
        working_df['street_city_category'] = street_city_categories
        
        # Now sort with the categorical street+city first
        working_df_sorted = working_df.sort_values([
            'street_city_category',      # PRIMARY: Group by street+city first (as categorical)
            'house_number_numeric',      # SECONDARY: Then by house number
            'house_number_letter'        # TERTIARY: Then by letter suffix
        ], na_position='last')
        
        print(f"Debug: Sorting completed with street+city grouping. First 10 addresses after sorting:")
        for i in range(min(10, len(working_df_sorted))):
            row = working_df_sorted.iloc[i]
            print(f"  {i+1}. {row['street_city_key']} {row['house_number_numeric']}{row['house_number_letter']}")
        
        # Debug: Show unique street+city combinations
        print(f"\nDebug: Street+City groups found:")
        for street_city in sorted(working_df_sorted['street_city_key'].unique()):
            if street_city != '':
                count = len(working_df_sorted[working_df_sorted['street_city_key'] == street_city])
                print(f"  - '{street_city}': {count} addresses")
            
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
    - Groups addresses by street name first
    - Sorts house numbers numerically within each street
    - Optimizes route between street groups geographically
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
            working_df.loc[i, 'geocoded'] = geocoded.get('geocoded', False)
            working_df.loc[i, 'geocoding_error'] = geocoded.get('error', '')
    
    # Detect street and house number columns for proper sorting
    street_col = house_num_col = ort_col = teilort_col = None
    
    for col in working_df.columns:
        col_lower = col.lower().strip()
        if any(keyword in col_lower for keyword in ['projektname strasse', 'strasse', 'straße', 'street']):
            street_col = col
        elif any(keyword in col_lower for keyword in ['hausnummer', 'haus nummer', 'haus-nummer']) or (col_lower == 'nummer' or col_lower == 'nr' or col_lower == 'nr.' or col_lower == 'hnr' or col_lower == 'number'):
            house_num_col = col
        elif any(keyword in col_lower for keyword in ['ort', 'stadt', 'city', 'location', 'municipality']) and 'teil' not in col_lower:
            # Only match "Ort" columns, not "Teilort"
            ort_col = col
        elif any(keyword in col_lower for keyword in ['teilort', 'stadtteil', 'ortsteil', 'district']):
            # Keep Teilort separate
            teilort_col = col
    
    # CRITICAL FIX: For geocoding, prefer "Ort" (main city) over "Teilort" (sub-locality)
    if not ort_col and teilort_col:
        ort_col = teilort_col
    
    print(f"Detected columns - Street: {street_col}, House Number: {house_num_col}, City: {ort_col}")
    
    # If we have street and house number columns, do street-based sorting first
    if street_col and house_num_col:
        print("Applying street-based sorting with numeric house numbers...")
        
        # Clean street names
        def clean_street_name(street_name):
            if pd.isna(street_name) or str(street_name).strip() == '':
                return ''
            
            street = str(street_name).strip()
            
            # Handle German address format: "624 Worpswede Albert-Schwedt-Weg"
            # Remove project code and city prefix
            parts = street.split()
            if len(parts) >= 3:
                # Check if first part is numeric (project code)
                if parts[0].isdigit():
                    # Remove first part (project code)
                    remaining = ' '.join(parts[1:])
                    
                    # Check if second part is a city name like "Worpswede"
                    if len(parts) >= 3 and parts[1].isalpha():
                        # Remove city name too, keep only street name
                        street = ' '.join(parts[2:])
                    else:
                        street = remaining
            
            # Additional cleanup for common prefixes
            if street.startswith('Worpswede '):
                street = street[10:].strip()
            
            return street.strip()
        
        working_df['street_clean'] = working_df[street_col].apply(clean_street_name)
        
        # CRITICAL FIX: Create street_city_key for proper grouping
        # Include Ortsteil so identical street names in different Ortsteilen stay separate
        def create_street_city_key(row):
            street = str(row['street_clean']).strip()
            city = str(row.get(ort_col, '')).strip() if ort_col else ''
            ot = str(row.get(teilort_col, '')).strip() if teilort_col else ''
            
            if street == '' or street == 'nan':
                return ''
            
            if ot and ot.lower() not in ('', 'nan', 'null', 'none') and ot != city:
                return f"{street}, {ot}, {city}" if city and city != 'nan' else f"{street}, {ot}"
            # Create unique key: "Straße, Stadt"
            if city and city != '' and city != 'nan':
                return f"{street}, {city}"
            else:
                return street
        
        working_df['street_city_key'] = working_df.apply(create_street_city_key, axis=1)
        
        # Extract house number parts for proper numeric sorting
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
        
        # Fill NaN values
        working_df['street_clean'] = working_df['street_clean'].fillna('')
        working_df['street_city_key'] = working_df['street_city_key'].fillna('')
        working_df['house_number_numeric'] = working_df['house_number_numeric'].fillna(0)
        working_df['house_number_letter'] = working_df['house_number_letter'].fillna('')
        
        # Sort by street+city FIRST, then house number SECOND
        try:
            working_df_sorted = working_df.sort_values([
                'street_city_key',        # PRIMARY: Group by street+city
                'house_number_numeric',   # SECONDARY: Numeric house number
                'house_number_letter'     # TERTIARY: Letter suffix
            ], na_position='last')
            
            print("Street+City-based sorting completed. Sample of sorted addresses:")
            for i in range(min(15, len(working_df_sorted))):
                row = working_df_sorted.iloc[i]
                house_display = f"{int(row['house_number_numeric'])}{row['house_number_letter']}" if row['house_number_numeric'] > 0 else "?"
                print(f"  {i+1:2d}. {row['street_city_key']:<35} {house_display}")
                
        except Exception as e:
            print(f"Error during street-based sorting: {e}")
            working_df_sorted = working_df
        
        # ── Ausreißer-Korrektur: falsch geocodierte Einzeladressen zurückholen ──
        # Eine Adresse >2 km vom Median ihrer Straße (oder >30 km vom Median der
        # Gesamtliste) wurde von der Geocoding-API falsch zugeordnet und wird auf
        # den Straßen-Median gesetzt, damit Route & Distanzen stimmen.
        try:
            valid_all = working_df_sorted.dropna(subset=['latitude', 'longitude'])
            if len(valid_all) >= 3:
                global_med_lat = valid_all['latitude'].median()
                global_med_lon = valid_all['longitude'].median()
                corrected = 0
                for sck in working_df_sorted['street_city_key'].unique():
                    if sck == '':
                        continue
                    mask = working_df_sorted['street_city_key'] == sck
                    grp = working_df_sorted[mask].dropna(subset=['latitude', 'longitude'])
                    if len(grp) == 0:
                        continue
                    med_lat = grp['latitude'].median()
                    med_lon = grp['longitude'].median()
                    for idx in grp.index:
                        lat = working_df_sorted.at[idx, 'latitude']
                        lon = working_df_sorted.at[idx, 'longitude']
                        d_street = calculate_distance_meters(lat, lon, med_lat, med_lon)
                        d_global = calculate_distance_meters(lat, lon, global_med_lat, global_med_lon)
                        is_outlier = (len(grp) >= 3 and d_street is not None and d_street > 2000) or \
                                     (d_global is not None and d_global > 30000)
                        if is_outlier:
                            # Ziel: Straßen-Median wenn plausibel, sonst globaler Median
                            tgt_lat, tgt_lon = med_lat, med_lon
                            d_med_global = calculate_distance_meters(med_lat, med_lon, global_med_lat, global_med_lon)
                            if len(grp) < 3 or (d_med_global is not None and d_med_global > 30000):
                                tgt_lat, tgt_lon = global_med_lat, global_med_lon
                            working_df_sorted.at[idx, 'latitude'] = tgt_lat
                            working_df_sorted.at[idx, 'longitude'] = tgt_lon
                            working_df_sorted.at[idx, 'geocoding_error'] = 'Koordinate korrigiert: API-Treffer lag weit entfernt (Ausreißer)'
                            corrected += 1
                            print(f"  ⚠️ Ausreißer korrigiert: '{sck}' Index {idx} lag {round((d_street or d_global)/1000, 1)} km entfernt")
                if corrected:
                    print(f"⚠️ Ausreißer-Korrektur: {corrected} falsch geocodierte Adressen auf Straßen-Median gesetzt")
        except Exception as e:
            print(f"Outlier correction skipped: {e}")
        
        # Now apply geographic optimization between street groups
        print("Applying geographic optimization between street groups...")
        
        # Group by street and get the center coordinates for each street
        street_groups = []
        street_centers = {}
        streets_without_coords = []  # Track streets with no valid coordinates
        
        for street_city_key in working_df_sorted['street_city_key'].unique():
            if street_city_key == '':
                continue
                
            street_addresses = working_df_sorted[working_df_sorted['street_city_key'] == street_city_key]
            valid_coords = street_addresses.dropna(subset=['latitude', 'longitude'])
            
            if len(valid_coords) > 0:
                # Calculate center of street using valid coordinates
                center_lat = valid_coords['latitude'].mean()
                center_lon = valid_coords['longitude'].mean()
                street_centers[street_city_key] = (center_lat, center_lon)
                # CRITICAL FIX: Always include the ENTIRE street (with both valid and invalid addresses)
                # This preserves street grouping and house number sorting within each street
                street_groups.append((street_city_key, street_addresses))
                
                # Log if street has mixed results
                if len(valid_coords) < len(street_addresses):
                    failed_count = len(street_addresses) - len(valid_coords)
                    print(f"Street+City '{street_city_key}': {len(valid_coords)} geocoded, {failed_count} failed addresses (keeping street grouped)")
            else:
                # Only separate streets that have NO valid coordinates at all (all addresses failed)
                streets_without_coords.append((street_city_key, street_addresses))
                print(f"Warning: Street+City '{street_city_key}' has no valid coordinates (all {len(street_addresses)} addresses failed), will be added at the end")
        
        # Sort street groups by HIERARCHICAL GEOGRAPHIC strategy:
        #   Level 1: Group streets by Ortsteil (OT) — use Teilort/OT col, fallback to Stadt (ort_col)
        #   Level 2: Order OTs via nearest-neighbor, starting from NORTHERNMOST OT
        #   Level 3: Within each OT, order streets via nearest-neighbor, starting from NORTHERNMOST street
        #   Level 4: Within each street, house numbers are already numerically sorted (preserved)
        if len(street_groups) > 1:
            print(f"Hierarchical optimization: {len(street_groups)} streets across multiple Ortsteile/cities...")

            # Helper: derive a stable "Ortsteil key" for a street group.
            # Priority: teilort_col (OT) > ort_col (Stadt) > 'UNKNOWN'
            def derive_ortsteil_key(street_addresses_df):
                if teilort_col and teilort_col in street_addresses_df.columns:
                    vals = street_addresses_df[teilort_col].dropna().astype(str).str.strip()
                    vals = vals[(vals != '') & (vals.str.lower() != 'nan') & (vals.str.lower() != 'null')]
                    if len(vals) > 0:
                        return vals.mode().iloc[0]
                if ort_col and ort_col in street_addresses_df.columns:
                    vals = street_addresses_df[ort_col].dropna().astype(str).str.strip()
                    vals = vals[(vals != '') & (vals.str.lower() != 'nan')]
                    if len(vals) > 0:
                        return vals.mode().iloc[0]
                return 'UNKNOWN'

            # Bucket streets by Ortsteil
            ot_buckets = {}  # ot_key -> list of (street_city_key, street_addresses_df)
            for street_city_key, street_addresses in street_groups:
                ot_key = derive_ortsteil_key(street_addresses)
                ot_buckets.setdefault(ot_key, []).append((street_city_key, street_addresses))

            # Compute centroid per OT (average of valid street centers in that OT)
            ot_centers = {}
            for ot_key, streets in ot_buckets.items():
                lats, lons = [], []
                for sck, _ in streets:
                    c = street_centers.get(sck)
                    if c:
                        lats.append(c[0])
                        lons.append(c[1])
                if lats:
                    ot_centers[ot_key] = (sum(lats)/len(lats), sum(lons)/len(lons))

            print(f"  → {len(ot_buckets)} Ortsteile/Städte: {sorted(ot_buckets.keys())[:10]}{'…' if len(ot_buckets) > 10 else ''}")

            # --- Level 2: Order OTs starting from NORTHERNMOST ---
            ot_keys_with_center = [k for k in ot_buckets.keys() if k in ot_centers]
            ot_keys_without = [k for k in ot_buckets.keys() if k not in ot_centers]

            if ot_keys_with_center:
                # Northernmost = highest latitude
                start_ot = max(ot_keys_with_center, key=lambda k: ot_centers[k][0])
                print(f"  → Start-Ortsteil (nördlichster): '{start_ot}' @ {ot_centers[start_ot]}")

                ot_order = [start_ot]
                remaining_ots = [k for k in ot_keys_with_center if k != start_ot]
                current = start_ot
                while remaining_ots:
                    cur_lat, cur_lon = ot_centers[current]
                    best_idx, best_dist = 0, float('inf')
                    for i, k in enumerate(remaining_ots):
                        lat, lon = ot_centers[k]
                        d = calculate_distance_meters(cur_lat, cur_lon, lat, lon)
                        if d is not None and d < best_dist:
                            best_dist = d
                            best_idx = i
                    current = remaining_ots.pop(best_idx)
                    ot_order.append(current)
                # OTs without any centroid go at the end
                ot_order.extend(ot_keys_without)
            else:
                ot_order = list(ot_buckets.keys())

            # --- Level 3: Within each OT, order streets starting from NORTHERNMOST street ---
            optimized_street_order = []
            for ot_key in ot_order:
                streets_in_ot = ot_buckets[ot_key]
                with_c = [(sck, sdf) for sck, sdf in streets_in_ot if sck in street_centers]
                without_c = [(sck, sdf) for sck, sdf in streets_in_ot if sck not in street_centers]

                if not with_c:
                    optimized_street_order.extend(streets_in_ot)
                    continue

                # Northernmost street in this OT as start
                start_idx = max(range(len(with_c)), key=lambda i: street_centers[with_c[i][0]][0])
                ordered = [with_c.pop(start_idx)]
                print(f"    OT '{ot_key}': {len(with_c) + 1} Straßen (Start: '{ordered[0][0]}')")

                while with_c:
                    cur_lat, cur_lon = street_centers[ordered[-1][0]]
                    best_idx, best_dist = 0, float('inf')
                    for i, (sck, _) in enumerate(with_c):
                        lat, lon = street_centers[sck]
                        d = calculate_distance_meters(cur_lat, cur_lon, lat, lon)
                        if d is not None and d < best_dist:
                            best_dist = d
                            best_idx = i
                    ordered.append(with_c.pop(best_idx))

                ordered.extend(without_c)
                optimized_street_order.extend(ordered)
            
            # Rebuild the dataframe in optimized street order
            optimized_parts = []
            for street_city_key, street_addresses in optimized_street_order:
                optimized_parts.append(street_addresses)
            
            # Add streets with no valid coordinates at the end
            for street_name, street_addresses in streets_without_coords:
                optimized_parts.append(street_addresses)
                print(f"Added street '{street_name}' with failed addresses at the end")
            
            optimized_df = pd.concat(optimized_parts, ignore_index=True) if optimized_parts else working_df_sorted
        else:
            # If only one street group, still need to add streets without coordinates
            if streets_without_coords:
                all_parts = [working_df_sorted]
                for street_name, street_addresses in streets_without_coords:
                    all_parts.append(street_addresses)
                    print(f"Added street '{street_name}' with failed addresses")
                optimized_df = pd.concat(all_parts, ignore_index=True)
            else:
                optimized_df = working_df_sorted
            
    else:
        # Fallback to basic geographic optimization if no street columns detected
        print("No street columns detected, using basic geographic optimization...")
        valid_addresses = working_df.dropna(subset=['latitude', 'longitude']).copy()
        invalid_addresses = working_df[working_df['latitude'].isna() | working_df['longitude'].isna()].copy()
        
        if len(valid_addresses) == 0:
            # All addresses failed geocoding
            optimized_df = working_df
        else:
            # Simple nearest neighbor optimization for valid addresses
            route_order = []
            remaining_indices = list(valid_addresses.index)
            current_index = remaining_indices[0]
            remaining_indices.remove(current_index)
            route_order.append(current_index)
            
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
            
            optimized_valid = valid_addresses.loc[route_order].copy()
            
            # Always include invalid addresses at the end
            if len(invalid_addresses) > 0:
                print(f"Adding {len(invalid_addresses)} failed addresses at the end of the route")
                optimized_df = pd.concat([optimized_valid, invalid_addresses], ignore_index=True)
            else:
                optimized_df = optimized_valid
    
    # Calculate distances between consecutive addresses
    distances = []
    total_distance = 0
    
    for i in range(len(optimized_df)):
        if i < len(optimized_df) - 1:
            try:
                current_row = optimized_df.iloc[i]
                next_row = optimized_df.iloc[i + 1]
                
                current_lat = current_row.get('latitude')
                current_lon = current_row.get('longitude')
                next_lat = next_row.get('latitude')
                next_lon = next_row.get('longitude')
                
                if (current_lat is not None and current_lon is not None and
                    next_lat is not None and next_lon is not None and
                    not pd.isna(current_lat) and not pd.isna(current_lon) and
                    not pd.isna(next_lat) and not pd.isna(next_lon)):
                    distance = calculate_distance_meters(current_lat, current_lon, next_lat, next_lon)
                    distances.append(round(distance) if distance else 0)
                    total_distance += distance if distance else 0
                else:
                    distances.append(None)
            except Exception as e:
                print(f"Error calculating distance for row {i}: {e}")
                distances.append(None)
        else:
            distances.append(None)  # Last address has no next address
    
    optimized_df['distance_to_next_m'] = distances
    
    print(f"Route optimization completed.")
    print(f"Total distance: {total_distance/1000:.2f} km")
    print(f"Average distance between stops: {(total_distance/len([d for d in distances if d]))/1000:.3f} km" if any(distances) else "No valid distances")
    
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

def validate_and_clean_german_address(address: str) -> dict:
    """
    Validate and clean German address format for better geocoding results
    CRITICAL FIX: Reformat address to prioritize PLZ for better geocoding accuracy
    """
    try:
        # Basic validation
        if not address or not address.strip():
            return {
                'is_valid': False,
                'cleaned_address': address,
                'error': 'Empty address'
            }
        
        address_clean = address.strip()
        
        # Check for minimum address components (street name and city/postal code)
        if len(address_clean) < 5:
            return {
                'is_valid': False,
                'cleaned_address': address,
                'error': 'Address too short'
            }
        
        # Basic German address pattern validation
        # Should contain at least some letters and potentially numbers
        if not any(c.isalpha() for c in address_clean):
            return {
                'is_valid': False,
                'cleaned_address': address,
                'error': 'No alphabetic characters found'
            }
        
        # Clean common formatting issues
        # Remove extra whitespace
        address_clean = ' '.join(address_clean.split())
        
        # Normalize German characters and common abbreviations
        replacements = {
            'ß': 'ss',
            'Str.': 'Straße',
            'str.': 'straße',
            'Pl.': 'Platz',
            'pl.': 'platz'
        }
        
        for old, new in replacements.items():
            address_clean = address_clean.replace(old, new)
        
        # CRITICAL FIX: Reformat to prioritize PLZ
        # Parse address components and reorder: "Street Number, City, PLZ, Germany"
        import re
        
        # Try to extract PLZ (5-digit German postal code)
        plz_match = re.search(r'\b(\d{5})\b', address_clean)
        if plz_match:
            plz = plz_match.group(1)
            
            # Try to extract city (word after PLZ)
            city_match = re.search(rf'{plz}\s+([A-Za-zäöüÄÖÜß\-]+)', address_clean)
            if city_match:
                city = city_match.group(1)
                
                # Extract street and house number (everything before PLZ)
                street_part = address_clean.split(',')[0].strip()
                
                # Reformat: "Street, City, PLZ, Germany"
                # This format helps OSM better identify the correct location
                address_clean = f"{street_part}, {city}, {plz}, Germany"
        
        return {
            'is_valid': True,
            'cleaned_address': address_clean,
            'error': None
        }
        
    except Exception as e:
        return {
            'is_valid': False,
            'cleaned_address': address,
            'error': f'Validation error: {str(e)}'
        }

def validate_geocoding_result(address: str, lat: float, lon: float, prev_address: dict = None) -> dict:
    """
    CRITICAL FIX: Validate geocoding results to detect false positives
    
    Checks:
    1. If two consecutive addresses are on the same street but >500m apart → suspicious
    2. Returns validation status and recommendation for re-try
    
    Args:
        address: Current address string
        lat: Latitude of geocoded result
        lon: Longitude of geocoded result
        prev_address: Previous address dict with 'address', 'lat', 'lon', 'street'
        
    Returns:
        dict with 'is_valid', 'confidence', 'warning', 'should_retry'
    """
    try:
        if not prev_address or not lat or not lon:
            return {
                'is_valid': True,
                'confidence': 'medium',
                'warning': None,
                'should_retry': False
            }
        
        # Extract street name from current address
        import re
        current_street = None
        # Try to extract street name (word before number or before comma)
        street_match = re.search(r'^([A-Za-zäöüÄÖÜß\s\-]+)', address.split(',')[0])
        if street_match:
            current_street = street_match.group(1).strip()
        
        prev_street = prev_address.get('street', '')
        prev_lat = prev_address.get('lat')
        prev_lon = prev_address.get('lon')
        
        # If same street name, check distance
        if current_street and prev_street and prev_lat and prev_lon:
            # Normalize street names for comparison
            current_street_norm = current_street.lower().replace('strasse', 'straße').strip()
            prev_street_norm = prev_street.lower().replace('strasse', 'straße').strip()
            
            if current_street_norm == prev_street_norm:
                # Calculate distance using Haversine formula
                from math import radians, cos, sin, asin, sqrt
                
                lon1, lat1, lon2, lat2 = map(radians, [prev_lon, prev_lat, lon, lat])
                dlon = lon2 - lon1
                dlat = lat2 - lat1
                a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
                c = 2 * asin(sqrt(a))
                distance_m = 6371000 * c  # Earth radius in meters
                
                # If same street but >500m apart → highly suspicious
                if distance_m > 500:
                    return {
                        'is_valid': False,
                        'confidence': 'low',
                        'warning': f'Same street but {distance_m:.0f}m apart - likely geocoding error',
                        'should_retry': True,
                        'distance': distance_m
                    }
                
                # If between 200-500m → moderately suspicious
                elif distance_m > 200:
                    return {
                        'is_valid': True,
                        'confidence': 'medium',
                        'warning': f'Same street, {distance_m:.0f}m apart - please verify',
                        'should_retry': False,
                        'distance': distance_m
                    }
        
        return {
            'is_valid': True,
            'confidence': 'high',
            'warning': None,
            'should_retry': False
        }
        
    except Exception as e:
        return {
            'is_valid': True,
            'confidence': 'unknown',
            'warning': f'Validation error: {str(e)}',
            'should_retry': False
        }

# ---------------------------------------------------------------------------
# Multi-API geocoding helpers
# ---------------------------------------------------------------------------

async def _try_photon(session: aiohttp.ClientSession, address: str) -> dict | None:
    """Photon (Komoot) – free, no key, Germany-optimised."""
    try:
        url = "https://photon.komoot.io/api/"
        params = {'q': address, 'limit': 1, 'lang': 'de'}
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                data = await resp.json(content_type=None)
                features = data.get('features', [])
                if features:
                    coords = features[0]['geometry']['coordinates']
                    props = features[0].get('properties', {})
                    parts = [
                        props.get('name', ''),
                        props.get('housenumber', ''),
                        props.get('postcode', ''),
                        props.get('city', '') or props.get('town', '') or props.get('village', '')
                    ]
                    formatted = ', '.join(p for p in parts if p)
                    return {'latitude': coords[1], 'longitude': coords[0],
                            'formatted_address': formatted or address,
                            'postcode': str(props.get('postcode', '') or ''),
                            'geocoded': True, 'source': 'photon'}
            elif resp.status == 429:
                api_cooldown['photon'] = time.time() + 120
    except Exception:
        pass
    return None


async def _try_locationiq(session: aiohttp.ClientSession, address: str) -> dict | None:
    """LocationIQ – 5 000 req/day free."""
    if not LOCATIONIQ_KEY:
        return None
    try:
        url = "https://us1.locationiq.com/v1/search"
        params = {'key': LOCATIONIQ_KEY, 'q': address, 'format': 'json',
                  'limit': 1, 'countrycodes': 'de', 'accept-language': 'de'}
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                data = await resp.json(content_type=None)
                if data:
                    r = data[0]
                    return {'latitude': float(r['lat']), 'longitude': float(r['lon']),
                            'formatted_address': r.get('display_name', address),
                            'geocoded': True, 'source': 'locationiq'}
            elif resp.status == 429:
                api_cooldown['locationiq'] = time.time() + 120
    except Exception:
        pass
    return None


async def _try_geoapify(session: aiohttp.ClientSession, address: str) -> dict | None:
    """Geoapify – 3 000 req/day free."""
    if not GEOAPIFY_KEY:
        return None
    try:
        url = "https://api.geoapify.com/v1/geocode/search"
        params = {'text': address, 'filter': 'countrycode:de',
                  'format': 'json', 'apiKey': GEOAPIFY_KEY, 'limit': 1, 'lang': 'de'}
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                data = await resp.json(content_type=None)
                results = data.get('results', [])
                if results:
                    r = results[0]
                    return {'latitude': r['lat'], 'longitude': r['lon'],
                            'formatted_address': r.get('formatted', address),
                            'geocoded': True, 'source': 'geoapify'}
            elif resp.status == 429:
                api_cooldown['geoapify'] = time.time() + 120
    except Exception:
        pass
    return None


async def _try_opencage(session: aiohttp.ClientSession, address: str) -> dict | None:
    """OpenCage – 2 500 req/day free."""
    if not OPENCAGE_KEY:
        return None
    try:
        url = "https://api.opencagedata.com/geocode/v1/json"
        params = {'q': address, 'key': OPENCAGE_KEY, 'countrycode': 'de',
                  'limit': 1, 'language': 'de', 'no_annotations': 1}
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                data = await resp.json(content_type=None)
                results = data.get('results', [])
                if results:
                    g = results[0].get('geometry', {})
                    return {'latitude': g['lat'], 'longitude': g['lng'],
                            'formatted_address': results[0].get('formatted', address),
                            'geocoded': True, 'source': 'opencage'}
            elif resp.status == 429:
                api_cooldown['opencage'] = time.time() + 120
    except Exception:
        pass
    return None


async def _try_nominatim(session: aiohttp.ClientSession, address: str) -> dict | None:
    """Nominatim (OSM) – last resort."""
    try:
        url = "https://nominatim.openstreetmap.org/search"
        params = {'q': address, 'format': 'json', 'limit': 1,
                  'countrycodes': 'de', 'addressdetails': 1,
                  'accept-language': 'de,en',
                  'viewbox': '5.8663153,47.2701114,15.0419319,55.099161',
                  'bounded': 1}
        headers = {'User-Agent': 'SalesRouteOptimizer/2.0'}
        async with session.get(url, params=params, headers=headers,
                               timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status == 200:
                data = await resp.json(content_type=None)
                if data:
                    r = data[0]
                    return {'latitude': float(r['lat']), 'longitude': float(r['lon']),
                            'formatted_address': r.get('display_name', address),
                            'street': r.get('address', {}).get('road', ''),
                            'geocoded': True, 'source': 'nominatim'}
            elif resp.status == 429:
                api_cooldown['nominatim'] = time.time() + 120
    except Exception:
        pass
    return None


async def geocode_address_with_cache(address: str, job_logger: JobLogger = None) -> dict:
    """
    Multi-API geocoding: Photon → LocationIQ → Geoapify → OpenCage → Nominatim.
    Immediately skips any API on cooldown (429). No long waits.
    """
    # ── Cache check ──────────────────────────────────────────────────────────
    if address in address_cache:
        return address_cache[address]

    address_clean = address.strip()
    if not address_clean:
        return {'latitude': None, 'longitude': None,
                'formatted_address': address, 'geocoded': False, 'error': 'Empty address'}

    # Use cleaned address from validator if valid
    validation = validate_and_clean_german_address(address_clean)
    if validation['is_valid']:
        address_clean = validation['cleaned_address']

    if job_logger:
        job_logger.log('INFO', f'Geocoding: {address_clean}', address=address_clean)

    # Erwartete PLZ aus der Anfrage extrahieren (Format: "Straße Nr, PLZ Ort")
    expected_plz = None
    plz_match = re.search(r',\s*(\d{4,5})\s+', address_clean + ' ')
    if plz_match:
        expected_plz = plz_match.group(1).zfill(5)

    # ── API cascade ───────────────────────────────────────────────────────────
    now = time.time()
    apis = [
        ('photon',    lambda s: _try_photon(s, address_clean)),
        ('locationiq', lambda s: _try_locationiq(s, address_clean)),
        ('geoapify',  lambda s: _try_geoapify(s, address_clean)),
        ('opencage',  lambda s: _try_opencage(s, address_clean)),
        ('nominatim', lambda s: _try_nominatim(s, address_clean)),
    ]

    connector = aiohttp.TCPConnector(limit=10, ttl_dns_cache=300, use_dns_cache=True)
    async with aiohttp.ClientSession(connector=connector) as session:
        for api_name, api_fn in apis:
            if api_cooldown.get(api_name, 0) > now:
                if job_logger:
                    job_logger.log('INFO', f'{api_name} on cooldown, skipping', address=address_clean)
                continue
            try:
                result = await api_fn(session)
                if result:
                    # PLZ-Plausibilitätsprüfung: Treffer in völlig falscher PLZ-Region verwerfen
                    # (z.B. "Hauptstraße 99, 06493" → Treffer in 64390 Erzhausen = 269 km entfernt)
                    if expected_plz:
                        result_plz = str(result.get('postcode') or '')
                        if not result_plz:
                            m = re.search(r'\b(\d{5})\b', str(result.get('formatted_address', '')))
                            result_plz = m.group(1) if m else ''
                        if result_plz and result_plz.zfill(5)[:2] != expected_plz[:2]:
                            if job_logger:
                                job_logger.log('WARNING',
                                    f'{api_name} Treffer verworfen: PLZ {result_plz} passt nicht zu erwarteter PLZ {expected_plz}',
                                    address=address_clean)
                            continue  # nächste API versuchen
                    if job_logger:
                        job_logger.log('INFO',
                            f'Geocoded via {api_name}: {result.get("formatted_address", "")}',
                            address=address_clean)
                    address_cache[address] = result
                    return result
                # API returned nothing (not found) – try next without penalty
            except Exception as exc:
                if job_logger:
                    job_logger.log('WARNING', f'{api_name} error: {exc}', address=address_clean)

    # ── All APIs exhausted ────────────────────────────────────────────────────
    fail = {'latitude': None, 'longitude': None,
            'formatted_address': address, 'geocoded': False,
            'error': 'All geocoding APIs failed or returned no result'}
    if job_logger:
        job_logger.log('WARNING', 'All APIs failed', address=address_clean)
    address_cache[address] = fail
    return fail

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
        teilort_col = None
        
        # Map specific German column names to address components
        for col in df.columns:
            col_lower = col.lower().strip()
            if any(keyword in col_lower for keyword in ['projektname strasse', 'strasse', 'straße', 'street']):
                street_col = col
            elif any(keyword in col_lower for keyword in ['hausnummer', 'haus nummer', 'haus-nummer']) or (col_lower == 'nummer' or col_lower == 'nr' or col_lower == 'nr.' or col_lower == 'hnr' or col_lower == 'number'):
                house_num_col = col
            elif any(keyword in col_lower for keyword in ['zusatz', 'zusätze', 'affix']):
                zusatz_col = col
            elif any(keyword in col_lower for keyword in ['plz', 'postleitzahl', 'postal']):
                plz_col = col
            elif any(keyword in col_lower for keyword in ['ort', 'stadt', 'city', 'location', 'municipality']) and 'teil' not in col_lower:
                # Only match "Ort" columns, not "Teilort"
                ort_col = col
            elif any(keyword in col_lower for keyword in ['teilort', 'stadtteil', 'ortsteil', 'district']):
                # Keep Teilort separate
                teilort_col = col
        
        # CRITICAL FIX: For geocoding, prefer "Ort" (main city) over "Teilort" (sub-locality)
        if not ort_col and teilort_col:
            ort_col = teilort_col
        
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
                # CRITICAL FIX: Use clean_numeric_string to avoid .0 in addresses
                street = clean_numeric_string(row[street_col]) if street_col else ""
                house_num = clean_numeric_string(row[house_num_col]) if house_num_col else ""
                zusatz = clean_numeric_string(row[zusatz_col]) if zusatz_col else ""
                plz = clean_numeric_string(row[plz_col]) if plz_col else ""
                ort = clean_numeric_string(row[ort_col]) if ort_col else ""
                
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
                # CRITICAL FIX: Handle NaT values properly - convert to None instead of string
                "original_row_data": {
                    col: None if pd.isna(row[col]) else (str(row[col]) if not isinstance(row[col], pd.Timestamp) else row[col].isoformat())
                    for col in df.columns
                },
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
        teilort_col = None
        
        for col in df.columns:
            col_lower = col.lower().strip()
            if any(keyword in col_lower for keyword in ['projektname strasse', 'strasse', 'straße', 'street']):
                street_col = col
            elif any(keyword in col_lower for keyword in ['hausnummer', 'haus nummer', 'haus-nummer']) or (col_lower == 'nummer' or col_lower == 'nr' or col_lower == 'nr.' or col_lower == 'hnr' or col_lower == 'number'):
                house_num_col = col
            elif any(keyword in col_lower for keyword in ['zusatz', 'zusätze', 'affix']):
                zusatz_col = col
            elif any(keyword in col_lower for keyword in ['plz', 'postleitzahl', 'postal']):
                plz_col = col
            elif any(keyword in col_lower for keyword in ['ort', 'stadt', 'city', 'location', 'municipality']) and 'teil' not in col_lower:
                # Only match "Ort" columns, not "Teilort"
                ort_col = col
            elif any(keyword in col_lower for keyword in ['teilort', 'stadtteil', 'ortsteil', 'district']):
                # Keep Teilort separate
                teilort_col = col
        
        # CRITICAL FIX: For geocoding, prefer "Ort" (main city) over "Teilort" (sub-locality)
        if not ort_col and teilort_col:
            ort_col = teilort_col
        
        has_german_format = street_col and house_num_col and plz_col and ort_col
        
        # Generate preview addresses - show ALL addresses, not just first 5
        preview_addresses = []
        for index, row in df.iterrows():
            if has_german_format:
                # CRITICAL FIX: Use clean_numeric_string to avoid .0 in addresses
                street = clean_numeric_string(row[street_col]) if street_col else ""
                house_num = clean_numeric_string(row[house_num_col]) if house_num_col else ""
                zusatz = clean_numeric_string(row[zusatz_col]) if zusatz_col else ""
                plz = clean_numeric_string(row[plz_col]) if plz_col else ""
                ort = clean_numeric_string(row[ort_col]) if ort_col else ""
                
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
    async with _geocoding_job_lock:
        await _process_street_sorted_job_inner(job_id, file_content, filename)


async def _process_street_sorted_job_inner(job_id: str, file_content: bytes, filename: str):
    """Inner implementation (called under job lock)"""
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
        street_col = house_num_col = zusatz_col = plz_col = ort_col = teilort_col = None
        
        for col in df.columns:
            col_lower = col.lower().strip()
            if any(keyword in col_lower for keyword in ['projektname strasse', 'strasse', 'straße', 'street']):
                street_col = col
            elif any(keyword in col_lower for keyword in ['hausnummer', 'haus nummer', 'haus-nummer']) or (col_lower == 'nummer' or col_lower == 'nr' or col_lower == 'nr.' or col_lower == 'hnr' or col_lower == 'number'):
                house_num_col = col
            elif any(keyword in col_lower for keyword in ['zusatz', 'zusätze', 'affix']):
                zusatz_col = col
            elif any(keyword in col_lower for keyword in ['plz', 'postleitzahl', 'postal']):
                plz_col = col
            elif any(keyword in col_lower for keyword in ['ort', 'stadt', 'city', 'location', 'municipality']) and 'teil' not in col_lower:
                # Only match "Ort" columns, not "Teilort"
                ort_col = col
            elif any(keyword in col_lower for keyword in ['teilort', 'stadtteil', 'ortsteil', 'district']):
                # Keep Teilort separate
                teilort_col = col
        
        # CRITICAL FIX: For geocoding, prefer "Ort" (main city) over "Teilort" (sub-locality)
        if not ort_col and teilort_col:
            ort_col = teilort_col
        
        has_german_format = street_col and house_num_col and plz_col and ort_col
        
        # Create address strings for geocoding
        addresses_to_geocode = []
        if has_german_format:
            for idx, row in df.iterrows():
                # CRITICAL FIX: Use clean_numeric_string to avoid .0 in addresses
                street = clean_numeric_string(row[street_col]) if pd.notna(row[street_col]) else ""
                house_num = clean_numeric_string(row[house_num_col]) if pd.notna(row[house_num_col]) else ""
                zusatz = clean_numeric_string(row[zusatz_col]) if zusatz_col and pd.notna(row[zusatz_col]) else ""
                plz = clean_numeric_string(row[plz_col]) if pd.notna(row[plz_col]) else ""
                ort = clean_numeric_string(row[ort_col]) if pd.notna(row[ort_col]) else ""
                
                # Clean street name - remove project prefixes
                if street.startswith('Worpswede '):
                    street = street[10:].strip()
                elif ' ' in street and len(street.split()[0]) < 4:
                    # Remove short prefixes that might be project codes
                    parts = street.split()
                    if parts[0].isalnum() and any(c.isdigit() for c in parts[0]) and len(parts) > 1:
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
        
        # Create job logger for monitoring
        job_logger = JobLogger(job_id)
        
        # Geocode all addresses
        geocoded_data = []
        geocoded_count = 0
        
        for i, address in enumerate(addresses_to_geocode):
            try:
                print(f"Geocoding address {i+1}/{total_addresses}: {address}")
                geocoded = await geocode_address_with_cache(address, job_logger)
                
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
                
                # Small polite delay between addresses
                await asyncio.sleep(0.1)
                
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
                # Only strip codes containing digits – NEVER German words like "Vor", "Am", "Alte"
                parts = street.split()
                if len(parts) > 1 and len(parts[0]) <= 4 and parts[0].isalnum() and any(c.isdigit() for c in parts[0]):
                    # Check if the rest looks like a street name
                    remaining = ' '.join(parts[1:])
                    if any(char.isalpha() for char in remaining):
                        street = remaining
                
                return street.strip()
            
            working_df['street_clean'] = working_df[street_col].apply(clean_street_name)
            
            # CRITICAL FIX: Create street_city_key for proper grouping
            # Include Ortsteil so identical street names in different Ortsteilen stay separate
            def create_street_city_key(row):
                street = str(row['street_clean']).strip()
                city = str(row.get(ort_col, '')).strip() if ort_col else ''
                ot = str(row.get(teilort_col, '')).strip() if teilort_col else ''
                
                if street == '' or street == 'nan':
                    return ''
                
                if ot and ot.lower() not in ('', 'nan', 'null', 'none') and ot != city:
                    return f"{street}, {ot}, {city}" if city and city != 'nan' else f"{street}, {ot}"
                # Create unique key: "Straße, Stadt"
                if city and city != '' and city != 'nan':
                    return f"{street}, {city}"
                else:
                    return street
            
            working_df['street_city_key'] = working_df.apply(create_street_city_key, axis=1)
            
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
            
            # Group by street+city and sort by house number
            try:
                # CRITICAL FIX: Create categorical variable for street_city_key to ensure proper grouping
                unique_street_cities = sorted(working_df['street_city_key'].unique())
                street_city_categories = pd.Categorical(working_df['street_city_key'], 
                                                       categories=unique_street_cities,
                                                       ordered=True)
                working_df['street_city_category'] = street_city_categories
                
                # Sort by street+city first, then house number
                working_df_sorted = working_df.sort_values(
                    ['street_city_category', 'house_number_numeric', 'house_number_letter'],
                    na_position='last'
                )
                
                # Debug output
                print("Sorted addresses with street+city grouping:")
                for i in range(min(10, len(working_df_sorted))):
                    row = working_df_sorted.iloc[i]
                    print(f"{i+1}. {row['street_city_key']} {row['house_number_numeric']}{row['house_number_letter']}")
                
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
            
            # Convert any NaN, infinity, or NaT values to None for JSON/MongoDB serialization
            row_dict = {}
            for k, v in row.to_dict().items():
                if isinstance(v, float) and (pd.isna(v) or math.isinf(v)):
                    row_dict[k] = None
                elif pd.isna(v):  # CRITICAL FIX: Handle NaT and other pd.NA values
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

# New endpoint to get job logs for frontend display
@app.get("/api/job/{job_id}/logs")
async def get_job_logs(job_id: str, recent: int = 50):
    """Get job logs for frontend display"""
    try:
        if job_id in job_logs:
            logs = job_logs[job_id]
            # Return recent logs
            return {"logs": logs[-recent:] if logs else []}
        else:
            return {"logs": []}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching logs: {str(e)}")

async def robust_geocode_with_monitoring(address: str, logger: JobLogger, address_index: int) -> dict:
    """Ultra-robust geocoding with comprehensive monitoring and error handling"""
    logger.log("INFO", f"Starting geocoding for address {address_index}", address_index, address)
    
    try:
        # Check cache first
        if address in address_cache:
            logger.log("INFO", f"Address found in cache", address_index, address)
            return address_cache[address]
        
        # Use the existing geocoding function but with monitoring
        result = await geocode_address_with_cache(address, logger)
        
        if result.get('geocoded'):
            logger.log("INFO", f"Successfully geocoded", address_index, address)
        else:
            logger.log("WARNING", f"Failed to geocode: {result.get('error', 'Unknown error')}", address_index, address)
        
        return result
        
    except Exception as e:
        error_msg = f"Critical geocoding error: {str(e)[:200]}"
        logger.log("CRITICAL", error_msg, address_index, address)
        return {
            'latitude': None,
            'longitude': None,
            'formatted_address': address,
            'geocoded': False,
            'error': error_msg
        }

@app.post("/api/upload-optimized")
async def upload_file_optimized(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """Upload file for combined geographic optimization (door-to-door sales)"""
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
            "optimization_type": "geographic_door_to_door"
        }
        
        upload_jobs_collection.insert_one(job_data)
        
        # Start background processing
        background_tasks.add_task(process_geographic_optimization_job, job_id, file_content, file.filename)
        
        return {"job_id": job_id, "status": "uploading", "message": "Datei wird für geografische Optimierung verarbeitet"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler beim Upload: {str(e)}")

async def process_geographic_optimization_job(job_id: str, file_content: bytes, filename: str):
    """
    Combined geographic optimization for door-to-door sales
    - Geocodes all addresses
    - Creates geographically logical route 
    - Calculates exact distances
    - Preserves all original columns
    """
    async with _geocoding_job_lock:
        await _process_geographic_optimization_job_inner(job_id, file_content, filename)


async def _process_geographic_optimization_job_inner(job_id: str, file_content: bytes, filename: str):
    """Inner implementation (called under job lock)"""
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
        street_col = house_num_col = zusatz_col = plz_col = ort_col = teilort_col = None
        
        for col in df.columns:
            col_lower = col.lower().strip()
            if any(keyword in col_lower for keyword in ['projektname strasse', 'strasse', 'straße', 'street']):
                street_col = col
            elif any(keyword in col_lower for keyword in ['hausnummer', 'haus nummer', 'haus-nummer']) or (col_lower == 'nummer' or col_lower == 'nr' or col_lower == 'nr.' or col_lower == 'hnr' or col_lower == 'number'):
                house_num_col = col
            elif any(keyword in col_lower for keyword in ['zusatz', 'zusätze', 'affix']):
                zusatz_col = col
            elif any(keyword in col_lower for keyword in ['plz', 'postleitzahl', 'postal']):
                plz_col = col
            elif any(keyword in col_lower for keyword in ['ort', 'stadt', 'city', 'location', 'municipality']) and 'teil' not in col_lower:
                # Only match "Ort" columns, not "Teilort"
                ort_col = col
            elif any(keyword in col_lower for keyword in ['teilort', 'stadtteil', 'ortsteil', 'district']):
                # Keep Teilort separate
                teilort_col = col
        
        # CRITICAL FIX: For geocoding, prefer "Ort" (main city) over "Teilort" (sub-locality)
        if not ort_col and teilort_col:
            ort_col = teilort_col
        
        has_german_format = street_col and house_num_col and plz_col and ort_col
        
        # Create address strings for geocoding
        addresses_to_geocode = []
        if has_german_format:
            for idx, row in df.iterrows():
                # CRITICAL FIX: Use clean_numeric_string to avoid .0 in addresses
                street = clean_numeric_string(row[street_col]) if pd.notna(row[street_col]) else ""
                house_num = clean_numeric_string(row[house_num_col]) if pd.notna(row[house_num_col]) else ""
                zusatz = clean_numeric_string(row[zusatz_col]) if zusatz_col and pd.notna(row[zusatz_col]) else ""
                plz = clean_numeric_string(row[plz_col]) if pd.notna(row[plz_col]) else ""
                ort = clean_numeric_string(row[ort_col]) if pd.notna(row[ort_col]) else ""
                
                # Clean street name - remove project prefixes
                if street.startswith('Worpswede '):
                    street = street[10:].strip()
                elif ' ' in street and len(street.split()[0]) < 4:
                    parts = street.split()
                    if parts[0].isalnum() and any(c.isdigit() for c in parts[0]) and len(parts) > 1:
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
        
        # Create job logger for monitoring
        job_logger = JobLogger(job_id)
        
        # Geocode all addresses with enhanced batch processing
        geocoded_data = []
        geocoded_count = 0
        failed_count = 0
        batch_size = 50  # Process in smaller batches to avoid memory issues
        
        print(f"Starting geocoding of {total_addresses} addresses in batches of {batch_size}...")
        
        for batch_start in range(0, total_addresses, batch_size):
            batch_end = min(batch_start + batch_size, total_addresses)
            print(f"Processing batch {batch_start + 1}-{batch_end} of {total_addresses}")
            
            for i in range(batch_start, batch_end):
                address = addresses_to_geocode[i]
                
                try:
                    print(f"Geocoding address {i+1}/{total_addresses}: {address}")
                    geocoded = await geocode_address_with_cache(address, job_logger)
                    geocoded_data.append(geocoded)
                    
                    if geocoded.get('latitude') and geocoded.get('longitude'):
                        geocoded_count += 1
                        print(f"✅ Successfully geocoded: {address}")
                    else:
                        failed_count += 1
                        print(f"❌ Failed to geocode: {address} - {geocoded.get('error', 'Unknown error')}")
                    
                    # Update progress more frequently
                    if (i + 1) % 10 == 0 or i == total_addresses - 1:
                        upload_jobs_collection.update_one(
                            {"id": job_id},
                            {"$set": {
                                "processed_addresses": i + 1,
                                "geocoded_addresses": geocoded_count,
                                "failed_addresses": failed_count
                            }}
                        )
                    
                    # Small polite delay between addresses (multi-API handles rate limits)
                    await asyncio.sleep(0.1)
                    
                    # Memory management: Clear cache periodically for very large datasets
                    if i > 0 and i % 1000 == 0:
                        print(f"Memory management: Clearing old cache entries at address {i}")
                        # Keep only recent entries in cache
                        if len(address_cache) > 2000:
                            # Clear oldest half of cache
                            keys_to_remove = list(address_cache.keys())[:len(address_cache)//2]
                            for key in keys_to_remove:
                                del address_cache[key]
                            print(f"Cleared {len(keys_to_remove)} old cache entries")
                    
                except Exception as e:
                    print(f"Critical error processing address {i+1}: {address} - {e}")
                    geocoded_data.append({
                        'latitude': None,
                        'longitude': None,
                        'formatted_address': address,
                        'geocoded': False,
                        'error': str(e)
                    })
                    failed_count += 1
                    
                    # Continue processing even if one address fails
                    continue
            
            # Update progress after each batch
            upload_jobs_collection.update_one(
                {"id": job_id},
                {"$set": {
                    "processed_addresses": batch_end,
                    "geocoded_addresses": geocoded_count,
                    "failed_addresses": failed_count,
                    "progress_message": f"Completed batch {batch_end}/{total_addresses}"
                }}
            )
            
            # Small delay between batches to prevent overwhelming the API
            if batch_end < total_addresses:
                print(f"Batch {batch_start + 1}-{batch_end} completed. Brief pause before next batch...")
                await asyncio.sleep(2.0)
        
        print(f"Geocoding completed: {geocoded_count} successful, {failed_count} failed out of {total_addresses} addresses")
        
        # Geographic optimization for door-to-door sales
        upload_jobs_collection.update_one(
            {"id": job_id},
            {"$set": {"status": "optimizing"}}
        )
        
        optimized_df, total_distance = optimize_geographic_route(df, geocoded_data, addresses_to_geocode)
        
        # Store results in database
        optimized_addresses = []
        for idx, row in optimized_df.iterrows():
            # Convert any NaN, infinity, or NaT values to None for JSON/MongoDB serialization
            row_dict = {}
            for k, v in row.to_dict().items():
                if isinstance(v, float) and (pd.isna(v) or math.isinf(v)):
                    row_dict[k] = None
                elif pd.isna(v):  # CRITICAL FIX: Handle NaT and other pd.NA values
                    row_dict[k] = None
                else:
                    row_dict[k] = v
            
            # Determine if address was successfully geocoded
            lat = row.get('latitude')
            lon = row.get('longitude')
            is_geocoded = (lat is not None and lon is not None and 
                          not pd.isna(lat) and not pd.isna(lon) and
                          lat != 0 and lon != 0)
            
            address_data = {
                "id": str(uuid.uuid4()),
                "original_address": row.get('original_address', ''),
                "latitude": None if pd.isna(lat) else lat,
                "longitude": None if pd.isna(lon) else lon,
                "formatted_address": row.get('formatted_address', ''),
                "geocoded": is_geocoded,
                "geocoding_error": row.get('geocoding_error', ''),
                "distance_to_next": None if pd.isna(row.get('distance_to_next_m')) else row.get('distance_to_next_m'),
                "row_data": row_dict
            }
            optimized_addresses.append(address_data)
        
        # Store in database
        route_data = {
            "job_id": job_id,
            "optimized_addresses": optimized_addresses,
            "total_distance": total_distance,
            "created_at": datetime.utcnow(),
            "optimization_type": "geographic_door_to_door"
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
        
        print(f"Geographic optimization job {job_id} completed successfully with {geocoded_count}/{total_addresses} geocoded addresses")
        
    except Exception as e:
        print(f"Error in geographic optimization job {job_id}: {e}")
        upload_jobs_collection.update_one(
            {"id": job_id},
            {"$set": {
                "status": "error",
                "error_message": str(e)
            }}
        )
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

# New endpoints for combined geographic optimization
@app.get("/api/optimized/{job_id}")
async def get_optimized_route(job_id: str):
    """Get optimized route data"""
    try:
        route_data = routes_collection.find_one({"job_id": job_id, "optimization_type": "geographic_door_to_door"})
        if not route_data:
            raise HTTPException(status_code=404, detail="Optimized route not found")
        
        # Convert MongoDB ObjectId to string
        route_data["_id"] = str(route_data["_id"])
        
        # Handle NaN and infinity values for JSON serialization
        def clean_for_json(obj):
            if isinstance(obj, dict):
                return {k: clean_for_json(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [clean_for_json(item) for item in obj]
            elif isinstance(obj, float):
                if math.isnan(obj) or math.isinf(obj):
                    return None
                return obj
            else:
                return obj
        
        cleaned_data = clean_for_json(route_data)
        return cleaned_data
        
    except Exception as e:
        print(f"Error fetching optimized route: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching optimized route: {str(e)}")

@app.get("/api/optimized/{job_id}/export")
async def export_optimized_route(job_id: str):
    """Export optimized route as Excel file with original columns + distance_to_next_m only"""
    try:
        # Get route data from database
        route_data = routes_collection.find_one({"job_id": job_id, "optimization_type": "geographic_door_to_door"})
        if not route_data:
            raise HTTPException(status_code=404, detail="Optimized route not found")
        
        # Get job info
        job = upload_jobs_collection.find_one({"id": job_id})
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        
        # Prepare data for Excel export with ONLY original columns + distance_to_next_m
        addresses = route_data['optimized_addresses']
        
        # Define system-generated columns to exclude
        system_columns = {
            'latitude', 'longitude', 'geocoded', 'geocoding_error', 'formatted_address',
            'geocoded_address', 'Breitengrad', 'Laengengrad', 'Geocodierte_Adresse',
            'street_clean', 'house_number_numeric', 'house_number_letter', 'Formatierte_Adresse',
            'Longitude', 'Latitude', 'Geocodiert', 'Geocoding_Fehler'
        }
        
        # Create DataFrame from optimized addresses preserving ONLY original columns + distance_to_next_m
        rows = []
        for addr in addresses:
            row_data = addr.get('row_data', {})
            
            # Filter out system-generated columns
            filtered_row = {}
            for key, value in row_data.items():
                if key not in system_columns:
                    filtered_row[key] = value
            
            # Add distance_to_next_m if it exists
            if 'distance_to_next' in addr and addr['distance_to_next'] is not None:
                filtered_row['distance_to_next_m'] = addr['distance_to_next']
            else:
                filtered_row['distance_to_next_m'] = None
                
            rows.append(filtered_row)
        
        df = pd.DataFrame(rows)
        
        # CRITICAL FIX: Clean NaT values before Excel export
        df = clean_dataframe_for_excel(df)
        
        # Create Excel file with enhanced formatting
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            # Main sheet with optimized addresses
            df.to_excel(writer, sheet_name='Geografisch Optimierte Route', index=False)
            
            # Get workbook and worksheet
            workbook = writer.book
            worksheet = writer.sheets['Geografisch Optimierte Route']
            
            # Style header row
            header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
            header_font = Font(color="FFFFFF", bold=True)
            
            for cell in worksheet[1]:
                cell.fill = header_fill
                cell.font = header_font
            
            # CRITICAL FIX: Apply percentage formatting to columns with '%' in name
            worksheet = apply_percentage_formatting(worksheet, df, 'Geografisch Optimierte Route')
            
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
                'Optimierung': ['Geografische Door-to-Door Route'],
                'Gesamtstrecke (m)': [route_data.get('total_distance', 0)],
                'Gesamtstrecke (km)': [round(route_data.get('total_distance', 0) / 1000, 2)]
            }
            
            summary_df = pd.DataFrame(summary_data)
            summary_df = clean_dataframe_for_excel(summary_df)
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
        filename = f"geografisch_optimiert_{timestamp}.xlsx"
        
        return StreamingResponse(
            BytesIO(output.read()),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except Exception as e:
        print(f"Error exporting optimized route: {e}")
        raise HTTPException(status_code=500, detail=f"Fehler beim Excel-Export: {str(e)}")
async def export_street_sorted_route(job_id: str):
    """Export street-sorted addresses as Excel file with original columns + distance_to_next_m only"""
    try:
        # Get route data from database
        route_data = routes_collection.find_one({"job_id": job_id, "sorting_type": "street_based"})
        if not route_data:
            raise HTTPException(status_code=404, detail="Street-sorted route not found")
        
        # Get job info
        job = upload_jobs_collection.find_one({"id": job_id})
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        
        # Prepare data for Excel export with ONLY original columns + distance_to_next_m
        addresses = route_data['sorted_addresses']
        
        # Define system-generated columns to exclude
        system_columns = {
            'latitude', 'longitude', 'geocoded', 'geocoding_error', 'formatted_address',
            'geocoded_address', 'Breitengrad', 'Laengengrad', 'Geocodierte_Adresse',
            'street_clean', 'house_number_numeric', 'house_number_letter', 'Formatierte_Adresse',
            'Longitude', 'Latitude', 'Geocodiert', 'Geocoding_Fehler'
        }
        
        # Create DataFrame from sorted addresses preserving ONLY original columns + distance_to_next_m
        rows = []
        for addr in addresses:
            row_data = addr.get('row_data', {})
            
            # Filter out system-generated columns
            filtered_row = {}
            for key, value in row_data.items():
                if key not in system_columns:
                    filtered_row[key] = value
            
            # Add distance_to_next_m if it exists
            if 'distance_to_next' in addr and addr['distance_to_next'] is not None:
                filtered_row['distance_to_next_m'] = addr['distance_to_next']
            else:
                filtered_row['distance_to_next_m'] = None
                
            rows.append(filtered_row)
        
        df = pd.DataFrame(rows)
        
        # CRITICAL FIX: Clean NaT values before Excel export
        df = clean_dataframe_for_excel(df)
        
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
            
            # CRITICAL FIX: Apply percentage formatting to columns with '%' in name
            worksheet = apply_percentage_formatting(worksheet, df, 'Straßen-sortierte Adressen')
            
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
                'Sortierung': ['Straßen-basiert'],
                'Gesamtstrecke (m)': [route_data.get('total_distance', 0)],
                'Gesamtstrecke (km)': [round(route_data.get('total_distance', 0) / 1000, 2)]
            }
            
            summary_df = pd.DataFrame(summary_data)
            summary_df = clean_dataframe_for_excel(summary_df)
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

@app.get("/api/street-sorted/{job_id}/export")
async def export_street_sorted_route_endpoint(job_id: str):
    """Export street-sorted addresses as Excel file with original columns + distance_to_next_m only"""
    return await export_street_sorted_route(job_id)

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
    
    # Start background processing with enhanced geocoding
    background_tasks.add_task(process_geographic_optimization_job, job_id, file_content, file.filename)
    
    return {"job_id": job_id, "message": "File uploaded successfully, processing started"}

# Endpoint to resume interrupted jobs
@app.post("/api/resume-job/{job_id}")
async def resume_job(job_id: str, background_tasks: BackgroundTasks):
    """Resume an interrupted geocoding job"""
    try:
        # Get the job
        job = upload_jobs_collection.find_one({"id": job_id})
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        
        # Check if job can be resumed
        if job.get("status") not in ["geocoding", "error"]:
            raise HTTPException(status_code=400, detail="Job cannot be resumed")
        
        # Reset status to allow resuming
        upload_jobs_collection.update_one(
            {"id": job_id},
            {"$set": {
                "status": "resuming",
                "resumed_at": datetime.utcnow()
            }}
        )
        
        # Get the original file content from a temporary storage or re-upload
        # For now, we'll require a re-upload for resume functionality
        return {"message": "Job resume initiated. Please re-upload the file to continue processing."}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error resuming job: {str(e)}")

# Enhanced endpoint with better error handling
@app.get("/api/job/{job_id}")
async def get_job_status(job_id: str):
    """Get job status with enhanced progress information"""
    job = upload_jobs_collection.find_one({"id": job_id})
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Convert MongoDB document to dict and handle datetime
    job_data = {
        "id": job["id"],
        "filename": job["filename"],
        "status": job["status"],
        "total_addresses": job.get("total_addresses", 0),
        "processed_addresses": job.get("processed_addresses", 0),
        "geocoded_addresses": job.get("geocoded_addresses", 0),
        "failed_addresses": job.get("failed_addresses", 0),
        "error_message": job.get("error_message"),
        "progress_message": job.get("progress_message"),
        "created_at": job["created_at"].isoformat() if job.get("created_at") else None,
        "completed_at": job["completed_at"].isoformat() if job.get("completed_at") else None,
        "optimization_type": job.get("optimization_type", "geographic_door_to_door"),
        "can_resume": job.get("status") in ["geocoding", "error"] and job.get("processed_addresses", 0) > 0
    }
    
    # Calculate progress percentage
    if job_data["total_addresses"] > 0:
        job_data["progress_percentage"] = round((job_data["processed_addresses"] / job_data["total_addresses"]) * 100, 1)
        job_data["success_rate"] = round((job_data["geocoded_addresses"] / max(job_data["processed_addresses"], 1)) * 100, 1)
    else:
        job_data["progress_percentage"] = 0
        job_data["success_rate"] = 0
    
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
        
        # Get original column structure from first address, excluding system columns
        original_columns = []
        system_columns = {
            'latitude', 'longitude', 'geocoded', 'geocoding_error', 'formatted_address',
            'geocoded_address', 'Breitengrad', 'Laengengrad', 'Geocodierte_Adresse',
            'street_clean', 'house_number_numeric', 'house_number_letter', 'Formatierte_Adresse',
            'Longitude', 'Latitude', 'Geocodiert', 'Geocoding_Fehler'
        }
        
        if addresses and addresses[0].get("original_row_data"):
            all_columns = list(addresses[0]["original_row_data"].keys())
            original_columns = [col for col in all_columns if col not in system_columns]
        
        # Create optimized route sheet with ALL original columns
        ws_route = wb.create_sheet("Geosortierte Route")
        
        # Define styles
        header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        header_font = Font(color="FFFFFF", bold=True)
        success_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
        error_fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
        
        # Headers: ONLY original columns + distance_to_next_m  
        route_headers = original_columns + ["distance_to_next_m"]
        
        # Write headers
        for col, header in enumerate(route_headers, 1):
            cell = ws_route.cell(row=1, column=col, value=header)
            cell.fill = header_fill
            cell.font = header_font
        
        # Write optimized data with ONLY original columns + distance_to_next_m
        for order_index, addr_index in enumerate(route["optimized_order"]):
            if addr_index < len(addresses):
                addr = addresses[addr_index]
                row_idx = order_index + 2
                
                # Original Excel columns
                if addr.get("original_row_data"):
                    for col_idx, col_name in enumerate(original_columns, 1):
                        original_value = addr["original_row_data"].get(col_name, "")
                        ws_route.cell(row=row_idx, column=col_idx, value=original_value)
                
                # Add distance_to_next_m column at the end
                distance_col = len(original_columns) + 1
                distance_value = addr.get("distance_to_next", None)
                ws_route.cell(row=row_idx, column=distance_col, value=distance_value)
        
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

@app.get("/api/job/{job_id}/failed-addresses")
async def get_failed_addresses(job_id: str):
    """Get detailed analysis of failed geocoding addresses for manual review"""
    try:
        # Check if job exists
        job = upload_jobs_collection.find_one({"id": job_id})
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        
        # Get addresses from routes collection (where they are actually stored)
        route_data = routes_collection.find_one({"job_id": job_id})
        if not route_data:
            # Fallback: try addresses collection for older jobs
            addresses = list(addresses_collection.find({"job_id": job_id}))
            if not addresses:
                raise HTTPException(status_code=404, detail="No addresses found for this job")
            
            # Convert addresses collection format
            all_addresses = addresses
        else:
            # Use optimized addresses from routes collection
            all_addresses = route_data.get('optimized_addresses', [])
        
        if not all_addresses:
            raise HTTPException(status_code=404, detail="No addresses found for this job")
        
        # Filter failed addresses and get detailed information
        failed_addresses = []
        for address in all_addresses:
            if not address.get('geocoded', False):
                # Handle both old and new data structures
                row_data = address.get('row_data', address.get('original_row_data', {}))
                
                failed_info = {
                    'id': address.get('id'),
                    'original_address': address.get('original_address', ''),
                    'row_data': row_data,
                    'geocoding_error': address.get('geocoding_error', address.get('error', 'Unknown error')),
                    'formatted_address': address.get('formatted_address', ''),
                    'address_components': {
                        'street': row_data.get('Projektname Strasse', ''),
                        'house_number': row_data.get('Hausnummer', ''),
                        'zusatz': row_data.get('Zusatz', ''),
                        'postal_code': row_data.get('PLZ', ''),
                        'city': row_data.get('Ort', '')
                    }
                }
                failed_addresses.append(failed_info)
        
        # Get job logs for additional context
        job_logger = JobLogger(job_id)
        logs = job_logger.get_logs()
        
        # Filter logs related to failed addresses
        error_logs = []
        for log in logs:
            if log.get('level') in ['WARNING', 'ERROR', 'CRITICAL']:
                log_address = log.get('address', '')
                # Try to match log entries to failed addresses
                for failed in failed_addresses:
                    if failed['original_address'] in log_address or log_address in failed['original_address']:
                        error_logs.append({
                            'address': log_address,
                            'level': log.get('level'),
                            'message': log.get('message'),
                            'timestamp': log.get('timestamp')
                        })
                        break
        
        # Calculate statistics
        total_addresses = len(all_addresses)
        failed_count = len(failed_addresses)
        success_count = total_addresses - failed_count
        failure_rate = (failed_count / total_addresses * 100) if total_addresses > 0 else 0
        
        # Categorize failures by error type
        error_categories = {}
        for failed in failed_addresses:
            error = failed['geocoding_error']
            if 'Invalid address format' in error:
                category = 'Invalid Format'
            elif 'Empty address' in error:
                category = 'Empty Address'
            elif 'No results found' in error or 'No geocoding results found' in error:
                category = 'Not Found'
            elif 'timeout' in error.lower():
                category = 'Timeout'
            elif 'rate limit' in error.lower():
                category = 'Rate Limited'
            else:
                category = 'Other Error'
            
            if category not in error_categories:
                error_categories[category] = []
            error_categories[category].append(failed)
        
        response_data = {
            'job_id': job_id,
            'job_info': {
                'filename': job.get('filename', 'Unknown'),
                'status': job.get('status', 'Unknown'),
                'created_at': job.get('created_at'),
                'completed_at': job.get('completed_at')
            },
            'statistics': {
                'total_addresses': total_addresses,
                'successful_geocoding': success_count,
                'failed_geocoding': failed_count,
                'failure_rate': round(failure_rate, 2)
            },
            'error_categories': {
                category: {
                    'count': len(addresses),
                    'percentage': round(len(addresses) / failed_count * 100, 1) if failed_count > 0 else 0
                }
                for category, addresses in error_categories.items()
            },
            'failed_addresses': failed_addresses,
            'error_logs': error_logs[:50],  # Limit to last 50 error logs
            'detailed_breakdown': error_categories
        }
        
        return response_data
        
    except Exception as e:
        print(f"Error getting failed addresses: {e}")
        raise HTTPException(status_code=500, detail=f"Error retrieving failed addresses: {str(e)}")

@app.get("/api/job/{job_id}/failed-addresses/export")
async def export_failed_addresses(job_id: str):
    """Export failed addresses analysis as Excel file"""
    try:
        # Get failed addresses data
        failed_data = await get_failed_addresses(job_id)
        
        # Create Excel file with detailed analysis
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            
            # Failed Addresses Sheet
            failed_df_data = []
            for failed in failed_data['failed_addresses']:
                row = {
                    'Original_Address': failed['original_address'],
                    'Error_Reason': failed['geocoding_error'],
                    'Street': failed['address_components']['street'],
                    'House_Number': failed['address_components']['house_number'],
                    'Additional': failed['address_components']['zusatz'],
                    'Postal_Code': failed['address_components']['postal_code'],
                    'City': failed['address_components']['city']
                }
                failed_df_data.append(row)
            
            failed_df = pd.DataFrame(failed_df_data)
            failed_df = clean_dataframe_for_excel(failed_df)
            failed_df.to_excel(writer, sheet_name='Failed Addresses', index=False)
            
            # Statistics Sheet
            stats_data = [
                ['Total Addresses', failed_data['statistics']['total_addresses']],
                ['Successful Geocoding', failed_data['statistics']['successful_geocoding']],
                ['Failed Geocoding', failed_data['statistics']['failed_geocoding']],
                ['Failure Rate (%)', failed_data['statistics']['failure_rate']],
                ['', ''],
                ['Error Categories', 'Count'],
            ]
            
            for category, info in failed_data['error_categories'].items():
                stats_data.append([category, info['count']])
            
            stats_df = pd.DataFrame(stats_data, columns=['Metric', 'Value'])
            stats_df = clean_dataframe_for_excel(stats_df)
            stats_df.to_excel(writer, sheet_name='Statistics', index=False)
            
            # Error Logs Sheet
            if failed_data['error_logs']:
                logs_df_data = []
                for log in failed_data['error_logs']:
                    logs_df_data.append({
                        'Timestamp': log['timestamp'],
                        'Level': log['level'],
                        'Address': log['address'],
                        'Message': log['message']
                    })
                
                logs_df = pd.DataFrame(logs_df_data)
                logs_df = clean_dataframe_for_excel(logs_df)
                logs_df.to_excel(writer, sheet_name='Error Logs', index=False)
        
        output.seek(0)
        
        # Prepare filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        job_filename = failed_data['job_info']['filename'].replace('.xlsx', '').replace('.csv', '')
        filename = f"failed_addresses_analysis_{job_filename}_{timestamp}.xlsx"
        
        return StreamingResponse(
            BytesIO(output.read()),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except Exception as e:
        print(f"Error exporting failed addresses: {e}")
        raise HTTPException(status_code=500, detail=f"Error exporting failed addresses: {str(e)}")

@app.get("/api/route/{job_id}")
async def get_route(job_id: str):
    """Get optimized route for a job"""
    
    # Check if job exists and is completed
    job = upload_jobs_collection.find_one({"id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job["status"] != "completed":
        raise HTTPException(status_code=400, detail="Job is not completed yet")
    
    # Get route from routes collection
    route = routes_collection.find_one({"job_id": job_id})
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    
    # Use optimized addresses from route data (new structure)
    optimized_addresses = route.get("optimized_addresses", [])
    
    # Convert to proper format for API response
    address_objects = []
    for addr in optimized_addresses:
        address_objects.append({
            "id": addr.get("id"),
            "original_address": addr.get("original_address", ""),
            "formatted_address": addr.get("formatted_address"),
            "latitude": addr.get("latitude"),
            "longitude": addr.get("longitude"),
            "geocoded": addr.get("geocoded", False),
            "geocoding_error": addr.get("geocoding_error", addr.get("error")),
            "distance_to_next": addr.get("distance_to_next")
        })
    
    return {
        "id": str(route.get("_id")),
        "job_id": job_id,
        "addresses": address_objects,
        "optimized_addresses": address_objects,  # Same as addresses since they're already optimized
        "total_distance": route.get("total_distance", 0),
        "created_at": route.get("created_at").isoformat() if route.get("created_at") else None
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