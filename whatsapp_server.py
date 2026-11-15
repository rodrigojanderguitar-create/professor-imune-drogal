# -*- coding: utf-8 -*-
"""
Servidor Webhook WhatsApp de Produção + Simulador Web Oficial do Agente "Professor Imune" — Rede Drogal.

Suporta nativamente:
1. Z-API (QR Code)     -> POST /webhook/zapi (Texto + Fotos de carteira/receita)
2. Evolution API       -> POST /webhook/evolution (Texto + Fotos)
3. Meta Cloud API      -> GET e POST /webhook/meta
4. Twilio WhatsApp     -> POST /webhook/twilio
5. API REST Genérica   -> POST /api/chat (para n8n, Typebot, Make ou sistemas internos Drogal)
6. Health Check Cloud  -> GET /health (para Render, Railway, Docker)
"""

import base64
import html
import os
from pathlib import Path
from typing import Optional

import requests
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from starlette.routing import Route

from knowledge_base import kb
from professor_imune import ENV_PATH, agent, load_env_file

BASE_DIR = Path(__file__).resolve().parent


def update_env_key(key: str, value: str) -> None:
    """Salva ou atualiza uma variável no arquivo .env e no ambiente em execução."""
    os.environ[key] = value
    try:
        lines = []
        if ENV_PATH.exists():
            lines = ENV_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
        found = False
        new_lines = []
        for ln in lines:
            if ln.strip().startswith(f"{key}="):
                new_lines.append(f"{key}={value}")
                found = True
            else:
                new_lines.append(ln)
        if not found:
            new_lines.append(f"{key}={value}")
        ENV_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    except Exception:
        pass


def download_image_from_url(url: str) -> Optional[bytes]:
    """Baixa imagem enviada no WhatsApp (ex.: foto de carteira de vacinação via Z-API)."""
    if not url:
        return None
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200 and r.content:
            return r.content
    except Exception:
        pass
    return None


# =====================================================================
# ENVIO DE MENSAGENS PARA OS PROVEDORES DE WHATSAPP
# =====================================================================

def send_evolution_message(remote_jid: str, text: str, instance: Optional[str] = None) -> bool:
    load_env_file()
    base_url = os.environ.get("EVOLUTION_API_URL", "").rstrip("/")
    api_key = os.environ.get("EVOLUTION_API_KEY", "")
    inst = instance or os.environ.get("EVOLUTION_INSTANCE", "")
    if not (base_url and api_key and inst):
        return False
    url = f"{base_url}/message/sendText/{inst}"
    headers = {"apikey": api_key, "Content-Type": "application/json"}
    payload = {"number": remote_jid, "text": text}
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=20)
        return r.status_code in (200, 201)
    except Exception as e:
        print(f"[Evolution API] Erro ao enviar mensagem: {e}")
        return False


def send_zapi_message(phone: str, text: str) -> bool:
    load_env_file()
    instance_id = os.environ.get("ZAPI_INSTANCE_ID", "")
    token = os.environ.get("ZAPI_TOKEN", "")
    client_token = os.environ.get("ZAPI_CLIENT_TOKEN", "")
    if not (instance_id and token):
        return False
    url = f"https://api.z-api.io/instances/{instance_id}/token/{token}/send-text"
    headers = {"Content-Type": "application/json"}
    if client_token:
        headers["Client-Token"] = client_token
    payload = {"phone": phone, "message": text}
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=20)
        return r.status_code in (200, 201)
    except Exception as e:
        print(f"[Z-API] Erro ao enviar mensagem: {e}")
        return False


def send_meta_whatsapp_message(to_phone: str, text: str) -> bool:
    load_env_file()
    token = os.environ.get("WHATSAPP_CLOUD_TOKEN", "")
    phone_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
    if not (token and phone_id):
        return False
    url = f"https://graph.facebook.com/v21.0/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "text",
        "text": {"body": text[:4096]},
    }
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=20)
        return r.status_code in (200, 201)
    except Exception as e:
        print(f"[Meta Cloud API] Erro ao enviar mensagem: {e}")
        return False


