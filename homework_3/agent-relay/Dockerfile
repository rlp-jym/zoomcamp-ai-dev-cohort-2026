# ---- Stage 1: build the frontend with Node ----
FROM node:20-alpine AS frontend-build
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: Python image with the backend and frontend static files ----
FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir \
    "fastapi>=0.141.1" \
    "uvicorn[standard]>=0.52.4" \
    "sqlalchemy>=2.0.52" \
    "pydantic-settings>=2.15.0" \
    "psycopg[binary]>=3.3.5" \
    "httpx>=0.28.1"
COPY *.py ./
COPY --from=frontend-build /frontend/dist ./frontend/dist
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]