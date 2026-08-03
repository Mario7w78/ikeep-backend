FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Requirements first so the dependency layer is cached across code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render (and most PaaS) inject the port to bind. Default to 8000 locally.
ENV PORT=8000
EXPOSE 8000

# Shell form so $PORT is expanded. No --reload: that is for local dev only,
# and main.py's __main__ block is not used here.
CMD uvicorn main:app --host 0.0.0.0 --port $PORT