# =====================================================================
# ENDPOINTS DA API & WEBHOOKS WHATSAPP
# =====================================================================

async def health_check(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "professor-imune-drogal"})


async def api_status(request: Request) -> JSONResponse:
    load_env_file()
    has_key = bool(agent.get_api_key())
    zapi_ready = bool(os.environ.get("ZAPI_INSTANCE_ID") and os.environ.get("ZAPI_TOKEN"))
    evo_ready = bool(os.environ.get("EVOLUTION_API_URL") and os.environ.get("EVOLUTION_API_KEY"))
    return JSONResponse({
        "agent": "Professor Imune — Especialista Virtual em Vacinação (Rede Drogal)",
        "gemini_configured": has_key,
        "gemini_model": agent.get_model_name(),
        "zapi_configured": zapi_ready,
        "evolution_configured": evo_ready,
        "knowledge_base": kb.stats(),
    })


async def api_config(request: Request) -> JSONResponse:
    data = await request.json()
    for field, env_name in [
        ("api_key", "GEMINI_API_KEY"),
        ("model", "GEMINI_MODEL"),
        ("zapi_instance_id", "ZAPI_INSTANCE_ID"),
        ("zapi_token", "ZAPI_TOKEN"),
        ("zapi_client_token", "ZAPI_CLIENT_TOKEN"),
        ("evolution_url", "EVOLUTION_API_URL"),
        ("evolution_key", "EVOLUTION_API_KEY"),
        ("evolution_instance", "EVOLUTION_INSTANCE"),
    ]:
        val = (data.get(field) or "").strip()
        if val:
            update_env_key(env_name, val)

    return JSONResponse({
        "ok": True,
        "gemini_configured": bool(agent.get_api_key()),
        "gemini_model": agent.get_model_name(),
    })


async def api_chat(request: Request) -> JSONResponse:
    data = await request.json()
    message = (data.get("message") or "").strip()
    session_id = (data.get("session_id") or "web-farmaceutico").strip()
    api_key = (data.get("api_key") or "").strip() or None
    model = (data.get("model") or "").strip() or None

    image_bytes: Optional[bytes] = None
    image_mime = data.get("image_mime") or "image/jpeg"
    img_b64 = data.get("image_base64")
    if img_b64:
        if "," in img_b64:
            img_b64 = img_b64.split(",", 1)[1]
        try:
            image_bytes = base64.b64decode(img_b64)
        except Exception:
            image_bytes = None

    reply, docs = agent.chat(
        user_message=message,
        session_id=session_id,
        image_bytes=image_bytes,
        image_mime=image_mime,
        api_key=api_key,
        model_name=model,
    )
    sources = [{"id": d["id"], "source": d["source"], "title": d["title"]} for d in docs]
    return JSONResponse({
        "reply": reply,
        "sources": sources,
        "session_id": session_id,
        "gemini_active": bool(agent.get_api_key(api_key)),
    })


async def webhook_evolution(request: Request) -> JSONResponse:
    """Webhook para Evolution API (evento messages.upsert)."""
    body = await request.json()
    data = body.get("data") or body
    instance = body.get("instance")

    key_info = data.get("key") or {}
    if key_info.get("fromMe"):
        return JSONResponse({"status": "ignored_from_me"})

    remote_jid = key_info.get("remoteJid") or data.get("from") or ""
    if not remote_jid or "@g.us" in remote_jid:
        return JSONResponse({"status": "ignored_group_or_empty"})

    msg_obj = data.get("message") or {}
    text = (
        msg_obj.get("conversation")
        or (msg_obj.get("extendedTextMessage") or {}).get("text")
        or (msg_obj.get("imageMessage") or {}).get("caption")
        or data.get("body")
        or ""
    ).strip()

    image_bytes: Optional[bytes] = None
    b64_media = data.get("base64") or (msg_obj.get("imageMessage") or {}).get("jpegThumbnail")
    if b64_media and isinstance(b64_media, str):
        try:
            image_bytes = base64.b64decode(b64_media)
        except Exception:
            image_bytes = None

    if not text and not image_bytes:
        return JSONResponse({"status": "empty_message"})

    reply, _ = agent.chat(
        user_message=text or "Analise esta imagem enviada pelo farmacêutico na sala de vacinas.",
        session_id=f"evo:{remote_jid}",
        image_bytes=image_bytes,
    )
    sent = send_evolution_message(remote_jid=remote_jid, text=reply, instance=instance)
    return JSONResponse({"status": "processed", "sent_to_evolution": sent, "reply": reply})


