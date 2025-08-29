import os
import threading
import time
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask, request, redirect, url_for, session,
    render_template_string, jsonify, send_from_directory, abort
)
from flask_socketio import SocketIO, join_room, leave_room, emit
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean
from sqlalchemy.orm import sessionmaker, declarative_base

# ------------ APP CONFIG ------------
app = Flask(__name__)
app.secret_key = "feyzchat_secret"
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25MB
app.config["UPLOAD_FOLDER"] = "uploads"

socketio = SocketIO(app, async_mode="eventlet")

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

# ------------ DB ------------
Base = declarative_base()
engine = create_engine("sqlite:///messages.db", echo=False, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)

class Room(Base):
    __tablename__ = "rooms"
    id = Column(Integer, primary_key=True)
    name = Column(String(64), unique=True, index=True)
    password = Column(String(128))  # basit tutuyoruz

class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True)
    room = Column(String(64), index=True)
    username = Column(String(64))
    type = Column(String(16), default="text")  # text,image,video,audio,file,deleted,reply
    content = Column(Text)                    # metin ya da dosya adı/url
    original_name = Column(String(255), nullable=True)
    reply_to = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    delivered = Column(Boolean, default=True)  # ✔ yerine posta simgesi için basit flag

Base.metadata.create_all(engine)

# odadaki online kullanıcılar (sadece sayım için)
ONLINE = {}  # {room: set(usernames)}

# ------------ UTIL ------------
def get_db():
    return SessionLocal()

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("username") or not session.get("room"):
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return wrapper

def sanitize_filename(name: str) -> str:
    bad = "/\\?%*:|\"<>"
    for ch in bad:
        name = name.replace(ch, "_")
    return name

# ------------ CLEANUP THREAD (5 günde bir) ------------
def cleanup_job():
    while True:
        try:
            db = get_db()
            cutoff = datetime.utcnow() - timedelta(days=5)
            db.query(Message).filter(Message.created_at < cutoff).delete()
            db.commit()
            db.close()
        except Exception as e:
            print("cleanup error:", e)
        time.sleep(24 * 3600)  # günde 1 kez kontrol yeter
threading.Thread(target=cleanup_job, daemon=True).start()

# ------------ LOAD TEMPLATES FROM FILES ------------
def load_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

INDEX_HTML = load_file("index.html")
CHAT_HTML  = load_file("chat.html")

# ------------ ROUTES ------------
@app.route("/", methods=["GET", "POST"])
def index():
    # giriş ekranı: kullanıcı adı, oda adı, şifre + mod seçimi
    if request.method == "POST":
        username = request.form.get("username","").strip()
        room = request.form.get("room","").strip()
        password = request.form.get("password","").strip()
        action = request.form.get("action","join")  # "create" or "join"
        mode = request.form.get("mode","modern")

        if not username or not room:
            return render_template_string(INDEX_HTML, error="Kullanıcı adı ve oda zorunlu", ok=None)

        db = get_db()
        r = db.query(Room).filter_by(name=room).first()

        if action == "create":
            if r:
                db.close()
                return render_template_string(INDEX_HTML, error="Bu oda zaten var", ok=None)
            r = Room(name=room, password=password)
            db.add(r); db.commit()
        else:  # join
            if not r or (r.password or "") != password:
                db.close()
                return render_template_string(INDEX_HTML, error="Oda adı/şifre hatalı", ok=None)

        db.close()
        session["username"] = username
        session["room"] = room
        session["mode"] = mode
        return redirect(url_for("chat"))

    return render_template_string(INDEX_HTML, error=None, ok=None)

@app.route("/chat")
@login_required
def chat():
    return render_template_string(
        CHAT_HTML,
        username=session["username"],
        room=session["room"],
        mode=session.get("mode","modern")
    )

# tek dizinden statik dosya servis (style.css, script.js vs.)
@app.route("/<path:filename>")
def serve_static(filename):
    if filename == "app.py":  # güvenlik amaçlı
        abort(403)
    return send_from_directory(".", filename)

@app.route("/uploads/<path:filename>")
def serve_upload(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename, as_attachment=False)

