# Automated Ricoh Printer Log Collector & Archiver

![Python](https://img.shields.io/badge/python-3.10+-blue.svg)
![Docker](https://img.shields.io/badge/docker-%230db7ed.svg?style=for-the-badge&logo=docker&logoColor=white)
![Playwright](https://img.shields.io/badge/Playwright-2EAD33?style=for-the-badge&logo=playwright&logoColor=white)

A Dockerized Python script for automatically collecting job logs from Ricoh printers and archiving them into a central MySQL database. Features headless browser automation, duplicate prevention, and configuration via an external JSON file.

## Key Features

- **Multi-Printer Support**: Manages and processes a list of any number of printers defined in the configuration.
- **Fully Externalized Configuration**: All settings (credentials, IPs, database details) are stored in a single `config.json` file, which is safely ignored by Git.
- **Dockerized for Portability**: Packaged with Docker and Docker Compose for one-command execution in a consistent, isolated environment.
- **Intelligent Duplicate Prevention**:
  1.  **File-Level Check**: Uses SHA1 hashing to identify if a newly downloaded log is identical to a previous one, preventing re-processing.
  2.  **Database-Level Check**: Employs a highly efficient staging table method to ensure only new, unique log entries are inserted into the main database.
- **Automated Cleanup**: Automatically deletes local log files after they have been successfully processed and archived.
- **Robust & Headless**: Built with Playwright's modern async capabilities and explicit waits to handle dynamic web pages reliably in the background.

## Workflow Overview

The script executes the following automated workflow for each printer in the configuration:

`Start` -> `Download Log` -> `Check if Duplicate` -> `Parse Data` -> `Archive to DB` -> `Delete Local File` -> `End`

1.  **Download**: Launches a headless browser, navigates to the printer's web interface, logs in, and downloads the job log CSV file.
2.  **Duplicate Check**: Computes a hash of the new file. If it matches an existing file, the new one is deleted and the process stops for that printer.
3.  **Parse & Clean**: If the file is unique, it is opened with Pandas, cleaned, structured, and formatted for the database.
4.  **Archive to Database**: Inserts only new, previously unsaved records into the target MySQL table using a staging process.
5.  **Cleanup**: If the database operation succeeds (or the file is empty), the local `.csv` file is deleted. If a DB error occurs, the file is kept for manual review.

## Prerequisites

- **Docker & Docker Compose**: The primary requirement for running the application. ([Install Docker](https://docs.docker.com/get-docker/))
- **MySQL Database**: A running MySQL server instance that is accessible from where you are running Docker.
- **Git**: For cloning the repository.

## Installation & Setup

1.  **Clone the Repository**

    ```bash
    git clone https://github.com/your-username/ricoh-log-collector.git
    cd ricoh-log-collector
    ```

2.  **Set Up the Database**
    Connect to your MySQL server and run the following SQL query to create the necessary table. The script will insert log data into this table.

    ```sql
    CREATE TABLE `printer_logs` (
      `id` INT NOT NULL AUTO_INCREMENT,
      `LogID` VARCHAR(255) NOT NULL,
      `StartDateTime` DATETIME NULL,
      `EndDateTime` DATETIME NULL,
      `LogType` TEXT NULL,
      `Result` TEXT NULL,
      `OperationMethod` TEXT NULL,
      `Status` TEXT NULL,
      `CancelledDetails` TEXT NULL,
      `UserID` VARCHAR(255) NULL,
      `HostIPAddress` VARCHAR(45) NULL,
      `Source` TEXT NULL,
      `PrintFileName` TEXT NULL,
      `CreatedPages` INT NULL,
      `ExitPages` INT NULL,
      `ExitPapers` INT NULL,
      `PaperSize` TEXT NULL,
      `PaperType` TEXT NULL,
      `PrinterName` VARCHAR(255) NOT NULL,
      `ArchivedAt` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY (`id`),
      UNIQUE INDEX `unique_log_entry` (`LogID`, `PrinterName`, `StartDateTime`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    ```

    **Note:** The `UNIQUE INDEX` is crucial. It provides a database-level guarantee against duplicate log entries based on the combination of the Log ID, Printer Name, and Start Time.

3.  **Create the Configuration File**
    This project uses a `.gitignore` file to intentionally keep your `config.json` file private. You must create it yourself from the template below.

    Create a file named `config.json` in the root of the project folder and add the following structure. **Fill it out with your own environment details.**

    **`config.json` (Template)**

    ```json
    {
      "database": {
        "user": "your_db_user",
        "password": "your_db_password",
        "host": "your_db_host_or_ip",
        "port": "3306",
        "name": "your_db_name"
      },
      "script_settings": {
        "main_log_table": "printer_logs",
        "log_file_encoding": "utf-8-sig",
        "printer_name_prefix": "RICOH",
        "base_download_directory": "./downloaded_logs",
        "base_url_template": "http://{ip_address}/",
        "log_download_url_template": "http://{ip_address}/web/entry/en/websys/config/getLogDownload.cgi",
        "browser_headless": true,
        "browser_slow_mo_ms": 0,
        "download_timeout_ms": 30000
      },
      "printers": [
        {
          "model": "PrinterModel_A",
          "ip_address": "ip_address_of_printer_a",
          "username": "printer_admin_user",
          "password": "printer_admin_password"
        },
        {
          "model": "PrinterModel_B",
          "ip_address": "ip_address_of_printer_b",
          "username": "printer_admin_user",
          "password": "another_printer_password"
        }
      ]
    }
    ```

## How to Run

The recommended way to run this application is with Docker Compose.

1.  **Build and Run the Container**
    Open a terminal in the project's root directory and run:

    ```bash
    docker compose up
    ```

    This command will:

    - Build the Docker image from the `Dockerfile` if it doesn't already exist.
    - Start a container to run the `complete_script.py`.
    - Mount your local `config.json` and `downloaded_logs` directory into the container.
    - Stream all script output directly to your terminal.

2.  **Useful Commands**
    - **Force a Rebuild:** If you change the `Dockerfile` or `requirements.txt`, run with the `--build` flag.
      ```bash
      docker compose up --build
      ```
    - **Run and Clean Up:** To automatically remove the container after the script finishes (ideal for scheduled tasks).
      ```bash
      docker compose up --remove-orphans
      ```

## Scheduling the Task (Automation)

To run this script on a schedule, you can use `cron` on Linux/macOS or Task Scheduler on Windows.

**Example `crontab` entry for Linux/macOS:**

This example runs the script at 2:00 AM every day.

1.  Open your crontab editor: `crontab -e`
2.  Add the following line, making sure to use **absolute paths**:

    ```crontab
    # Run the Ricoh Log Collector at 2:00 AM daily
    0 2 * * * cd /path/to/your/project_folder && /usr/bin/docker compose up --remove-orphans >> /path/to/your/project_folder/cron.log 2>&1
    ```

## Project Structure

```
.
├── complete_script.py      # The main Python automation script.
├── config.json             # (Ignored by Git) Your local configuration with secrets.
├── Dockerfile              # Instructions to build the Docker image.
├── docker-compose.yml      # Simplifies running the application with Docker.
├── .gitignore              # Specifies files for Git to ignore (e.g., config.json).
├── requirements.txt        # A list of Python libraries needed for the project.
└── README.md               # This file.
```
