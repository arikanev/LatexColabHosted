#!/usr/bin/env python3.11

import http.server
import socketserver
import json
import threading
import time
from urllib.parse import urlparse, parse_qs
import os
import webbrowser
import tempfile
import subprocess
import sys

class WebLoggerServer:
    """
    A server for tracking logging messages and other information.
    Provides a web interface with a dark theme and two panels:
    - Left panel (70%): For log messages (level 0)
    - Right panel (30%): For other information (level 1)
    """
    
    def __init__(self, port=8000):
        """Initialize the server with the given port."""
        self.port = port
        self.server = None
        self.logs = []  # Store logs
        self.info = []  # Store information
        self.server_thread = None
        self.running = False
        self.html_template = self._generate_html_template()
        
    def _generate_html_template(self):
        """Generate the HTML template for the web interface."""
        return """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Web Logger</title>
            <style>
                body {
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    background-color: #000000;
                    color: #00e0e0;
                    margin: 0;
                    padding: 0;
                    display: flex;
                    height: 100vh;
                }
                
                #log-container {
                    width: 70%;
                    height: 100%;
                    // border-right: 1px solid #200;
                    padding: 10px;
                    // box-sizing: border-box;
                    overflow: hidden;
                    display: flex;
                    flex-direction: column;
                    position: relative;
                }
                
                #info-container {
                    width: 30%;
                    height: 97%;
                    padding: 10px;
                   // border: 1px solid #005545;
                    box-sizing: border-box;
                    overflow: hidden;
                    display: flex;
                    flex-direction: column;
                    position: relative;
                }
                
                .bg-gif {
                    position: absolute;
                    top: 0;
                    left: 0;
                    width: 100%;
                    height: 100%;
                    object-fit: cover;
                    z-index: 0;
                    opacity: 0.4; /* Default transparency */
                }
                
                .title {
                    font-size: 18px;
                    font-weight: bold;
                    margin-bottom: 10px;
                    color: #B05545;
                    position: relative;
                    z-index: 1;
                }
                
                .content {
                    flex: 1;
                    overflow-y: auto;
                    // border: 1px solid #005545;
                    border-radius: 5px;
                    padding: 5px;
                    background-color: rgba(0, 0, 0, 0.1);
                    position: relative;
                    z-index: 1;
                }
                
                .log-entry {
                    margin-bottom: 8px;
                    padding: 5px;
                    color: #B0F0F0;
                    border-bottom: 1px solid rgba(0, 0, 0, 0.2);
                    word-wrap: break-word;
                    background-color: rgba(0, 0, 0, 0);
                    border-radius: 4px;
                    z-index: -1;
                }
                
                .box {
                    margin-bottom: 15px;
                    border: 1px solid rgba(102, 102, 102, 0.7);
                    border-radius: 5px;
                    overflow: hidden;
                    background-color: rgba(15, 15, 15, 0.2);
                }
                
                .box-title {
                    background-color: rgba(0, 0, 0, 0.4);
                    color: #005545;
                    padding: 5px 10px;
                    font-weight: bold;
                }
                
                .box-content {
                    padding: 8px;
                    max-height: 200px;
                    color: #B0F0E0;
                    overflow-y: auto;
                    background-color: rgba(3, 3, 3, 0.4);
                    white-space: pre-wrap;
                    word-wrap: break-word;
                }

                /* Auto-scrolling */
                .auto-scroll {
                    margin-top: 10px;
                    background-color: rgba(0, 0, 0, 0.7);
                    padding: 5px;
                    border-radius: 4px;
                    display: inline-block;
                }
                
                #auto-scroll-checkbox {
                    margin-right: 5px;
                }
            </style>
        </head>
        <body>
            <div id="log-container">
                <div class="title">Logs</div>
                <div id="logs" class="content"></div>
                <div class="auto-scroll">
                    <input type="checkbox" id="auto-scroll-checkbox" checked>
                    <label for="auto-scroll-checkbox">Auto-scroll</label>
                </div>
            </div>
            <div id="info-container">
                <div class="title">Information</div>
                <div id="info" class="content"></div>
            </div>
            
            <script>
                // Generate a random client ID to track updates
                const clientId = 'client_' + Math.random().toString(36).substring(2, 15);
                
                // Function to add log entry
                function addLog(text) {
                    const logContainer = document.getElementById('logs');
                    const logEntry = document.createElement('div');
                    logEntry.className = 'log-entry';
                    logEntry.textContent = text;
                    logContainer.appendChild(logEntry);
                    scrollIfNeeded(logContainer);
                }
                
                // Function to add a box
                function addBox(text, title, level) {
                    const container = level === 0 ? document.getElementById('logs') : document.getElementById('info');
                    
                    const box = document.createElement('div');
                    box.className = 'box';
                    
                    const boxTitle = document.createElement('div');
                    boxTitle.className = 'box-title';
                    boxTitle.textContent = title;
                    
                    const boxContent = document.createElement('div');
                    boxContent.className = 'box-content';
                    boxContent.textContent = text;
                    
                    box.appendChild(boxTitle);
                    box.appendChild(boxContent);
                    
                    container.appendChild(box);
                    scrollIfNeeded(container);
                }
                
                // Auto-scroll if checkbox is checked
                function scrollIfNeeded(container) {
                    if (document.getElementById('auto-scroll-checkbox').checked) {
                        container.scrollTop = container.scrollHeight;
                    }
                }
                
                // Function to set background GIF
                function setBackgroundGif(gifUrl, level, transparency) {
                    const container = level === 0 ? document.getElementById('log-container') : document.getElementById('info-container');
                    
                    // Remove any existing background GIF
                    const existingGifs = container.querySelectorAll('.bg-gif');
                    existingGifs.forEach(gif => gif.remove());
                    
                    // Create and add the new background GIF
                    const gifElement = document.createElement('img');
                    gifElement.className = 'bg-gif';
                    gifElement.src = gifUrl;
                    gifElement.style.opacity = transparency;
                    
                    // Insert at the beginning of the container
                    container.insertBefore(gifElement, container.firstChild);
                    
                    // Make sure GIF is behind content by setting z-index
                    // gifElement.style.zIndex = "0";
                    
                    // Find the content div and ensure its background is semi-transparent
                    const contentDiv = container.querySelector('.content');
                    if (contentDiv) {
                        contentDiv.style.backgroundColor = "rgba(0, 0, 0, 0.4)";
                    }
                }
                
                // Fetch updates every second
                setInterval(async function() {
                    try {
                        // Send client ID in header to track updates per client
                        const response = await fetch('/updates', {
                            headers: {
                                'X-Client-ID': clientId
                            }
                        });
                        const data = await response.json();
                        
                        if (data.updates && data.updates.length > 0) {
                            for (const update of data.updates) {
                                if (update.command === 'log') {
                                    addLog(update.args);
                                } else if (update.command === 'box') {
                                    addBox(update.args, update.title || 'Info', update.level);
                                } else if (update.command === 'gif') {
                                    setBackgroundGif(update.args, update.level, update.transparency);
                                }
                            }
                        }
                    } catch (error) {
                        console.error('Error fetching updates:', error);
                    }
                }, 1000);
            </script>
        </body>
        </html>
        """
    
    class RequestHandler(http.server.SimpleHTTPRequestHandler):
        """Handle HTTP requests to the server."""
        
        def __init__(self, *args, **kwargs):
            self.server_instance = kwargs.pop('server_instance')
            super().__init__(*args, **kwargs)
        
        def do_GET(self):
            """Handle GET requests."""
            path = urlparse(self.path).path
            
            if path == '/':
                # Serve the main HTML page
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(self.server_instance.html_template.encode())
            elif path == '/updates':
                # Get client identifier to track updates per client
                client_id = self.headers.get('X-Client-ID', self.client_address[0])
                
                # Ensure we have a tracking dictionary for clients
                if not hasattr(self.server_instance, 'client_indices'):
                    self.server_instance.client_indices = {}
                
                # Initialize this client's tracking indices if needed
                if client_id not in self.server_instance.client_indices:
                    self.server_instance.client_indices[client_id] = {
                        'log_index': 0,
                        'info_index': 0
                    }
                
                # Return new logs and info as JSON
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                
                updates = []
                
                # Get new logs since last request for this client
                client_data = self.server_instance.client_indices[client_id]
                log_index = client_data['log_index']
                if log_index < len(self.server_instance.logs):
                    for log in self.server_instance.logs[log_index:]:
                        updates.append(log)
                    client_data['log_index'] = len(self.server_instance.logs)
                
                # Get new info since last request for this client
                info_index = client_data['info_index']
                if info_index < len(self.server_instance.info):
                    for info in self.server_instance.info[info_index:]:
                        updates.append(info)
                    client_data['info_index'] = len(self.server_instance.info)
                
                response = {'updates': updates}
                self.wfile.write(json.dumps(response).encode())
            else:
                self.send_response(404)
                self.end_headers()
        
        def do_POST(self):
            """Handle POST requests."""
            path = urlparse(self.path).path
            
            if path == '/submit':
                # Read the request body
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length).decode('utf-8')
                
                try:
                    data = json.loads(post_data)
                    sender_id = data.get('id', 'unknown')
                    command = data.get('command')
                    level = data.get('level', 0)
                    args = data.get('args')
                    
                    if command == 'log':
                        log_entry = {
                            'id': sender_id,
                            'command': 'log',
                            'level': level,
                            'args': args
                        }
                        
                        if level == 0:
                            self.server_instance.logs.append(log_entry)
                        else:
                            self.server_instance.info.append(log_entry)
                    
                    elif command == 'box':
                        box_entry = {
                            'id': sender_id,
                            'command': 'box',
                            'level': level,
                            'args': args,
                            'title': data.get('title', 'Information')
                        }
                        
                        if level == 0:
                            self.server_instance.logs.append(box_entry)
                        else:
                            self.server_instance.info.append(box_entry)
                    
                    elif command == 'gif':
                        gif_entry = {
                            'id': sender_id,
                            'command': 'gif',
                            'level': level,
                            'args': args,  # URL or Base64 of the GIF
                            'transparency': data.get('transparency', 0.3)
                        }
                        
                        if level == 0:
                            self.server_instance.logs.append(gif_entry)
                        else:
                            self.server_instance.info.append(gif_entry)
                    
                    # Send a success response
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    response = {'status': 'success'}
                    self.wfile.write(json.dumps(response).encode())
                
                except json.JSONDecodeError:
                    # Send an error response
                    self.send_response(400)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    response = {'status': 'error', 'message': 'Invalid JSON'}
                    self.wfile.write(json.dumps(response).encode())
            
            elif path == '/shutdown':
                # Shutdown the server
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                response = {'status': 'success', 'message': 'Server shutting down'}
                self.wfile.write(json.dumps(response).encode())
                
                # Schedule server shutdown after response is sent
                threading.Thread(target=self.server_instance.stop).start()
            
            else:
                self.send_response(404)
                self.end_headers()

    @staticmethod
    def open_chrome_with_size(url, width=800, height=600):
        print("Opening Chromuim browser")
        subprocess.Popen([
            "chromium-browser",  # or "google-chrome", or full path to Chrome
            f"--window-size={width},{height}",
            url
        ])

    @staticmethod
    def open_browser_with_size(url, width=200, height=300, cleanup=True):
        """Open a browser window with specific dimensions"""
        
        # Create HTML content with JavaScript to resize the window
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Redirecting...</title>
            <script>
                // Resize current window
                window.resizeTo({width}, {height});
                // Navigate to the desired URL
                window.location.href = "{url}";
            </script>
        </head>
        <body>
            <p>Redirecting to {url}...</p>
        </body>
        </html>
        """
        
        # Use a file in the current directory instead of a temp file
        file_path = os.path.join(os.getcwd(), "browser_redirect.html")
        
        # Write the HTML to the file
        with open(file_path, 'w') as f:
            f.write(html_content)
        
        # Convert to file URL with proper format
        file_url = f"file://{os.path.abspath(file_path)}"
        
        # Open the file in the browser
        webbrowser.open(file_url, new=1)


    
    def start(self, open_browser=True):
        """Start the server."""
        if self.running:
            print("Server is already running")
            return

        # Save the original stdout/stderr
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        # Redirect to null device
        sys.stdout = open(os.devnull, 'w')
        sys.stderr = open(os.devnull, 'w')

        # Create server with custom request handler
        handler = lambda *args, **kwargs: self.RequestHandler(*args, server_instance=self, **kwargs)
        self.server = socketserver.TCPServer(('127.0.0.1', self.port), handler)
        self.running = True
        
        print(f"Server started at http://127.0.0.1:{self.port}")
        
        # Start the server in a separate thread
        self.server_thread = threading.Thread(target=self.server.serve_forever)
        self.server_thread.daemon = True
        self.server_thread.start()
        
        # Open browser if requested
        if open_browser:
            self.open_browser_with_size(f"http://127.0.0.1:{self.port}")
            #webbrowser.open(f"http://127.0.0.1:{self.port}", new=1)
    
    def stop(self):
        """Stop the server."""
        if not self.running:
            print("Server is not running")
            return
        
        print("Shutting down server...")
        self.server.shutdown()
        self.server.server_close()
        self.running = False
        sys.stdout = self.original_stdout
        sys.stderr = self.original_stderr
        print("Server stopped")
    
    def add_gif_background(self, gif_url, level=0, transparency=0.3, sender_id='system'):
        """Add an animated GIF background to a window level.
        
        Args:
            gif_url (str): URL or Base64 encoded GIF.
            level (int): Panel level (0 for logs, 1 for info).
            transparency (float): Transparency level from 0 (invisible) to 1 (fully opaque).
            sender_id (str): Identifier for the sender.
        """
        gif_entry = {
            'id': sender_id,
            'command': 'gif',
            'level': level,
            'args': gif_url,
            'transparency': transparency
        }
        
        if level == 0:
            self.logs.append(gif_entry)
        else:
            self.info.append(gif_entry)
    
    def add_log(self, text, level=0, sender_id='system'):
        """Add a log entry programmatically."""
        log_entry = {
            'id': sender_id,
            'command': 'log',
            'level': level,
            'args': text
        }
        
        if level == 0:
            self.logs.append(log_entry)
        else:
            self.info.append(log_entry)
    
    def add_box(self, text, title="Information", level=0, sender_id='system'):
        """Add a box entry programmatically."""
        box_entry = {
            'id': sender_id,
            'command': 'box',
            'level': level,
            'args': text,
            'title': title
        }
        
        if level == 0:
            self.logs.append(box_entry)
        else:
            self.info.append(box_entry)

# Example usage
if __name__ == "__main__":
    import base64

    def gif_to_base64_data_url(gif_path):
        """Convert a GIF file to a Base64 data URL."""
        with open(gif_path, "rb") as gif_file:
            encoded_string = base64.b64encode(gif_file.read()).decode('utf-8')
            return f"data:image/gif;base64,{encoded_string}"
        
    # Create a server instance
    server = WebLoggerServer(port=8000)

    #server.open_chrome_with_size("http://example.com")
    #input('sdsd')
    
    # Start the server
    server.start()
    
    # Add background GIFs
    server.add_gif_background(
        gif_url=gif_to_base64_data_url("assets/LC1.png"),
        level=0,
        transparency=0.8
    )
    
    server.add_gif_background(
        gif_url=gif_to_base64_data_url("assets/LC2.png"),
        level=1,
        transparency=0.9
    )
    
    while server.running:
        pass



    # # Add some test messages
    # server.add_log("Server started successfully", level=0)
    # server.add_log("Initializing components...", level=0)
    # server.add_box("System Information\nPython version: 3.9\nOS: Windows 10", 
    #               title="System Info", level=1)
    
    # # Keep the server running for 60 seconds
    # try:
    #     for i in range(10):
    #         time.sleep(1)
    #         server.add_log(f"Periodic update {i+1}", level=0)
    #         if i % 3 == 0:
    #             server.add_box(f"CPU: {20+i}%\nMemory: {50+i}%\nDisk: {30+i}%", 
    #                           title="Resource Usage", level=1)
    # except KeyboardInterrupt:
    #     pass
    # finally:
    #     # Stop the server after the test
    #     server.stop()