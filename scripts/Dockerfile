FROM python:3.10-slim

# Install system dependencies for libtorrent
RUN apt-get update && \
    apt-get install -y \
        curl \
        libtorrent-rasterbar-dev \
        python3-libtorrent \
        && apt-get clean

# Set working directory
WORKDIR /app

# Copy script and requirements
COPY . .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Default command to run the diagnostic
CMD ["python3", "sev1.py"]
