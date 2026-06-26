FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt requirements-api.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-api.txt
COPY api/ ./api/
COPY src/ ./src/
COPY data/ ./data/
ENV IE_HOST=0.0.0.0
ENV IE_PORT=8080
ENV IE_STAGE_DELAY_MS=300
EXPOSE 8080
CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080"]
