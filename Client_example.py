import requests
import json
import time
import random

def send_log(message, level=0, sender_id="client"):
    """Send a log message to the server."""
    data = {
        'id': sender_id,
        'command': 'log',
        'level': level,
        'args': message
    }
    
    try:
        response = requests.post('http://127.0.0.1:8000/submit', json=data)
        return response.status_code == 200
    except requests.exceptions.RequestException as e:
        print(f"Error sending log: {e}")
        return False

def send_box(content, title="Information", level=0, sender_id="client"):
    """Send a box to the server."""
    data = {
        'id': sender_id,
        'command': 'box',
        'level': level,
        'args': content,
        'title': title
    }
    
    try:
        response = requests.post('http://127.0.0.1:8000/submit', json=data)
        return response.status_code == 200
    except requests.exceptions.RequestException as e:
        print(f"Error sending box: {e}")
        return False

def shutdown_server():
    """Send a request to shutdown the server."""
    try:
        response = requests.post('http://127.0.0.1:8000/shutdown')
        return response.status_code == 200
    except requests.exceptions.RequestException as e:
        print(f"Error shutting down server: {e}")
        return False

if __name__ == "__main__":
    # Example usage
    print("Sending test messages to the web logger server...")
    
    # Send some log messages
    send_log("Client connected", level=0)
    send_log("Initializing client components", level=0)
    
    # Send some information to the info panel
    send_log("Client version: 1.0.2", level=1)
    send_box("Client ID: ABC123\nSession: XYZ789\nStarted: 2023-04-15 14:30", 
             title="Session Information", level=1)
    
    # Simulate some activity
    for i in range(10):
        time.sleep(1)
        
        # Log activity
        actions = ["Reading data", "Processing request", "Updating cache", 
                  "Sending response", "Validating input", "Analyzing results"]
        send_log(f"{random.choice(actions)} - Step {i+1}", level=0)
        
        # Every few steps, send more detailed info
        if i % 3 == 0:
            status = "Normal" if random.random() > 0.3 else "Warning"
            memory_usage = random.randint(40, 90)
            connections = random.randint(1, 10)
            
            metrics = f"Status: {status}\nMemory usage: {memory_usage}%\nActive connections: {connections}"
            send_box(metrics, title="Client Metrics", level=1)
    
    # Final log and cleanup
    send_log("Client operations completed", level=0)
    send_box("Operation Summary:\n- 10 steps completed\n- 0 errors\n- 4 metrics reports", 
             title="Summary", level=0)
    
    # Don't shutdown the server here, let the user do it manually
    print("Test complete. Server will remain running.")