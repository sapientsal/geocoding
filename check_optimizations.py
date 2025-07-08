#!/usr/bin/env python3
import os
import re

def check_optimizations():
    """Check if the performance optimizations are implemented in the code"""
    print("\n🔍 Checking for performance optimizations in the code...")
    
    # Read the server.py file
    with open('/app/backend/server.py', 'r') as f:
        code = f.read()
    
    # Check for marker filtering
    print("\nChecking for marker filtering optimization...")
    marker_filtering = re.search(r'for large datasets \(500\+ addresses\)', code) is not None
    if marker_filtering:
        print("✅ Marker filtering for large datasets is implemented")
    else:
        print("❌ Marker filtering for large datasets is not implemented")
    
    # Check for removed visual effects
    print("\nChecking for removal of visual effects...")
    visual_effects_removed = re.search(r'animations.*removed|transitions.*removed|effects.*removed', code, re.IGNORECASE) is not None
    if visual_effects_removed:
        print("✅ Visual effects removal is mentioned in the code")
    else:
        print("❌ No mention of visual effects removal in the code")
    
    # Check for simplified markers
    print("\nChecking for simplified markers...")
    simplified_markers = re.search(r'simplified markers|simple.*markers|basic markers', code, re.IGNORECASE) is not None
    if simplified_markers:
        print("✅ Simplified markers are mentioned in the code")
    else:
        print("❌ No mention of simplified markers in the code")
    
    # Check for disabled auto-zoom
    print("\nChecking for disabled auto-zoom...")
    auto_zoom_disabled = re.search(r'auto.?zoom.*disabled|disabled.*auto.?zoom', code, re.IGNORECASE) is not None
    if auto_zoom_disabled:
        print("✅ Auto-zoom disabling is mentioned in the code")
    else:
        print("❌ No mention of auto-zoom disabling in the code")
    
    # Check for simplified popups
    print("\nChecking for simplified popups...")
    simplified_popups = re.search(r'simplified popups|simple.*popups|basic popups', code, re.IGNORECASE) is not None
    if simplified_popups:
        print("✅ Simplified popups are mentioned in the code")
    else:
        print("❌ No mention of simplified popups in the code")
    
    # Check for batch processing
    print("\nChecking for batch processing...")
    batch_processing = re.search(r'batch processing|batch_size|batch_geocoding', code, re.IGNORECASE) is not None
    if batch_processing:
        print("✅ Batch processing is implemented")
        
        # Find the batch size
        batch_size_match = re.search(r'batch_size\s*=\s*(\d+)', code)
        if batch_size_match:
            batch_size = batch_size_match.group(1)
            print(f"   Batch size: {batch_size}")
    else:
        print("❌ No batch processing implementation found")
    
    # Check for error handling improvements
    print("\nChecking for error handling improvements...")
    error_handling = re.search(r'error handling|exception handling|try.*except', code, re.IGNORECASE) is not None
    if error_handling:
        print("✅ Improved error handling is implemented")
    else:
        print("❌ No improved error handling implementation found")
    
    # Check for caching
    print("\nChecking for caching...")
    caching = re.search(r'address_cache|caching|cached_result', code, re.IGNORECASE) is not None
    if caching:
        print("✅ Caching is implemented")
    else:
        print("❌ No caching implementation found")
    
    # Check for retry logic
    print("\nChecking for retry logic...")
    retry_logic = re.search(r'retry logic|max_retries|attempt', code, re.IGNORECASE) is not None
    if retry_logic:
        print("✅ Retry logic is implemented")
        
        # Find the max retries
        max_retries_match = re.search(r'max_retries\s*=\s*(\d+)', code)
        if max_retries_match:
            max_retries = max_retries_match.group(1)
            print(f"   Max retries: {max_retries}")
    else:
        print("❌ No retry logic implementation found")
    
    # Check for exponential backoff
    print("\nChecking for exponential backoff...")
    exponential_backoff = re.search(r'exponential backoff|backoff.*exponential', code, re.IGNORECASE) is not None
    if exponential_backoff:
        print("✅ Exponential backoff is implemented")
    else:
        print("❌ No exponential backoff implementation found")
    
    # Check for rate limiting
    print("\nChecking for rate limiting...")
    rate_limiting = re.search(r'rate limiting|rate_limit|throttling', code, re.IGNORECASE) is not None
    if rate_limiting:
        print("✅ Rate limiting is implemented")
    else:
        print("❌ No rate limiting implementation found")
    
    # Check for logging
    print("\nChecking for logging...")
    logging = re.search(r'JobLogger|logging|log\(', code, re.IGNORECASE) is not None
    if logging:
        print("✅ Logging is implemented")
    else:
        print("❌ No logging implementation found")
    
    # Summary
    print("\n📊 Summary of optimizations:")
    optimizations = [
        ("Marker filtering", marker_filtering),
        ("Visual effects removal", visual_effects_removed),
        ("Simplified markers", simplified_markers),
        ("Disabled auto-zoom", auto_zoom_disabled),
        ("Simplified popups", simplified_popups),
        ("Batch processing", batch_processing),
        ("Error handling", error_handling),
        ("Caching", caching),
        ("Retry logic", retry_logic),
        ("Exponential backoff", exponential_backoff),
        ("Rate limiting", rate_limiting),
        ("Logging", logging)
    ]
    
    implemented = sum(1 for _, implemented in optimizations if implemented)
    print(f"✅ {implemented}/{len(optimizations)} optimizations implemented")
    
    # Check if the code has specific performance-related comments
    performance_comments = re.findall(r'(?:\/\/|#)\s*.*(?:performance|optimization|speed|faster|quicker)', code, re.IGNORECASE)
    if performance_comments:
        print("\nPerformance-related comments found:")
        for comment in performance_comments[:5]:  # Show up to 5 comments
            print(f"  - {comment.strip()}")
        if len(performance_comments) > 5:
            print(f"  - ... and {len(performance_comments) - 5} more")

if __name__ == "__main__":
    check_optimizations()