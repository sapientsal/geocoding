import React, { useState, useEffect, useCallback } from 'react';
import './App.css';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || 'http://localhost:8001';

function App() {
  const [jobs, setJobs] = useState([]);
  const [selectedFile, setSelectedFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const [currentJobId, setCurrentJobId] = useState(null);
  const [jobStatus, setJobStatus] = useState(null);
  const [route, setRoute] = useState(null);
  const [showRoute, setShowRoute] = useState(false);

  // Fetch jobs on component mount
  useEffect(() => {
    fetchJobs();
  }, []);

  // Poll job status when there's a current job
  useEffect(() => {
    if (currentJobId) {
      const interval = setInterval(() => {
        fetchJobStatus(currentJobId);
      }, 2000);

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

      if (data.status === 'completed') {
        setCurrentJobId(null);
        fetchJobs();
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
      setSelectedFile(e.dataTransfer.files[0]);
    }
  }, []);

  const handleFileSelect = (e) => {
    if (e.target.files && e.target.files[0]) {
      setSelectedFile(e.target.files[0]);
    }
  };

  const handleUpload = async () => {
    if (!selectedFile) return;

    setUploading(true);
    const formData = new FormData();
    formData.append('file', selectedFile);

    try {
      const response = await fetch(`${BACKEND_URL}/api/upload`, {
        method: 'POST',
        body: formData,
      });

      const data = await response.json();
      
      if (response.ok) {
        setCurrentJobId(data.job_id);
        setSelectedFile(null);
        fetchJobs();
      } else {
        alert(`Upload failed: ${data.detail}`);
      }
    } catch (error) {
      console.error('Error uploading file:', error);
      alert('Error uploading file');
    } finally {
      setUploading(false);
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

  const exportRouteExcel = async () => {
    if (!route) return;

    try {
      const response = await fetch(`${BACKEND_URL}/api/route/${route.job_id}/export`);
      
      if (response.ok) {
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        
        // Get filename from response headers or create default
        const contentDisposition = response.headers.get('Content-Disposition');
        let filename = `optimized_route_${route.job_id}.xlsx`;
        
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
        alert('Fehler beim Export der Excel-Datei');
      }
    } catch (error) {
      console.error('Error exporting Excel:', error);
      alert('Fehler beim Export der Excel-Datei');
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
              onClick={handleUpload}
              disabled={!selectedFile || uploading}
              className={`px-8 py-3 rounded-lg font-semibold transition-colors ${
                !selectedFile || uploading
                  ? 'bg-gray-300 text-gray-500 cursor-not-allowed'
                  : 'bg-green-600 text-white hover:bg-green-700'
              }`}
            >
              {uploading ? 'Hochladen...' : 'Hochladen & Verarbeiten'}
            </button>
          </div>
        </div>

        {/* Current Job Status */}
        {jobStatus && (
          <div className="bg-white rounded-lg shadow-lg p-8 mb-8">
            <h2 className="text-2xl font-semibold text-gray-800 mb-6">Processing Status</h2>
            
            <div className="space-y-4">
              <div className="flex justify-between items-center">
                <span className="text-gray-700">File: {jobStatus.filename}</span>
                <span className={`px-3 py-1 rounded-full text-sm font-medium ${getStatusColor(jobStatus.status)}`}>
                  {jobStatus.status.charAt(0).toUpperCase() + jobStatus.status.slice(1)}
                </span>
              </div>
              
              <div className="w-full bg-gray-200 rounded-full h-4">
                <div
                  className="bg-blue-600 h-4 rounded-full transition-all duration-300"
                  style={{ width: `${getProgressPercentage(jobStatus)}%` }}
                ></div>
              </div>
              
              <div className="grid grid-cols-3 gap-4 text-sm">
                <div>
                  <span className="text-gray-600">Total Addresses:</span>
                  <span className="font-semibold ml-2">{jobStatus.total_addresses}</span>
                </div>
                <div>
                  <span className="text-gray-600">Processed:</span>
                  <span className="font-semibold ml-2">{jobStatus.processed_addresses}</span>
                </div>
                <div>
                  <span className="text-gray-600">Geocoded:</span>
                  <span className="font-semibold ml-2">{jobStatus.geocoded_addresses}</span>
                </div>
              </div>
              
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
          <h2 className="text-2xl font-semibold text-gray-800 mb-6">Upload History</h2>
          
          {jobs.length === 0 ? (
            <p className="text-gray-500 text-center py-8">No uploads yet. Upload your first address list above!</p>
          ) : (
            <div className="space-y-4">
              {jobs.map((job) => (
                <div key={job.id} className="border border-gray-200 rounded-lg p-6 hover:shadow-md transition-shadow">
                  <div className="flex justify-between items-start mb-4">
                    <div>
                      <h3 className="text-lg font-semibold text-gray-800">{job.filename}</h3>
                      <p className="text-sm text-gray-500">
                        Uploaded: {new Date(job.created_at).toLocaleDateString()}
                      </p>
                    </div>
                    <div className="flex items-center space-x-3">
                      <span className={`px-3 py-1 rounded-full text-sm font-medium ${getStatusColor(job.status)}`}>
                        {job.status.charAt(0).toUpperCase() + job.status.slice(1)}
                      </span>
                      <button
                        onClick={() => handleDeleteJob(job.id)}
                        className="text-red-600 hover:text-red-800 transition-colors"
                      >
                        🗑️
                      </button>
                    </div>
                  </div>
                  
                  <div className="grid grid-cols-3 gap-4 text-sm mb-4">
                    <div>
                      <span className="text-gray-600">Total:</span>
                      <span className="font-semibold ml-2">{job.total_addresses}</span>
                    </div>
                    <div>
                      <span className="text-gray-600">Processed:</span>
                      <span className="font-semibold ml-2">{job.processed_addresses}</span>
                    </div>
                    <div>
                      <span className="text-gray-600">Geocoded:</span>
                      <span className="font-semibold ml-2">{job.geocoded_addresses}</span>
                    </div>
                  </div>
                  
                  {job.status === 'completed' && (
                    <div className="flex space-x-3">
                      <button
                        onClick={() => fetchRoute(job.id)}
                        className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
                      >
                        View Route
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
                    onClick={exportRouteExcel}
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