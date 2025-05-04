FROM python:3.10-slim

WORKDIR /app

COPY . .

RUN pip install deluge-client 

CMD ["python", "deluge_control.py"]
