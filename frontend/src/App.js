import React, { useState, useEffect, useCallback } from 'react';
import { MapContainer, TileLayer, Marker, Popup, Polyline } from 'react-leaflet';
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

// Custom Icons für nummerierte Marker
const createNumberedIcon = (number, isStart = false, isEnd = false) => {
  const color = isStart ? '#22c55e' : isEnd ? '#ef4444' : '#3b82f6';
  const textColor = '#ffffff';
  
  return L.divIcon({
    html: `<div style="
      background-color: ${color}; 
      color: ${textColor}; 
      width: 30px; 
      height: 30px; 
      border-radius: 50%; 
      display: flex; 
      align-items: center; 
      justify-content: center; 
      font-weight: bold; 
      font-size: 12px;
      border: 2px solid white;
      box-shadow: 0 2px 4px rgba(0,0,0,0.3);
    ">${number}</div>`,
    className: 'custom-div-icon',
    iconSize: [30, 30],
    iconAnchor: [15, 15]
  });
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
      setJobs(data.jobs);
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
    } catch (error) {
      console.error('Error fetching route:', error);
      alert('Error fetching route data');
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
    
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const file = e.dataTransfer.files[0];
      setSelectedFile(file);
      // Automatische Vorschau
      previewFile(file);
    }
  }, []);

  const previewFile = async (file) => {
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await fetch(`${BACKEND_URL}/api/preview`, {
        method: 'POST',
        body: formData,
      });

      if (response.ok) {
        const preview = await response.json();
        setFilePreview(preview);
        setShowPreview(true);
      } else {
        const error = await response.json();
        alert(`Fehler bei der Datei-Vorschau: ${error.detail}`);
      }
    } catch (error) {
      console.error('Error previewing file:', error);
      alert('Fehler bei der Datei-Vorschau');
    }
  };

  const handleFileSelect = (e) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      
      // Reset alle states vor neuer Preview
      setUploadStatus('idle');
      setUploadProgress(0);
      setShowPreview(false);
      setFilePreview(null);
      
      setSelectedFile(file);
      // Automatische Vorschau
      previewFile(file);
    }
  };

  // Sofortiger Upload-Handler
  const handleInstantUpload = () => {
    if (!selectedFile) return;
    
    // SOFORT UI-State setzen - keine Verzögerung
    setUploadStatus('uploading');
    setShowPreview(false);
    setFilePreview(null);
    setUploadProgress(0);
    
    // Upload-Prozess starten
    performUpload();
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
      const response = await fetch(`${BACKEND_URL}/api/route/${jobId}/export`);
      
      if (response.ok) {
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        
        // Get filename from response headers or create default
        const contentDisposition = response.headers.get('Content-Disposition');
        let filename = `optimized_route_${jobId}.xlsx`;
        
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
          <h2 className="text-2xl font-semibold text-gray-800 mb-6">Adressliste hochladen</h2>
          
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
              className={`px-8 py-3 rounded-lg font-semibold transition-colors ${
                !selectedFile || uploadStatus !== 'idle'
                  ? 'bg-gray-300 text-gray-500 cursor-not-allowed'
                  : 'bg-green-600 text-white hover:bg-green-700'
              }`}
            >
              {uploadStatus === 'uploading' ? 'Hochladen...' : 'Hochladen & Verarbeiten'}
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
                onClick={() => {
                  // Komplett zurücksetzen für neue Datei-Auswahl
                  setSelectedFile(null);
                  setShowPreview(false);
                  setFilePreview(null);
                  setUploadStatus('idle');
                  setUploadProgress(0);
                  // Input field zurücksetzen
                  const fileInput = document.getElementById('file-input');
                  if (fileInput) fileInput.value = '';
                }}
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
                      <h3 className="text-lg font-semibold text-gray-800">{job.filename}</h3>
                      <p className="text-sm text-gray-500">
                        Hochgeladen: {new Date(job.created_at).toLocaleDateString('de-DE')}
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
                        onClick={() => fetchRoute(job.id)}
                        className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
                      >
                        Route anzeigen
                      </button>
                      <button
                        onClick={() => {
                          fetchRoute(job.id);
                          setShowMap(true);
                        }}
                        className="px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition-colors"
                      >
                        🗺️ Karte
                      </button>
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

        {/* Route Map Modal */}
        {showMap && route && (
          <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
            <div className="bg-white rounded-lg max-w-7xl max-h-[90vh] w-full overflow-hidden">
              <div className="p-6 border-b border-gray-200 flex justify-between items-center">
                <h2 className="text-2xl font-semibold text-gray-800">🗺️ Optimierte Route - Kartenansicht</h2>
                <button
                  onClick={() => setShowMap(false)}
                  className="text-gray-500 hover:text-gray-700 text-2xl"
                >
                  ×
                </button>
              </div>
              
              <div className="p-6">
                <div className="grid grid-cols-1 lg:grid-cols-4 gap-6 h-[70vh]">
                  {/* Map Container */}
                  <div className="lg:col-span-3 h-full">
                    {route.optimized_addresses && route.optimized_addresses.length > 0 && (
                      <MapContainer
                        center={[
                          route.optimized_addresses[0].latitude || 53.3498, 
                          route.optimized_addresses[0].longitude || 8.8071
                        ]}
                        zoom={13}
                        style={{ height: '100%', width: '100%' }}
                        className="rounded-lg"
                      >
                        <TileLayer
                          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                        />
                        
                        {/* Markers für alle Adressen */}
                        {route.optimized_addresses.map((address, index) => {
                          if (!address.latitude || !address.longitude) return null;
                          
                          const isStart = index === 0;
                          const isEnd = index === route.optimized_addresses.length - 1;
                          
                          return (
                            <Marker
                              key={address.id}
                              position={[address.latitude, address.longitude]}
                              icon={createNumberedIcon(index + 1, isStart, isEnd)}
                            >
                              <Popup>
                                <div className="text-center">
                                  <div className="font-bold text-lg mb-2">
                                    {isStart ? '🟢 Start' : isEnd ? '🔴 Ziel' : `📍 Stopp ${index + 1}`}
                                  </div>
                                  <div className="text-sm">
                                    <strong>{address.original_address}</strong>
                                  </div>
                                  {address.formatted_address && (
                                    <div className="text-xs text-gray-600 mt-1">
                                      {address.formatted_address}
                                    </div>
                                  )}
                                  <div className="text-xs text-gray-500 mt-1">
                                    Lat: {address.latitude.toFixed(6)}<br/>
                                    Lng: {address.longitude.toFixed(6)}
                                  </div>
                                </div>
                              </Popup>
                            </Marker>
                          );
                        })}
                        
                        {/* Route-Linie */}
                        {route.optimized_addresses.length > 1 && (
                          <Polyline
                            positions={route.optimized_addresses
                              .filter(addr => addr.latitude && addr.longitude)
                              .map(addr => [addr.latitude, addr.longitude])}
                            color="#3b82f6"
                            weight={4}
                            opacity={0.8}
                          />
                        )}
                      </MapContainer>
                    )}
                  </div>
                  
                  {/* Route Info Sidebar */}
                  <div className="lg:col-span-1 overflow-y-auto custom-scrollbar">
                    <div className="space-y-4">
                      <div className="bg-blue-50 rounded-lg p-4">
                        <h3 className="font-semibold text-blue-900 mb-2">📊 Route-Statistiken</h3>
                        <div className="space-y-2 text-sm">
                          <div>
                            <span className="text-blue-700">Gesamtdistanz:</span>
                            <span className="font-semibold ml-2">{formatDistance(route.total_distance)}</span>
                          </div>
                          <div>
                            <span className="text-blue-700">Anzahl Stopps:</span>
                            <span className="font-semibold ml-2">{route.optimized_addresses.length}</span>
                          </div>
                          <div>
                            <span className="text-blue-700">Algorithmus:</span>
                            <span className="font-semibold ml-2">2-opt optimiert</span>
                          </div>
                        </div>
                      </div>
                      
                      <div>
                        <h3 className="font-semibold text-gray-800 mb-3">📍 Route-Reihenfolge</h3>
                        <div className="space-y-2">
                          {route.optimized_addresses.map((address, index) => {
                            const isStart = index === 0;
                            const isEnd = index === route.optimized_addresses.length - 1;
                            
                            return (
                              <div
                                key={address.id}
                                className={`p-3 rounded-lg border-l-4 text-sm ${
                                  isStart ? 'bg-green-50 border-green-500' :
                                  isEnd ? 'bg-red-50 border-red-500' :
                                  'bg-gray-50 border-blue-500'
                                }`}
                              >
                                <div className="flex items-center">
                                  <span className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold mr-2 ${
                                    isStart ? 'bg-green-500 text-white' :
                                    isEnd ? 'bg-red-500 text-white' :
                                    'bg-blue-500 text-white'
                                  }`}>
                                    {index + 1}
                                  </span>
                                  <div className="flex-1 min-w-0">
                                    <div className="font-medium truncate">
                                      {address.original_address}
                                    </div>
                                    {!address.geocoded && (
                                      <div className="text-xs text-red-600">
                                        ⚠️ Nicht geocodiert
                                      </div>
                                    )}
                                  </div>
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
                
                <div className="mt-6 flex justify-between items-center">
                  <div className="flex space-x-4 text-sm text-gray-600">
                    <div className="flex items-center">
                      <div className="w-3 h-3 bg-green-500 rounded-full mr-2"></div>
                      Start
                    </div>
                    <div className="flex items-center">
                      <div className="w-3 h-3 bg-blue-500 rounded-full mr-2"></div>
                      Zwischenstopps
                    </div>
                    <div className="flex items-center">
                      <div className="w-3 h-3 bg-red-500 rounded-full mr-2"></div>
                      Ziel
                    </div>
                    <div className="flex items-center">
                      <div className="w-8 h-1 bg-blue-500 mr-2"></div>
                      Optimierte Route
                    </div>
                  </div>
                  
                  <button
                    onClick={() => downloadExcel(route.job_id)}
                    className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors"
                  >
                    📊 Excel exportieren
                  </button>
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