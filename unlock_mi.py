import os
import sys
import time
import json
import hashlib
import random
import statistics
import socket
import requests
import urllib3
import pytz
import ntplib
from datetime import datetime, timedelta, timezone

# Constants
NTP_SERVERS = [
    "ntp0.ntp-servers.net", "ntp1.ntp-servers.net", "ntp2.ntp-servers.net",
    "ntp3.ntp-servers.net", "ntp4.ntp-servers.net", "ntp5.ntp-servers.net",
    "ntp6.ntp-servers.net"
]

MI_SERVERS = ['sgp-api.buy.mi.com', '20.157.18.26']

COOKIE_VALUE = os.getenv("COOKIE_VALUE")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
THREAD_ID = os.getenv("TELEGRAM_TOPIC_ID")

class HTTP11Session:
    def __init__(self):
        self.http = urllib3.PoolManager(
            maxsize=10,
            retries=True,
            timeout=urllib3.Timeout(connect=1.0, read=4.0)
        )

    def make_request(self, method, url, headers=None, body=None):
        try:
            request_headers = headers or {}
            request_headers['Content-Type'] = 'application/json; charset=utf-8'
            if method == 'POST':
                body = body or '{"is_retry":true}'.encode('utf-8')
                request_headers['Content-Length'] = str(len(body))
                request_headers.update({
                    'Accept-Encoding': 'gzip, deflate, br',
                    'User -Agent': 'okhttp/4.12.0',
                    'Connection': 'keep-alive'
                })
            response = self.http.request(method, url, headers=request_headers, body=body, preload_content=False)
            return response
        except Exception as e:
            print(f"[Network error] {e}")
            return None

def debug_ping(host, port=80):
    try:
        start_time = time.time()
        with socket.create_connection((host, port), timeout=2):
            return (time.time() - start_time) * 1000  # Convert to ms
    except Exception:
        return None

def get_average_ping():
    all_pings = []
    print("Starting ping calculation...")

    for server in MI_SERVERS:
        pings = [debug_ping(server) for _ in range(3)]
        pings = [p for p in pings if p is not None]
        if pings:
            all_pings.append(statistics.mean(pings))
        else:
            print(f"\nFailed to get ping to server {server}")

    if not all_pings:
        print("\nFailed to get ping to any server! Using default value: 300 ms")
        return 300

    avg_ping = statistics.mean(all_pings)
    print(f"Average ping: {avg_ping:.2f} ms")
    return avg_ping

def generate_device_id():
    random_data = f"{random.random()}-{time.time()}"
    device_id = hashlib.sha1(random_data.encode('utf-8')).hexdigest().upper()
    print(f"Generated deviceId: {device_id}")
    return device_id

def get_initial_beijing_time():
    client = ntplib.NTPClient()
    beijing_tz = pytz.timezone("Asia/Shanghai")
    for server in NTP_SERVERS:
        try:
            print(f"Attempting to connect to NTP server: {server}")
            response = client.request(server, version=3)
            ntp_time = datetime.fromtimestamp(response.tx_time, timezone.utc)
            beijing_time = ntp_time.astimezone(beijing_tz)
            print(f"Beijing time received from server {server}: {beijing_time.strftime('%Y-%m-%d %H:%M:%S.%f')}")
            return beijing_time
        except Exception as e:
            print(f"Failed to connect to {server}: {e}")
    print("Failed to connect to any NTP server.")
    return None

def get_synchronized_beijing_time(start_beijing_time, start_timestamp):
    elapsed = time.time() - start_timestamp
    return start_beijing_time + timedelta(seconds=elapsed)

def wait_until_target_time(start_beijing_time, start_timestamp, ping_delay):
    next_day = start_beijing_time + timedelta(days=1)
    total_delay = (ping_delay / 2 - 30) / 1000.0
    target_time = next_day.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(seconds=total_delay)

    print(f"Waiting until {target_time.strftime('%Y-%m-%d %H:%M:%S.%f')} (Considering approximately calculated network delay).")
    
    while True:
        current_time = get_synchronized_beijing_time(start_beijing_time, start_timestamp)
        time_diff = target_time - current_time
        
        if time_diff.total_seconds() > 1:
            time.sleep(min(1.0, time_diff.total_seconds() - 1))
        elif current_time >= target_time:
            print(f"Time reached: {current_time.strftime('%Y-%m-%d %H:%M:%S.%f')}. Starting to send requests...")
            break
        else:
            time.sleep(0.0001)

def telegram(message, chat_id=CHAT_ID, thread_id=THREAD_ID):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }
    if thread_id:
        data["message_thread_id"] = thread_id
    requests.post(url, json=data)

