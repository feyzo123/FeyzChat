import os, time, threading
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask, request, redirect, url_for, session,
    render_template_string, jsonify, send_from_directory, abort
)
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean
from sqlalchemy.orm import sessionmaker, declarative_base

# ------------ APP CONFIG ------------
app = Flask(__name__)
app.secret_key = "feyzchat_secret"
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB
app.config["UPLOAD_FOLDER"] = "uploads"
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

# ------------ DB ------------
Base = declarative_base()
engine = create_engine("sqlite:///feyzchat.db", echo=False, connect_args={"check_same_thread": False})
DB = sessionmaker(bind=engine)

class Room(Base):
    __tablename__ = "rooms"
    id = Column(Integer, primary_key=True)
    name = Column(String(64), unique=True, index=True)
    password = Column(String(128), default="")

class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True)
    room = Column(String(64), index=True)
    username = Column(String(64))
    type = Column(String(16), default="text")  # text,image,video,audio,file,deleted,reply
    content = Column(Text)                    # metin veya dosya adı
    original_name = Column(String(255), nullable=True)
    reply_to = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    delivered = Column(Boolean, default=True)  # "posta" göstergesi

class Presence(Base):
    __tablename__ = "presence"
    id = Column(Integer, primary_key=True)
    room = Column(String(64), index=True)
    username = Column(String(64), index=True)
    last_seen = Column(DateTime, default=datetime.utcnow)
    typing_until = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(engine)

# ------------ HTML LOADER ------------
def load_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

INDEX_HTML = """{{INDEX_HTML}}"""
CHAT_HTML  = """{{CHAT_HTML}}"""

def login_required(f):
    @wraps(f)
    def w(*a, **k):
        if not session.get("username") or not session.get("room"):
            return redirect(url_for("index"))
        return f(*a, **k)
    return w

def sanitize_filename(name: str) -> str:
    bad = '/\\?%*:|"<>'
    for ch in bad:
        name = name.replace(ch, "_")
    return name

# ------------ CLEANUP (5 günde bir sil) ------------
def cleanup_job():
    while True:
        try:
            db = DB()
            cutoff = datetime.utcnow() - timedelta(days=5)
            # eski mesajları sil
            old = db.query(Message).filter(Message.created_at < cutoff).all()
            for m in old:
                # dosyaları da temizle
                if m.type in ("image","video","audio","file") and m.content:
                    p = os.path.join(app.config["UPLOAD_FOLDER"], m.content)
                    if os.path.exists(p):
                        try: os.remove(p)
                        except: pass
                db.delete(m)
            # eski presence kayıtları
            db.query(Presence).filter(Presence.last_seen < datetime.utcnow()-timedelta(days=1)).delete()
            db.commit()
            db.close()
        except Exception as e:
            print("cleanup error:", e)
        time.sleep(24*3600)  # günde 1
threading.Thread(target=cleanup_job, daemon=True).start()

# ------------ ROUTES ------------
@app.route("/", methods=["GET","POST"])
def index():
    if request.method == "POST":
        username = request.form.get("username","").strip()
        room = request.form.get("room","").strip()
        password = request.form.get("password","").strip()
        action = request.form.get("action","join")
        mode = request.form.get("mode","modern")
        if not username or not room:
            return render_template_string(INDEX_HTML, error="Kullanıcı adı ve oda zorunlu", ok=None)
        db = DB()
        r = db.query(Room).filter_by(name=room).first()
        if action == "create":
            if r:
                db.close()
                return render_template_string(INDEX_HTML, error="Bu oda zaten var", ok=None)
            r = Room(name=room, password=password or "")
            db.add(r); db.commit()
        else:
            if not r or (r.password or "") != (password or ""):
                db.close()
                return render_template_string(INDEX_HTML, error="Oda/Şifre yanlış", ok=None)
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

# statik dosyalar (root’tan servis)
@app.route("/<path:filename>")
def root_static(filename):
    if filename == "app.py":
        abort(403)
    return send_from_directory(".", filename)

@app.route("/uploads/<path:filename>")
def get_upload(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename, as_attachment=False)

# --- Mesaj listeleme (son 20 + offset) ---
@app.route("/messages")
@login_required
def messages_list():
    room = session["room"]
    offset = int(request.args.get("offset", 0))
    limit  = int(request.args.get("limit", 20))
    db = DB()
    rows = (db.query(Message)
        .filter_by(room=room)
        .order_by(Message.id.desc())
        .offset(offset).limit(limit).all())
    db.close()
    rows = list(reversed(rows))
    out = []
    for m in rows:
        out.append({
            "id": m.id,
            "username": m.username,
            "type": m.type,
            "content": m.content,
            "original_name": m.original_name,
            "reply_to": m.reply_to,
            "time": m.created_at.isoformat(),
            "delivered": m.delivered
        })
    return jsonify(out)

