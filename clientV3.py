import time, uuid, atexit, socket, binascii, os, json
from multiprocessing.managers import BaseManager
from threading import Thread
from pathlib import Path
from flask import Flask, render_template, jsonify, request
from queue import Empty
from collections import deque

import hashlib
import pyrx # Import the pyrx library
import kawpow # Import the kawpow library
from job import Job # Import the Job class
import logging

# --- Flask App Definition ---
app = Flask(__name__, template_folder=str(Path(__file__).parent/'templates'), static_folder=str(Path(__file__).parent/'static'))

# Silence Flask's default GET/POST logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

CLIENT_DATA_FILE = os.path.join(str(Path(__file__).parents[1]), '_data', 'client_data_v2.json')

class Client:
    def __init__(self, host='127.0.0.1', port=8625, authkey=b'769ac424-adb6-5a73-83b0-d22eb27e543b'):
        self.host, self.port, self.authkey = host, port, authkey
        self.q, self.res_q = None, None
        self.id = str(uuid.uuid4())
        self.manager = None
        self.client_thread = None
        self.load_data()
        self.load_config()

        # Stats
        self.connected = False
        self.current_job_id = "N/A"
        self.current_job_data = "{}" # New: Store raw job JSON
        self.current_nonce = 0
        self.last_nonce_check = 0
        self.hashrate = 0.0
        self.last_event = "Ready to connect"
        self.finished_shares = deque(maxlen=20)
        self.console_log = deque(maxlen=50) # New: For detailed logging

    def log_event(self, message):
        """Adds a message to the console log and updates the last event."""
        timestamp = time.strftime("%H:%M:%S")
        self.console_log.appendleft({"time": timestamp, "msg": message})
        self.last_event = message

    def load_config(self):
        """Loads the algorithm preference from the config file."""
        self.algo_preference = 'both' # Default to mining both
        config_file = "client_config.json"
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r') as f:
                    config_data = json.load(f)
                    pref = config_data.get("algorithm_preference", "both").lower()
                    if pref in ['randomx', 'kawpow', 'both']:
                        self.algo_preference = pref
            except Exception:
                pass # Ignore errors and use default
        self.last_event = f"Configured to mine: {self.algo_preference.upper()}"

    def load_data(self):
        if os.path.exists(CLIENT_DATA_FILE):
            with open(CLIENT_DATA_FILE, 'r') as f: data = json.load(f)
            self.wallet_address = data.get('wallet_address', '')
        else: self.wallet_address = ''

    def save_data(self):
        os.makedirs(os.path.dirname(CLIENT_DATA_FILE), exist_ok=True)
        with open(CLIENT_DATA_FILE, 'w') as f: json.dump({'wallet_address': self.wallet_address}, f)

    def connect(self):
        self.manager = BaseManager(address=(self.host, self.port), authkey=self.authkey)
        self.manager.register('get_queue'); self.manager.register('result_queue'); self.manager.register('get_clients')
        self.last_event = "Connecting..."
        try:
            self.manager.connect()
            self.q, self.res_q = self.manager.get_queue(), self.manager.result_queue()

            # Register with the shared client list
            client_list = self.manager.get_clients()
            client_list.append(self.id)

            self.register()
            self.connected = True
            self.last_event = "Connected to server"
            if self.client_thread is None or not self.client_thread.is_alive():
                self.client_thread = Thread(target=self.run, daemon=True)
                self.client_thread.start()
        except Exception as e:
            self.manager = None; self.connected = False
            self.last_event = f"Connection Failed: {e}"

    def register(self):
        msg = {'lodging':True, 'client_id':self.id, 'client_node':[self.id, socket.gethostname()]}
        self.res_q.put(msg)

    def disconnect(self):
        if self.manager and self.connected:
            try: self.res_q.put({'type':'disconnect','client_id':self.id})
            except: pass
        self.connected = False
        self.last_event = "Disconnected"
        self.current_job_id = "N/A"; self.hashrate = 0.0

    def mine(self, job_data: dict):
        try:
            job = Job()
            job.set_id(job_data.get('job_id', ''))
            job.set_blob(job_data.get('blob', ''))
            job.set_target(job_data.get('target', ''))
            job.set_height(job_data.get('height', 0))
            job.set_seed_hash(job_data.get('seed_hash', ''))
            job.set_algo(job_data.get('algo', ''))

            if not job.is_valid():
                self.log_event("Error: Received invalid job from server")
                return None, None

            self.current_job_id = job.id
            blob_bytes = binascii.unhexlify(job.blob)
            target = job.target
            nonce_offset = job.get_nonce_offset()
            nonce_size = job.get_nonce_size()
            
            nonce = 0
            
            if job.algo == 'kawpow':
                self.log_event(f"Starting KawPow hashing for job {job.id[:8]}...")
                header_hash = blob_bytes
                while self.connected:
                    # Corrected call to the kawpow library using positional arguments
                    result = kawpow.hash(header_hash, job.height, nonce)
                    hash_output = result['result']
                    
                    if int.from_bytes(hash_output, 'big') < target:
                        self.log_event(f"Share found! Nonce: {nonce}")
                        mix_hash = result['mix_hash']
                        return nonce.to_bytes(8, 'big').hex(), binascii.hexlify(mix_hash).decode()
                    nonce += 1
                    self.current_nonce = nonce

            elif job.algo and 'rx' in job.algo:
                self.log_event(f"Initializing RandomX VM for job {job.id[:8]}...")
                seed_hash_bytes = binascii.unhexlify(job.seed_hash)
                rx_vm = pyrx.RandomxVM(seed_hash_bytes)
                self.log_event("RandomX VM initialized. Starting hashing...")

                while self.connected:
                    mining_blob = bytearray(blob_bytes)
                    nonce_bytes = nonce.to_bytes(nonce_size, 'little')
                    mining_blob[nonce_offset : nonce_offset + nonce_size] = nonce_bytes
                    
                    hash_output = rx_vm.get_hash(mining_blob)
                    
                    if int.from_bytes(hash_output, 'big') < target:
                        self.log_event(f"Share found! Nonce: {nonce}")
                        return nonce_bytes.hex(), binascii.hexlify(hash_output).decode()
                    nonce += 1
                    self.current_nonce = nonce
            else:
                self.log_event(f"Error: Unsupported algorithm '{job.algo}'")
                return None, None
        except Exception as e:
            self.log_event(f"FATAL MINING ERROR: {e}")
            return None, None

        return None, None

    def heartbeat(self):
        while self.connected:
            time.sleep(3)
            try:
                nonce_diff = self.current_nonce - self.last_nonce_check
                self.hashrate = nonce_diff / 3.0
                self.last_nonce_check = self.current_nonce
                if self.connected:
                    self.res_q.put({'type': 'heartbeat', 'client_id': self.id, 'hashrate': self.hashrate})
            except (IOError, EOFError, ConnectionResetError): 
                self.log_event("Heartbeat failed: Connection lost.")
                self.disconnect(); 
                break

    def run(self):
        atexit.register(self.disconnect)
        heartbeat_thread = Thread(target=self.heartbeat, daemon=True)
        heartbeat_thread.start()
        
        while self.connected:
            try:
                self.log_event("Requesting new job from server...")
                job_data = self.q.get(timeout=60)
                self.current_job_data = json.dumps(job_data, indent=4)
                self.log_event(f"Job {job_data.get('job_id', 'N/A')[:8]}... received.")

                job_algo = job_data.get('algo', '')
                if self.algo_preference == 'randomx' and 'rx' not in job_algo:
                    self.log_event(f"Ignoring {job_algo.upper()} job (Set to RandomX only)")
                    continue
                elif self.algo_preference == 'kawpow' and 'kawpow' not in job_algo:
                    self.log_event(f"Ignoring {job_algo.upper()} job (Set to KawPow only)")
                    continue
                
                nonce, final_hash = self.mine(job_data)
                
                if nonce is not None and self.connected:
                    res = {'result':True,'client_id':self.id,'job_id':job_data['job_id'],'nonce':nonce,'hash':final_hash}
                    self.res_q.put(res)
                    self.log_event(f"Submitted share for job {job_data['job_id'][:8]}.")
                    self.finished_shares.appendleft({"id": job_data['job_id'], "hash": final_hash[:12]})
                
            except Empty: 
                self.log_event("No job received from server. Retrying..."); 
                continue
            except (IOError, EOFError, ConnectionResetError): 
                self.log_event("Connection to server lost.")
                self.disconnect()
            except Exception as e: 
                self.log_event(f"An error occurred in the main loop: {e}")
                time.sleep(5) # Wait before retrying after a general error

