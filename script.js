const socket = io();
const chat = document.getElementById("chatScroll");
const typingEl = document.getElementById("typing");
const onlineEl = document.getElementById("online");
const msgInput = document.getElementById("msg");
const sendBtn = document.getElementById("send");
const fileInput = document.getElementById("file");
const recBtn = document.getElementById("rec");
const refreshBtn = document.getElementById("refresh");

let offset = 0;
const LIMIT = 20;
let loadingHistory = false;

// --- helpers ---
function timeText(iso){
  try{ return new Date(iso).toLocaleTimeString("tr-TR",{hour:"2-digit",minute:"2-digit"}); }
  catch(e){ return ""; }
}
function makeBubble(m){
  const wrap = document.createElement("div");
  wrap.className = "message" + (m.username===USERNAME? " mine":"");
  wrap.dataset.id = m.id;

  const content = document.createElement("div");
  content.className = "bubble";

  if(m.type==="text" || m.type==="reply"){
    content.textContent = m.content;
  } else if(m.type==="image"){
    const img = document.createElement("img");
    img.className = "thumb";
    img.src = `/uploads/${m.content}`;
    img.alt = m.original_name || "image";
    content.appendChild(img);
  } else if(m.type==="video"){
    if(MODE==="modern"){
      const v = document.createElement("video");
      v.className="thumb"; v.controls = true; v.src = `/uploads/${m.content}`;
      content.appendChild(v);
    } else {
      const a = document.createElement("a");
      a.href = `/uploads/${m.content}`;
      a.textContent = `📦 Video indir (${m.original_name||"dosya"})`;
      content.appendChild(a);
    }
  } else if(m.type==="audio"){
    if(MODE==="modern"){
      const a = document.createElement("audio");
      a.controls = true; a.src = `/uploads/${m.content}`;
      content.appendChild(a);
    } else {
      const link = document.createElement("a");
      link.href = `/uploads/${m.content}`;
      link.textContent = `📦 Ses indir (${m.original_name||"dosya"})`;
      content.appendChild(link);
    }
  } else if(m.type==="file"){
    const a = document.createElement("a");
    a.href = `/uploads/${m.content}`;
    a.textContent = `📦 ${m.original_name||"dosya"} (indir)`;
    content.appendChild(a);
  } else if(m.type==="deleted"){
    content.textContent = "❌ Bu mesaj silindi";
  }

  const meta = document.createElement("div");
  meta.className = "meta";
  meta.textContent = `${m.username} · ${timeText(m.time)} · ${m.delivered ? "📮" : ""}`;

  // basılı tut → sil/yanıtla
  let pressTimer;
  wrap.addEventListener("touchstart", e=>{
    pressTimer = setTimeout(()=>optionsMenu(m, wrap), 500);
  });
  wrap.addEventListener("touchend", e=>clearTimeout(pressTimer));
  wrap.addEventListener("mousedown", e=>{
    pressTimer = setTimeout(()=>optionsMenu(m, wrap), 500);
  });
  wrap.addEventListener("mouseup", e=>clearTimeout(pressTimer));

  wrap.appendChild(content);
  wrap.appendChild(meta);
  return wrap;
}

function optionsMenu(m, el){
  // chrome varsayılan menüsü gelmesin
  // (mobilde uzun basınca genelde engellenir)
  if(confirm("Bu mesaja işlem yap: OK=Sil, İptal=Yanıtla")){
    if(m.username===USERNAME){ socket.emit("delete_message", {id:m.id}); }
    else alert("Sadece kendi mesajını silebilirsin");
  } else {
    // yanıtla
    msgInput.value = `↩️ ${m.username}: ${m.type==="text"?m.content:"(ek)"}\n`;
    msgInput.focus();
  }
}

// --- initial join ---
socket.emit("join", {username: USERNAME, room: ROOM});

// --- load initial 20 ---
async function loadMore(initial=false){
  if(loadingHistory) return;
  loadingHistory = true;
  const prevHeight = chat.scrollHeight;
  const res = await fetch(`/messages?offset=${offset}&limit=${LIMIT}`);
  const arr = await res.json();
  arr.forEach(m=>{
    chat.appendChild(makeBubble(m));
  });
  offset += arr.length;
  if(initial){ chat.scrollTop = chat.scrollHeight; }
  else { chat.scrollTop = chat.scrollHeight - prevHeight; }
  loadingHistory = false;
}
loadMore(true);

// scroll top → more
chat.addEventListener("scroll", ()=>{
  if(chat.scrollTop===0){ loadMore(false); }
});

// typing
msgInput.addEventListener("input", ()=>{
  socket.emit("typing", {});
});

// send text
sendBtn.addEventListener("click", sendText);
msgInput.addEventListener("keydown", e=>{
  if(e.key==="Enter" && !e.shiftKey){ e.preventDefault(); sendText(); }
});
function sendText(){
  const t = msgInput.value.trim();
  if(!t) return;
  socket.emit("text", {msg:t});
  msgInput.value = "";
}

// file upload
if(fileInput){
  fileInput.addEventListener("change", async ()=>{
    if(!fileInput.files || !fileInput.files[0]) return;
    const f = fileInput.files[0];
    if(f.size > 25*1024*1024){ alert("25 MB sınırı!"); fileInput.value=""; return; }
    const fd = new FormData();
    fd.append("file", f);
    const res = await fetch("/upload", {method:"POST", body:fd});
    if(!res.ok){ alert("Yükleme hatası"); }
    fileInput.value="";
  });
}

// nokia yenile
if(refreshBtn){
  refreshBtn.addEventListener("click", async()=>{
    // ekrana yeni gelenleri getir (offset zaten tuttuğumuz kadar yükledi)
    await loadMore(false);
  });
}

// voice record (modern)
let mediaRecorder, chunks=[];
if(recBtn && MODE==="modern" && navigator.mediaDevices && navigator.mediaDevices.getUserMedia){
  recBtn.addEventListener("click", async ()=>{
    try{
      if(!mediaRecorder || mediaRecorder.state==="inactive"){
        const stream = await navigator.mediaDevices.getUserMedia({audio:true});
        mediaRecorder = new MediaRecorder(stream);
        chunks = [];
        mediaRecorder.ondataavailable = e=>chunks.push(e.data);
        mediaRecorder.onstop = async ()=>{
          const blob = new Blob(chunks, {type:"audio/webm"});
          const file = new File([blob], `voice_${Date.now()}.webm`, {type:"audio/webm"});
          const fd = new FormData(); fd.append("file", file);
          const res = await fetch("/upload", {method:"POST", body:fd});
          if(!res.ok) alert("Ses yükleme hatası");
        };
        mediaRecorder.start();
        recBtn.textContent = "⏹️ Durdur";
      } else {
        mediaRecorder.stop();
        recBtn.textContent = "🎙️ Ses Kaydı";
      }
    }catch(e){
      alert("Mikrofon izni gerekli");
    }
  });
}

// incoming events
socket.on("message", (m)=>{
  chat.appendChild(makeBubble(m));
  chat.scrollTop = chat.scrollHeight;
});
socket.on("deleted", ({id})=>{
  const el = chat.querySelector(`[data-id="${id}"]`);
  if(el){
    const b = el.querySelector(".bubble");
    b.textContent = "❌ Bu mesaj silindi";
  }
});
socket.on("status", (data)=>{
  if(typeof data.online==="number"){
    onlineEl.textContent = `📮 ${data.online}`;
  }
});
socket.on("typing", ({username})=>{
  typingEl.textContent = `${username} yazıyor…`;
  setTimeout(()=>typingEl.textContent="", 1500);
});