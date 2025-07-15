import os
import asyncio
from playwright.async_api import async_playwright
from datetime import datetime
import pandas as pd
from io import StringIO
import csv
import time
import json
import hashlib
from sqlalchemy import create_engine, text

# =================================================================================
# === CORE FUNCTIONS ==============================================================
# =================================================================================

def load_config(config_path='config.json'):
    """Loads the configuration from a JSON file."""
    try:
        with open(config_path, 'r') as f:
            print(f"Loading configuration from '{config_path}'...")
            return json.load(f)
    except FileNotFoundError:
        print(f"FATAL: Configuration file '{config_path}' not found. Please create it.")
        return None
    except json.JSONDecodeError:
        print(f"FATAL: Could not parse '{config_path}'. Please check for syntax errors.")
        return None

def compute_sha1(file_path, block_size=65536):
    """Compute SHA1 hash of a file's content."""
    sha1 = hashlib.sha1()
    try:
        with open(file_path, 'rb') as f:
            while chunk := f.read(block_size):
                sha1.update(chunk)
        return sha1.hexdigest()
    except Exception as e:
        print(f"Error computing hash for {file_path}: {e}")
        return None

def is_duplicate(new_file_path, log_directory):
    """Checks if the new file is a content-duplicate of any existing file in the directory."""
    new_file_hash = compute_sha1(new_file_path)
    if not new_file_hash: return False

    for existing_filename in os.listdir(log_directory):
        existing_file_path = os.path.join(log_directory, existing_filename)
        if os.path.samefile(new_file_path, existing_file_path): continue
        
        if new_file_hash == compute_sha1(existing_file_path):
            print(f"Duplicate content found. New file is identical to existing file '{existing_filename}'.")
            return True
    return False

def safe_delete(file_path, reason=""):
    """Safely deletes a file and prints a confirmation message with the reason."""
    try:
        os.remove(file_path)
        print(f"✅ Deleted log file: {os.path.basename(file_path)} ({reason})")
    except OSError as e:
        print(f"❌ Error deleting file {file_path}: {e}")


async def download_printer_log(printer_config, settings):
    """
    Automates downloading the job log using fully externalized configuration.
    This version includes robust waits to prevent race conditions.
    """
    model, ip = printer_config['model'], printer_config['ip_address']
    
    base_url = settings['base_url_template'].format(ip_address=ip)
    log_download_url = settings['log_download_url_template'].format(ip_address=ip)
    
    download_dir = os.path.join(settings['base_download_directory'], f"{model}_logs")
    os.makedirs(download_dir, exist_ok=True)
    
    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{settings['printer_name_prefix']}-{model}_JobLog.csv"
    destination_path = os.path.join(download_dir, filename)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=settings['browser_headless'], slow_mo=settings['browser_slow_mo_ms'])
        context = await browser.new_context(ignore_https_errors=True)
        page = await context.new_page()

        try:
            print(f"Navigating to {base_url}...")
            await page.goto(base_url)

            # --- CHANGE #1: Wait for the frame to exist before using it ---
            # Instead of just waiting for the page, we now explicitly wait for the
            # frame we need. Locators have built-in auto-waiting.
            print("Waiting for login frame to be available...")
            header_frame_locator = page.frame_locator('[name="header"]')
            
            # Now, when we try to click, Playwright will automatically wait until
            # the frame and the button inside it are ready.
            await header_frame_locator.locator('a:has(span:text-is("Login"))').click()
            
            # --- CHANGE #2: Wait for the new page to be fully loaded after login ---
            # The login action navigates to a new URL. We wait for it to settle.
            await page.wait_for_load_state('networkidle')
            print("Login successful, page loaded.")

            await page.locator('input[name="userid_work"]').fill(printer_config['username'])
            await page.locator('input[name="password_work"]').fill(printer_config['password'])
            await page.locator('input[type="submit"][value="Login"]').click()
            
            # After submitting login, wait again for the network to be idle.
            await page.wait_for_load_state('networkidle')

            print("Navigating to log download page...")
            await page.goto(log_download_url)
            
            # Wait for the download button to be ready before clicking.
            download_button = page.locator('td.defaultTableButton:has(a:has-text("Download"))')
            await download_button.wait_for(state="visible", timeout=settings['download_timeout_ms'])

            async with page.expect_download(timeout=settings['download_timeout_ms']) as download_info:
                await download_button.click()
            
            download = await download_info.value
            await download.save_as(destination_path)
            
            print(f"✅ DOWNLOAD SUCCESS for {model}. File saved to: {destination_path}")
            return destination_path, download_dir

        except Exception as e:
            print(f"❌ DOWNLOAD FAILED for printer {model} ({ip}). Error: {e}")
            return None, None
        finally:
            await context.close()
            await browser.close()


