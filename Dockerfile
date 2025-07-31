FROM python:3.10-slim-bookworm
WORKDIR /app

ENV PYTHONUNBUFFERED 1
ENV PYTHONDONTWRITEBYTECODE 1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    netcat-traditional \
    redis-tools \
    telnet \
    openssl \
    net-tools \
    iputils-ping \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN playwright install \
    && playwright install-deps

COPY entrypoint.sh /app/entrypoint.sh
COPY . .

RUN chmod +x entrypoint.sh

EXPOSE 5000

ENTRYPOINT ["./entrypoint.sh"]

CMD [ "bash", "-c", "flask db upgrade && gunicorn -w 4 --timeout 120 -k gevent -b 0.0.0.0:5000 app.wsgi:app" ]