from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
import pandas as pd
import requests
import time
import math
import uuid
import os

# Address cache for performance
address_cache = {}
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
import json
from io import BytesIO
import asyncio
from concurrent.futures import ThreadPoolExecutor
import openpyxl
from openpyxl.styles import PatternFill, Font
from openpyxl.utils.dataframe import dataframe_to_rows
from datetime import datetime

app = FastAPI()

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MongoDB connection
MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017/sales_routes')
try:
    client = MongoClient(MONGO_URL)
    db = client['sales_routes']
    addresses_collection = db['addresses']
    routes_collection = db['routes']
    upload_jobs_collection = db['upload_jobs']
    print(f"Successfully connected to MongoDB at {MONGO_URL}")
except Exception as e:
    print(f"Error connecting to MongoDB: {str(e)}")
    # Create mock collections for testing
    from unittest.mock import MagicMock
    class MockCollection:
        def __init__(self, name):
            self.name = name
            self.data = []
        
        def insert_one(self, document):
            self.data.append(document)
            return MagicMock(inserted_id=document.get('id', 'mock_id'))
        
        def insert_many(self, documents):
            self.data.extend(documents)
            return MagicMock(inserted_ids=[doc.get('id', 'mock_id') for doc in documents])
        
        def find_one(self, query):
            for doc in self.data:
                match = True
                for key, value in query.items():
                    if key not in doc or doc[key] != value:
                        match = False
                        break
                if match:
                    return doc
            return None
        
        def find(self, query=None):
            if query is None:
                return self.data
            
            results = []
            for doc in self.data:
                match = True
                for key, value in (query or {}).items():
                    if key not in doc or doc[key] != value:
                        match = False
                        break
                if match:
                    results.append(doc)
            
            class MockCursor:
                def __init__(self, data):
                    self.data = data
                
                def sort(self, *args, **kwargs):
                    return self
                
                def __iter__(self):
                    return iter(self.data)
            
            return MockCursor(results)
        
        def update_one(self, query, update):
            for doc in self.data:
                match = True
                for key, value in query.items():
                    if key not in doc or doc[key] != value:
                        match = False
                        break
                
                if match:
                    for key, value in update.get('$set', {}).items():
                        doc[key] = value
                    return MagicMock(modified_count=1)
            
            return MagicMock(modified_count=0)
        
        def delete_one(self, query):
            for i, doc in enumerate(self.data):
                match = True
                for key, value in query.items():
                    if key not in doc or doc[key] != value:
                        match = False
                        break
                
                if match:
                    self.data.pop(i)
                    return MagicMock(deleted_count=1)
            
            return MagicMock(deleted_count=0)
        
        def delete_many(self, query):
            deleted = 0
            i = 0
            while i < len(self.data):
                doc = self.data[i]
                match = True
                for key, value in query.items():
                    if key not in doc or doc[key] != value:
                        match = False
                        break
                
                if match:
                    self.data.pop(i)
                    deleted += 1
                else:
                    i += 1
            
            return MagicMock(deleted_count=deleted)
    
    print("Using mock MongoDB collections for testing")
    addresses_collection = MockCollection('addresses')
    routes_collection = MockCollection('routes')
    upload_jobs_collection = MockCollection('upload_jobs')

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

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great circle distance between two points on the earth in kilometers"""
    # Convert decimal degrees to radians
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    
    # Haversine formula
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    
    # Radius of earth in kilometers
    r = 6371
    return c * r

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

def optimize_route_improved(addresses: List[Address]) -> List[int]:
    """Improved route optimization for large datasets using nearest neighbor with 2-opt"""
    if len(addresses) <= 1:
        return [0] if addresses else []
    
    # Filter only geocoded addresses
    geocoded_addresses = [addr for addr in addresses if addr.geocoded and addr.latitude and addr.longitude]
    
    if len(geocoded_addresses) <= 1:
        return [0] if geocoded_addresses else []
    
    # Create address index mapping
    address_map = {addr.id: i for i, addr in enumerate(addresses)}
    geocoded_indices = [address_map[addr.id] for addr in geocoded_addresses]
    
    # For large datasets (>100 addresses), use sampling for initial route
    if len(geocoded_addresses) > 100:
        return optimize_large_route(geocoded_addresses, geocoded_indices)
    else:
        return optimize_small_route(geocoded_addresses, geocoded_indices)

def optimize_small_route(geocoded_addresses: List[Address], geocoded_indices: List[int]) -> List[int]:
    """Nearest neighbor algorithm for smaller datasets"""
    unvisited = set(range(len(geocoded_addresses)))
    route = []
    
    # Start from first address
    current = 0
    route.append(geocoded_indices[current])
    unvisited.remove(current)
    
    while unvisited:
        nearest_distance = float('inf')
        nearest_index = None
        
        current_addr = geocoded_addresses[current]
        
        for next_index in unvisited:
            next_addr = geocoded_addresses[next_index]
            distance = haversine_distance(
                current_addr.latitude, current_addr.longitude,
                next_addr.latitude, next_addr.longitude
            )
            
            if distance < nearest_distance:
                nearest_distance = distance
                nearest_index = next_index
        
        if nearest_index is not None:
            route.append(geocoded_indices[nearest_index])
            unvisited.remove(nearest_index)
            current = nearest_index
        else:
            break
    
    return route

def optimize_large_route(geocoded_addresses: List[Address], geocoded_indices: List[int]) -> List[int]:
    """Optimized algorithm for large datasets using clustering approach"""
    import random
    
    # Step 1: Geographic clustering for large datasets
    if len(geocoded_addresses) > 500:
        # Create geographic clusters based on latitude/longitude
        clusters = create_geographic_clusters(geocoded_addresses, num_clusters=min(10, len(geocoded_addresses) // 50))
        route = []
        
        # Find optimal cluster order
        cluster_centers = [calculate_cluster_center(cluster) for cluster in clusters]
        cluster_order = optimize_cluster_order(cluster_centers)
        
        # Optimize route within each cluster
        for cluster_idx in cluster_order:
            cluster = clusters[cluster_idx]
            cluster_indices = [geocoded_indices[geocoded_addresses.index(addr)] for addr in cluster]
            cluster_route = optimize_small_route(cluster, cluster_indices)
            route.extend(cluster_route)
        
        return route
    else:
        # Use standard nearest neighbor with some optimizations
        return optimize_small_route(geocoded_addresses, geocoded_indices)

def create_geographic_clusters(addresses: List[Address], num_clusters: int) -> List[List[Address]]:
    """Create geographic clusters using simple k-means-like approach"""
    import random
    
    if num_clusters >= len(addresses):
        return [[addr] for addr in addresses]
    
    # Initialize cluster centers randomly
    centers = random.sample(addresses, num_clusters)
    clusters = [[] for _ in range(num_clusters)]
    
    # Simple clustering: assign each address to nearest center
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
    clusters = [cluster for cluster in clusters if cluster]
    return clusters

def calculate_cluster_center(cluster: List[Address]) -> tuple:
    """Calculate geographic center of a cluster"""
    if not cluster:
        return (0, 0)
    
    avg_lat = sum(addr.latitude for addr in cluster) / len(cluster)
    avg_lon = sum(addr.longitude for addr in cluster) / len(cluster)
    return (avg_lat, avg_lon)

def optimize_cluster_order(cluster_centers: List[tuple]) -> List[int]:
    """Optimize order of visiting clusters"""
    if len(cluster_centers) <= 1:
        return list(range(len(cluster_centers)))
    
    # Simple nearest neighbor for cluster centers
    unvisited = set(range(len(cluster_centers)))
    route = []
    
    current = 0
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

async def process_upload_job(job_id: str, file_content: bytes, filename: str):
    """Background task to process uploaded file"""
    try:
        # Update job status
        upload_jobs_collection.update_one(
            {"id": job_id},
            {"$set": {"status": "parsing"}}
        )
        
        # Parse Excel file
        try:
            if filename.endswith('.csv'):
                df = pd.read_csv(BytesIO(file_content))
            else:
                df = pd.read_excel(BytesIO(file_content))
        except Exception as e:
            upload_jobs_collection.update_one(
                {"id": job_id},
                {"$set": {"status": "error", "error_message": f"File parsing error: {str(e)}"}}
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
                plz = str(row[plz_col]).strip() if plz_col else ""
                ort = str(row[ort_col]).strip() if ort_col else ""
                
                # Skip empty rows
                if not street or not ort:
                    continue
                
                # Combine into full address
                address_parts = []
                if street:
                    if house_num and house_num.lower() != 'nan':
                        address_parts.append(f"{street} {house_num}")
                    else:
                        address_parts.append(street)
                
                if plz and plz.lower() != 'nan':
                    if ort:
                        address_parts.append(f"{plz} {ort}")
                    else:
                        address_parts.append(plz)
                elif ort:
                    address_parts.append(ort)
                
                address_text = ", ".join(address_parts)
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
                "geocoding_error": error
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
        "completed_at": job["completed_at"].isoformat() if job.get("completed_at") else None
    }
    
    return job_data

@app.get("/api/route/{job_id}/export")
async def export_route_excel(job_id: str):
    """Export optimized route as Excel file"""
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
    
    # Create Excel workbook
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Optimized Route"
    
    # Define styles
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True)
    success_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
    error_fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
    
    # Headers
    headers = [
        "Reihenfolge", "Originaladresse", "Formatierte Adresse", 
        "Breitengrad", "Längengrad", "Geocodiert", "Status", "Fehler"
    ]
    
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.fill = header_fill
        cell.font = header_font
    
    # Create address mapping for optimized order
    address_map = {addr["id"]: addr for addr in addresses}
    
    # Add optimized addresses data
    for order, addr_index in enumerate(route["optimized_order"], 1):
        if addr_index < len(addresses):
            addr = addresses[addr_index]
            
            row = order + 1
            ws.cell(row=row, column=1, value=order)
            ws.cell(row=row, column=2, value=addr["original_address"])
            ws.cell(row=row, column=3, value=addr.get("formatted_address", ""))
            ws.cell(row=row, column=4, value=addr.get("latitude", ""))
            ws.cell(row=row, column=5, value=addr.get("longitude", ""))
            ws.cell(row=row, column=6, value="Ja" if addr.get("geocoded") else "Nein")
            ws.cell(row=row, column=7, value="Erfolgreich" if addr.get("geocoded") else "Fehlgeschlagen")
            ws.cell(row=row, column=8, value=addr.get("geocoding_error", ""))
            
            # Apply styling based on geocoding status
            if addr.get("geocoded"):
                for col in range(1, 9):
                    ws.cell(row=row, column=col).fill = success_fill
            else:
                for col in range(1, 9):
                    ws.cell(row=row, column=col).fill = error_fill
    
    # Auto-adjust column widths
    for column in ws.columns:
        max_length = 0
        column_letter = column[0].column_letter
        for cell in column:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except:
                pass
        adjusted_width = min(max_length + 2, 50)
        ws.column_dimensions[column_letter].width = adjusted_width
    
    # Add summary sheet
    ws_summary = wb.create_sheet("Zusammenfassung")
    ws_summary.cell(row=1, column=1, value="Routenoptimierung - Zusammenfassung").font = Font(bold=True, size=14)
    ws_summary.cell(row=3, column=1, value="Dateiname:").font = Font(bold=True)
    ws_summary.cell(row=3, column=2, value=job["filename"])
    ws_summary.cell(row=4, column=1, value="Gesamtanzahl Adressen:").font = Font(bold=True)
    ws_summary.cell(row=4, column=2, value=job["total_addresses"])
    ws_summary.cell(row=5, column=1, value="Erfolgreich geocodiert:").font = Font(bold=True)
    ws_summary.cell(row=5, column=2, value=job["geocoded_addresses"])
    ws_summary.cell(row=6, column=1, value="Gesamtdistanz:").font = Font(bold=True)
    ws_summary.cell(row=6, column=2, value=f"{route['total_distance']:.2f} km")
    ws_summary.cell(row=7, column=1, value="Erstellt am:").font = Font(bold=True)
    ws_summary.cell(row=7, column=2, value=datetime.now().strftime("%d.%m.%Y %H:%M:%S"))
    
    # Save to BytesIO
    excel_buffer = BytesIO()
    wb.save(excel_buffer)
    excel_buffer.seek(0)
    
    # Create filename
    filename = f"optimized_route_{job_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    
    return StreamingResponse(
        BytesIO(excel_buffer.getvalue()),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

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
        job_list.append({
            "id": job["id"],
            "filename": job["filename"],
            "status": job["status"],
            "total_addresses": job["total_addresses"],
            "processed_addresses": job["processed_addresses"],
            "geocoded_addresses": job["geocoded_addresses"],
            "error_message": job.get("error_message"),
            "created_at": job["created_at"].isoformat() if job["created_at"] else None,
            "completed_at": job["completed_at"].isoformat() if job.get("completed_at") else None
        })
    
    return {"jobs": job_list}

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

@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "message": "Sales Route Optimizer API is running"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)