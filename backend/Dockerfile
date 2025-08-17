FROM python:3.11-slim
WORKDIR /app
# Copy only requirements first to leverage Docker layer cache for dependencies
COPY requirements.txt /app/requirements.txt
RUN pip --default-timeout=100 install --no-cache-dir -r /app/requirements.txt
# Now copy the rest of the application
COPY . /app
EXPOSE 8000
CMD ["python", "app.py"]
