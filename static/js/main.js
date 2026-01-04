// File upload progress and storage updates
document.addEventListener('DOMContentLoaded', function() {
    const fileInput = document.getElementById('file');
    const fileInfo = document.getElementById('fileInfo');
    const fileSizeDisplay = document.getElementById('fileSize');
    const remainingStorageDisplay = document.getElementById('remainingStorage');
    const uploadForm = document.querySelector('.upload-form');
    const uploadProgressContainer = document.getElementById('uploadProgress');
    const uploadProgressBar = document.getElementById('uploadProgressBar');
    const uploadProgressText = document.getElementById('uploadProgressText');
    const uploadSuccess = document.getElementById('uploadSuccess');
    const storageBar = document.getElementById('storageBar') || document.querySelector('.storage-bar');
    const usedStorageDisplay = document.getElementById('usedStorage');
    
    // Get initial storage values from data attributes or elements
    let initialUsedGB = 0;
    let initialRemainingGB = 0;
    let initialLimitGB = 0;
    
    if (storageBar) {
        initialUsedGB = parseFloat(storageBar.dataset.used || 0);
        initialLimitGB = parseFloat(storageBar.dataset.limit || 5.0);
    }
    
    if (remainingStorageDisplay) {
        initialRemainingGB = parseFloat(remainingStorageDisplay.dataset.remaining || 0);
    }
    
    // Fallback: Get limit from total storage display
    if (initialLimitGB === 0) {
        const totalStorageElements = document.querySelectorAll('.storage-stat-value');
        if (totalStorageElements.length >= 3) {
            initialLimitGB = parseFloat(totalStorageElements[2].textContent) || 5.0;
            initialUsedGB = parseFloat(totalStorageElements[0].textContent) || 0;
        }
    }
    
    function updateStorageBar(usedGB, limitGB) {
        if (!storageBar) return;
        
        const usagePercent = limitGB > 0 ? (usedGB / limitGB * 100) : 0;
        // Ensure minimum width for visibility even with tiny files
        const minWidth = 0.1; // Minimum 0.1% width for visibility
        const finalWidth = Math.max(usagePercent, minWidth);
        
        storageBar.style.width = finalWidth + '%';
        
        // Add a pulse animation to show the change
        storageBar.style.animation = 'none';
        setTimeout(() => {
            storageBar.style.animation = 'pulse 0.5s ease-in-out';
        }, 10);
    }
    
    function formatFileSize(bytes) {
        if (bytes < 1024) return bytes.toFixed(2) + ' Bytes';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(2) + ' KB';
        if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
        return (bytes / (1024 * 1024 * 1024)).toFixed(4) + ' GB';
    }
    
    if (fileInput) {
        fileInput.addEventListener('change', function(e) {
            const file = e.target.files[0];
            if (file) {
                const fileSizeBytes = file.size;
                const fileSizeMB = (fileSizeBytes / (1024 * 1024)).toFixed(2);
                const fileSizeGB = fileSizeBytes / (1024 * 1024 * 1024);
                const fileSizeKB = (fileSizeBytes / 1024).toFixed(2);
                
                // Show file size in appropriate unit
                let sizeDisplay = '';
                if (fileSizeBytes < 1024) {
                    sizeDisplay = fileSizeBytes + ' Bytes';
                } else if (fileSizeBytes < 1024 * 1024) {
                    sizeDisplay = fileSizeKB + ' KB';
                } else if (fileSizeBytes < 1024 * 1024 * 1024) {
                    sizeDisplay = fileSizeMB + ' MB';
                } else {
                    sizeDisplay = fileSizeGB.toFixed(4) + ' GB';
                }
                
                // Show file info
                if (fileInfo) {
                    fileInfo.classList.add('active');
                    if (fileSizeDisplay) {
                        fileSizeDisplay.textContent = sizeDisplay + ' (' + fileSizeGB.toFixed(6) + ' GB)';
                    }
                }
                
                // Calculate new storage values
                const newUsedGB = initialUsedGB + fileSizeGB;
                const newRemainingGB = initialRemainingGB - fileSizeGB;
                
                // Update storage bar immediately - even for tiny files
                updateStorageBar(newUsedGB, initialLimitGB);
                
                // Check if file fits in remaining storage
                if (remainingStorageDisplay) {
                    const remainingAfterUpload = document.getElementById('remainingAfterUpload');
                    
                    if (fileSizeGB > initialRemainingGB) {
                        fileInfo.classList.add('storage-warning');
                        if (fileSizeDisplay) {
                            fileSizeDisplay.innerHTML = sizeDisplay + ' <span style="color: #ef4444;">⚠️ Exceeds available storage</span>';
                        }
                        if (remainingAfterUpload) {
                            remainingAfterUpload.innerHTML = '<span style="color: #ef4444;">⚠️ Insufficient storage</span>';
                        }
                        // Revert storage bar
                        updateStorageBar(initialUsedGB, initialLimitGB);
                    } else {
                        fileInfo.classList.remove('storage-warning');
                        if (remainingAfterUpload) {
                            remainingAfterUpload.textContent = newRemainingGB.toFixed(6) + ' GB';
                        }
                        
                        // Update remaining storage display
                        if (remainingStorageDisplay) {
                            remainingStorageDisplay.textContent = newRemainingGB.toFixed(6);
                            remainingStorageDisplay.dataset.remaining = newRemainingGB;
                        }
                        
                        // Update used storage display
                        if (usedStorageDisplay) {
                            usedStorageDisplay.textContent = newUsedGB.toFixed(6);
                        }
                        
                        // Update storage bar data attributes
                        if (storageBar) {
                            storageBar.dataset.used = newUsedGB;
                        }
                    }
                }
            } else {
                // Reset when no file selected
                if (fileInfo) {
                    fileInfo.classList.remove('active');
                }
                updateStorageBar(initialUsedGB, initialLimitGB);
                if (remainingStorageDisplay) {
                    remainingStorageDisplay.textContent = initialRemainingGB.toFixed(6);
                }
                if (usedStorageDisplay) {
                    usedStorageDisplay.textContent = initialUsedGB.toFixed(6);
                }
            }
        });
    }
    
    // Upload form submission with progress
    if (uploadForm) {
        uploadForm.addEventListener('submit', function(e) {
            const fileInput = document.getElementById('file');
            if (!fileInput || !fileInput.files[0]) {
                return;
            }
            
            const file = fileInput.files[0];
            const fileSize = file.size;
            
            // Show progress container
            if (uploadProgressContainer) {
                uploadProgressContainer.classList.add('active');
            }
            
            // Simulate progress (since we can't get real progress from form submission)
            let progress = 0;
            const interval = setInterval(function() {
                progress += Math.random() * 15;
                if (progress > 95) {
                    progress = 95;
                }
                
                if (uploadProgressBar) {
                    uploadProgressBar.style.width = progress + '%';
                }
                
                if (uploadProgressText) {
                    uploadProgressText.textContent = 'Uploading... ' + Math.round(progress) + '%';
                }
            }, 200);
            
            // Clear interval after form submits (progress will complete on page reload)
            setTimeout(function() {
                clearInterval(interval);
            }, 5000);
        });
    }
    
    // Update storage display after page load
    updateStorageDisplay();
});

function updateStorageDisplay() {
    // This function can be called after file operations to update storage
    // For now, it's handled server-side on page reload
}

// Format file size helper
function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}

