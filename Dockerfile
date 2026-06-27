# Use Python 3.12 runtime
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install dependencies first (for Docker caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the code
COPY . .

# Create necessary folders so Docker doesn't crash when mapping volumes
RUN mkdir -p /app/instance /app/backups

# Expose the port the app runs on
EXPOSE 5000

# Run in production mode -> app.py serves via waitress (see config.py).
ENV APP_ENV=production

# Command to run the app
CMD ["python", "app.py"]