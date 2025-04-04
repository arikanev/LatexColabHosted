#!/usr/bin/env python3

import sys
import os
import threading
import json
from PyQt5.QtWidgets import QApplication, QMainWindow, QSizePolicy
from PyQt5.QtCore import QUrl, Qt, QSize
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineProfile, QWebEnginePage
from PyQt5.QtGui import QIcon
import base64

# Import your existing WebLoggerServer class
from LoggerServer import WebLoggerServer

class LoggerApp(QMainWindow):
    def __init__(self, port=8000):
        super().__init__()
        
        # Start the WebLoggerServer but don't open a browser
        self.server = WebLoggerServer(port=port)
        self.server.start(open_browser=False)

        def gif_to_base64_data_url(gif_path):
            """Convert a GIF file to a Base64 data URL."""
            with open(gif_path, "rb") as gif_file:
                encoded_string = base64.b64encode(gif_file.read()).decode('utf-8')
                return f"data:image/gif;base64,{encoded_string}"
        
    
        # Add background GIFs
        self.server.add_gif_background(
            gif_url=gif_to_base64_data_url("assets/LC.png"),
            level=0,
            transparency=0.8
        )
        
        self.server.add_gif_background(
            gif_url=gif_to_base64_data_url("assets/wavegrower.gif"),
            level=1,
            transparency=0.9
        )
        
        # Set up the main window
        self.setWindowTitle("LatexColab")
        self.setMinimumSize(800, 600)
        self.resize(800, 600)
        
        # Create a web view widget to display the server content
        self.web_view = QWebEngineView()
        self.web_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        # Configure web engine settings for better performance
        profile = QWebEngineProfile.defaultProfile()
        profile.setPersistentCookiesPolicy(QWebEngineProfile.NoPersistentCookies)
        
        # Create a custom page with adjusted settings
        page = QWebEnginePage(profile, self.web_view)
        self.web_view.setPage(page)
        
        # Load the local server URL
        self.web_view.load(QUrl(f"http://127.0.0.1:{port}"))
        
        # Set as central widget
        self.setCentralWidget(self.web_view)
        
        # Connect close event to ensure server shuts down
        self.closeEvent = self.on_close_event
    
    def on_close_event(self, event):
        """Handle window close event to properly shut down the server."""
        # Stop the server before closing
        if hasattr(self, 'server') and self.server.running:
            self.server.stop()
        event.accept()

    # Helper methods to expose server functionality
    def add_log(self, text, level=0, sender_id='system'):
        """Add a log entry."""
        self.server.add_log(text, level, sender_id)
    
    def add_box(self, text, title="Information", level=0, sender_id='system'):
        """Add a box entry."""
        self.server.add_box(text, title, level, sender_id)
    
    def add_gif_background(self, gif_url, level=0, transparency=0.3, sender_id='system'):
        """Add a GIF background."""
        self.server.add_gif_background(gif_url, level, transparency, sender_id)

def main():
    app = QApplication(sys.argv)
    
    # Set application icon (optional)
    # app.setWindowIcon(QIcon("path/to/icon.png"))
    
    # Create and show the main logger application
    logger_window = LoggerApp()
    logger_window.show()
    
    # Start the Qt application event loop
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()