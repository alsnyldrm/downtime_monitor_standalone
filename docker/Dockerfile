FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libxml2-dev libxmlsec1-dev libxmlsec1-openssl pkg-config iputils-ping \
    traceroute whois dnsutils \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
