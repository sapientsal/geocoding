import React, { useState, useEffect, useCallback, useRef } from 'react';
import { MapContainer, TileLayer, Marker, Popup, Polyline, useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import './App.css';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || 'http://localhost:8001';

// Fix für Leaflet Default-Icons
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
});

// Erweiterte Custom Icons für nummerierte Marker
const createEnhancedNumberedIcon = (number, isStart = false, isEnd = false) => {
  const baseColor = isStart ? '#22c55e' : isEnd ? '#ef4444' : '#3b82f6';
  const shadowColor = isStart ? '#16a34a' : isEnd ? '#dc2626' : '#2563eb';
  const textColor = '#ffffff';
  const size = isStart || isEnd ? 40 : 35;
  
  return L.divIcon({
    html: `
      <div style="
        position: relative;
        width: ${size}px;
        height: ${size}px;
      ">
        <div style="
          background: linear-gradient(145deg, ${baseColor} 0%, ${shadowColor} 100%);
          color: ${textColor}; 
          width: ${size}px; 
          height: ${size}px; 
          border-radius: 50%; 
          display: flex; 
          align-items: center; 
          justify-content: center; 
          font-weight: bold; 
          font-size: ${isStart || isEnd ? '14px' : '12px'};
          border: 3px solid white;
          box-shadow: 0 4px 12px rgba(0,0,0,0.4), 0 2px 6px rgba(0,0,0,0.2);
          position: relative;
          z-index: 2;
          transform: ${isStart || isEnd ? 'scale(1.1)' : 'scale(1)'};
          transition: all 0.3s ease;
        ">${number}</div>
        <div style="
          position: absolute;
          top: 50%;
          left: 50%;
          transform: translate(-50%, -50%);
          width: ${size + 10}px;
          height: ${size + 10}px;
          background: ${baseColor};
          border-radius: 50%;
          opacity: 0.2;
          z-index: 1;
          animation: pulse 2s infinite;
        "></div>
      </div>
    `,
    className: 'custom-enhanced-icon',
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
    popupAnchor: [0, -size / 2]
  });
};

// Komponente für automatische Kartenanpassung
const MapFitBounds = ({ addresses }) => {
  const map = useMap();
  
  useEffect(() => {
    if (addresses && addresses.length > 0) {
      const validAddresses = addresses.filter(addr => addr.latitude && addr.longitude);
      if (validAddresses.length > 0) {
        const bounds = L.latLngBounds(
          validAddresses.map(addr => [addr.latitude, addr.longitude])
        );
        
        // Padding hinzufügen für bessere Sicht
        const options = {
          padding: [20, 20],
          maxZoom: 16
        };
        
        map.fitBounds(bounds, options);
      }
    }
  }, [addresses, map]);
  
  return null;
};

// Komponente für erweiterte Kartensteuerung
const MapControls = ({ onFullscreen, onResetView, onLayerChange, currentLayer }) => {
  const map = useMap();
  
  const handleResetView = () => {
    onResetView();
  };
  
  return (
    <div className="map-controls">
      <div className="map-control-panel">
        <button
          onClick={onFullscreen}
          className="map-control-btn fullscreen-btn"
          title="Vollbild"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" />
          </svg>
        </button>
        <button
          onClick={handleResetView}
          className="map-control-btn reset-btn"
          title="Ansicht zurücksetzen"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
        </button>
        <select
          value={currentLayer}
          onChange={(e) => onLayerChange(e.target.value)}
          className="map-layer-select"
          title="Kartenansicht wählen"
        >
          <option value="standard">Standard</option>
          <option value="satellite">Satellit</option>
          <option value="terrain">Terrain</option>
        </select>
      </div>
    </div>
  );
};

