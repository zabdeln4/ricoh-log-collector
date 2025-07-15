# Step 1: Start with an official base image from Microsoft.
# This image already contains Python and all the complex dependencies needed by Playwright.
FROM mcr.microsoft.com/playwright/python:v1.53.0-jammy

# Step 2: Set a working directory inside the container.
# This is where your files will live inside the "magic box".
WORKDIR /app

# Step 3: Copy and install the Python requirements.
# This is done in a separate step to take advantage of Docker's caching,
# which speeds up future builds if your requirements don't change.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Step 4: Copy all your project files (the script and config) into the container.
COPY . .

# Step 5: Specify the command to run when the container starts.
# We use "python3 -u" to make sure the script's output (print statements)
# appears in the Docker logs immediately, which is great for debugging.
CMD ["python3", "-u", "complete_script_z.py"]