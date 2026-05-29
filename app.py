from flask import Flask, render_template, request, redirect, session, jsonify
import requests
import os
import re
import time
from datetime import datetime
from bs4 import BeautifulSoup

app = Flask(__name__)
app.secret_key = "telecom_secure_session_key_2026"

# Base Configurations
BASE = "http://51.210.208.26/ints"
LOGIN_URL = BASE + "/login"
SIGNIN_URL = BASE + "/signin"
ACTION_BASE = BASE.replace("/ints/", "/nints/")

# Endpoints
RANGES_URL = BASE + "/client/res/aj_smsranges.php"
NUMBERS_URL = BASE + "/client/res/data_smsnumbers.php"
DASHBOARD_URL = BASE + "/client/SMSDashboard"
CLIENT_CDR_URL = BASE + "/client/res/data_smscdr.php"
CLIENT_CDR_PAGE = BASE + "/client/SMSCDRStats"

AGENT_BULK_URL = BASE + "/agent/SMSBulkAllocations"
AGENT_DATA_RANGES = BASE + "/agent/res/data_smsranges.php"
AGENT_REQUEST_URL = ACTION_BASE + "/agent/res/requestsmsnumberfinal.php"

AGENT_USERNAME = "Ashok20"
AGENT_PASSWORD = "aura20"

# ---------------- HELPER UTILITIES ----------------

def clean_html(text):
    if not text:
        return ""
    cleaned = BeautifulSoup(str(text), "html.parser").get_text().strip()
    cleaned = re.sub(r'<[^>]*>', '', cleaned)
    return cleaned

def solve_captcha(session_obj, url):
    try:
        response = session_obj.get(url)
        match = re.search(r"What is\s+(\d+)\s*\+\s*(\d+)", response.text)
        if match:
            return int(match.group(1)) + int(match.group(2))
    except Exception as e:
        print(f"[-] Captcha parse error: {e}")
    return None

def extract_real_numeric_id(row_data):
    if not isinstance(row_data, (list, tuple)):
        return None
    patterns = [
        r'info=["\'](\d+)["\']',
        r'rid=["\'](\d+)["\']',
        r'id=["\']\w*?_?(\d+)["\']',
        r'value=["\'](\d+)["\']',
        r'href=.*?[=\((](\d+)[ \)/"\']'
    ]
    for cell in row_data:
        cell_str = str(cell)
        for pattern in patterns:
            match = re.search(pattern, cell_str, re.IGNORECASE)
            if match:
                return match.group(1)
    return None

def restore_client_session():
    cookies = session.get("remote_cookies")
    if not cookies:
        return None
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "en-US,en;q=0.9"
    })
    s.cookies.update(cookies)
    return s

def get_agent_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "en-US,en;q=0.9"
    })
    captcha = solve_captcha(s, LOGIN_URL)
    if captcha is None:
        return None
    payload = {"username": AGENT_USERNAME, "password": AGENT_PASSWORD, "capt": str(captcha)}
    resp = s.post(SIGNIN_URL, data=payload, headers={"Origin": "http://51.210.208.26", "Referer": LOGIN_URL}, allow_redirects=True)
    if "/agent/" not in resp.url:
        return None
    return s

# ---------------- CORE ROUTES ----------------

@app.route("/")
def home():
    if session.get("logged_in") and restore_client_session():
        return redirect("/dashboard")
    session.clear()
    return render_template("login.html")

@app.route("/login", methods=["POST"])
def login():
    username = request.form.get("username")
    password = request.form.get("password")
    
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.9"})
    captcha = solve_captcha(s, LOGIN_URL)
    
    if captcha is None:
        return render_template("login.html", error="Verification math puzzle parsing error.")
        
    payload = {"username": username, "password": password, "capt": str(captcha)}
    resp = s.post(SIGNIN_URL, data=payload, headers={"Origin": "http://51.210.208.26", "Referer": LOGIN_URL}, allow_redirects=True)
    
    if "/client/" not in resp.url:
        return render_template("login.html", error="Client credentials rejected.")
        
    session["logged_in"] = True
    session["username"] = username
    session["remote_cookies"] = requests.utils.dict_from_cookiejar(s.cookies)
    return redirect("/dashboard")

