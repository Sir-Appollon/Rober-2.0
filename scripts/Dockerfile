FROM ubuntu:22.04

RUN apt-get update && \
    apt-get install -y python3 mktorrent && \
    mkdir /seedcheck

WORKDIR /seedcheck

COPY create_dummy_torrent.py .

CMD ["python3", "create_dummy_torrent.py"]
