# Build context is the REPO ROOT (see docker-compose.yml).
FROM python:3.12-slim

WORKDIR /app

COPY services/sales_service/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY common ./common
COPY services/sales_service/app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
