from flask import Flask, render_template, request, redirect, url_for, session
from flask_socketio import SocketIO, join_room, leave_room, emit
import os
import time
import threading

app = Flask(__name__)
app.secret_key = "feyzchat_secret"
socketio = SocketIO(app)

# Bellekte mesajları saklayalım
messages = {}  # {"oda_adi": [{"username": "", "msg": "", "time": ...}, ...]}

# 5 günde bir mesajları temizle
def clear_messages():
    while True:
        time.sleep(5 * 24 * 60 * 60)  # 5 gün
        messages.clear()
        print("✅ Eski mesajlar temizlendi.")

threading.Thread(target=clear_messages, daemon=True).start()

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        username = request.form["username"]
        room = request.form["room"]
        mode = request.form.get("mode", "modern")
        session["username"] = username
        session["room"] = room
        session["mode"] = mode
        return redirect(url_for("chat"))
    return render_template("index.html")

@app.route("/chat")
def chat():
    if "username" in session and "room" in session:
        if session["mode"] == "nokia":
            return render_template("chat_nokia.html", username=session["username"], room=session["room"])
        return render_template("chat.html", username=session["username"], room=session["room"])
    return redirect(url_for("index"))

@socketio.on("join")
def handle_join(data):
    username = data["username"]
    room = data["room"]
    join_room(room)
    if room not in messages:
        messages[room] = []
    emit("status", {"msg": f"🔔 {username} odaya katıldı"}, room=room)

    # Son 20 mesajı gönder
    last_msgs = messages[room][-20:]
    for m in last_msgs:
        emit("message", m)

@socketio.on("leave")
def handle_leave(data):
    username = data["username"]
    room = data["room"]
    leave_room(room)
    emit("status", {"msg": f"👋 {username} odadan ayrıldı"}, room=room)

@socketio.on("text")
def handle_text(data):
    room = session["room"]
    msg = {"username": session["username"], "msg": data["msg"]}
    if room not in messages:
        messages[room] = []
    messages[room].append(msg)
    if len(messages[room]) > 1000:  # gereksiz şişmesin
        messages[room] = messages[room][-1000:]
    emit("message", msg, room=room)

@socketio.on("typing")
def handle_typing(data):
    emit("typing", {"username": session["username"]}, room=session["room"], include_self=False)

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))