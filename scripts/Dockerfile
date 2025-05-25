FROM python:3.10-slim

RUN apt-get update && \
    apt-get install -y python3-pip python3-dev libtorrent-rasterbar-dev python3-libtorrent && \
    pip install --no-cache-dir --upgrade pip && \
    mkdir /seedcheck

WORKDIR /seedcheck

COPY vpn_peer_seed_check.py .

CMD ["python3", "vpn_peer_seed_check.py"]