def check_unlock_status(session, cookie_value, device_id):
    try:
        url = "https://sgp-api.buy.mi.com/bbs/api/global/user/bl-switch/state"
        headers = {
            "Cookie": f"new_bbs_serviceToken={cookie_value};versionCode=500415;versionName=5.4.15;deviceId={device_id};"
        }
        
        response = session.make_request('GET', url, headers=headers)
        if response is None:
            print("[Error] Failed to get unlock status.")
            return False

        response_data = json.loads(response.data.decode('utf-8'))
        response.release_conn()

        if response_data.get("code") == 100004:
            print("[Error] Cookie expired, needs to be updated!")
            telegram("<b>✹ Unlock Bootloader</b>\n<i>-> Cookie expired, needs to be updated!</i>")
            sys.exit(0)

        data = response_data.get("data", {})
        is_pass = data.get("is_pass")
        button_state = data.get("button_state")
        deadline_format = data.get("deadline_format", "")

        if is_pass == 4:
            if button_state == 1:
                print("[Status] Account can submit an unlock request.")
                telegram("<b>✹ Unlock Bootloader</b>\n<i>-> Account can submit an unlock request.</i>")
                return True
            elif button_state == 2:
                print(f"[Status] Account is blocked from submitting requests until {deadline_format} (Month/Day).")
                telegram(f"<b>✹ Unlock Bootloader</b>\n<i>-> Account is blocked from submitting requests until {deadline_format} (Month/Day).</i>")
                sys.exit(0)
            elif button_state == 3:
                print("[Status] Account is less than 30 days old.")
                telegram("<b>✹ Unlock Bootloader</b>\n<i>-> Account is less than 30 days old.</i>")
                sys.exit(0)
        elif is_pass == 1:
            print(f"[Status] Request approved, unlock available until {deadline_format}.")
            telegram(f"<b>✹ Unlock Bootloader</b>\n<i>-> Request approved, unlock available until {deadline_format}.</i>")
            sys.exit(0)
        else:
            print("[Error] Unknown status.")
            sys.exit(0)
    except Exception as e:
        print(f"[Status check error] {e}")
        return False

def wait_until_ping_time(start_beijing_time, start_timestamp):
    next_day = start_beijing_time
    target_time = next_day.replace(hour=23, minute=59, second=30)
    
    print(f"Waiting until {target_time.strftime('%Y-%m-%d %H:%M:%S')} to start ping calculation.")
    
    while True:
        current_time = get_synchronized_beijing_time(start_beijing_time, start_timestamp)
        time_diff = (target_time - current_time).total_seconds()

        if time_diff <= 0:
            print(f"Time reached: {current_time.strftime('%Y-%m-%d %H:%M:%S')}. Starting ping calculation...")
            return get_average_ping()
        else:
            time.sleep(min(1, time_diff))

def main():
    cookie_value = COOKIE_VALUE
    device_id = generate_device_id()
    session = HTTP11Session()

    if check_unlock_status(session, cookie_value, device_id):
        start_beijing_time = get_initial_beijing_time()
        if start_beijing_time is None:
            print("Failed to set initial time.")
            sys.exit(0)

        start_timestamp = time.time()
        
        avg_ping = wait_until_ping_time(start_beijing_time, start_timestamp)
        
        if avg_ping is None:
            print("Using default ping: 50 ms")
            avg_ping = 50
            
        wait_until_target_time(start_beijing_time, start_timestamp, avg_ping)

        url = "https://sgp-api.buy.mi.com/bbs/api/global/apply/bl-auth"
        headers = {
            "Cookie": f"new_bbs_serviceToken={cookie_value};versionCode=500415;versionName=5.4.15;deviceId={device_id};"
        }

        try:
            while True:
                request_time = get_synchronized_beijing_time(start_beijing_time, start_timestamp)
                print(f"\n[Request] Sending request at {request_time.strftime('%Y-%m-%d %H:%M:%S.%f')} (UTC+8)")
                
                response = session.make_request('POST', url, headers=headers)
                if response is None:
                    continue

                response_time = get_synchronized_beijing_time(start_beijing_time, start_timestamp)
                print(f"[Response] Response received at {response_time.strftime('%Y-%m-%d %H:%M:%S.%f')} (UTC+8)")

                try:
                    response_data = response.data
                    response.release_conn()
                    json_response = json.loads(response_data.decode('utf-8'))
                    code = json_response.get("code")
                    data = json_response.get("data", {})

                    if code == 0:
                        apply_result = data.get("apply_result")
                        if apply_result == 1:
                            print(f"[Status] Request approved, checking status...")
                            check_unlock_status(session, cookie_value, device_id)
                        elif apply_result in [3, 4]:
                            deadline_format = data.get("deadline_format", "Not specified")
                            status_message = "not submitted, request limit reached" if apply_result == 3 else "not submitted, blocked from submitting requests"
                            print(f"[Status] Request {status_message} until {deadline_format} (Month/Day).")
                            telegram(f"<b>✹ Unlock Bootloader</b>\n<i>-> Request {status_message} until {deadline_format} (Month/Day).</i>")
                            sys.exit(0)
                    elif code in [100001, 100003]:
                        print(f"[Status] Request {'rejected' if code == 100001 else 'possibly approved, checking status...'}")
                        if code == 100003:
                            check_unlock_status(session, cookie_value, device_id)
                    else:
                        print(f"[Status] Unknown request status: {code}")
                        print(f"[Full server response]: {json_response}")

                except json.JSONDecodeError:
                    print("[Error] Failed to decode JSON response.")
                    print(f"Server response: {response_data}")
                except Exception as e:
                    print(f"[Response processing error] {e}")
                    continue

        except Exception as e:
            print(f"[Request error] {e}")
            sys.exit(0)

if __name__ == "__main__":
    main()
