FROM node:20-slim AS ui
WORKDIR /ui
COPY frontend-app/package.json frontend-app/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend-app/ ./
RUN npm run build

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GUARDLENS_HOST=0.0.0.0 \
    GUARDLENS_PORT=8080

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY --from=ui /ui/dist ./frontend-app/dist
RUN mkdir -p data/snapshots data/faces data/clips
EXPOSE 8080
CMD ["python", "-m", "guardlens"]
