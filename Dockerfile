# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Install git
RUN apt-get update && apt-get install -y --no-install-recommends git \\
    # Clean up apt cache to reduce image size
    && rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container first
# Since the build context is LatexColab/, the path is relative to it
COPY requirements.txt /app/requirements.txt

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire application code (everything in the build context) 
# into the container's working directory
COPY . /app/

# Make port 8000 available to the world outside this container
# Render will map its public port to this one
EXPOSE 8000

# Define the command to run your app using uvicorn
# Ensure it listens on 0.0.0.0 to be accessible outside the container
# Do NOT use --reload in production
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"] 