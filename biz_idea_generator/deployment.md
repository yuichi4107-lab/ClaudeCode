# Server Deployment Guide

You can run this application on any server (VPS, Cloud Run, etc.) using Docker.

## 1. Prerequisites
- A server with **Docker** installed.
- Your `.env` file credentials.

## 2. Setup
1. Transfer the project files to your server (or clone via git).
2. Ensure your `.env` file is present in the project root with valid keys.

## 3. Build & Run
Run the following commands in the project directory:

```bash
# Build the Docker image
docker build -t biz-idea-generator .

# Run the container (manual test)
docker run --rm --env-file .env -v $(pwd)/reports:/app/reports biz-idea-generator
```

## 4. Automation (Cron)
To run this daily at 7:00 AM on a Linux server, add a cron job:

1. Open crontab: `crontab -e`
2. Add the line:
   ```bash
   0 7 * * * docker run --rm --env-file /path/to/.env -v /path/to/reports:/app/reports biz-idea-generator
   ```

## Local Debugging (Windows)
If the automated task failed on your PC:
1. Check the newly created `logs/run.log` file after a failed run.
2. It will contain the error details (e.g., network error, path issue).
