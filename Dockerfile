# Use the official Python image as a base
FROM python:3.11

# Set the working directory inside the container
WORKDIR /app

# Copy all files from the current directory to /app inside the container
COPY . .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose port 8080 for Cloud Run
EXPOSE 8080

# Run the bot when the container starts
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
