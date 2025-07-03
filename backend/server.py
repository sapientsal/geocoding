from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
import pandas as pd
import requests
import time
import math
import uuid
import os
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
import json
from io import BytesIO
import asyncio
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

def geocode_address(address: str) -> tuple:
    """Geocode an address using OpenStreetMap Nominatim API"""
    try:
        # Add delay to respect rate limits (1 request per second)
        time.sleep(1)
        
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
            return lat, lon, formatted_address, None
        else:
            return None, None, None, f"No results found for address: {address}"
            
    except requests.exceptions.RequestException as e:
        return None, None, None, f"Geocoding API error: {str(e)}"
    except Exception as e:
        return None, None, None, f"Geocoding error: {str(e)}"

def optimize_route(addresses: List[Address]) -> List[int]:
    """Optimize route using nearest neighbor algorithm"""
    if len(addresses) <= 1:
        return [0] if addresses else []
    
    # Filter only geocoded addresses
    geocoded_addresses = [addr for addr in addresses if addr.geocoded and addr.latitude and addr.longitude]
    
    if len(geocoded_addresses) <= 1:
        return [0] if geocoded_addresses else []
    
    # Create address index mapping
    address_map = {addr.id: i for i, addr in enumerate(addresses)}
    geocoded_indices = [address_map[addr.id] for addr in geocoded_addresses]
    
    # Nearest neighbor algorithm
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
        
        # Find address column
        address_column = None
        for col in df.columns:
            if any(keyword in col.lower() for keyword in ['address', 'street', 'location', 'addr']):
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
            address_text = str(row[address_column]).strip()
            if not address_text or address_text.lower() == 'nan':
                continue
            
            address_id = str(uuid.uuid4())
            
            # Geocode address
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
        optimized_order = optimize_route(address_objects)
        
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