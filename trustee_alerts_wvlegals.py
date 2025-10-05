import requests,os,re,smtplib,time,schedule,json
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from email.mime.text import MIMEText
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.service import Service as FirefoxService
from webdriver_manager.firefox import GeckoDriverManager as firefox

with open("config.json","r") as json_file:
    debug=json.load(json_file)["debug"]

def init_selenium_driver(debug=False):
    """
    Initialize a headless Firefox WebDriver safely.
    Provides detailed diagnostics if it fails due to permissions or missing dependencies.
    """
    options = Options()
    options.set_preference("dom.webnotifications.enabled", False)
    options.set_preference("media.volume_scale", "0.0")
    options.add_argument("--headless")          # required for servers / containers
    options.add_argument("--no-sandbox")        # fix for container restrictions
    options.add_argument("--disable-dev-shm-usage")  # handle small /dev/shm volumes
    options.add_argument("--window-size=1920,1080")

    try:
        service = FirefoxService(firefox().install())
        driver = webdriver.Firefox(service=service, options=options)
        if debug:
            print("[INFO] Firefox WebDriver initialized successfully.")
        return driver
    except Exception as e:
        print("\n[ERROR] Could not start Firefox WebDriver.")
        print("Possible causes:")
        print("  1. Firefox or geckodriver lacks execute permissions.")
        print("  2. SELinux/AppArmor is blocking Firefox from spawning.")
        print("  3. The container environment disallows GUI or sandboxing.")
        print("  4. Missing dependencies (e.g., libgtk-3, libx11, fonts, etc.).")
        print(f"Full exception: {e}\n")
        raise  # Re-raise so you can handle it higher up if desired

# Initialize driver once
driver = init_selenium_driver(debug)


# Load email credentials from .env
load_dotenv()
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
if debug:
    EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER_DEBUG")
else:
    EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")
if EMAIL_SENDER.endswith("@yahoo.com"):
    SMTP_SERVER = "smtp.mail.yahoo.com"
    SMTP_PORT = 587
elif EMAIL_SENDER.endswith("@gmail.com"):
    SMTP_SERVER = "smtp.gmail.com"
    SMTP_PORT = 587
elif EMAIL_SENDER.endswith("@outlook.com") or EMAIL_SENDER.endswith("@hotmail.com"):
    SMTP_SERVER = "smtp.office365.com"
    SMTP_PORT = 587
else:
    SMTP_SERVER = os.getenv("SMTP_SERVER")
    if os.getenv("SMTP_PORT") != None:
        SMTP_PORT = int(os.getenv("SMTP_PORT"))
    else:
        SMTP_PORT = 587

# Configuration
with open("config.json","r") as json_file:
    config=json.load(json_file)
TARGET_COUNTIES = config["counties"]
SEARCH_TERM = config["search"]
PAGES_TO_SCAN = config["pages"]
BASE_URL = config["url"]
SEND_TIME = config["send_time"]

delay = ((((11*PAGES_TO_SCAN)-1)*3)+(5*(PAGES_TO_SCAN*10)))/60
sending_time = SEND_TIME.split(":")
send_hour = int(sending_time[0])
send_minute = int(sending_time[1])
send_minute = send_minute-delay
while send_minute < 0:
    send_minute = send_minute+60
    send_hour = send_hour-1
send_minute = int(send_minute)
SEND_TIME = f"{send_hour}:{send_minute}"
CONFIG_SEND_TIME = config["send_time"]

# Email sending function
def send_email(subject, body, files):
    msg = MIMEMultipart()
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECEIVER
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    for file_path in files:
        with open(file_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f'attachment; filename="{os.path.basename(file_path)}"')
            msg.attach(part)

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.send_message(msg)

