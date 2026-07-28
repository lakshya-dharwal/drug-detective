# Drug Detective backend — FastAPI wrapping the Phase 1 pipeline.
#
# The build context must be the repo root (the directory containing phase1/ and
# phase2/) so that the Phase 1 package can be copied in and imported as-is:
#
#   docker build -f phase2/backend/Dockerfile -t drug-detective-api .
#   docker run -p 8000:8000 --env-file phase2/backend/.env drug-detective-api
#
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PHASE1_ROOT=/app/phase1

WORKDIR /app

# Install backend deps (which also cover Phase 1's runtime deps).
COPY phase2/backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Bring in Phase 1 (imported as a module) and the backend code.
COPY phase1 /app/phase1
COPY phase2/backend /app/backend

WORKDIR /app/backend

# Render/Railway inject $PORT; default to 8000 for local runs.
ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
