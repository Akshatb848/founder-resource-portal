# Founder's Resource Portal: API + built frontend (dist/). Demo use only; see README.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend backend
COPY dist dist
COPY content content
RUN useradd --create-home portal && mkdir -p content/uploads && chown -R portal content/uploads
USER portal
EXPOSE 8000
# Apply the schema, load the fictional demo data (idempotent), then serve.
CMD ["sh", "-c", "python -m backend.seed && python backend/scripts/import_portfolio.py --apply && python backend/scripts/import_sector_news.py --apply && exec uvicorn backend.main:app --host 0.0.0.0 --port 8000"]
