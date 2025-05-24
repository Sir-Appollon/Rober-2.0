FROM python:3.10-slim

RUN apt-get update && \
    apt-get install -y docker.io curl && \
    apt-get clean

WORKDIR /app
COPY . .

RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "Health.py"]