@app.route("/dashboard")
def dashboard():
    if not session.get("logged_in"): return redirect("/")
    client_session = restore_client_session()
    
    stats = {"today": "0", "last7": "0", "last30": "0"}
    if client_session:
        try:
            r = client_session.get(DASHBOARD_URL)
            today = re.search(r"Today SMS.*?(\d+)", r.text, re.S)
            last7 = re.search(r"Last 7 Day SMS.*?(\d+)", r.text, re.S)
            last30 = re.search(r"Last 30 Day SMS.*?(\d+)", r.text, re.S)
            stats = {
                "today": today.group(1) if today else "0",
                "last7": last7.group(1) if last7 else "0",
                "last30": last30.group(1) if last30 else "0"
            }
        except:
            pass
            
    return render_template("dashboard_home.html", username=session.get("username"), stats=stats)

@app.route("/my-numbers")
def my_numbers():
    if not session.get("logged_in"): return redirect("/")
    return render_template("dashboard.html", username=session.get("username"))

@app.route("/api/numbers")
def api_numbers():
    client_session = restore_client_session()
    if not client_session: return jsonify({"error": "Unauthorized"}), 401
    
    clean_rows = []
    try:
        r = client_session.get(RANGES_URL, params={"max": 100, "page": 1}, headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"})
        ranges = r.json().get("results", [])
        
        for rng in ranges:
            rid = rng.get("id")
            range_label = rng.get("text", f"Range {rid}")
            if not rid: continue
            
            params = {"frange": rid, "fclient": "", "sEcho": "1", "iColumns": "6", "iDisplayStart": "0", "iDisplayLength": "100", "_": str(int(time.time() * 1000))}
            num_resp = client_session.get(NUMBERS_URL, params=params, headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"})
            raw_data = num_resp.json().get("aaData", [])
            
            for row in raw_data:
                # Discard non-list structures and config items
                if not isinstance(row, list) or len(row) < 3:
                    continue
                
                first_cell = str(row[0])
                if 'sEcho' in first_cell or 'iTotalRecords' in first_cell or '{' in first_cell:
                    continue
                
                # Append the targeted range context string as part of the pipeline parameters
                row.append(range_label)
                clean_rows.append(row)
    except Exception as e:
        print(f"Fetch numbers error: {e}")
        
    return jsonify({"aaData": clean_rows})

@app.route("/allocate")
def allocate_page():
    if not session.get("logged_in"): return redirect("/")
    agent_session = get_agent_session()
    processed_list = []
    
    if agent_session:
        agent_session.get(BASE + "/agent/SMSRanges")
        params = {'sEcho': '1', 'iColumns': '10', 'iDisplayStart': '0', 'iDisplayLength': '-1'}
        r = agent_session.get(AGENT_DATA_RANGES, params=params, headers={"X-Requested-With": "XMLHttpRequest"})
        raw_table_rows = r.json().get("aaData", [])
        
        for index, row in enumerate(raw_table_rows):
            if not isinstance(row, list) or len(row) == 0:
                continue
            if 'sEcho' in str(row[0]) or '{' in str(row[0]):
                continue
                
            real_numeric_id = extract_real_numeric_id(row)
            name_string = clean_html(row[0])
            route_string = clean_html(row[1]) if len(row) > 1 else ""
            display_label = name_string if name_string else route_string
            if not real_numeric_id: real_numeric_id = f"NOT_FOUND_{index}"
            
            processed_list.append({
                "db_id": real_numeric_id,
                "label": display_label
            })
            
    return render_template("allocate.html", username=session.get("username"), ranges=processed_list)

@app.route("/api/allocate", methods=["POST"])
def api_allocate():
    if not session.get("logged_in"): return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    chosen_rid = request.json.get("rid")
    qty_requested = request.json.get("qty")
    username = session.get("username")
    
    agent_session = get_agent_session()
    if not agent_session: return jsonify({"success": False, "message": "System Agent session failed"})
    
    client_id = None
    try:
        r = agent_session.get(AGENT_BULK_URL)
        soup = BeautifulSoup(r.text, "html.parser")
        for opt in soup.select("#xclient option[value]"):
            if opt.get_text(strip=True).lower() == username.lower():
                client_id = opt["value"]
                break
    except:
        pass
        
    if not client_id: return jsonify({"success": False, "message": "Database mapping lookup error"})
    
    payload = {"action": "allocate", "ntype": "-2", "range[]": str(chosen_rid), "client[]": str(client_id), "payterm": "1", "payout": "0", "qty": str(qty_requested)}
    r = agent_session.post(AGENT_BULK_URL, data=payload, headers={"Referer": AGENT_BULK_URL}, allow_redirects=True)
    
    if "allocated" in r.text.lower():
        return jsonify({"success": True, "message": "Direct Allocation Successful!"})
        
    request_payload = {"rid": str(chosen_rid), "payterm": "2", "qty": str(qty_requested)}
    request_headers = {"Origin": "http://51.210.208.26", "Referer": ACTION_BASE + "agent/SMSRanges", "X-Requested-With": "XMLHttpRequest"}
    agent_session.post(AGENT_REQUEST_URL, data=request_payload, headers=request_headers)
    
    retry = agent_session.post(AGENT_BULK_URL, data=payload, headers={"Referer": AGENT_BULK_URL}, allow_redirects=True)
    if "allocated" in retry.text.lower():
        return jsonify({"success": True, "message": "Allocation successfully claimed via secondary routing line!"})
        
    return jsonify({"success": False, "message": "All pipeline allocation instances returned standard execution failures"})

@app.route("/report", methods=["GET", "POST"])
def report():
    if not session.get("logged_in"): return redirect("/")
    client_session = restore_client_session()
    
    records = []
    target_date = request.form.get("date", datetime.today().strftime('%Y-%m-%d'))
    
    if request.method == "POST" and client_session:
        client_session.get(CLIENT_CDR_PAGE)
        params = {
            "fdate1": f"{target_date} 00:00:00", "fdate2": f"{target_date} 23:59:59",
            "frange": "", "fnum": "", "fcli": "", "fgdate": "", "fgmonth": "",
            "fgrange": "", "fgnumber": "", "fgcli": "", "fg": "0", "sEcho": "2",
            "iColumns": "7", "sColumns": ",,,,,,,", "iDisplayStart": "0", "iDisplayLength": "-1",
            "sSearch": "", "bRegex": "false", "iSortCol_0": "0", "sSortDir_0": "desc", "iSortingCols": "1",
            "_": str(int(time.time() * 1000))
        }
        for i in range(7): 
            params[f"mDataProp_{i}"] = str(i)
            params[f"bRegex_{i}"] = "false"
            params[f"bSearchable_{i}"] = "true"
            params[f"bSortable_{i}"] = "true"
            
        try:
            res = client_session.get(CLIENT_CDR_URL, params=params, headers={"X-Requested-With": "XMLHttpRequest", "Referer": CLIENT_CDR_PAGE})
            raw_records = res.json().get("aaData", [])
            for row in raw_records:
                if isinstance(row, list) and len(row) > 0:
                    if 'sEcho' in str(row[0]) or '{' in str(row[0]):
                        continue
                    records.append([clean_html(cell) for cell in row])
        except Exception as e:
            print(f"CDR processing fault: {e}")
            
    return render_template("report.html", username=session.get("username"), records=records, target_date=target_date)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
