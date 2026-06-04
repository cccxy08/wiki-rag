FROM python:3.10-slim

WORKDIR /app

COPY requirements.hf.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .
COPY wiki-data/ /app/wiki-data/
COPY start.render.sh /app/start.sh

RUN chmod +x /app/start.sh

ENV HOST=0.0.0.0
ENV PORT=10000

EXPOSE 10000

CMD ["/app/start.sh"]
