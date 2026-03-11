# ------------------------------------------------------------------------------
# Dockerfile for GPX Trail Waypoint Generator
#
# Base Image:       python:3.13.3-bookworm
# Script:           gpx_trail_wpt.py
# Description:      Analyzes GPX track files and adds waypoint markers such as
#                   Trail Head, Trail End, Highest/Lowest points, Halfway marker,
#                   and step-size-based distance markers (e.g., every 1km).
# Author:           nahumestrada001@gmail.com
# Version:          1.0
# ------------------------------------------------------------------------------

# === BASE IMAGE ===
# Use the official Python 3.13.3 image based on Debian Bookworm.
FROM python:3.13.3-bookworm

# === METADATA ===
LABEL maintainer="nahumestrada001@gmail.com"
LABEL version="1.0"
LABEL description="CLI tool to generate GPX trail waypoints with elevation and distance metadata"

# === SECURITY: CREATE NON-ROOT USER ===
# For better container security, create and use a non-root user.
RUN useradd -m wheisenberg
USER wheisenberg

# === WORKING DIRECTORY ===
# Set working directory inside the container for code and data.
WORKDIR /app

# === COPY AND INSTALL PYTHON DEPENDENCIES ===
# Copy the requirements file (must be in same folder as Dockerfile).
# Use --chown to ensure non-root ownership of the file.
COPY --chown=wheisenberg:wheisenberg requirements.txt .

# Install dependencies efficiently using pip.
# --no-cache-dir prevents caching to reduce image size.
RUN pip install --no-cache-dir -r requirements.txt

# === COPY APPLICATION SCRIPT ===
# Copy the main script into the working directory.
COPY --chown=wheisenberg:wheisenberg gpx_trail_wpt.py /app/gpx_trail_wpt.py

# === ENTRYPOINT ===
# Set the default executable for the container.
# The script supports command-line args (GPX file, prefix, step size).
ENTRYPOINT ["python", "/app/gpx_trail_wpt.py"]

# === CMD (Optional) ===
# If no args are passed to docker run, show help.
CMD ["--help"]
