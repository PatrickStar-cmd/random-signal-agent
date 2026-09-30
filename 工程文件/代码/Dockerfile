FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements-repro.txt .
RUN pip install --no-cache-dir -r requirements-repro.txt
COPY . .

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=6 \
  CMD python -c "import json,urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=3); assert json.load(r)['status']=='ok'"
CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8000"]
