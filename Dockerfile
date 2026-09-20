FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libsndfile1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/main.py ./main.py
COPY backend/converters ./converters
COPY backend/start.sh ./start.sh
RUN chmod +x /app/start.sh /app/converters/http_converter.py
ENV PORT=10000 FUSIONVOICE_DATA=/tmp/fusionvoice
EXPOSE 10000
CMD ["/app/start.sh"]