def parse_and_clean_ricoh_log(file_path, printer_name, encoding):
    """Reads, cleans, and structures a Ricoh log file."""
    try:
        with open(file_path, 'r', encoding=encoding, errors='ignore') as f: lines = f.readlines()
    except FileNotFoundError: return pd.DataFrame()
    csv_start_index = next((i for i, line in enumerate(lines) if line.strip().lower().replace('"', '').startswith('start date/time')), -1)
    if csv_start_index == -1: return pd.DataFrame()
    csv_lines = [line.strip() for line in lines[csv_start_index:] if line.strip() and "download completed" not in line.lower()]
    reader = csv.reader(StringIO('\n'.join(csv_lines)))
    try: header = next(reader)
    except StopIteration: return pd.DataFrame()
    processed_events = []
    current_event = {}
    for row in reader:
        if len(row) > 1 and row[0]:
            if current_event: processed_events.append(current_event)
            current_event = dict(zip(header, row))
        elif current_event:
            for i in range(min(len(header), len(row))):
                if row[i] and not current_event.get(header[i]): current_event[header[i]] = row[i]
    if current_event: processed_events.append(current_event)
    if not processed_events: return pd.DataFrame()
    df = pd.DataFrame(processed_events)
    rename_map = {'Log ID':'LogID','Start Date/Time':'StartDateTime','End Date/Time':'EndDateTime','Log Type':'LogType','Result':'Result','Operation Method':'OperationMethod','Status ':'Status','Cancelled: Details':'CancelledDetails','User ID':'UserID','Host IP Address':'HostIPAddress','Source':'Source','Print File Name':'PrintFileName','Created Pages':'CreatedPages','Exit Pages':'ExitPages','Exit Papers':'ExitPapers','Paper Size':'PaperSize','Paper Type':'PaperType'}
    for col in rename_map:
        if col not in df.columns: df[col] = None
    df_cleaned = df[list(rename_map.keys())].rename(columns=rename_map)
    df_cleaned['PrinterName'] = printer_name
    print(f"🔩 Parsed {len(df_cleaned)} events from '{os.path.basename(file_path)}'.")
    return df_cleaned


def process_and_insert_logs_via_staging(new_df, printer_name, db_engine, main_table):
    """Uses a staging table to insert new records. Returns inserted count or -1 on DB error."""
    if db_engine is None or new_df.empty: return 0
    staging_table = f"staging_{printer_name.lower().replace('-', '_')}_{int(time.time())}"
    df = new_df.copy()
    for col in ['CreatedPages', 'ExitPages', 'ExitPapers']:
        df[col] = pd.to_numeric(df[col], errors='coerce').astype('Int64')
    for col in ['StartDateTime', 'EndDateTime']:
        df[col] = pd.to_datetime(df[col], errors='coerce')
    df.dropna(subset=['LogID', 'PrinterName', 'StartDateTime'], inplace=True)
    if df.empty: return 0
    inserted_count = 0
    with db_engine.connect() as conn:
        trans = conn.begin()
        try:
            df.to_sql(name=staging_table, con=conn, if_exists='replace', index=False)
            query = text(f"SELECT st.* FROM {staging_table} st LEFT JOIN {main_table} mt ON st.LogID = mt.LogID AND st.PrinterName = mt.PrinterName AND st.StartDateTime = mt.StartDateTime WHERE mt.LogID IS NULL;")
            new_rows_df = pd.read_sql(query, conn)
            inserted_count = len(new_rows_df)
            if inserted_count > 0:
                print(f"Found {inserted_count} new entries. Inserting into '{main_table}'...")
                new_rows_df.to_sql(main_table, conn, if_exists='append', index=False)
            else:
                print("No new log entries to add to the database.")
            trans.commit()
        except Exception as e:
            trans.rollback(); print(f"❌ DB Error for {printer_name}. Rolled back. Error: {e}"); return -1 # Return error code
        finally:
            conn.execute(text(f"DROP TABLE IF EXISTS {staging_table};"))
    return inserted_count


async def main():
    """Main orchestrator: loads config, connects to DB, and processes all printers."""
    config = load_config()
    if not config: return

    db_cfg, settings = config['database'], config['script_settings']
    try:
        conn_str = f"mysql+mysqlconnector://{db_cfg['user']}:{db_cfg['password']}@{db_cfg['host']}:{db_cfg['port']}/{db_cfg['name']}"
        db_engine = create_engine(conn_str)
        with db_engine.connect() as conn: print("Successfully connected to MySQL database!\n")
    except Exception as e:
        print(f"FATAL: Could not connect to database. Aborting. Error: {e}"); return

    for printer_config in config['printers']:
        printer_id = f"{settings['printer_name_prefix']}_{printer_config['model']}"
        print("\n" + "="*80 + f"\nPROCESSING PRINTER: {printer_id} ({printer_config['ip_address']})\n" + "="*80)
        
        log_file, log_dir = await download_printer_log(printer_config, settings)
        
        if log_file and os.path.exists(log_file):
            if is_duplicate(log_file, log_dir):
                safe_delete(log_file, reason="Duplicate")
                print(f"--- SUMMARY for {printer_id}: No changes. Log file is a duplicate. ---")
                continue

            parsed_df = parse_and_clean_ricoh_log(log_file, printer_id, settings['log_file_encoding'])
            
            if not parsed_df.empty:
                new_rows = process_and_insert_logs_via_staging(parsed_df, printer_id, db_engine, settings['main_log_table'])
                
                if new_rows >= 0: # Success (0 or more rows inserted)
                    print(f"--- SUMMARY for {printer_id}: {new_rows} new log(s) inserted. ---")
                    safe_delete(log_file, reason="Successfully processed")
                else: # DB Error
                    print(f"--- SUMMARY for {printer_id}: Database error. Log file was NOT deleted. ---")
            else:
                print(f"--- SUMMARY for {printer_id}: Log file was empty or unparseable. ---")
                safe_delete(log_file, reason="Empty or unparseable")
        else:
            print(f"Processing for {printer_id} skipped due to download failure.")

    print("\n\nAll configured printers have been processed. Workflow complete.")


if __name__ == "__main__":
    asyncio.run(main())