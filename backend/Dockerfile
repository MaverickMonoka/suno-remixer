FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libsndfile1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
COPY runpod_handler.py .
ENV PORT=8000 FUSIONVOICE_DATA=/data
VOLUME ["/data"]
EXPOSE 8000
CMD ["python","-u","runpod_handler.py"]