async def webhook_zapi(request: Request) -> JSONResponse:
    """Webhook para Z-API (Ao receber mensagem de texto ou imagem)."""
    body = await request.json()
    if body.get("fromMe") or body.get("isGroup"):
        return JSONResponse({"status": "ignored"})

    phone = str(body.get("phone") or "").strip()
    if not phone:
        return JSONResponse({"status": "empty_phone"})

    text = (
        (body.get("text") or {}).get("message")
        or (body.get("image") or {}).get("caption")
        or body.get("message")
        or ""
    ).strip()

    image_bytes: Optional[bytes] = None
    img_url = (body.get("image") or {}).get("imageUrl")
    if img_url:
        image_bytes = download_image_from_url(img_url)

    if not text and not image_bytes:
        return JSONResponse({"status": "empty_content"})

    reply, _ = agent.chat(
        user_message=text or "Analise esta foto enviada pelo farmacêutico na sala de vacinas.",
        session_id=f"zapi:{phone}",
        image_bytes=image_bytes,
    )
    sent = send_zapi_message(phone=phone, text=reply)
    return JSONResponse({"status": "processed", "sent_to_zapi": sent, "reply": reply})


async def webhook_meta(request: Request) -> Response:
    """Webhook para WhatsApp Cloud API Oficial da Meta (GET para verificação + POST para mensagens)."""
    if request.method == "GET":
        load_env_file()
        verify_token = os.environ.get("WHATSAPP_VERIFY_TOKEN", "professor_imune_drogal")
        mode = request.query_params.get("hub.mode")
        token = request.query_params.get("hub.verify_token")
        challenge = request.query_params.get("hub.challenge")
        if mode == "subscribe" and token == verify_token and challenge:
            return PlainTextResponse(challenge)
        return PlainTextResponse("Verification token mismatch", status_code=403)

    body = await request.json()
    try:
        entries = body.get("entry") or []
        for entry in entries:
            for change in entry.get("changes") or []:
                val = change.get("value") or {}
                for msg in val.get("messages") or []:
                    from_phone = msg.get("from")
                    text = ((msg.get("text") or {}).get("body") or "").strip()
                    if from_phone and text:
                        reply, _ = agent.chat(user_message=text, session_id=f"meta:{from_phone}")
                        send_meta_whatsapp_message(to_phone=from_phone, text=reply)
    except Exception as e:
        print(f"[Webhook Meta] Erro: {e}")

    return JSONResponse({"status": "ok"})


async def webhook_twilio(request: Request) -> Response:
    """Webhook para Twilio WhatsApp (form-urlencoded)."""
    form = await request.form()
    from_number = str(form.get("From") or "twilio-user")
    body_text = str(form.get("Body") or "").strip()

    if not body_text:
        return Response("<Response></Response>", media_type="application/xml")

    reply, _ = agent.chat(user_message=body_text, session_id=f"twilio:{from_number}")
    escaped = html.escape(reply)
    twiml = f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{escaped}</Message></Response>'
    return Response(twiml, media_type="application/xml")


# =====================================================================
# INTERFACE WEB — SIMULADOR E PAINEL DE CONEXÃO WHATSAPP
# =====================================================================

