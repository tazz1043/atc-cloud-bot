import os
import time
import datetime
import traceback
from flask import Flask, request, render_template_string
from werkzeug.utils import secure_filename
from openpyxl import load_workbook

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains

app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

DUTY_ENTRY_URL = "https://iamatc.aai.aero/atc/duty-entry"

def dismiss_popups(driver):
    try:
        driver.switch_to.alert.accept()
        time.sleep(0.1)
    except: pass
    try:
        ok_btns = driver.find_elements(By.XPATH, "//button[normalize-space(text())='OK' or normalize-space(text())='Ok' or normalize-space(text())='ok']")
        for btn in ok_btns:
            if btn.is_displayed():
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(0.2)
    except: pass

def wait_and_click(driver, xpath, timeout=5):
    try:
        el = WebDriverWait(driver, timeout).until(EC.element_to_be_clickable((By.XPATH, xpath)))
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
        time.sleep(0.1)
        try: ActionChains(driver).move_to_element(el).click().perform()
        except: driver.execute_script("arguments[0].click();", el)
        return True
    except: return False

def smart_type(driver, xpath_list, text_val):
    if not text_val or str(text_val).lower() == 'nan': return False
    for xp in xpath_list:
        try:
            elements = driver.find_elements(By.XPATH, xp)
            for el in elements:
                if el.is_displayed():
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
                    time.sleep(0.1)
                    try: ActionChains(driver).move_to_element(el).click().perform()
                    except: driver.execute_script("arguments[0].click();", el)
                   
                    el.send_keys(Keys.CONTROL, 'a')
                    time.sleep(0.05)
                    el.send_keys(Keys.BACKSPACE)
                    time.sleep(0.05)
                    el.send_keys(str(text_val))
                    time.sleep(0.05)
                    el.send_keys(Keys.TAB)
                    return True
        except: pass
    return False

def handle_react_select(driver, label_name, placeholder_text, value):
    if not value or str(value).lower() == 'nan': return
    exact_target = str(value).strip()
    if "UNIT" in label_name:
        search_str = exact_target.lower()
        if search_str in ["adc", "twr", "tower", "control tower"]: exact_target = "ADC"
        elif search_str in ["adc+app", "twrapp", "twr/app"]: exact_target = "ADC+APP"
        elif search_str in ["app", "approach", "app_surv", "app+app"]: exact_target = "APP"
        elif search_str in ["app(p) + app(s)", "app p+s", "app ps"]: exact_target = "APP(P) + APP(S)"

    try:
        label_xpath = f"//label[contains(translate(., 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'), '{label_name}')]"
        label = driver.find_element(By.XPATH, label_xpath)
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", label)
        time.sleep(0.2)
        ActionChains(driver).move_to_element(label).move_by_offset(0, 40).click().perform()
    except: pass

    time.sleep(0.5)
    try:
        js_sniper = f"""
            var target = '{exact_target}';
            var elements = Array.from(document.querySelectorAll('div, span, li')).filter(el => {{
                return el.textContent.trim() === target && el.children.length === 0;
            }});
            if(elements.length > 0) {{
                var el = elements[elements.length - 1];
                el.scrollIntoView({{block: 'center'}});
                el.dispatchEvent(new MouseEvent('mousedown', {{bubbles: true, cancelable: true}}));
                el.dispatchEvent(new MouseEvent('mouseup', {{bubbles: true, cancelable: true}}));
                el.click();
                return true;
            }}
            return false;
        """
        if not driver.execute_script(js_sniper):
            ActionChains(driver).send_keys(exact_target).perform()
            time.sleep(0.6)
            ActionChains(driver).send_keys(Keys.ENTER).perform()
        time.sleep(0.3)
    except: pass

