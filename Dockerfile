# Use an official, lightweight Python image
FROM python:3.13-slim

# Set the working directory inside the container
WORKDIR /workspace

# Keep Python from generating .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Copy the requirements file and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the actual application code into the container
COPY ./app /workspace/app

# Expose the port the app runs on
EXPOSE 8080

# Command to run the FastAPI server
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}