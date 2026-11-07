FROM node:22-slim AS frontend
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ backend/
COPY ml/ ml/
COPY --from=frontend /src/dist frontend/dist
RUN useradd --create-home app && mkdir -p ml/models && chown -R app ml/models
USER app
ENV HOST=0.0.0.0 PORT=10000
EXPOSE 10000
CMD ["python", "-m", "backend.main"]
