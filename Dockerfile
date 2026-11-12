FROM python:3.12-slim

WORKDIR /srv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --no-cache-dir .

COPY config ./config
RUN useradd --create-home --uid 10001 app && mkdir -p /srv/data && chown app /srv/data
USER app
VOLUME ["/srv/data"]
EXPOSE 8000

CMD ["uvicorn", "--factory", "app.main:app_factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
