FROM python:3.10-slim

RUN apt-get update && \
    apt-get install -y curl && \
    apt-get clean

WORKDIR /peer
COPY vpn_peer_seed.py .
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

CMD ["python3", "vpn_peer_seed.py"]