def run_automation(filepath):
    try:
        wb = load_workbook(filename=filepath, data_only=True)
        ws = wb.active
        headers = [str(cell.value).strip() if cell.value else f"Col_{i}" for i, cell in enumerate(ws[1])]
       
        df = []
        for row in ws.iter_rows(min_row=2):
            row_dict = {}
            for idx, cell in enumerate(row):
                val = cell.value
                header = headers[idx]
                header_lower = header.lower()
               
                if header_lower in ['tow', 'from', 'how', 'to']:
                    if isinstance(val, (float, int)):
                        if 0 <= val <= 1:
                            total_minutes = int(round(val * 24 * 60))
                            hh, mm = divmod(total_minutes, 60)
                            if hh == 24: hh = 0
                            val = f"{hh:02d}:{mm:02d}"
                        else:
                            s = f"{val:.2f}".replace(".", "") if isinstance(val, float) else str(val)
                            s = s[:4].zfill(4)
                            val = f"{s[:2]}:{s[2:]}"
                    elif isinstance(val, (datetime.time, datetime.datetime)):
                        val = val.strftime('%H:%M')
                    elif val:
                        s = str(val).replace(":", "").replace(".", "").strip()
                        s = s[:4].zfill(4)
                        val = f"{s[:2]}:{s[2:]}"
                    else: val = ""
                       
                elif 'date' in header_lower:
                    if isinstance(val, datetime.datetime):
                        val = val.strftime('%d-%m-%Y')
                    elif isinstance(val, str) and val.strip():
                        tmp_val = val.strip().replace(" ", "-").replace("/", "-")
                        parsed_success = False
                        for fmt in ("%d-%b-%y", "%d-%b-%Y", "%d-%m-%y", "%d-%m-%Y", "%Y-%m-%d"):
                            try:
                                val = datetime.datetime.strptime(tmp_val, fmt).strftime('%d-%m-%Y')
                                parsed_success = True
                                break
                            except ValueError: pass
                        if not parsed_success: val = str(val).strip()
                    else: val = str(val).strip() if val else ""
               
                elif isinstance(val, datetime.datetime): val = str(val)
                elif val is None: val = ""
                else: val = str(val).strip()
                   
                row_dict[header] = val
            if any(row_dict.values()): df.append(row_dict)

        # ---------------------------------------------------------
        # CLOUD HEADLESS CHROME CONFIGURATION
        # ---------------------------------------------------------
        chrome_options = webdriver.ChromeOptions()
        chrome_options.binary_location = "/usr/bin/google-chrome" # CRITICAL FOR RENDER
        chrome_options.add_argument('--headless=new')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
       
        # Native Selenium 4 will automatically find the correct Chrome driver
        driver = webdriver.Chrome(options=chrome_options)
       
        # ---------------------------------------------------------
        # CLOUD AUTO-LOGIN
        # ---------------------------------------------------------
        driver.get("https://iamatc.aai.aero/login")
        time.sleep(3)
       
        try:
            # 1. Type Username (Using the exact XPath from your screenshot)
            driver.find_element(By.XPATH, '//*[@id="user_id"]').send_keys("tapask")
            time.sleep(0.5)
           
            # 2. Type Password
            # Note: I am assuming the ID is "password". If it fails, update this XPath!
            driver.find_element(By.XPATH, '//*[@id="password"]').send_keys("Kunmunprem21@")
            time.sleep(0.5)
           
            # 3. Click Login
            # Note: I am assuming the button text is "Login". If it fails, update this XPath!
            driver.find_element(By.XPATH, '//button[contains(translate(., "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "login")]').click()
            time.sleep(5)
           
        except Exception as e:
            return f"Auto-Login Failed. Check your Password/Button XPaths! Error: {str(e)}"
           
        driver.get(DUTY_ENTRY_URL)
        time.sleep(3)
       
        current_locked_date = None
        for index, row in enumerate(df):
            try:
                dismiss_popups(driver)
                target_date = str(row.get('Date', '')).strip()
               
                if target_date != current_locked_date:
                    try:
                        change_btn_xpath = "//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'change date')] | //button[contains(., 'Change Date')]"
                        change_btns = driver.find_elements(By.XPATH, change_btn_xpath)
                        for btn in change_btns:
                            if btn.is_displayed():
                                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                                time.sleep(0.1)
                                driver.execute_script("arguments[0].click();", btn)
                                time.sleep(1.2)
                                break
                    except: pass
                       
                    dismiss_popups(driver)
                    smart_type(driver, ["//input[@type='date']", "//input[contains(@placeholder, 'Date')]"], target_date)
                    time.sleep(0.3)
                   
                    clicked = wait_and_click(driver, "//button[contains(., 'Set & Begin Duty Log')] | //button[contains(., 'Set & Begin')]")
                    if not clicked:
                        try:
                            btn = driver.find_element(By.XPATH, "//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'set & begin')]")
                            driver.execute_script("arguments[0].click();", btn)
                        except: pass
                       
                    time.sleep(2.5)
                    dismiss_popups(driver)
                    current_locked_date = target_date

                position_type = str(row.get('Position', '')).lower()
                if 'pract' in position_type or 'ojt' in position_type or 'trn' in position_type or 'theory' in position_type:
                    duty_radio_xpath = "//label[contains(., 'Training')]/input | //label[contains(., 'Training')]"
                    is_training = True
                elif 'controlling' in position_type or 'con' in position_type:
                    duty_radio_xpath = "//label[contains(., 'Control')]/input | //label[contains(., 'Control')]"
                    is_training = False
                else:
                    duty_radio_xpath = "//label[contains(., 'Other')]/input | //label[contains(., 'Other')]"
                    is_training = False
                   
                wait_and_click(driver, duty_radio_xpath)
                time.sleep(1.0)

                unit_val = str(row.get('Unit', ''))
                handle_react_select(driver, "OPERATIONAL UNIT", "- Select Unit -", unit_val)
               
                start_time = row.get('TOW', row.get('From', ''))
                end_time = row.get('HOW', row.get('To', ''))
               
                smart_type(driver, ["//label[contains(., 'FROM (UTC)')]/parent::*//input", "(//input[contains(@placeholder, 'HH:MM')])[1]"], start_time)
                smart_type(driver, ["//label[contains(., 'TO (UTC)')]/parent::*//input", "(//input[contains(@placeholder, 'HH:MM')])[2]"], end_time)
               
                if is_training:
                    ojti_name = str(row.get('Name', row.get('name', row.get('Instructor', row.get('OJTI', ''))))).strip()
                    if ojti_name and ojti_name.lower() != 'nan':
                        handle_react_select(driver, "INSTRUCTOR", "Select", ojti_name)

                wait_and_click(driver, "//button[contains(., '+ Add Position Entry') or contains(., 'Add Position')]")
                time.sleep(2.5)
                dismiss_popups(driver)
   
            except Exception as e:
                driver.refresh()
                time.sleep(3)
                current_locked_date = None
               
        driver.quit()
        return "Automation Cycle Finished Successfully!"
       
    except Exception as e:
        return f"Automation Failed: {str(e)}\n{traceback.format_exc()}"

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>ATC Cloud Bot</title>
    <style>
        body { font-family: Arial, sans-serif; background-color: #f4f4f9; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
        .container { background: white; padding: 40px; border-radius: 10px; box-shadow: 0 4px 8px rgba(0,0,0,0.1); text-align: center; }
        input[type=file] { margin: 20px 0; }
        button { background-color: #4CAF50; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; font-size: 16px; }
        button:hover { background-color: #45a049; }
    </style>
</head>
<body>
    <div class="container">
        <h2>ATC Cloud Automation Engine</h2>
        <p>Upload your Excel logbook to begin remote processing.</p>
        <form action="/upload" method="post" enctype="multipart/form-data">
            <input type="file" name="file" accept=".xlsx, .xls" required>
            <br>
            <button type="submit">Start Cloud Automation</button>
        </form>
    </div>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return "No file part in the request.", 400
    file = request.files['file']
    if file.filename == '':
        return "No selected file.", 400
    if file:
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        result = run_automation(filepath)
        os.remove(filepath)
        return f"<h3>Status Report:</h3><pre>{result}</pre><br><a href='/'>Go Back</a>"

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