# --- Global Client & Web Routes ---
client = Client()

@app.route('/')
def index():
    stats = {
        "client_id": client.id, "server_host": client.host, "server_port": client.port,
        "connected": client.connected, "job_id": client.current_job_id, "hashrate": client.hashrate,
        "last_event": client.last_event,
        "raw_job": client.current_job_data
    }
    return render_template('client_v3.html', stats=stats, wallet_address=client.wallet_address, finished_shares=list(client.finished_shares), console_log=list(client.console_log))

@app.route('/connect', methods=['POST'])
def connect_client():
    if not client.connected: client.connect()
    return jsonify({"status": "ok"})

@app.route('/disconnect', methods=['POST'])
def disconnect_client():
    if client.connected: client.disconnect()
    return jsonify({"status": "ok"})

@app.route('/save_wallet', methods=['POST'])
def save_wallet_route():
    client.wallet_address = request.json.get('wallet_address', '')
    client.save_data()
    return jsonify({"status": "ok"})

def find_free_port(start_port=8081):
    port = start_port
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('localhost', port)) != 0: return port
            port += 1

if __name__ == '__main__':
    port = find_free_port()
    print(f"Starting client dashboard on http://127.0.0.1:{port}")
    app.run(host='0.0.0.0', port=port, debug=False)