SIMULATOR_HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Professor Imune — WhatsApp & Sala de Vacinação (Rede Drogal)</title>
  <style>
    :root {
      --drogal-red: #d71920;
      --drogal-blue: #004a8f;
      --wa-green: #008069;
      --wa-light-green: #d9fdd3;
      --wa-bg: #efeae2;
      --panel-bg: #ffffff;
      --text-main: #111b21;
      --text-muted: #54656f;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; }
    body { background: #f0f2f5; color: var(--text-main); height: 100vh; display: flex; overflow: hidden; }
    .sidebar {
      width: 390px;
      background: var(--panel-bg);
      border-right: 1px solid #d1d7db;
      display: flex;
      flex-direction: column;
      height: 100vh;
      overflow-y: auto;
    }
    .brand-header {
      background: linear-gradient(135deg, var(--drogal-blue), #002d5a);
      color: #fff;
      padding: 18px 20px;
      border-bottom: 4px solid var(--drogal-red);
    }
    .brand-header h1 { font-size: 1.2rem; display: flex; align-items: center; gap: 8px; }
    .brand-header p { font-size: 0.82rem; opacity: 0.9; margin-top: 4px; }
    .badge-row { display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap; }
    .badge {
      font-size: 0.72rem;
      padding: 3px 8px;
      border-radius: 12px;
      background: rgba(255,255,255,0.16);
      font-weight: 600;
    }
    .badge.ok { background: #16a34a; color: #fff; }
    .badge.warn { background: #ca8a04; color: #fff; }
    .section { padding: 14px 18px; border-bottom: 1px solid #e9edef; }
    .section h3 { font-size: 0.84rem; text-transform: uppercase; letter-spacing: 0.5px; color: var(--drogal-blue); margin-bottom: 8px; }
    .form-group { margin-bottom: 8px; }
    .form-group label { display: block; font-size: 0.76rem; color: var(--text-muted); margin-bottom: 3px; font-weight: 600; }
    .form-group input, .form-group select {
      width: 100%; padding: 7px 10px; border: 1px solid #cbd5e1; border-radius: 6px; font-size: 0.83rem;
    }
    .btn {
      background: var(--drogal-blue); color: #fff; border: none; border-radius: 6px;
      padding: 8px 12px; font-size: 0.83rem; font-weight: 600; cursor: pointer; width: 100%;
      transition: background 0.15s;
    }
    .btn:hover { background: #00376b; }
    .btn-outline {
      background: #f8fafc; color: var(--text-main); border: 1px solid #cbd5e1;
      text-align: left; padding: 8px 10px; border-radius: 6px; font-size: 0.8rem;
      cursor: pointer; margin-bottom: 6px; width: 100%; transition: all 0.15s;
    }
    .btn-outline:hover { background: #e2e8f0; border-color: #94a3b8; }
    .webhook-box {
      background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 8px 10px;
      font-size: 0.76rem; color: #334155; line-height: 1.45;
    }
    .webhook-box code {
      display: block; background: #1e293b; color: #38bdf8; padding: 5px 7px;
      border-radius: 4px; margin: 3px 0 7px 0; font-family: Consolas, monospace; font-size: 0.72rem;
      word-break: break-all;
    }
    .chat-area {
      flex: 1; display: flex; flex-direction: column; height: 100vh; background: var(--wa-bg);
    }
    .wa-header {
      background: var(--wa-green); color: #fff; padding: 12px 20px;
      display: flex; align-items: center; justify-content: space-between;
      box-shadow: 0 1px 3px rgba(0,0,0,0.12);
    }
    .wa-profile { display: flex; align-items: center; gap: 12px; }
    .wa-avatar {
      width: 42px; height: 42px; border-radius: 50%; background: #fff; color: var(--drogal-red);
      display: flex; align-items: center; justify-content: center; font-weight: 800; font-size: 1.2rem;
    }
    .wa-title h2 { font-size: 1rem; font-weight: 600; }
    .wa-title span { font-size: 0.78rem; opacity: 0.9; }
    .messages {
      flex: 1; padding: 20px 8%; overflow-y: auto; display: flex; flex-direction: column; gap: 12px;
    }
    .msg {
      max-width: 78%; padding: 10px 14px; border-radius: 8px; font-size: 0.9rem; line-height: 1.48;
      position: relative; box-shadow: 0 1px 1px rgba(0,0,0,0.08); white-space: pre-wrap; word-wrap: break-word;
    }
    .msg.bot { align-self: flex-start; background: #fff; border-top-left-radius: 0; }
    .msg.user { align-self: flex-end; background: var(--wa-light-green); border-top-right-radius: 0; }
    .input-bar {
      background: #f0f2f5; padding: 10px 16px; display: flex; align-items: center; gap: 10px;
      border-top: 1px solid #d1d7db;
    }
    .input-bar textarea {
      flex: 1; border: none; border-radius: 8px; padding: 10px 14px; font-size: 0.92rem;
      resize: none; height: 44px; outline: none; background: #fff;
    }
    .send-btn {
      background: var(--wa-green); color: #fff; border: none; border-radius: 50%;
      width: 44px; height: 44px; cursor: pointer; font-size: 1.1rem; display: flex;
      align-items: center; justify-content: center;
    }
    .file-label {
      cursor: pointer; padding: 8px 10px; border-radius: 6px; background: #e2e8f0;
      font-size: 0.82rem; color: #334155; font-weight: 600;
    }
    .preview-chip {
      font-size: 0.75rem; background: #dbeafe; color: #1e40af; padding: 4px 8px;
      border-radius: 12px; display: none; align-items: center; gap: 6px;
    }
  </style>
</head>
<body>
  <aside class="sidebar">
    <div class="brand-header">
      <h1>💉 Professor Imune</h1>
      <p>Especialista Virtual em Vacinação — Rede Drogal</p>
      <div class="badge-row">
        <span id="geminiBadge" class="badge warn">Verificando Gemini...</span>
        <span id="waBadge" class="badge">WhatsApp Pronto</span>
      </div>
    </div>

    <div class="section">
      <h3>⚙️ 1. Motor IA (Google Gemini)</h3>
      <div class="form-group">
        <label>Chave da API Google Gemini (GEMINI_API_KEY)</label>
        <input type="password" id="apiKeyInput" placeholder="Ja configurada no servidor (ou cole para atualizar)" />
      </div>
      <div class="form-group">
        <label>Modelo Gemini</label>
        <select id="modelSelect">
          <option value="gemini-3.8-flash">Gemini 3.8 Flash (Recomendado / Padrão)</option>
          <option value="gemini-2.5-flash">Gemini 2.5 Flash</option>
          <option value="gemini-2.5-pro">Gemini Pro (Raciocínio Clínico Profundo)</option>
        </select>
      </div>
      <button class="btn" onclick="saveConfig()">Salvar Configuração</button>
    </div>

    <div class="section">
      <h3>📱 2. Conexão WhatsApp (QR Code)</h3>
      <div class="webhook-box" style="margin-bottom:8px;">
        <strong>URL do Webhook na Z-API (Ao Receber):</strong>
        <code id="zapiWebhookUrl">POST .../webhook/zapi</code>
        <strong>URL do Webhook na Evolution API:</strong>
        <code id="evoWebhookUrl">POST .../webhook/evolution</code>
      </div>
      <div class="form-group">
        <label>Z-API Instance ID (Opcional se usar Z-API)</label>
        <input type="text" id="zapiInstanceInput" placeholder="Ex: 3C8F9A..." />
      </div>
      <div class="form-group">
        <label>Z-API Token</label>
        <input type="password" id="zapiTokenInput" placeholder="Token da instância Z-API" />
      </div>
      <div class="form-group">
        <label>Z-API Client-Token (Segurança da Conta)</label>
        <input type="password" id="zapiClientTokenInput" placeholder="Client-Token Z-API (se ativado)" />
      </div>
      <button class="btn" onclick="saveConfig()">Salvar Credenciais WhatsApp</button>
    </div>

    <div class="section">
      <h3>⚡ Exemplos Rápidos para Testar</h3>
      <button class="btn-outline" onclick="askSample('Paciente gestante de 28 semanas veio aplicar Abrysvo e dTpa (Refortrix) hoje. Posso aplicar as duas no mesmo dia?')">
        🤰 Gestante 28 sem: Abrysvo® + dTpa no mesmo dia?
      </button>
      <button class="btn-outline" onclick="askSample('Paciente de 32 anos quer tomar a 1ª dose da Qdenga e aproveitar para tomar a Influvac Tetra hoje. Qual a conduta?')">
        🦟 Qdenga® + Gripe (Influvac Tetra®) juntas?
      </button>
      <button class="btn-outline" onclick="askSample('Criança de 8 meses nunca tomou vacina pneumocócica e a mãe trouxe para aplicar Prevenar 20. Precisa de receita? Qual o esquema?')">
        👶 Bebê 8 meses em atraso: Prevenar 20®
      </button>
      <button class="btn-outline" onclick="askSample('A câmara refrigerada amanheceu marcando máxima de 9,8°C após queda de energia na madrugada. O que devo fazer?')">
        🌡️ Desvio de Cadeia de Frio (9,8°C na câmara)
      </button>
    </div>
  </aside>

  <main class="chat-area">
    <header class="wa-header">
      <div class="wa-profile">
        <div class="wa-avatar">PI</div>
        <div class="wa-title">
          <h2>Professor Imune — Rede Drogal</h2>
          <span>Especialista Virtual em Vacinação • Online</span>
        </div>
      </div>
      <button class="btn" style="width:auto; background:rgba(255,255,255,0.2);" onclick="resetChat()">🔄 Limpar Conversa</button>
    </header>

    <section class="messages" id="messagesContainer">
      <div class="msg bot">Olá, colega farmacêutico! 👋 Sou o <b>Professor Imune</b>, Especialista Virtual em Vacinação da <b>Rede Drogal</b>.

Como posso apoiar você hoje na sala de vacinação?</div>
    </section>

    <footer class="input-bar">
      <label class="file-label" title="Enviar foto de carteira de vacinação, receita ou termômetro">
        📷 Foto
        <input type="file" id="imageInput" accept="image/*" style="display:none" onchange="onImageSelected(event)" />
      </label>
      <span id="imageChip" class="preview-chip"></span>
      <textarea id="msgInput" placeholder="Digite a dúvida clínica/operacional da sala de vacinas..." onkeydown="handleKey(event)"></textarea>
      <button class="send-btn" onclick="sendMessage()" title="Enviar">➤</button>
    </footer>
  </main>

  <script>
    let selectedImageBase64 = null;
    let selectedImageMime = "image/jpeg";

    document.getElementById('zapiWebhookUrl').textContent = window.location.origin + '/webhook/zapi';
    document.getElementById('evoWebhookUrl').textContent = window.location.origin + '/webhook/evolution';

    async function loadStatus() {
      try {
        const r = await fetch('/api/status');
        const d = await r.json();
        const badge = document.getElementById('geminiBadge');
        if (d.gemini_configured) {
          badge.className = 'badge ok';
          badge.textContent = 'Gemini Ativo (' + d.gemini_model + ')';
        } else {
          badge.className = 'badge warn';
          badge.textContent = 'Modo RAG Local';
        }
        const waBadge = document.getElementById('waBadge');
        if (d.zapi_configured) {
          waBadge.className = 'badge ok';
          waBadge.textContent = 'Z-API Conectada';
        } else if (d.evolution_configured) {
          waBadge.className = 'badge ok';
          waBadge.textContent = 'Evolution API Conectada';
        }
        document.getElementById('modelSelect').value = d.gemini_model || 'gemini-3.8-flash';
      } catch (e) {}
    }

    async function saveConfig() {
      const payload = {
        api_key: document.getElementById('apiKeyInput').value.trim(),
        model: document.getElementById('modelSelect').value,
        zapi_instance_id: document.getElementById('zapiInstanceInput').value.trim(),
        zapi_token: document.getElementById('zapiTokenInput').value.trim(),
        zapi_client_token: document.getElementById('zapiClientTokenInput').value.trim()
      };
      await fetch('/api/config', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
      });
      await loadStatus();
      alert('Configurações salvas com sucesso!');
    }

    function onImageSelected(ev) {
      const file = ev.target.files[0];
      if (!file) return;
      selectedImageMime = file.type || 'image/jpeg';
      const reader = new FileReader();
      reader.onload = () => {
        selectedImageBase64 = reader.result;
        const chip = document.getElementById('imageChip');
        chip.style.display = 'inline-flex';
        chip.textContent = '📎 ' + file.name;
      };
      reader.readAsDataURL(file);
    }

    function formatWhatsAppText(txt) {
      let safe = txt
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
      safe = safe.replace(/\\*\\*(.+?)\\*\\*/g, '<b>$1</b>');
      safe = safe.replace(/\\*(.+?)\\*/g, '<b>$1</b>');
      return safe;
    }

    function appendMessage(role, text) {
      const container = document.getElementById('messagesContainer');
      const div = document.createElement('div');
      div.className = 'msg ' + role;
      div.innerHTML = formatWhatsAppText(text);
      container.appendChild(div);
      container.scrollTop = container.scrollHeight;
      return div;
    }

    async function sendMessage(customText) {
      const input = document.getElementById('msgInput');
      const text = (customText !== undefined ? customText : input.value).trim();
      if (!text && !selectedImageBase64) return;

      input.value = '';
      appendMessage('user', text || '📷 [Imagem enviada para análise]');

      const loadingDiv = appendMessage('bot', '⏳ Digitando...');
      const apiKey = document.getElementById('apiKeyInput').value.trim();
      const model = document.getElementById('modelSelect').value;

      try {
        const r = await fetch('/api/chat', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            message: text,
            session_id: 'simulador-drogal',
            image_base64: selectedImageBase64,
            image_mime: selectedImageMime,
            api_key: apiKey || undefined,
            model: model
          })
        });
        const data = await r.json();
        loadingDiv.remove();
        appendMessage('bot', data.reply);
      } catch (e) {
        loadingDiv.textContent = '❌ Erro ao processar mensagem: ' + e;
      } finally {
        selectedImageBase64 = null;
        document.getElementById('imageInput').value = '';
        document.getElementById('imageChip').style.display = 'none';
      }
    }

    function askSample(q) {
      sendMessage(q);
    }

    async function resetChat() {
      await sendMessage('/reset');
    }

    function handleKey(ev) {
      if (ev.key === 'Enter' && !ev.shiftKey) {
        ev.preventDefault();
        sendMessage();
      }
    }

    loadStatus();
  </script>
</body>
</html>
"""


async def index_page(request: Request) -> HTMLResponse:
    return HTMLResponse(SIMULATOR_HTML)


routes = [
    Route("/", index_page, methods=["GET"]),
    Route("/health", health_check, methods=["GET"]),
    Route("/api/status", api_status, methods=["GET"]),
    Route("/api/config", api_config, methods=["POST"]),
    Route("/api/chat", api_chat, methods=["POST"]),
    Route("/webhook/evolution", webhook_evolution, methods=["POST"]),
    Route("/webhook/zapi", webhook_zapi, methods=["POST"]),
    Route("/webhook/meta", webhook_meta, methods=["GET", "POST"]),
    Route("/webhook/twilio", webhook_twilio, methods=["POST"]),
]

app = Starlette(debug=False, routes=routes)

if __name__ == "__main__":
    load_env_file()
    port = int(os.environ.get("PORT", "8000"))
    print("=" * 72)
    print("💉 PROFESSOR IMUNE — ESPECIALISTA VIRTUAL EM VACINAÇÃO (REDE DROGAL)")
    print(f"📚 Base carregada: {kb.stats()}")
    print(f"🌐 Simulador Web & Painel: http://localhost:{port}")
    print(f"📱 Webhook Z-API         : http://localhost:{port}/webhook/zapi")
    print(f"📱 Webhook Evolution API : http://localhost:{port}/webhook/evolution")
    print(f"📱 Webhook Meta Cloud API: http://localhost:{port}/webhook/meta")
    print("=" * 72)
    uvicorn.run(app, host="0.0.0.0", port=port)
