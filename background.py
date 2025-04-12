from flask import Flask
from threading import Thread
import subprocess

app = Flask('')

@app.route('/')
def home():
    return "I'm alive"

def run():
    app.run(host='0.0.0.0', port=5000)

def start_bot():
    subprocess.Popen(["python", "main.py"])  # Запускаем main.py

def keep_alive():
    t1 = Thread(target=run)
    t2 = Thread(target=start_bot)
    t1.start()
    t2.start()

if __name__ == "__main__":
    keep_alive()
