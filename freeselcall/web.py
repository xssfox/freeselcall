import threading
from flask import Flask, render_template
from flask_socketio import SocketIO, emit, send
import logging
from flask import request, abort, make_response, send_file, redirect
from .modem import CallCategories
app = Flask(__name__)
socketio = SocketIO(app)

class Server():
    def __init__(self, host, port, tx_func, id):
        global tx # there's probably a nicer way to do this in flask
        tx = tx_func
        self.port = port
        self.host = host
        self.id = id
        global server 
        server = self
    def start(self):
        logging.debug("Starting Flask")

        server = threading.Thread(target=socketio.run, args=[app], kwargs={"port": self.port, "host": self.host})
        server.setDaemon(True)
        server.start()
        logging.debug("Flask started")
    
    def rx(self, data):
        with app.app_context():
            logging.debug(f"Send websocket alert {data}")
            emit("selcall",data,json=True, broadcast=True, namespace="/freeselcall")
            logging.debug(f"Sent websocket")
    def send_log(self, data):
        with app.app_context():
            logging.debug(f"Send websocket alert {data}")
            emit("sending",data,json=True, broadcast=True, namespace="/freeselcall")
            logging.debug(f"Sent websocket")
    def preamble(self, data):
        with app.app_context():
            logging.debug(f"Send websocket preable {data}")
            emit("preamble",data,json=True, broadcast=True, namespace="/freeselcall")
            logging.debug(f"Sent websocket")

@socketio.on("client_connected", namespace="/freeselcall")
def on_connect(a):
    logging.debug(a)

@app.route("/")
def default():
    return redirect("/static/index.html")

@app.route("/selcall",methods=["POST"])
def selcall():
    if 'id' not in request.form:
        abort(401)
    try:
        id = int(request.form['id'])
        if id < 0 or id > 9999:
            abort(401)
    except:
        abort(401)
    
    logging.debug(f"Web Selcall request {id}")
    tx(id, CallCategories[request.form['category'] if 'category' in request.form else 'RTN'])
    return "Calling"

@socketio.on("selcall", namespace="/freeselcall")
def ws_selcall(args):
    try:
        id = int(args['id'])
        if id < 0 or id > 9999:
            logging.warning(f"Invalid Selcall id in call from websockets {id}")
            emit("error", {"message": "Incorrect selcall id"})
            return
    except:
        logging.warning(f"Invalid Selcall id in call from websockets {args}")
        emit("error", {"message": "Incorrect selcall id"})
        return
    tx(id, CallCategories[args['category'] if 'category' in args else 'RTN'])
    logging.info(f"websocket selcall {id}")

@socketio.on("chantest", namespace="/freeselcall")
def ws_chantest(args):
    try:
        id = int(args['id'])
        if id < 0 or id > 9999:
            logging.warning(f"Invalid Selcall id in call from websockets {id}")
            emit("error", {"message": "Incorrect selcall id"})
            return
    except:
        logging.warning(f"Invalid Selcall id in call from websockets {args}")
        emit("error", {"message": "Incorrect selcall id"})
        return
    tx(id, CallCategories[args['category'] if 'category' in args else 'RTN'], True)
    logging.info(f"websocket chantest {id}")

@socketio.on("page", namespace="/freeselcall")
def ws_page(args):
    try:
        id = int(args['id'])
        if id < 0 or id > 9999:
            logging.warning(f"Invalid Selcall id in call from websockets {id}")
            emit("error", {"message": "Incorrect selcall id"})
            return
    except:
        logging.warning(f"Invalid Selcall id in call from websockets {args}")
        emit("error", {"message": "Incorrect selcall id"})
        return
    tx(id, CallCategories[args['category'] if 'category' in args else 'RTN'], True, page=args['page'])
    logging.info(f"websocket page {id}")

@socketio.on("info", namespace="/freeselcall")
def ws_info(args):
    emit("info", {"id": server.id}, json=True, namespace="/freeselcall")