// Berechnung der Distanz zwischen zwei Punkten (Haversine-Formel)
const calculateDistance = (lat1, lon1, lat2, lon2) => {
  const R = 6371; // Erdradius in km
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const a = 
    Math.sin(dLat/2) * Math.sin(dLat/2) +
    Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * 
    Math.sin(dLon/2) * Math.sin(dLon/2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
  return R * c;
};

function App() {
  const [jobs, setJobs] = useState([]);
  const [selectedFile, setSelectedFile] = useState(null);
  const [uploadStatus, setUploadStatus] = useState('idle'); // 'idle', 'uploading', 'processing'
  const [uploadProgress, setUploadProgress] = useState(0);
  const [dragActive, setDragActive] = useState(false);
  const [currentJobId, setCurrentJobId] = useState(null);
  const [jobStatus, setJobStatus] = useState(null);
  const [route, setRoute] = useState(null);
  const [showRoute, setShowRoute] = useState(false);
  const [filePreview, setFilePreview] = useState(null);
  const [showPreview, setShowPreview] = useState(false);
  const [showMap, setShowMap] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [currentMapLayer, setCurrentMapLayer] = useState('standard');
  const [routeDistances, setRouteDistances] = useState([]);
  const [sortingMode, setSortingMode] = useState('route_optimization'); // 'route_optimization' or 'street_sorting'
  const mapRef = useRef(null);

  // Fetch jobs on component mount
  useEffect(() => {
    fetchJobs();
  }, []);

  // Poll job status more frequently for better live updates
  useEffect(() => {
    if (currentJobId) {
      const interval = setInterval(() => {
        fetchJobStatus(currentJobId);
      }, 1000); // Update every 1 second instead of 2

      return () => clearInterval(interval);
    }
  }, [currentJobId]);

  const fetchJobs = async () => {
    try {
      const response = await fetch(`${BACKEND_URL}/api/jobs`);
      const data = await response.json();
      setJobs(data); // Backend returns array directly now
    } catch (error) {
      console.error('Error fetching jobs:', error);
    }
  };

  const fetchJobStatus = async (jobId) => {
    try {
      const response = await fetch(`${BACKEND_URL}/api/job/${jobId}`);
      const data = await response.json();
      setJobStatus(data);

      if (data.status === 'completed' || data.status === 'error') {
        // Stop polling wenn Job fertig ist
        setCurrentJobId(null);
        fetchJobs();
        
        // Clear job status nach kurzer Zeit um UI sauber zu halten
        setTimeout(() => {
          setJobStatus(null);
        }, 5000); // Zeige Completion-Status 5 Sekunden lang
      }
    } catch (error) {
      console.error('Error fetching job status:', error);
    }
  };

  const fetchRoute = async (jobId) => {
    try {
      const response = await fetch(`${BACKEND_URL}/api/route/${jobId}`);
      const data = await response.json();
      setRoute(data);
      setShowRoute(true);
      
      // Berechne Distanzen zwischen aufeinanderfolgenden Punkten
      if (data.optimized_addresses && data.optimized_addresses.length > 1) {
        const distances = [];
        for (let i = 0; i < data.optimized_addresses.length - 1; i++) {
          const current = data.optimized_addresses[i];
          const next = data.optimized_addresses[i + 1];
          
          if (current.latitude && current.longitude && next.latitude && next.longitude) {
            const distance = calculateDistance(
              current.latitude, current.longitude,
              next.latitude, next.longitude
            );
            distances.push({
              from: i,
              to: i + 1,
              distance: distance,
              fromAddress: current.original_address,
              toAddress: next.original_address
            });
          }
        }
        setRouteDistances(distances);
      }
    } catch (error) {
      console.error('Error fetching route:', error);
      alert('Error fetching route data');
    }
  };

  const handleFullscreen = () => {
    setIsFullscreen(!isFullscreen);
  };

  const handleResetView = () => {
    if (mapRef.current && route?.optimized_addresses) {
      const validAddresses = route.optimized_addresses.filter(addr => addr.latitude && addr.longitude);
      if (validAddresses.length > 0) {
        const bounds = L.latLngBounds(
          validAddresses.map(addr => [addr.latitude, addr.longitude])
        );
        mapRef.current.fitBounds(bounds, { padding: [20, 20], maxZoom: 16 });
      }
    }
  };

  const handleLayerChange = (layer) => {
    setCurrentMapLayer(layer);
  };

  const getTileLayerUrl = (layer) => {
    switch (layer) {
      case 'satellite':
        return 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';
      case 'terrain':
        return 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png';
      default:
        return 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
    }
  };

  const getTileLayerAttribution = (layer) => {
    switch (layer) {
      case 'satellite':
        return '&copy; <a href="https://www.esri.com/">Esri</a> &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community';
      case 'terrain':
        return '&copy; <a href="https://www.opentopomap.org/">OpenTopoMap</a> contributors';
      default:
        return '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
    }
  };

  const handleDrag = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  }, []);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    
    console.log('File drop triggered:', e.dataTransfer.files); // Debug log
    
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const file = e.dataTransfer.files[0];
      
      console.log('New file dropped:', file.name); // Debug log
      
      // Reset alle states vor neuer Preview
      setUploadStatus('idle');
      setUploadProgress(0);
      setShowPreview(false);
      setFilePreview(null);
      
      setSelectedFile(file);
      
      // Etwas Verzögerung für UI-Update
      setTimeout(() => {
        previewFile(file);
      }, 100);
    }
  }, []);

  const previewFile = async (file) => {
    if (!file) return;

    // Sofort Preview-Loading-State setzen
    setShowPreview(false);
    setFilePreview(null);

    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await fetch(`${BACKEND_URL}/api/preview`, {
        method: 'POST',
        body: formData,
      });

      if (response.ok) {
        const preview = await response.json();
        console.log('Preview received:', preview); // Debug log
        setFilePreview(preview);
        setShowPreview(true);
      } else {
        const error = await response.json();
        console.error('Preview error:', error); // Debug log
        handleApiError({ response: { data: error } }, 'Datei-Vorschau');
      }
    } catch (error) {
      console.error('Error previewing file:', error);
      handleApiError(error, 'Datei-Vorschau');
    }
  };

  // Komplett neues File Reset System
  // Enhanced error handling function
  const handleApiError = (error, context = 'API call') => {
    console.error(`Error in ${context}:`, error);
    
    if (error.response) {
      // API returned an error response
      const errorData = error.response.data;
      const errorMessage = errorData.detail || errorData.message || 'Ein Fehler ist aufgetreten';
      const errorId = errorData.error_id ? ` (ID: ${errorData.error_id})` : '';
      alert(`Fehler${errorId}: ${errorMessage}`);
    } else if (error.request) {
      // Network error
      alert('Netzwerkfehler: Keine Verbindung zum Server möglich. Bitte prüfen Sie Ihre Internetverbindung.');
    } else {
      // Other error
      alert(`Unerwarteter Fehler: ${error.message || 'Unbekannter Fehler'}`);
    }
  };
  const resetFileSelection = () => {
    setSelectedFile(null);
    setFilePreview(null);
    setShowPreview(false);
    setUploadStatus('idle');
    setUploadProgress(0);
    
    // File Input komplett zurücksetzen
    const fileInput = document.getElementById('file-input');
    if (fileInput) {
      fileInput.value = '';
      fileInput.type = 'text';
      fileInput.type = 'file';
    }
  };

  const handleFileSelect = (e) => {
    console.log('File select triggered:', e.target.files); // Debug log
    
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      
      console.log('New file selected:', file.name); // Debug log
      
      // Komplett zurücksetzen vor neuer Datei
      setUploadStatus('idle');
      setUploadProgress(0);
      setShowPreview(false);
      setFilePreview(null);
      
      setSelectedFile(file);
      
      // Etwas Verzögerung für UI-Update
      setTimeout(() => {
        previewFile(file);
      }, 100);
    }
  };

  // Upload-Handler für kombinierte geografische Optimierung
  const handleInstantUpload = () => {
    if (!selectedFile) return;
    
    // SOFORT UI-State setzen - keine Verzögerung
    setUploadStatus('uploading');
    setShowPreview(false);
    setFilePreview(null);
    setUploadProgress(0);
    
    // Upload-Prozess starten - jetzt nur noch eine Funktion
    performOptimizedUpload();
  };

  const performOptimizedUpload = async () => {
    const formData = new FormData();
    formData.append('file', selectedFile);

    try {
      setUploadProgress(10);
      
      const response = await fetch(`${BACKEND_URL}/api/upload-optimized`, {
        method: 'POST',
        body: formData,
      });

      setUploadProgress(50);

      const data = await response.json();
      
      if (response.ok) {
        setUploadProgress(80);
        setCurrentJobId(data.job_id);
        setUploadProgress(100);
        
        // Nach erfolgreichem Upload Status zurücksetzen
        setTimeout(() => {
          setUploadStatus('idle');
          setUploadProgress(0);
          // Reset file selection und preview states für nächsten Upload
          setSelectedFile(null);
          setFilePreview(null);
          setShowPreview(false);
        }, 1000);
        
        fetchJobs();
      } else {
        alert(`Upload fehlgeschlagen: ${data.detail}`);
        setUploadStatus('idle');
        setShowPreview(true);
        setUploadProgress(0);
      }
    } catch (error) {
      console.error('Error uploading file for optimization:', error);
      alert('Fehler beim Upload der Datei für Optimierung');
      setUploadStatus('idle');
      setShowPreview(true);
      setUploadProgress(0);
    }
  };

  const performUpload = async () => {
    const formData = new FormData();
    formData.append('file', selectedFile);

    try {
      setUploadProgress(10);
      
      const response = await fetch(`${BACKEND_URL}/api/upload`, {
        method: 'POST',
        body: formData,
      });

      setUploadProgress(50);

      const data = await response.json();
      
      if (response.ok) {
        setUploadProgress(80);
        setCurrentJobId(data.job_id);
        setUploadProgress(100);
        
        // Nach erfolgreichem Upload Status zurücksetzen
        setTimeout(() => {
          setUploadStatus('idle');
          setUploadProgress(0);
          // Reset file selection und preview states für nächsten Upload
          setSelectedFile(null);
          setFilePreview(null);
          setShowPreview(false);
        }, 1000);
        
        fetchJobs();
      } else {
        alert(`Upload fehlgeschlagen: ${data.detail}`);
        setUploadStatus('idle');
        setShowPreview(true);
        setUploadProgress(0);
      }
    } catch (error) {
      console.error('Error uploading file:', error);
      alert('Fehler beim Upload der Datei');
      setUploadStatus('idle');
      setShowPreview(true);
      setUploadProgress(0);
    }
  };

  const handleDeleteJob = async (jobId) => {
    if (!confirm('Are you sure you want to delete this job?')) return;

    try {
      const response = await fetch(`${BACKEND_URL}/api/job/${jobId}`, {
        method: 'DELETE',
      });

      if (response.ok) {
        fetchJobs();
      } else {
        alert('Error deleting job');
      }
    } catch (error) {
      console.error('Error deleting job:', error);
      alert('Error deleting job');
    }
  };

  const formatDistance = (distance) => {
    return `${distance.toFixed(2)} km`;
  };

  const getStatusColor = (status) => {
    switch (status) {
      case 'completed':
        return 'text-green-600 bg-green-100';
      case 'error':
        return 'text-red-600 bg-red-100';
      case 'uploading':
      case 'parsing':
      case 'geocoding':
      case 'optimizing':
        return 'text-blue-600 bg-blue-100';
      default:
        return 'text-gray-600 bg-gray-100';
    }
  };

  const getProgressPercentage = (job) => {
    if (job.total_addresses === 0) return 0;
    
    switch (job.status) {
      case 'uploading':
        return 5;
      case 'parsing':
        return 10;
      case 'geocoding':
        // More granular progress for geocoding
        const geocodingProgress = (job.processed_addresses / job.total_addresses) * 70;
        return 10 + geocodingProgress;
      case 'optimizing':
        return 85;
      case 'completed':
        return 100;
      default:
        return 0;
    }
  };

  const getEstimatedTime = (job) => {
    if (!job || job.status === 'completed' || job.status === 'error') return null;
    
    const remaining = job.total_addresses - job.processed_addresses;
    
    switch (job.status) {
      case 'geocoding':
        // Estimate based on improved speed (0.5 seconds per address with caching)
        const avgTimePerAddress = 0.7; // seconds (accounting for cache hits)
        const estimatedSeconds = remaining * avgTimePerAddress;
        
        if (estimatedSeconds < 60) {
          return `~${Math.ceil(estimatedSeconds)} Sekunden`;
        } else if (estimatedSeconds < 3600) {
          return `~${Math.ceil(estimatedSeconds / 60)} Minuten`;
        } else {
          return `~${Math.ceil(estimatedSeconds / 3600)} Stunden`;
        }
      case 'optimizing':
        // Route optimization is much faster
        return '~30 Sekunden';
      default:
        return 'Wird geschätzt...';
    }
  };

  const downloadExcel = async (jobId) => {
    try {
      // Für die neue kombinierte Lösung verwenden wir nur noch den optimized endpoint
      const response = await fetch(`${BACKEND_URL}/api/optimized/${jobId}/export`);
      
      if (response.ok) {
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        
        // Get filename from response headers or create default
        const contentDisposition = response.headers.get('Content-Disposition');
        let filename = `geografisch_optimiert_${jobId}.xlsx`;
        
        if (contentDisposition) {
          const filenameMatch = contentDisposition.match(/filename="?([^"]*)"?/);
          if (filenameMatch) {
            filename = filenameMatch[1];
          }
        }
        
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      } else {
        alert('Fehler beim Excel-Export');
      }
    } catch (error) {
      console.error('Error downloading Excel:', error);
      alert('Fehler beim Excel-Export');
    }
  };

  const fetchOptimizedRoute = async (jobId) => {
    try {
      const response = await fetch(`${BACKEND_URL}/api/optimized/${jobId}`);
      const data = await response.json();
      
      // Transform optimized data to be compatible with the existing route display
      const transformedData = {
        ...data,
        optimized_addresses: data.optimized_addresses.map((addr, index) => ({
          id: addr.id,
          original_address: addr.original_address,
          formatted_address: addr.formatted_address,
          latitude: addr.latitude,
          longitude: addr.longitude,
          geocoded: addr.geocoded,
          distance_to_next: addr.distance_to_next,
          row_data: addr.row_data,
          index: index
        })),
        job_id: jobId,
        optimization_type: 'geographic_door_to_door'
      };
      
      setRoute(transformedData);
      setShowRoute(true);
      
      // Calculate distances for route visualization
      if (data.optimized_addresses && data.optimized_addresses.length > 1) {
        const distances = [];
        for (let i = 0; i < data.optimized_addresses.length - 1; i++) {
          const current = data.optimized_addresses[i];
          const next = data.optimized_addresses[i + 1];
          
          if (current.latitude && current.longitude && next.latitude && next.longitude) {
            const distance = calculateDistance(
              current.latitude, current.longitude,
              next.latitude, next.longitude
            );
            distances.push({
              from: i,
              to: i + 1,
              distance: distance,
              fromAddress: current.original_address || 'Adresse',
              toAddress: next.original_address || 'Adresse'
            });
          }
        }
        setRouteDistances(distances);
      }
    } catch (error) {
      console.error('Error fetching optimized route:', error);
      alert('Error fetching route data');
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100">
      <div className="container mx-auto px-4 py-8">
        {/* Header */}
        <div className="text-center mb-12">
          <h1 className="text-4xl font-bold text-gray-900 mb-4">
            🚀 Sales Route Optimizer
          </h1>
          <p className="text-lg text-gray-600 max-w-2xl mx-auto">
            Laden Sie Ihre Excel-Adressliste hoch und erhalten Sie eine optimierte Route für effiziente Vertriebsbesuche
          </p>
          <p className="text-sm text-gray-500 mt-2">
            Unterstützt deutsche Adressformate (Straße, Hausnummer, PLZ, Ort) und internationale Formate
          </p>
        </div>

        {/* Upload Section */}
        <div className="bg-white rounded-lg shadow-lg p-8 mb-8">
          <h2 className="text-2xl font-semibold text-gray-800 mb-6">📍 Adressliste für Door-to-Door-Vertrieb hochladen</h2>
          
          {/* Feature Description */}
          <div className="mb-6 p-4 bg-gradient-to-r from-blue-50 to-green-50 rounded-lg border border-blue-200">
            <h3 className="text-lg font-medium text-gray-800 mb-3 flex items-center">
              <svg className="w-6 h-6 mr-2 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
              Geografische Route-Optimierung
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
              <div className="flex items-start">
                <span className="text-green-600 mr-2">✅</span>
                <div>
                  <div className="font-semibold">Automatische Geocodierung</div>
                  <div className="text-gray-600">Alle Adressen werden automatisch geocodiert</div>
                </div>
              </div>
              <div className="flex items-start">
                <span className="text-green-600 mr-2">✅</span>
                <div>
                  <div className="font-semibold">Geografische Optimierung</div>
                  <div className="text-gray-600">Kürzeste Wege zwischen allen Adressen</div>
                </div>
              </div>
              <div className="flex items-start">
                <span className="text-green-600 mr-2">✅</span>
                <div>
                  <div className="font-semibold">Exakte Distanzen</div>
                  <div className="text-gray-600">Meter-genaue Entfernungsberechnung</div>
                </div>
              </div>
            </div>
          </div>
          
          <div
            className={`border-2 border-dashed rounded-lg p-8 text-center transition-colors ${
              dragActive
                ? 'border-blue-500 bg-blue-50'
                : 'border-gray-300 hover:border-blue-400'
            }`}
            onDragEnter={handleDrag}
            onDragLeave={handleDrag}
            onDragOver={handleDrag}
            onDrop={handleDrop}
          >
            <div className="mb-4">
              <svg className="w-12 h-12 text-gray-400 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
              </svg>
              <p className="text-lg text-gray-600 mb-2">
                Ziehen Sie Ihre Excel-Datei hierher oder klicken Sie zum Durchsuchen
              </p>
              <p className="text-sm text-gray-500">
                Unterstützt .xlsx, .xls und .csv Dateien mit deutschen Adressformaten
              </p>
            </div>
            
            <input
              type="file"
              accept=".xlsx,.xls,.csv"
              onChange={handleFileSelect}
              className="hidden"
              id="file-input"
            />
            
            <label
              htmlFor="file-input"
              className="inline-block px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 cursor-pointer transition-colors"
            >
              Datei auswählen
            </label>
            
            {selectedFile && (
              <div className="mt-4 p-4 bg-gray-50 rounded-lg">
                <p className="text-sm text-gray-700">
                  Ausgewählt: <span className="font-semibold">{selectedFile.name}</span>
                </p>
                <p className="text-xs text-gray-500 mt-1">
                  Größe: {(selectedFile.size / 1024 / 1024).toFixed(2)} MB
                </p>
              </div>
            )}
          </div>
          
          <div className="flex justify-center mt-6">
            <button
              onClick={handleInstantUpload}
              disabled={!selectedFile || uploadStatus !== 'idle'}
              className={`px-8 py-3 rounded-lg font-semibold transition-all duration-300 ${
                !selectedFile || uploadStatus !== 'idle'
                  ? 'bg-gray-300 text-gray-500 cursor-not-allowed'
                  : 'bg-gradient-to-r from-blue-600 to-green-600 text-white hover:from-blue-700 hover:to-green-700 transform hover:-translate-y-1 shadow-lg hover:shadow-xl'
              }`}
            >
              {uploadStatus === 'uploading' ? (
                <div className="flex items-center">
                  <svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-white" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
                  Hochladen & Optimieren...
                </div>
              ) : '🚀 Hochladen & Geografisch Optimieren'}
            </button>
          </div>
        </div>

        {/* Compact Processing Banner for Any Active Job */}
        {(uploadStatus === 'uploading' || (jobStatus && jobStatus.status !== 'completed' && jobStatus.status !== 'error')) && (
          <div className="bg-gradient-to-r from-blue-600 to-blue-700 text-white px-6 py-3 mb-4 rounded-lg shadow-lg">
            <div className="flex items-center justify-between">
              <div className="flex items-center">
                <svg className="animate-spin h-5 w-5 text-white mr-3" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                <span className="font-medium">
                  {uploadStatus === 'uploading' ? '📁 Datei wird hochgeladen' :
                   jobStatus?.status === 'geocoding' ? '🗺️ Geocodierung läuft' :
                   jobStatus?.status === 'optimizing' ? '🚀 Route wird optimiert' :
                   jobStatus?.status === 'sorting' ? '📍 Straßen-Sortierung läuft' :
                   jobStatus?.status === 'parsing' ? '📊 Datei wird analysiert' :
                   '⚡ Verarbeitung läuft'}
                </span>
              </div>
              <div className="flex items-center space-x-4">
                <div className="text-sm font-medium">
                  {uploadStatus === 'uploading' ? 
                    `Upload: ${uploadProgress}%` :
                    jobStatus?.status === 'geocoding' ? 
                      `${jobStatus.processed_addresses}/${jobStatus.total_addresses} Adressen geocodiert` :
                    jobStatus?.status === 'optimizing' ?
                      `${jobStatus.geocoded_addresses} Adressen → Route optimieren` :
                    jobStatus ? 
                      `${getProgressPercentage(jobStatus).toFixed(0)}%` :
                      `${uploadProgress}%`
                  }
                </div>
                <div className="w-32 bg-blue-500 rounded-full h-2">
                  <div 
                    className="bg-white h-2 rounded-full transition-all duration-500"
                    style={{width: `${uploadStatus === 'uploading' ? uploadProgress : jobStatus ? getProgressPercentage(jobStatus) : 0}%`}}
                  ></div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Instant Upload Status Indicator */}

        {/* File Preview */}
        {showPreview && filePreview && (
          <div className="bg-white rounded-lg shadow-lg p-8 mb-8">
            <div className="flex justify-between items-center mb-6">
              <h2 className="text-2xl font-semibold text-gray-800">📋 Datei-Vorschau</h2>
              <button
                onClick={() => setShowPreview(false)}
                className="text-gray-500 hover:text-gray-700 text-2xl"
              >
                ×
              </button>
            </div>
            
            <div className="grid grid-cols-2 gap-6 mb-6">
              <div>
                <h3 className="text-lg font-semibold text-gray-700 mb-3">📄 Datei-Informationen</h3>
                <div className="space-y-2 text-sm">
                  <div><span className="font-medium">Dateiname:</span> {filePreview.filename}</div>
                  <div><span className="font-medium">Erkanntes Format:</span> <span className="text-green-600">{filePreview.detected_format}</span></div>
                  <div><span className="font-medium">Anzahl Spalten:</span> {filePreview.columns.length}</div>
                </div>
              </div>
              
              <div>
                <h3 className="text-lg font-semibold text-gray-700 mb-3">🎯 Erkannte Adress-Spalten</h3>
                <div className="space-y-2 text-sm">
                  <div><span className="font-medium">Straße:</span> {filePreview.detected_columns.street || 'Nicht erkannt'}</div>
                  <div><span className="font-medium">Hausnummer:</span> {filePreview.detected_columns.house_number || 'Nicht erkannt'}</div>
                  <div><span className="font-medium">PLZ:</span> {filePreview.detected_columns.plz || 'Nicht erkannt'}</div>
                  <div><span className="font-medium">Ort:</span> {filePreview.detected_columns.ort || 'Nicht erkannt'}</div>
                  {filePreview.detected_columns.zusatz && (
                    <div><span className="font-medium">Zusatz:</span> {filePreview.detected_columns.zusatz}</div>
                  )}
                </div>
              </div>
            </div>
            
            {filePreview.preview_addresses && filePreview.preview_addresses.length > 0 && (
              <div className="mb-6">
                <h3 className="text-lg font-semibold text-gray-700 mb-3">
                  🏠 Alle erkannten Adressen ({filePreview.preview_addresses.length} Adressen)
                </h3>
                <div className="bg-gray-50 rounded-lg p-4 max-h-96 overflow-y-auto custom-scrollbar">
                  <div className="space-y-2">
                    {filePreview.preview_addresses.map((addressObj, index) => (
                      <div key={index} className="flex items-start bg-white rounded-lg p-3 shadow-sm hover:shadow-md transition-shadow">
                        <span className="w-8 h-8 bg-blue-600 text-white rounded-full flex items-center justify-center text-sm font-semibold mr-3 mt-0.5 flex-shrink-0">
                          {addressObj.index || index + 1}
                        </span>
                        <div className="flex-1 min-w-0">
                          <div className="text-gray-800 font-medium mb-1">
                            {addressObj.address || addressObj}
                          </div>
                          {addressObj.original_parts && (
                            <div className="text-xs text-gray-500 grid grid-cols-2 gap-2">
                              <span>Straße: {addressObj.original_parts.street}</span>
                              <span>Nr: {addressObj.original_parts.house_number}{addressObj.original_parts.zusatz ? ` ${addressObj.original_parts.zusatz}` : ''}</span>
                              <span>PLZ: {addressObj.original_parts.plz}</span>
                              <span>Ort: {addressObj.original_parts.ort}</span>
                            </div>
                          )}
                        </div>
                        <div className="ml-2 flex-shrink-0">
                          <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-green-100 text-green-800">
                            ✓ Erkannt
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
                <div className="mt-3 text-center">
                  <p className="text-sm text-gray-600">
                    📊 {filePreview.preview_addresses.length} Adressen werden verarbeitet und geosortiert
                  </p>
                </div>
              </div>
            )}
            
            <div className="flex space-x-4">
              <button
                onClick={handleInstantUpload}
                disabled={!selectedFile || uploadStatus !== 'idle'}
                className="px-6 py-3 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors disabled:opacity-50 flex items-center"
              >
                {uploadStatus === 'uploading' ? (
                  <>
                    <svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                    Upload läuft... ({uploadProgress}%)
                  </>
                ) : (
                  <>
                    ✅ Datei verarbeiten ({filePreview.preview_addresses?.length || 0} Adressen)
                  </>
                )}
              </button>
              
              <button
                onClick={resetFileSelection}
                className="px-6 py-3 bg-gray-600 text-white rounded-lg hover:bg-gray-700 transition-colors"
                disabled={uploadStatus !== 'idle'}
              >
                🔄 Andere Datei wählen
              </button>
            </div>
          </div>
        )}

        {/* Current Job Status with Address Counter */}
        {jobStatus && (
          <div className="bg-white rounded-lg shadow-lg p-6 mb-8">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-semibold text-gray-800">📊 Verarbeitungs-Status</h2>
              <span className={`px-3 py-1 rounded-full text-sm font-medium ${getStatusColor(jobStatus.status)}`}>
                {jobStatus.status === 'completed' ? 'Abgeschlossen' :
                 jobStatus.status === 'error' ? 'Fehler' :
                 jobStatus.status === 'geocoding' ? 'Geocodierung läuft' :
                 jobStatus.status === 'optimizing' ? 'Route wird optimiert' :
                 jobStatus.status === 'sorting' ? 'Straßen-Sortierung läuft' :
                 jobStatus.status === 'parsing' ? 'Datei wird gelesen' :
                 jobStatus.status === 'uploading' ? 'Upload läuft' : jobStatus.status}
              </span>
            </div>
            
            <div className="space-y-4">
              <div className="flex justify-between items-center">
                <span className="text-gray-700">📁 Datei: {jobStatus.filename}</span>
              </div>
              
              {/* Enhanced Progress Bar with Address Counter */}
              <div className="space-y-2">
                <div className="flex justify-between text-sm text-gray-600">
                  <span>Fortschritt</span>
                  <span>
                    {jobStatus.status === 'geocoding' ? 
                      `${jobStatus.processed_addresses}/${jobStatus.total_addresses} Adressen geocodiert` :
                      jobStatus.status === 'completed' ?
                      `✅ ${jobStatus.geocoded_addresses}/${jobStatus.total_addresses} Adressen erfolgreich` :
                      `${getProgressPercentage(jobStatus).toFixed(0)}%`
                    }
                  </span>
                </div>
                <div className="w-full bg-gray-200 rounded-full h-3">
                  <div
                    className="bg-blue-600 h-3 rounded-full transition-all duration-300"
                    style={{ width: `${getProgressPercentage(jobStatus)}%` }}
                  ></div>
                </div>
              </div>
              
              {/* Detailed Statistics */}
              <div className="grid grid-cols-3 gap-4 text-sm bg-gray-50 rounded-lg p-4">
                <div className="text-center">
                  <div className="text-2xl font-bold text-blue-600">{jobStatus.total_addresses}</div>
                  <div className="text-gray-600">Gesamt</div>
                </div>
                <div className="text-center">
                  <div className="text-2xl font-bold text-orange-600">{jobStatus.processed_addresses}</div>
                  <div className="text-gray-600">Verarbeitet</div>
                </div>
                <div className="text-center">
                  <div className="text-2xl font-bold text-green-600">{jobStatus.geocoded_addresses}</div>
                  <div className="text-gray-600">Geocodiert</div>
                </div>
              </div>
              
              {getEstimatedTime(jobStatus) && (
                <div className="p-3 bg-blue-50 border border-blue-200 rounded-lg">
                  <div className="flex items-center">
                    <svg className="w-5 h-5 text-blue-600 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    <span className="text-blue-800 font-medium">
                      ⏱️ Verbleibende Zeit: {getEstimatedTime(jobStatus)}
                    </span>
                  </div>
                  {jobStatus.status === 'geocoding' && jobStatus.total_addresses > 100 && (
                    <p className="text-blue-700 text-sm mt-2">
                      🚀 Verwende optimierte Batch-Verarbeitung für {jobStatus.total_addresses} Adressen
                    </p>
                  )}
                </div>
              )}
              
              {jobStatus.error_message && (
                <div className="p-4 bg-red-50 border border-red-200 rounded-lg">
                  <p className="text-red-700">{jobStatus.error_message}</p>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Jobs List */}
        <div className="bg-white rounded-lg shadow-lg p-8">
          <h2 className="text-2xl font-semibold text-gray-800 mb-6">Upload-Verlauf</h2>
          
          {jobs.length === 0 ? (
            <p className="text-gray-500 text-center py-8">Noch keine Uploads. Laden Sie Ihre erste Adressliste oben hoch!</p>
          ) : (
            <div className="space-y-4">
              {jobs.map((job) => (
                <div key={job.id} className="border border-gray-200 rounded-lg p-6 hover:shadow-md transition-shadow">
                  <div className="flex justify-between items-start mb-4">
                    <div>
                      <h3 className="text-lg font-semibold text-gray-800 flex items-center">
                        {job.sorting_type === 'street_based' ? (
                          <>📍 {job.filename}</>
                        ) : (
                          <>🚀 {job.filename}</>
                        )}
                      </h3>
                      <p className="text-sm text-gray-500">
                        Hochgeladen: {new Date(job.created_at).toLocaleDateString('de-DE')}
                      </p>
                      <p className="text-xs text-blue-600 font-medium">
                        {job.sorting_type === 'street_based' ? 'Straßen-sortiert' : 'Route-optimiert'}
                      </p>
                      {job.status === 'completed' && job.completed_at && (
                        <p className="text-sm text-green-600">
                          Fertiggestellt: {new Date(job.completed_at).toLocaleDateString('de-DE')} um {new Date(job.completed_at).toLocaleTimeString('de-DE')}
                        </p>
                      )}
                    </div>
                    <div className="flex items-center space-x-3">
                      <span className={`px-3 py-1 rounded-full text-sm font-medium ${getStatusColor(job.status)}`}>
                        {job.status === 'completed' ? 'Abgeschlossen' :
                         job.status === 'error' ? 'Fehler' :
                         job.status === 'geocoding' ? 'Geocodierung' :
                         job.status === 'optimizing' ? 'Optimierung' :
                         job.status === 'parsing' ? 'Verarbeitung' :
                         job.status === 'uploading' ? 'Upload' : job.status}
                      </span>
                      <button
                        onClick={() => handleDeleteJob(job.id)}
                        className="text-red-600 hover:text-red-800 transition-colors"
                        title="Job löschen"
                      >
                        🗑️
                      </button>
                    </div>
                  </div>
                  
                  <div className="grid grid-cols-3 gap-4 text-sm mb-4">
                    <div>
                      <span className="text-gray-600">Gesamt:</span>
                      <span className="font-semibold ml-2">{job.total_addresses}</span>
                    </div>
                    <div>
                      <span className="text-gray-600">Verarbeitet:</span>
                      <span className="font-semibold ml-2">{job.processed_addresses}</span>
                    </div>
                    <div>
                      <span className="text-gray-600">Geocodiert:</span>
                      <span className="font-semibold ml-2 text-green-600">{job.geocoded_addresses}</span>
                    </div>
                  </div>
                  
                  {job.status === 'completed' && (
                    <div className="flex space-x-3">
                      <button
                        onClick={() => {
                          if (job.sorting_type === 'street_based') {
                            fetchStreetSortedRoute(job.id);
                          } else {
                            fetchRoute(job.id);
                          }
                        }}
                        className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
                      >
                        {job.sorting_type === 'street_based' ? '📍 Liste anzeigen' : 'Route anzeigen'}
                      </button>
                      {job.sorting_type !== 'street_based' && (
                        <button
                          onClick={() => {
                            fetchRoute(job.id);
                            setShowMap(true);
                          }}
                          className="px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition-colors"
                        >
                          🗺️ Karte anzeigen
                        </button>
                      )}
                      <button
                        onClick={() => downloadExcel(job.id)}
                        className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors"
                      >
                        📊 Excel Export
                      </button>
                    </div>
                  )}
                  
                  {job.error_message && (
                    <div className="mt-4 p-4 bg-red-50 border border-red-200 rounded-lg">
                      <p className="text-red-700 text-sm">{job.error_message}</p>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Erweiterte Route Map Modal */}
        {showMap && route && (
          <div className={`fixed inset-0 bg-black bg-opacity-60 flex items-center justify-center z-50 ${isFullscreen ? 'p-0' : 'p-4'}`}>
            <div className={`bg-white rounded-lg w-full overflow-hidden ${isFullscreen ? 'h-full max-w-full max-h-full rounded-none' : 'max-w-7xl max-h-[95vh] shadow-2xl'}`}>
              <div className="p-4 border-b border-gray-200 flex justify-between items-center bg-gradient-to-r from-blue-600 to-purple-600 text-white">
                <div className="flex items-center space-x-4">
                  <h2 className="text-xl font-semibold">🗺️ Optimierte Route - Erweiterte Kartenansicht</h2>
                  <div className="flex items-center space-x-2 text-sm bg-white bg-opacity-20 px-3 py-1 rounded-full">
                    <span>📍 {route.optimized_addresses.length} Stopps</span>
                    <span>•</span>
                    <span>📏 {formatDistance(route.total_distance)}</span>
                  </div>
                </div>
                <div className="flex items-center space-x-2">
                  <button
                    onClick={handleFullscreen}
                    className="text-white hover:text-gray-200 p-2 rounded-lg hover:bg-white hover:bg-opacity-10 transition-all duration-300"
                    title={isFullscreen ? 'Fenstermodus' : 'Vollbild'}
                  >
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      {isFullscreen ? (
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 9V4.5M9 9H4.5M9 9L3.5 3.5M15 9V4.5M15 9h4.5M15 9l5.5-5.5M9 15v4.5M9 15H4.5M9 15l-5.5 5.5M15 15v4.5M15 15h4.5M15 15l5.5 5.5" />
                      ) : (
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" />
                      )}
                    </svg>
                  </button>
                  <button
                    onClick={() => {
                      setShowMap(false);
                      setIsFullscreen(false);
                    }}
                    className="text-white hover:text-gray-200 text-2xl p-2 rounded-lg hover:bg-white hover:bg-opacity-10 transition-all duration-300"
                  >
                    ×
                  </button>
                </div>
              </div>
              
              <div className="flex h-full">
                {/* Haupt-Kartenbereich */}
                <div className={`${isFullscreen ? 'w-4/5' : 'w-3/4'} relative bg-gray-100`}>
                  <div className={`${isFullscreen ? 'h-screen' : 'h-[75vh]'} relative`}>
                    {route.optimized_addresses && route.optimized_addresses.length > 0 && (
                      <MapContainer
                        ref={mapRef}
                        center={[
                          route.optimized_addresses[0].latitude || 53.3498, 
                          route.optimized_addresses[0].longitude || 8.8071
                        ]}
                        zoom={13}
                        style={{ height: '100%', width: '100%' }}
                        className="enhanced-map"
                        zoomControl={true}
                        scrollWheelZoom={true}
                        doubleClickZoom={true}
                        dragging={true}
                      >
                        <TileLayer
                          url={getTileLayerUrl(currentMapLayer)}
                          attribution={getTileLayerAttribution(currentMapLayer)}
                        />
                        
                        {/* Automatische Kartenanpassung */}
                        <MapFitBounds addresses={route.optimized_addresses} />
                        
                        {/* Erweiterte Marker für alle Adressen */}
                        {route.optimized_addresses.map((address, index) => {
                          if (!address.latitude || !address.longitude) return null;
                          
                          const isStart = index === 0;
                          const isEnd = index === route.optimized_addresses.length - 1;
                          
                          return (
                            <Marker
                              key={address.id}
                              position={[address.latitude, address.longitude]}
                              icon={createEnhancedNumberedIcon(index + 1, isStart, isEnd)}
                            >
                              <Popup maxWidth={320} className="enhanced-popup">
                                <div className="p-4">
                                  <div className="flex items-center mb-3">
                                    <div className={`w-10 h-10 rounded-full flex items-center justify-center font-bold text-white text-sm mr-3 shadow-lg ${
                                      isStart ? 'bg-gradient-to-r from-green-500 to-green-600' : 
                                      isEnd ? 'bg-gradient-to-r from-red-500 to-red-600' : 
                                      'bg-gradient-to-r from-blue-500 to-blue-600'
                                    }`}>
                                      {index + 1}
                                    </div>
                                    <div className="font-bold text-lg">
                                      {isStart ? '🟢 Start' : isEnd ? '🔴 Ziel' : `📍 Stopp ${index + 1}`}
                                    </div>
                                  </div>
                                  
                                  <div className="space-y-3 text-sm">
                                    <div className="bg-gray-50 rounded-lg p-3">
                                      <div className="font-semibold text-gray-800 mb-1">
                                        {address.original_address}
                                      </div>
                                      {address.formatted_address && (
                                        <div className="text-gray-600 text-xs">
                                          📍 {address.formatted_address}
                                        </div>
                                      )}
                                    </div>
                                    
                                    <div className="grid grid-cols-2 gap-2 text-xs">
                                      <div className="bg-blue-50 rounded p-2">
                                        <div className="text-blue-700 font-medium">Breitengrad</div>
                                        <div className="text-blue-900">{address.latitude.toFixed(6)}</div>
                                      </div>
                                      <div className="bg-blue-50 rounded p-2">
                                        <div className="text-blue-700 font-medium">Längengrad</div>
                                        <div className="text-blue-900">{address.longitude.toFixed(6)}</div>
                                      </div>
                                    </div>
                                    
                                    {/* Distanz-Informationen */}
                                    {routeDistances.length > 0 && (
                                      <div className="border-t pt-3">
                                        {routeDistances.find(d => d.from === index) && (
                                          <div className="flex items-center text-xs text-green-600 bg-green-50 rounded p-2 mb-1">
                                            <svg className="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7l5 5m0 0l-5 5m5-5H6" />
                                            </svg>
                                            Zum nächsten Stopp: <span className="font-bold ml-1">{routeDistances.find(d => d.from === index).distance.toFixed(2)} km</span>
                                          </div>
                                        )}
                                        {routeDistances.find(d => d.to === index) && index > 0 && (
                                          <div className="flex items-center text-xs text-gray-500 bg-gray-50 rounded p-2">
                                            <svg className="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 17l-5-5m0 0l5-5m-5 5h12" />
                                            </svg>
                                            Vom vorherigen Stopp: <span className="font-medium ml-1">{routeDistances.find(d => d.to === index).distance.toFixed(2)} km</span>
                                          </div>
                                        )}
                                      </div>
                                    )}
                                    
                                    {/* Status Badge */}
                                    <div className="flex justify-end">
                                      <span className={`px-2 py-1 rounded-full text-xs font-medium ${
                                        address.geocoded
                                          ? 'bg-green-100 text-green-700'
                                          : 'bg-red-100 text-red-700'
                                      }`}>
                                        {address.geocoded ? '✅ Erfolgreich geocodiert' : '⚠️ Geocodierung fehlgeschlagen'}
                                      </span>
                                    </div>
                                  </div>
                                </div>
                              </Popup>
                            </Marker>
                          );
                        })}
                        
                        {/* Erweiterte Route-Linie mit Animationen */}
                        {route.optimized_addresses.length > 1 && (
                          <Polyline
                            positions={route.optimized_addresses
                              .filter(addr => addr.latitude && addr.longitude)
                              .map(addr => [addr.latitude, addr.longitude])}
                            color="#3b82f6"
                            weight={5}
                            opacity={0.9}
                            dashArray="10, 5"
                            className="animated-route"
                          />
                        )}
                      </MapContainer>
                    )}
                    
                    {/* Floating Map Controls */}
                    <div className="absolute top-4 right-4 z-1000">
                      <div className="bg-white bg-opacity-95 backdrop-blur-sm rounded-xl shadow-lg p-3 space-y-3">
                        <div className="flex flex-col space-y-2">
                          <button
                            onClick={handleResetView}
                            className="px-3 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-xs font-medium transition-all duration-300 shadow-md hover:shadow-lg"
                            title="Ansicht zurücksetzen"
                          >
                            <svg className="w-4 h-4 mx-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                            </svg>
                          </button>
                          <select
                            value={currentMapLayer}
                            onChange={(e) => handleLayerChange(e.target.value)}
                            className="px-2 py-1 border border-gray-300 rounded-lg text-xs focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white"
                            title="Kartenansicht wählen"
                          >
                            <option value="standard">🗺️ Standard</option>
                            <option value="satellite">🛰️ Satellit</option>
                            <option value="terrain">🏔️ Terrain</option>
                          </select>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
                
                {/* Erweiterte Seitenleiste */}
                <div className={`${isFullscreen ? 'w-1/5' : 'w-1/4'} bg-gradient-to-b from-gray-50 to-gray-100 border-l border-gray-200 overflow-y-auto custom-scrollbar`}>
                  <div className="p-4 space-y-4">
                    {/* Statistiken */}
                    <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
                      <h3 className="font-semibold text-gray-800 mb-4 flex items-center">
                        <svg className="w-5 h-5 mr-2 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v4a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                        </svg>
                        Route-Statistiken
                      </h3>
                      <div className="grid grid-cols-2 gap-3">
                        <div className="bg-blue-50 rounded-lg p-3 text-center">
                          <div className="text-2xl font-bold text-blue-600">{formatDistance(route.total_distance)}</div>
                          <div className="text-xs text-blue-700">Gesamtdistanz</div>
                        </div>
                        <div className="bg-green-50 rounded-lg p-3 text-center">
                          <div className="text-2xl font-bold text-green-600">{route.optimized_addresses.length}</div>
                          <div className="text-xs text-green-700">Stopps</div>
                        </div>
                        <div className="bg-purple-50 rounded-lg p-3 text-center">
                          <div className="text-sm font-bold text-purple-600">2-opt</div>
                          <div className="text-xs text-purple-700">Algorithmus</div>
                        </div>
                        <div className="bg-orange-50 rounded-lg p-3 text-center">
                          <div className="text-sm font-bold text-orange-600">~{Math.round(route.total_distance * 1.5)} min</div>
                          <div className="text-xs text-orange-700">Fahrzeit</div>
                        </div>
                      </div>
                    </div>
                    
                    {/* Route-Reihenfolge */}
                    <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
                      <h3 className="font-semibold text-gray-800 mb-4 flex items-center">
                        <svg className="w-5 h-5 mr-2 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
                        </svg>
                        Route-Reihenfolge
                      </h3>
                      <div className="space-y-2 max-h-80 overflow-y-auto custom-scrollbar">
                        {route.optimized_addresses.map((address, index) => {
                          const isStart = index === 0;
                          const isEnd = index === route.optimized_addresses.length - 1;
                          const routeDistance = routeDistances.find(d => d.from === index);
                          
                          return (
                            <div
                              key={address.id}
                              className={`p-3 rounded-lg border-l-4 text-sm transition-all hover:shadow-md cursor-pointer ${
                                isStart ? 'bg-gradient-to-r from-green-50 to-green-100 border-green-500 hover:from-green-100 hover:to-green-200' :
                                isEnd ? 'bg-gradient-to-r from-red-50 to-red-100 border-red-500 hover:from-red-100 hover:to-red-200' :
                                'bg-gradient-to-r from-blue-50 to-blue-100 border-blue-500 hover:from-blue-100 hover:to-blue-200'
                              }`}
                            >
                              <div className="flex items-center justify-between">
                                <div className="flex items-center">
                                  <span className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold text-white mr-3 shadow-md ${
                                    isStart ? 'bg-gradient-to-r from-green-500 to-green-600' :
                                    isEnd ? 'bg-gradient-to-r from-red-500 to-red-600' :
                                    'bg-gradient-to-r from-blue-500 to-blue-600'
                                  }`}>
                                    {index + 1}
                                  </span>
                                  <div className="min-w-0 flex-1">
                                    <div className="font-medium text-gray-800 truncate mb-1">
                                      {address.original_address}
                                    </div>
                                    {routeDistance && (
                                      <div className="text-xs text-gray-600 flex items-center">
                                        <svg className="w-3 h-3 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7l5 5m0 0l-5 5m5-5H6" />
                                        </svg>
                                        {routeDistance.distance.toFixed(2)} km
                                      </div>
                                    )}
                                  </div>
                                </div>
                                {!address.geocoded && (
                                  <div className="text-xs text-red-600 font-bold">
                                    ⚠️
                                  </div>
                                )}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                    
                    {/* Aktionen */}
                    <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
                      <h3 className="font-semibold text-gray-800 mb-4 flex items-center">
                        <svg className="w-5 h-5 mr-2 text-indigo-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 100 4m0-4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 100 4m0-4v2m0-6V4" />
                        </svg>
                        Aktionen
                      </h3>
                      <div className="space-y-3">
                        <button
                          onClick={() => downloadExcel(route.job_id)}
                          className="w-full p-3 bg-gradient-to-r from-green-600 to-green-700 hover:from-green-700 hover:to-green-800 text-white rounded-lg text-sm font-medium transition-all duration-300 shadow-md hover:shadow-lg transform hover:-translate-y-0.5"
                        >
                          <div className="flex items-center justify-center">
                            <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                            </svg>
                            Excel exportieren
                          </div>
                        </button>
                        <button
                          onClick={() => setShowRoute(true)}
                          className="w-full p-3 bg-gradient-to-r from-blue-600 to-blue-700 hover:from-blue-700 hover:to-blue-800 text-white rounded-lg text-sm font-medium transition-all duration-300 shadow-md hover:shadow-lg transform hover:-translate-y-0.5"
                        >
                          <div className="flex items-center justify-center">
                            <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                            </svg>
                            Detailliste anzeigen
                          </div>
                        </button>
                      </div>
                    </div>
                    
                    {/* Legende */}
                    <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
                      <h3 className="font-semibold text-gray-800 mb-3 flex items-center">
                        <svg className="w-5 h-5 mr-2 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>
                        Legende
                      </h3>
                      <div className="space-y-2 text-xs">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center">
                            <div className="w-4 h-4 bg-gradient-to-r from-green-500 to-green-600 rounded-full mr-2"></div>
                            <span>Start</span>
                          </div>
                        </div>
                        <div className="flex items-center justify-between">
                          <div className="flex items-center">
                            <div className="w-4 h-4 bg-gradient-to-r from-blue-500 to-blue-600 rounded-full mr-2"></div>
                            <span>Zwischenstopps</span>
                          </div>
                        </div>
                        <div className="flex items-center justify-between">
                          <div className="flex items-center">
                            <div className="w-4 h-4 bg-gradient-to-r from-red-500 to-red-600 rounded-full mr-2"></div>
                            <span>Ziel</span>
                          </div>
                        </div>
                        <div className="flex items-center justify-between">
                          <div className="flex items-center">
                            <div className="w-6 h-1 bg-blue-500 mr-2"></div>
                            <span>Optimierte Route</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Route Modal */}
        {showRoute && route && (
          <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
            <div className="bg-white rounded-lg max-w-6xl max-h-[90vh] w-full overflow-hidden">
              <div className="p-6 border-b border-gray-200 flex justify-between items-center">
                <h2 className="text-2xl font-semibold text-gray-800">Optimized Route</h2>
                <button
                  onClick={() => setShowRoute(false)}
                  className="text-gray-500 hover:text-gray-700 text-2xl"
                >
                  ×
                </button>
              </div>
              
              <div className="p-6 overflow-y-auto max-h-[calc(90vh-200px)]">
                <div className="mb-6">
                  <div className="grid grid-cols-2 gap-4 mb-4">
                    <div>
                      <span className="text-gray-600">Total Distance:</span>
                      <span className="font-semibold ml-2">{formatDistance(route.total_distance)}</span>
                    </div>
                    <div>
                      <span className="text-gray-600">Total Stops:</span>
                      <span className="font-semibold ml-2">{route.optimized_addresses.length}</span>
                    </div>
                  </div>
                  
                  <button
                    onClick={() => downloadExcel(route.job_id)}
                    className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors"
                  >
                    Export Route (Excel)
                  </button>
                </div>
                
                <div className="space-y-3">
                  {route.optimized_addresses.map((address, index) => (
                    <div key={address.id} className="border border-gray-200 rounded-lg p-4">
                      <div className="flex items-start justify-between">
                        <div className="flex-1">
                          <div className="flex items-center mb-2">
                            <span className="w-8 h-8 bg-blue-600 text-white rounded-full flex items-center justify-center text-sm font-semibold mr-3">
                              {index + 1}
                            </span>
                            <h4 className="font-semibold text-gray-800">{address.original_address}</h4>
                          </div>
                          
                          {address.formatted_address && (
                            <p className="text-sm text-gray-600 ml-11">{address.formatted_address}</p>
                          )}
                          
                          {address.latitude && address.longitude && (
                            <p className="text-xs text-gray-500 ml-11">
                              Coordinates: {address.latitude.toFixed(6)}, {address.longitude.toFixed(6)}
                            </p>
                          )}
                        </div>
                        
                        <div className="flex items-center space-x-2">
                          <span className={`px-2 py-1 rounded text-xs font-medium ${
                            address.geocoded
                              ? 'bg-green-100 text-green-700'
                              : 'bg-red-100 text-red-700'
                          }`}>
                            {address.geocoded ? 'Geocoded' : 'Failed'}
                          </span>
                        </div>
                      </div>
                      
                      {address.geocoding_error && (
                        <div className="mt-2 ml-11 p-2 bg-red-50 border border-red-200 rounded text-xs text-red-700">
                          {address.geocoding_error}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default App;