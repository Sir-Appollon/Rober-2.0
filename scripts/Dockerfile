FROM ubuntu:22.04

RUN apt-get update && \
    apt-get install -y python3 python3-pip python3-libtorrent && \
    pip3 install --no-cache-dir --upgrade pip && \
    mkdir /seedcheck

WORKDIR /seedcheck

COPY vpn_peer_seed_check.py .

CMD ["python3", "vpn_peer_seed_check.py"]
