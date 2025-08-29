const chat = document.getElementById("messages");
const typingEl = document.getElementById("typing");
const msgInput = document.getElementById("msg");
const sendBtn = document.getElementById("send");
const fileInput = document.getElementById("file");
const recBtn = document.getElementById("rec");
const refreshBtn = document.getElementById("refresh");
const onlineBadge = document.getElementById("onlineBadge");
const emojiBtn = document.getElementById("emojiBtn");
const emojiBar = document.getElementById("emojiBar");

let offset = 0;
const LIMIT = 20;
let loading = false;

// --- helpers ---
function timeText(iso){
  try{ return new Date(iso).toLocaleTimeString("tr-TR",{hour:"2-digit",minute:"2-digit"}); }
  catch(e){ return ""; }
}
function el(tag, cls){ const x=document.createElement(tag); if(cls) x.className=cls; return x; }

function makeBubble(m){
  const wrap = el("div","message"+(m.username===USERNAME?" mine":""));
  wrap.dataset.id = m.id;
  const bubble = el("div","bubble");
  if(m.type==="text" || m.type==="reply"){ bubble.textContent = m.content; }
  else if(m.type==="image"){
    const img = el("img","thumb"); img.src=`/uploads/${m.content}`; img.alt=m.original_name||"image"; bubble.appendChild(img);
  } else if(m.type==="video"){
    if(MODE==="modern"){ const v=el("video","thumb"); v.controls=true; v.src=`/uploads/${m.content}`; bubble.appendChild(v); }
    else { const a=el("a"); a.href=`/uploads/${m.content}`; a.textContent=`📦 Video indir (${m.original_name||"dosya"})`; bubble.appendChild(a); }
  } else if(m.type==="audio"){
    if(MODE==="modern"){ const a=el("audio"); a.controls=true; a.src=`/uploads/${m.content}`; bubble.appendChild(a); }
    else { const link=el("a"); link.href=`/uploads/${m.content}`; link.textContent=`📦 Ses indir (${m.original_name||"dosya"})`; bubble.appendChild(link); }
  } else if(m.type==="file"){
    const a=el("a"); a.href=`/uploads/${m.content}`; a.textContent=`📦 ${m.original_name||"dosya"} (indir)`; bubble.appendChild(a);
  } else if(m.type==="deleted"){
    bubble.textContent = "❌ Bu mesaj silindi";
  }
  const meta = el("div","meta");
  meta.textContent = `${m.username} · ${timeText(m.time)} · 📮`;

  // uzun bas → seçenek
  let timer;
  wrap.addEventListener("touchstart", ()=>{ timer=setTimeout(()=>optionsMenu(m),500); });
  wrap.addEventListener("touchend", ()=>clearTimeout(timer));
  wrap.addEventListener("mousedown", ()=>{ timer=setTimeout(()=>optionsMenu(m),500); });
  wrap.addEventListener("mouseup", ()=>clearTimeout(timer));

  wrap.appendChild(bubble); wrap.appendChild(meta);
  return wrap;
}
function optionsMenu(m){
  const act = confirm("OK=Sil, İptal=Yanıtla");
  if(act){
    if(m.username!==USERNAME){ alert("Sadece kendi mesajını silebilirsin"); return; }
    fetch("/delete",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:m.id})})
      .then(()=> refreshNew());
  }else{
    msgInput.value = `↩️ ${m.username}: ${m.type==="text"?m.content:"(ek)"}\n`;
    msgInput.focus();
  }
}

// --- ilk 20 ---
async function loadMore(initial=false){
  if(loading) return; loading=true;
  const prevH = chat.scrollHeight;
  const res = await fetch(`/messages?offset=${offset}&limit=${LIMIT}`);
  const arr = await res.json();
  arr.forEach(m=> chat.appendChild(makeBubble(m)));
  offset += arr.length;
  if(initial) chat.scrollTop = chat.scrollHeight;
  else chat.scrollTop = chat.scrollHeight - prevH;
  loading=false;
}
loadMore(true);

// scroll top → eski mesaj
chat.addEventListener("scroll", ()=>{ if(chat.scrollTop===0) loadMore(false); });

