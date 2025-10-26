from flask import Flask
from flask_socketio import SocketIO

api = Flask(__name__)
socketio = SocketIO(api, cors_allowed_origins="*")