# --- Mesaj gönder (text) ---
@app.route("/send", methods=["POST"])
@login_required
def send_text():
    data = request.get_json() or {}
    text = (data.get("msg") or "").strip()
    reply_to = data.get("reply_to")
    if not text:
        return jsonify({"error":"boş mesaj"}), 400
    m = Message(
        room=session["room"], username=session["username"],
        type="text", content=text, reply_to=reply_to
    )
    db = DB(); db.add(m); db.commit()
    payload = {
        "id": m.id, "username": m.username, "type": m.type,
        "content": m.content, "reply_to": m.reply_to,
        "time": m.created_at.isoformat(), "delivered": True
    }
    db.close()
    return jsonify(payload)

# --- Mesaj sil (soft delete) ---
@app.route("/delete", methods=["POST"])
@login_required
def delete_msg():
    data = request.get_json() or {}
    mid = int(data.get("id", 0))
    db = DB()
    m = db.query(Message).filter_by(id=mid, room=session["room"]).first()
    if not m:
        db.close(); return jsonify({"error":"bulunamadı"}), 404
    if m.username != session["username"]:
        db.close(); return jsonify({"error":"sadece kendi mesajını silebilirsin"}), 403
    m.type = "deleted"; m.content = "❌ Bu mesaj silindi"; db.commit()
    db.close()
    return jsonify({"ok":True, "id": mid})

# --- Dosya yükleme (foto/video/ses/dosya) ---
@app.route("/upload", methods=["POST"])
@login_required
def upload():
    if "file" not in request.files:
        return jsonify({"error":"dosya yok"}), 400
    f = request.files["file"]
    if not f or f.filename == "": return jsonify({"error":"dosya seçilmedi"}), 400
    fname = sanitize_filename(f.filename)
    save_as = f"{int(time.time()*1000)}_{fname}"
    path = os.path.join(app.config["UPLOAD_FOLDER"], save_as)
    f.save(path)
    ext = fname.rsplit(".",1)[-1].lower() if "." in fname else ""
    if ext in ["jpg","jpeg","png","gif","webp"]: mtype="image"
    elif ext in ["mp4","webm","mov","m4v"]: mtype="video"
    elif ext in ["mp3","wav","m4a","ogg","oga","opus","webm"]: mtype="audio"
    else: mtype="file"
    m = Message(
        room=session["room"], username=session["username"], type=mtype,
        content=save_as, original_name=fname
    )
    db = DB(); db.add(m); db.commit()
    payload = {
        "id": m.id, "username": m.username, "type": m.type,
        "content": m.content, "original_name": m.original_name,
        "time": m.created_at.isoformat(), "delivered": True
    }
    db.close()
    return jsonify(payload)

# --- Presence: ping + typing + sayım ---
@app.route("/ping", methods=["POST"])
@login_required
def ping():
    db = DB()
    p = (db.query(Presence)
         .filter_by(room=session["room"], username=session["username"]).first())
    if not p:
        p = Presence(room=session["room"], username=session["username"])
        db.add(p)
    p.last_seen = datetime.utcnow()
    db.commit(); db.close()
    return jsonify({"ok":True})

@app.route("/typing", methods=["POST"])
@login_required
def typing():
    db = DB()
    p = (db.query(Presence)
         .filter_by(room=session["room"], username=session["username"]).first())
    if not p:
        p = Presence(room=session["room"], username=session["username"])
        db.add(p)
    p.last_seen = datetime.utcnow()
    p.typing_until = datetime.utcnow() + timedelta(seconds=2)
    db.commit(); db.close()
    return jsonify({"ok":True})

@app.route("/who")
@login_required
def who():
    db = DB()
    now = datetime.utcnow()
    items = (db.query(Presence)
             .filter_by(room=session["room"]).all())
    online = [x.username for x in items if x.last_seen > now - timedelta(seconds=40)]
    typing = [x.username for x in items if x.typing_until > now]
    db.close()
    return jsonify({"online": sorted(set(online)), "typing": sorted(set(typing))})

# ------------ MAIN ------------
if __name__ == "__main__":
    # local test: python app.py
    app.run(host="0.0.0.0", port=5000, debug=False)