# Extract sale info from post text
def extract_sale_info(text,county,url,defined_text):
    sale_data = {}
    sale_data["Sale Date/Time"] = re.search(r"((on\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})|((the\s)?[1-3]?\d(th|rd|nd|st)\s(day\s)?of (January|Feburary|March|April|May|June|July|August|September|October|November|December),?\s(19|20)\d\d))\sat\s\d[0-2]?:[0-5]\d(\s?(a|p)\.?m\.?)?|(at\s+(\d{1,2}:\d{2}\s*(?:AM|PM)?)\s+on\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})|[1-3]?\d(th|rd|nd|st)\s(day\s)?of (January|Feburary|March|April|May|June|July|August|September|October|November|December),?\s(19|20)\d\d))", text, re.IGNORECASE)
    sale_data["Sale Date/Time"] = sale_data["Sale Date/Time"].group(0) if sale_data["Sale Date/Time"] else ""

    sale_data["Location"] = county
    sale_data["Location"] = sale_data["Location"] if sale_data["Location"] else ""

    sale_data["Address"] = re.search(r"\d{1,5}\s[a-zA-Z]+\s[a-zA-Z]+,\s?[a-z\sA-Z]+,\s?w(est\s)?v(irginia)?\s\d{5}", text, re.IGNORECASE)
    sale_data["Address"] = sale_data["Address"].group(0) if sale_data["Address"] else ""

    borrower = re.search(r"((executed\sby|from)\s(the\s)?(Borrower)?(\(s\))?\,?(([a-zA-Z].?)+\s){1,2}[a-zA-Z]+\,?|(([a-zA-Z.],?)+\s){1,2}[a-zA-Z]+\sdid\sconvey\sunto)", text, re.IGNORECASE)
    borrower = borrower.group(0) if borrower else ""
    borrower = borrower.split(",") if "," in borrower else borrower.split()
    try:
        if borrower[1] == "":
            borrower = borrower[0].split()
    except IndexError:
        print(f"no borrower found for {url}")
    try:
        if len(borrower)==2 and borrower[0].startswith("executed") or borrower[0].startswith("from"):
            borrower = borrower[0].split()
    except IndexError:
        print(f"no borrower found for {url}")
    if debug:
        print(borrower)
    sale_data["Grantor/Borrower"] = ""
    if borrower == None or borrower == [] or borrower == [""] or borrower == "":
        sale_data["Grantor/Borrower"] = None
    elif borrower[0] == "from":
        if len(borrower) == 3:
            sale_data["Grantor/Borrower"] = borrower[1]+" "+borrower[2]
        elif len(borrower) == 4:
            sale_data["Grantor/Borrower"] = borrower[1]+" "+borrower[2]+" "+borrower[3]
    elif borrower[0] == "executed":
        if len(borrower) == 4:
            sale_data["Grantor/Borrower"] = borrower[2]+" "+borrower[3]
        elif len(borrower) == 5:
            sale_data["Grantor/Borrower"] = borrower[2]+" "+borrower[3]+" "+borrower[4]
    elif " " in borrower[1]:
        sale_data["Grantor/Borrower"] = borrower[1]
    elif borrower[2] == "did" or borrower[3] == "did":
        if len(borrower) == 5:
            sale_data["Grantor/Borrower"] = borrower[0]+" "+borrower[1]
        elif len(borrower) == 6:
            sale_data["Grantor/Borrower"] = borrower[0]+" "+borrower[1]+" "+borrower[2]
    sale_data["Grantor/Borrower"] = sale_data["Grantor/Borrower"] if sale_data["Grantor/Borrower"] else ""

    sale_data["Trustee Name"] = re.search(r"(Trustee(?:s)?[:,]?\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)|(WV Trustee Services,?\sLLC))", text, re.IGNORECASE)
    sale_data["Trustee Name"] = sale_data["Trustee Name"].group(0) if sale_data["Trustee Name"] else ""

    deposit = re.search(r"(?:deposit\s+of\s+\$[0-9,]+)|(?:\$\s?[0-9,]+\s+cash)|(?:\d{1,3}%)", text, re.IGNORECASE)
    deposit = deposit.group(0) if deposit else "Not Found"
    deposit = deposit.split()
    for word in deposit:
        if word.startswith("$"):
            sale_data["Deposit/Amount"] = word
        elif word.endswith("%"):
            sale_data["Deposit/Amount"] = word
        elif word == "Not":
            sale_data["Deposit/Amount"] = None
    sale_data["Deposit/Amount"] = sale_data["Deposit/Amount"] if sale_data["Deposit/Amount"] else ""

    deed_date = re.search(r"dated\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", text, re.IGNORECASE)
    deed_date = deed_date.group(0) if deed_date else ""
    if deed_date != "":
        deed_date = deed_date.split()
        deed_month = deed_date[1]
        deed_day = int(deed_date[2].replace(",",""))
        deed_year = int(deed_date[3])
        if deed_month == "January":
            deed_month = 1
        elif deed_month == "Feburary":
            deed_month = 2
        elif deed_month == "March":
            deed_month = 3
        elif deed_month == "April":
            deed_month = 4
        elif deed_month == "May":
            deed_month = 5
        elif deed_month == "June":
            deed_month = 6
        elif deed_month == "July":
            deed_month = 7
        elif deed_month == "August":
            deed_month = 8
        elif deed_month == "September":
            deed_month = 9
        elif deed_month == "October":
            deed_month = 10
        elif deed_month == "November":
            deed_month = 11
        elif deed_month == "December":
            deed_month = 12
        else:
            deed_month = 0
        formatted_deed_date = f"{deed_month}/{deed_day}/{deed_year}"
    else:
        formatted_deed_date = None
    sale_data["Original Deed Date"] = formatted_deed_date
    sale_data["Original Deed Date"] = sale_data["Original Deed Date"] if sale_data["Original Deed Date"] else ""

    return sale_data

