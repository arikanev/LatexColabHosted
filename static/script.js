document.addEventListener('DOMContentLoaded', () => {
    const gitUrlInput = document.getElementById('git-url');
    const gitTokenInput = document.getElementById('git-token');
    const filePathInput = document.getElementById('file-path');
    const fetchButton = document.getElementById('fetch-button');
    const editorSection = document.querySelector('.editor-section');
    const latexEditor = document.getElementById('latex-editor');
    const processButton = document.getElementById('process-button');
    const syncButton = document.getElementById('sync-button');
    const statusMessage = document.getElementById('status-message');

    let currentContent = '';

    function showStatus(message, type = 'loading', duration = null) {
        statusMessage.textContent = message;
        statusMessage.className = `status ${type}`;
        statusMessage.style.display = 'block';

        // Disable buttons during loading
        const isLoading = type === 'loading';
        fetchButton.disabled = isLoading;
        processButton.disabled = isLoading;
        syncButton.disabled = isLoading;
        latexEditor.disabled = isLoading;

        if (duration) {
            setTimeout(() => {
                hideStatus();
            }, duration);
        }
    }

    function hideStatus() {
        statusMessage.textContent = '';
        statusMessage.style.display = 'none';
        // Re-enable buttons (unless they were initially disabled)
        fetchButton.disabled = false;
        processButton.disabled = editorSection.style.display === 'none'; // Only enable if editor is visible
        syncButton.disabled = editorSection.style.display === 'none';
        latexEditor.disabled = false;
    }

    async function makeApiCall(endpoint, body) {
        try {
            const response = await fetch(endpoint, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                },
                body: JSON.stringify(body)
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ detail: 'Unknown server error' }));
                throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
            }

            return await response.json();
        } catch (error) {
            console.error(`Error calling ${endpoint}:`, error);
            showStatus(`Error: ${error.message}`, 'error', 5000);
            throw error; // Re-throw to stop further processing in the calling function
        }
    }

    fetchButton.addEventListener('click', async () => {
        const gitUrl = gitUrlInput.value.trim();
        const gitToken = gitTokenInput.value.trim();
        const filePath = filePathInput.value.trim();

        if (!gitUrl || !gitToken || !filePath) {
            showStatus('Please fill in all configuration fields.', 'error', 3000);
            return;
        }

        showStatus('Fetching document...');
        try {
            const data = await makeApiCall('/fetch', {
                git_url: gitUrl,
                git_token: gitToken,
                relative_file_path: filePath
            });

            currentContent = data.file_content;
            latexEditor.value = currentContent;
            editorSection.style.display = 'block';
            showStatus('Document fetched successfully.', 'success', 3000);
            // Enable process/sync buttons now that content is loaded
            processButton.disabled = false;
            syncButton.disabled = false;
        } catch (error) {
            // Error message is already shown by makeApiCall
            editorSection.style.display = 'none'; // Hide editor on error
        }
    });

    processButton.addEventListener('click', async () => {
        const contentToSend = latexEditor.value;
        if (!contentToSend) {
            showStatus('Editor is empty, nothing to process.', 'error', 3000);
            return;
        }

        // --- Added Client-Side Debug Logging ---
        console.log("Sending to /process (first 500 chars):", contentToSend.substring(0, 500));
        // --- End Debug Logging ---

        showStatus('Processing AI prompts...');
        try {
            const data = await makeApiCall('/process', {
                latex_content: contentToSend
            });

            if (data.processed) {
                latexEditor.value = data.processed_content;
                currentContent = data.processed_content;
                showStatus('AI prompt processed successfully.', 'success', 3000);
            } else {
                showStatus('No active prompts (status=start) found to process.', 'success', 3000); 
            }
        } catch (error) {
            // Error handled by makeApiCall
        }
    });

    syncButton.addEventListener('click', async () => {
        const gitUrl = gitUrlInput.value.trim();
        const gitToken = gitTokenInput.value.trim();
        const filePath = filePathInput.value.trim();
        const contentToSync = latexEditor.value;

        if (!gitUrl || !gitToken || !filePath) {
            showStatus('Configuration is missing.', 'error', 3000);
            return;
        }
        if (contentToSync === currentContent) {
             // Optimization: Check if content has actually changed, though this check is basic
             // A more robust check might involve comparing ASTs or using diff libraries
             // For now, let the user sync even if content *seems* unchanged, backend handles no-op commit
             //showStatus('No changes detected to sync.', 'success', 3000);
             //return;
        }

        showStatus('Syncing changes to Overleaf...');
        try {
            await makeApiCall('/sync', {
                git_url: gitUrl,
                git_token: gitToken,
                relative_file_path: filePath,
                file_content: contentToSync
            });
            currentContent = contentToSync; // Update baseline content after successful sync
            showStatus('Successfully synced to Overleaf.', 'success', 3000);
        } catch (error) {
            // Error handled by makeApiCall
        }
    });
}); 