// --- ping & who (online / typing) ---
async function heartbeat(){
  await fetch("/ping",{method:"POST"});
}
async function updateWho(){
  const r = await fetch("/who"); const j = await r.json();
  onlineBadge.textContent = `${j.online.length ? "🟢" : "🔴"} ${j.online.length||0}`;
  if(j.typing.length){
    typingEl.textContent = `${j.typing.join(", ")} yazıyor…`;
  } else typingEl.textContent = "";
}
setInterval(()=>{ heartbeat(); updateWho(); }, 4000);

// typing
let typingTimer;
msgInput.addEventListener("input", ()=>{
  fetch("/typing",{method:"POST"});
  clearTimeout(typingTimer);
  typingTimer = setTimeout(()=>{},1500);
});

// --- gönder ---
function sendNow(){
  const t = msgInput.value.trim();
  if(!t) return;
  fetch("/send",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({msg:t})
  }).then(()=>{ msgInput.value=""; refreshNew(); });
}
sendBtn.addEventListener("click", sendNow);
msgInput.addEventListener("keydown", e=>{
  if(e.key==="Enter" && !e.shiftKey){ e.preventDefault(); sendNow(); }
});

// --- yeni gelenleri getir (polling) ---
let lastPull = 0;
async function refreshNew(){
  // basit yaklaşım: son yüklenen sayıya göre tekrar /messages çekelim (offset=0 sadece yeni değil son 20 getirir)
  // çözüm: sadece son 20'de yeniler görünür, eskiye kaydırınca yine çalışır.
  const atBottom = (chat.scrollTop + chat.clientHeight + 10) >= chat.scrollHeight;
  const res = await fetch(`/messages?offset=${0}&limit=${Math.max(LIMIT, offset)}`);
  const arr = await res.json();
  chat.innerHTML = ""; offset = 0;
  arr.forEach(m=> chat.appendChild(makeBubble(m)));
  offset += arr.length;
  if(atBottom) chat.scrollTop = chat.scrollHeight;
}
setInterval(refreshNew, 3000);

// --- dosya yükle ---
if(fileInput){
  fileInput.addEventListener("change", async ()=>{
    if(!fileInput.files || !fileInput.files[0]) return;
    const f = fileInput.files[0];
    if(f.size > 25*1024*1024){ alert("25 MB sınırı!"); fileInput.value=""; return; }
    const fd = new FormData(); fd.append("file", f);
    const r = await fetch("/upload",{method:"POST", body:fd});
    if(!r.ok){ alert("Yükleme hatası"); }
    fileInput.value=""; refreshNew();
  });
}

// --- Nokia yenile ---
if(refreshBtn){ refreshBtn.addEventListener("click", refreshNew); }

// --- Ses kaydı (Modern) ---
let mediaRecorder, chunks=[];
if(recBtn && MODE==="modern" && navigator.mediaDevices && navigator.mediaDevices.getUserMedia){
  recBtn.addEventListener("click", async ()=>{
    try{
      if(!mediaRecorder || mediaRecorder.state==="inactive"){
        const stream = await navigator.mediaDevices.getUserMedia({audio:true});
        mediaRecorder = new MediaRecorder(stream);
        chunks=[];
        mediaRecorder.ondataavailable = e=>chunks.push(e.data);
        mediaRecorder.onstop = async ()=>{
          const blob = new Blob(chunks, {type:"audio/webm"});
          const file = new File([blob], `voice_${Date.now()}.webm`, {type:"audio/webm"});
          const fd = new FormData(); fd.append("file", file);
          await fetch("/upload",{method:"POST", body:fd});
          refreshNew();
        };
        mediaRecorder.start();
        recBtn.textContent = "⏹️ Durdur";
      } else {
        mediaRecorder.stop();
        recBtn.textContent = "🎙️ Ses Kaydı";
      }
    }catch(e){ alert("Mikrofon izni gerekli"); }
  });
}

// --- Emoji bar ---
if(emojiBtn && emojiBar){
  emojiBtn.addEventListener("click", ()=>{
    emojiBar.hidden = !emojiBar.hidden;
  });
  emojiBar.textContent.split("").forEach(()=>{});
  // hazır emojiler
  const ems = "😀 😂 😍 🔥 🥳 👍 🙏 ❤️ 😎 😭 😡 😉 😅 ✨ 💯".split(" ");
  emojiBar.innerHTML = "";
  ems.forEach(e=>{
    const b=document.createElement("button"); b.textContent=e;
    b.onclick=()=>{ msgInput.value += e; msgInput.focus(); };
    emojiBar.appendChild(b);
  });
          }