# --- Mesaj listeleme (son 20 + sayfalama) ---
@app.route("/messages")
@login_required
def list_messages():
    db = get_db()
    room = session["room"]
    offset = int(request.args.get("offset", 0))
    limit  = int(request.args.get("limit", 20))
    rows = (
        db.query(Message)
        .filter_by(room=room)
        .order_by(Message.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    db.close()
    # eski -> yeni
    rows = list(reversed(rows))
    data = []
    for m in rows:
        data.append({
            "id": m.id,
            "username": m.username,
            "type": m.type,
            "content": m.content,
            "original_name": m.original_name,
            "reply_to": m.reply_to,
            "time": m.created_at.isoformat(),
            "delivered": m.delivered
        })
    return jsonify(data)

# --- Dosya yükleme (foto/video/ses/dosya) ---
@app.route("/upload", methods=["POST"])
@login_required
def upload():
    if "file" not in request.files:
        return jsonify({"error":"dosya yok"}), 400
    f = request.files["file"]
    if not f or f.filename == "":
        return jsonify({"error":"dosya seçilmedi"}), 400

    fname = sanitize_filename(f.filename)
    save_as = f"{int(time.time()*1000)}_{fname}"
    path = os.path.join(app.config["UPLOAD_FOLDER"], save_as)
    f.save(path)

    # tip tespiti kaba (uzantı)
    ext = fname.rsplit(".",1)[-1].lower() if "." in fname else ""
    if ext in ["jpg","jpeg","png","gif","webp"]:
        mtype = "image"
    elif ext in ["mp4","webm","mov","m4v"]:
        mtype = "video"
    elif ext in ["mp3","wav","m4a","ogg","oga","opus"]:
        mtype = "audio"
    else:
        mtype = "file"

    db = get_db()
    msg = Message(
        room=session["room"],
        username=session["username"],
        type=mtype,
        content=save_as,
        original_name=fname
    )
    db.add(msg); db.commit()
    out = {
        "id": msg.id,
        "username": msg.username,
        "type": msg.type,
        "content": msg.content,
        "original_name": msg.original_name,
        "time": msg.created_at.isoformat(),
        "delivered": True
    }
    db.close()
    socketio.emit("message", out, room=session["room"])
    return jsonify(out)

# ------------ SOCKET.IO ------------
@socketio.on("join")
def on_join(data):
    username = session.get("username")
    room = session.get("room")
    join_room(room)
    ONLINE.setdefault(room, set()).add(username)
    emit("status", {"msg": f"🔔 {username} odaya katıldı", "online": len(ONLINE[room])}, room=room)

@socketio.on("leave")
def on_leave(data):
    username = session.get("username")
    room = session.get("room")
    leave_room(room)
    if room in ONLINE and username in ONLINE[room]:
        ONLINE[room].remove(username)
    emit("status", {"msg": f"👋 {username} odadan ayrıldı", "online": len(ONLINE.get(room,set()))}, room=room)

@socketio.on("typing")
def on_typing(data):
    username = session.get("username")
    room = session.get("room")
    emit("typing", {"username": username}, room=room, include_self=False)

@socketio.on("text")
def on_text(data):
    db = get_db()
    msg = Message(
        room=session["room"],
        username=session["username"],
        type="text",
        content=data.get("msg",""),
        reply_to=data.get("reply_to")
    )
    db.add(msg); db.commit()
    payload = {
        "id": msg.id,
        "username": msg.username,
        "type": msg.type,
        "content": msg.content,
        "reply_to": msg.reply_to,
        "time": msg.created_at.isoformat(),
        "delivered": True
    }
    db.close()
    emit("message", payload, room=session["room"])

@socketio.on("delete_message")
def on_delete(data):
    mid = int(data.get("id",0))
    db = get_db()
    m = db.query(Message).filter_by(id=mid, room=session["room"]).first()
    if m:
        m.type = "deleted"
        m.content = "❌ Bu mesaj silindi"
        db.commit()
        emit("deleted", {"id": m.id}, room=session["room"])
    db.close()

# ------------ MAIN ------------
if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))