def get_visible_detail_text(detail_url, debug=False):
    """
    Opens a detail URL in Selenium, extracts all visible div/p elements.
    Returns (article_text, text_elements).
    """
    try:
        driver.get(detail_url)
        time.sleep(5)  # give the page a moment to finish rendering

        elements = driver.find_elements(By.XPATH, "//div | //p")
        visible_texts = []
        for el in elements:
            if el.is_displayed():
                txt = el.text.strip()
                if txt:
                    visible_texts.append(txt)

        article_text = " ".join(visible_texts)
        if debug:
            print(visible_texts)

        return article_text, visible_texts

    except Exception as e:
        if debug:
            print(f"[ERROR] Failed to fetch detail {detail_url}: {e}")
        return "", []

# Main scraper
def scrape_notices():
    all_sales = []
    miscatches = []
    log_entries = []
    def log(text):
        log_entries.append(text)
        print(text)

    for page in range(1, PAGES_TO_SCAN + 1):
        url = f"{BASE_URL}/page/{page}/?s={SEARCH_TERM}"
        try:
            response = requests.get(url, timeout=60)
            time.sleep(3)
            response.raise_for_status()
        except Exception as e:
            log(f"Fetch failed (list page {page}): {e}")
            continue

        soup = BeautifulSoup(response.text, "html.parser")
        posts = soup.find_all("h3", class_="entry-title")
        if debug:
            print(posts)

        for post in posts:
            detail_url = post.find("a")["href"]
            print (f"Requested {detail_url}")

            try:
                detail_resp = requests.get(detail_url, timeout=15)
                time.sleep(3)
                detail_resp.raise_for_status()
            except Exception as e:
                log(f"Failed to fetch detail {detail_url}: {e}")
                
                continue
            article_text,visible_texts = get_visible_detail_text(detail_url,debug)
            article_text = visible_texts[0]
            article_text_county = re.split("read more",article_text,flags=re.IGNORECASE)[0]
            if debug:
                print(visible_texts)
            def get_last_chars(string, n):
                return string[-n:]
            mini_article_text = get_last_chars(article_text,350)

            for county in TARGET_COUNTIES:
                county_regex = re.search(county,article_text_county,re.IGNORECASE)
                if county_regex:
                    sale_info = extract_sale_info(article_text,county,detail_url,mini_article_text)
                    sale_info["Detail URL"] = detail_url
                    if sale_info["Location"] == TARGET_COUNTIES[0] and sale_info["Sale Date/Time"] == "" and sale_info["Address"] == "" and sale_info["Grantor/Borrower"] == "" and sale_info["Deposit/Amount"] == "" and sale_info["Original Deed Date"] == "":
                        miscatches.append(sale_info)
                        log(f"{sale_info["Detail URL"]} was triggered as likely a miscatch moving to \"Likely Miscatches\" sheet")
                        print(".\n.\n.\n.\n.\n")
                    else:
                        all_sales.append(sale_info)
                    log(f"{detail_url} is for {county}")
                    break
                else:
                    log(f"County not a match to {county}")

    # Save Excel
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    excel_path = f"trustee_sales_{timestamp}.xlsx"
    with pd.ExcelWriter(excel_path,engine="xlsxwriter") as excel_file:
        pd.DataFrame(all_sales).to_excel(excel_file, index=False, sheet_name="Sales Data")
        pd.DataFrame(miscatches).to_excel(excel_file, index=False, sheet_name="Likely Miscatches")

    # Save log
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_path = f"trustee_sales_log_{timestamp}.txt"
    with open(log_path, "w") as log_file:
        log_file.write("\n".join(log_entries) if log_entries else "Scrape completed successfully.")

    return excel_path, log_path
def send():
    if __name__ == "__main__":
        excel_file, log_file = scrape_notices()
        send_email("WV Trustee Sales Report", "See attached Excel and log file.", [excel_file, log_file])
        timestamp = datetime.now().strftime('%Y:%m:%d %H:%M:%S')
        print(f"Report sent at {timestamp}.")
    time.sleep(5*60)
    os.remove(excel_file)
    os.remove(log_file)

if not debug:
    schedule.every().day.at(SEND_TIME).do(send)
    print(f"Schedule ready for {SEND_TIME} ({CONFIG_SEND_TIME}-{delay} minutes (to combat ratelimit))")
    while True:
        schedule.run_pending()
        time.sleep(1)
else:
    delay_minutes=int(delay)
    delay_seconds=int((delay-delay_minutes)*60)
    print (f"Email will take about {delay_minutes} minutes and {delay_seconds} seconds")
    send()