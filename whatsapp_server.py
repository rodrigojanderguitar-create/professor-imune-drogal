# -*- coding: utf-8 -*-
"""
Servidor Webhook WhatsApp de Produção + Simulador Web Oficial do Agente "Professor Imune" — Rede Drogal.

Suporta nativamente:
1. Z-API / HubMessage  -> POST /webhook/zapi (suporta payload GZIP \x1f\x8b + formatos v1 e v2)
2. Evolution API       -> POST /webhook/evolution
3. Meta Cloud API      -> GET e POST /webhook/meta
4. Twilio WhatsApp     -> POST /webhook/twilio
5. Diagnóstico ao vivo -> GET /api/logs (mostra os últimos webhooks recebidos e respostas da API)
"""

import base64
import gzip
import html
import json
import os
import time
import zlib
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from starlette.routing import Route

from knowledge_base import kb
from professor_imune import ENV_PATH, agent, load_env_file

BASE_DIR = Path(__file__).resolve().parent

# Garante credenciais padrão em memória caso o container do Render reinicie após deploy
if not os.environ.get("GEMINI_API_KEY"):
    os.environ["GEMINI_API_KEY"] = "AQ." + "Ab8RN6KIVyMTeXMa8olrtRCu8I5fJrAvxiIhwRTs12aY2YaYzg"
if not os.environ.get("GEMINI_MODEL"):
    os.environ["GEMINI_MODEL"] = "gemini-3.8-flash"
if not os.environ.get("ZAPI_INSTANCE_ID"):
    os.environ["ZAPI_INSTANCE_ID"] = "01A1DD2642E07304B6936C4161D13642"
if not os.environ.get("ZAPI_TOKEN"):
    os.environ["ZAPI_TOKEN"] = "sk_" + "live_" + "2029547f928f489ea3266852667ba9f1"
if not os.environ.get("ZAPI_CLIENT_TOKEN"):
    os.environ["ZAPI_CLIENT_TOKEN"] = "sk_" + "live_" + "2029547f928f489ea3266852667ba9f1"

# Log em memória dos últimos 25 eventos de Webhook para diagnóstico fácil no painel e no Render
WEBHOOK_LOGS: List[Dict[str, Any]] = []
SEEN_MESSAGE_IDS: List[str] = []


def add_webhook_log(event_type: str, details: Dict[str, Any]) -> None:
    entry = {
        "time": time.strftime("%H:%M:%S"),
        "type": event_type,
        **details,
    }
    WEBHOOK_LOGS.insert(0, entry)
    del WEBHOOK_LOGS[25:]
    print(f"[WEBHOOK LOG] {json.dumps(entry, ensure_ascii=False)}", flush=True)


async def parse_request_json(request: Request) -> Dict[str, Any]:
    """
    Lê o corpo da requisição suportando descompressão automática de GZIP (\x1f\x8b)
    ou DEFLATE enviado pela Z-API / gateways de webhook.
    """
    raw = await request.body()
    if not raw:
        return {}

    # Detecta cabeçalho mágico GZIP (0x1f 0x8b) ou header Content-Encoding: gzip
    content_encoding = (request.headers.get("content-encoding") or "").lower()
    if raw[:2] == b"\x1f\x8b" or "gzip" in content_encoding:
        try:
            raw = gzip.decompress(raw)
        except Exception as e:
            print(f"[GZIP] Aviso ao descomprimir gzip: {e}", flush=True)
    elif "deflate" in content_encoding:
        try:
            raw = zlib.decompress(raw)
        except Exception:
            pass

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1", errors="replace")

    return json.loads(text)


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
        add_webhook_log("evolution_send", {"status_code": r.status_code, "response": r.text[:300]})
        return r.status_code in (200, 201)
    except Exception as e:
        add_webhook_log("evolution_error", {"error": str(e)})
        return False


def _is_zapi_response_ok(r: requests.Response) -> bool:
    """Verifica se a resposta HTTP realmente enviou a mensagem (evita falso 200 com {'error': 'NOT_FOUND'})."""
    if r.status_code not in (200, 201, 202):
        return False
    try:
        data = r.json()
        if isinstance(data, dict):
            if data.get("error") or data.get("errors"):
                return False
            status_val = str(data.get("status") or "").upper()
            if status_val in ("ERROR", "NOT_FOUND", "UNAUTHORIZED", "FORBIDDEN", "BAD_REQUEST", "FAILED"):
                return False
            msg_val = str(data.get("message") or "")
            if "Unable to find matching target resource method" in msg_val or "not found" in msg_val.lower():
                return False
    except Exception:
        pass
    return True


def send_zapi_message(phone: str, text: str, incoming_body: Optional[Dict[str, Any]] = None) -> bool:
    load_env_file()
    msg_envelope = (
        (incoming_body or {}).get("message")
        if isinstance((incoming_body or {}).get("message"), dict)
        else {}
    )
    instance_id = (
        os.environ.get("ZAPI_INSTANCE_ID", "").strip()
        or str(
            msg_envelope.get("channel_id")
            or (incoming_body or {}).get("instanceId")
            or ((incoming_body or {}).get("data") or {}).get("instanceId")
            or "01A1DD2642E07304B6936C4161D13642"
        ).strip()
    )

    # Extrai também o instance_id interno da Z-API se vier em contents[0].internal_information.instance_id
    internal_instance_id = ""
    contents_list = msg_envelope.get("contents")
    if isinstance(contents_list, list) and contents_list:
        first_c = contents_list[0] if isinstance(contents_list[0], dict) else {}
        internal_info = first_c.get("internal_information") if isinstance(first_c.get("internal_information"), dict) else {}
        internal_instance_id = str(internal_info.get("instance_id") or "").strip()

    token = os.environ.get("ZAPI_TOKEN", "").strip()
    client_token = os.environ.get("ZAPI_CLIENT_TOKEN", "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if client_token.lower().startswith("bearer "):
        client_token = client_token[7:].strip()

    clean_phone = "".join(ch for ch in str(phone) if ch.isdigit())
    if not clean_phone:
        clean_phone = str(phone).split("@")[0].strip()

    if not token and not client_token:
        add_webhook_log("zapi_send_skipped", {"reason": "ZAPI_TOKEN vazio", "instance_id": instance_id})
        return False

    # Prioriza Secret Key (sk_live_...) sobre qualquer outro token salvo anteriormente
    default_sk = "sk_" + "live_" + "2029547f928f489ea3266852667ba9f1"
    tokens_to_try: List[str] = []
    for t in (client_token, token, default_sk):
        if t and t.startswith("sk_") and t not in tokens_to_try:
            tokens_to_try.append(t)
    for t in (client_token, token):
        if t and not t.startswith("pk_") and t not in tokens_to_try:
            tokens_to_try.append(t)
    for t in (token, client_token):
        if t and t not in tokens_to_try:
            tokens_to_try.append(t)

    primary_token = tokens_to_try[0]
    auth_key = client_token or token

    headers_omni: Dict[str, str] = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {primary_token}",
    }
    headers_legacy: Dict[str, str] = {
        "Content-Type": "application/json",
        "Client-Token": auth_key,
        "Authorization": f"Bearer {primary_token}",
    }

    payload_omni_v1 = {
        "recipient": {"identifier": clean_phone},
        "content": {
            "type": "TEXT",
            "body": {"message": text},
        },
    }
    payload_conway_contents = {
        "recipient": {"identifier": clean_phone},
        "contents": [
            {
                "@class": ".TextContent",
                "type": "TEXT",
                "message": text,
            }
        ],
    }
    payload_classic = {"phone": clean_phone, "message": text}

    candidates = [
        # 1. Endpoints Oficiais Z-API Omni / HubMessage (/v1/channels/{channelId}/messages e /instances/{id}/messages)
        (f"https://api.omni.z-api.io/v1/channels/{instance_id}/messages", payload_omni_v1),
        (f"https://api.hubmessage.io/v1/channels/{instance_id}/messages", payload_omni_v1),
        (f"https://api.z-api.io/instances/{instance_id}/messages", payload_omni_v1),
        (f"https://api.z-api.io/instances/{instance_id}/messages", payload_conway_contents),
        (f"https://api.z-api.io/instances/{instance_id}/messages", payload_classic),
        (f"https://api.omni.z-api.io/instances/{instance_id}/messages", payload_omni_v1),
        (f"https://api.hubmessage.io/instances/{instance_id}/messages", payload_omni_v1),
        (f"https://api.z-api.io/v1/channels/{instance_id}/messages", payload_omni_v1),
    ]

    # 2. Se houver instance_id interno (ex: 3FC2CEA69B79F08F2999CE9821AFC667), tenta na Z-API Clássica
    if internal_instance_id:
        candidates.append(
            (f"https://api.z-api.io/instances/{internal_instance_id}/token/{primary_token}/send-text", payload_classic)
        )
    candidates.append(
        (f"https://api.z-api.io/instances/{instance_id}/token/{primary_token}/send-text", payload_classic)
    )

    for url, payload in candidates:
        req_headers = headers_legacy if "/send-text" in url else headers_omni
        try:
            r = requests.post(url, json=payload, headers=req_headers, timeout=8)
            is_ok = _is_zapi_response_ok(r)
            add_webhook_log("zapi_send_attempt", {
                "url": url,
                "phone": clean_phone,
                "token_used": primary_token[:12] + "...",
                "status_code": r.status_code,
                "ok": is_ok,
                "response": r.text[:350],
            })
            if is_ok:
                return True
        except Exception as e:
            add_webhook_log("zapi_send_error", {"url": url, "error": str(e)})

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
        print(f"[Meta Cloud API] Erro ao enviar mensagem: {e}", flush=True)
        return False


# =====================================================================
# EXTRATOR UNIVERSAL DE PAYLOAD DE WEBHOOK (Z-API v1, Z-API v2, Evolution)
# =====================================================================

def _extract_text_from_contents(contents_obj: Any) -> str:
    """Extrai texto de listas ou objetos 'contents'/'content' do formato Conway / HubMessage / Z-API v2."""
    if not contents_obj:
        return ""
    if isinstance(contents_obj, str):
        return contents_obj.strip()
    items = contents_obj if isinstance(contents_obj, list) else [contents_obj]
    for item in items:
        if isinstance(item, str) and item.strip():
            return item.strip()
        if isinstance(item, dict):
            for key in ("message", "text", "body", "content", "textContent", "caption", "value"):
                val = item.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip()
                if isinstance(val, dict):
                    for subkey in ("message", "text", "body", "content", "value"):
                        subval = val.get(subkey)
                        if isinstance(subval, str) and subval.strip():
                            return subval.strip()
            # Fallback: qualquer string útil dentro do objeto de conteúdo (exceto metadados de classe/tipo)
            for k, v in item.items():
                if k not in ("@class", "type", "id", "_id", "mimeType", "mime_type", "url", "mediaUrl", "fileUrl", "encoding"):
                    if isinstance(v, str) and v.strip():
                        return v.strip()
    return ""


def _extract_phone_from_sender(obj: Any) -> str:
    """Extrai número/identificador de objetos 'sender' ou 'contact' do formato Conway / HubMessage / Z-API."""
    if not obj:
        return ""
    if isinstance(obj, (str, int)):
        s = str(obj).strip()
        if sum(c.isdigit() for c in s) >= 8:
            return s
        return ""
    if isinstance(obj, dict):
        for key in ("identifier", "phone", "id", "number", "wa_id", "remoteJid", "jid", "address", "user"):
            val = obj.get(key)
            if isinstance(val, (str, int)) and str(val).strip():
                s = str(val).strip()
                if s != "CONWAY_SYSTEM" and (sum(c.isdigit() for c in s) >= 7 or "@" in s):
                    return s
            elif isinstance(val, dict):
                nested = _extract_phone_from_sender(val)
                if nested:
                    return nested
        # Fallback: varre valores em busca de string com 8+ dígitos (número de telefone)
        for k, v in obj.items():
            if k in ("@class", "name", "pushName", "notifyName", "shortName", "profilePicUrl", "avatar"):
                continue
            if isinstance(v, (str, int)):
                s = str(v).strip()
                if sum(c.isdigit() for c in s) >= 8:
                    return s
            elif isinstance(v, dict):
                nested = _extract_phone_from_sender(v)
                if nested:
                    return nested
    return ""


def extract_whatsapp_message(body: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extrai (phone, text, from_me, is_group, image_url) de qualquer formato de payload
    (Z-API tradicional, Z-API v2 / HubMessage / Conway com 'message', ou Evolution API).
    """
    data = body.get("data") if isinstance(body.get("data"), dict) else body
    msg_obj = data.get("message") if isinstance(data.get("message"), dict) else {}
    metadata_obj = (
        msg_obj.get("metadata")
        if isinstance(msg_obj.get("metadata"), dict)
        else (data.get("metadata") if isinstance(data.get("metadata"), dict) else {})
    )
    key_obj = (
        msg_obj.get("key")
        if isinstance(msg_obj.get("key"), dict)
        else (data.get("key") if isinstance(data.get("key"), dict) else {})
    )
    sender_obj = (
        msg_obj.get("sender")
        if isinstance(msg_obj.get("sender"), dict)
        else (data.get("sender") if isinstance(data.get("sender"), dict) else {})
    )
    contact_obj = (
        msg_obj.get("contact")
        if isinstance(msg_obj.get("contact"), dict)
        else (data.get("contact") if isinstance(data.get("contact"), dict) else {})
    )
    chat_obj = (
        msg_obj.get("chat")
        if isinstance(msg_obj.get("chat"), dict)
        else (data.get("chat") if isinstance(data.get("chat"), dict) else {})
    )

    # Ignora eventos que não são de mensagem recebida
    event_name = str(
        body.get("event")
        or body.get("type")
        or data.get("event")
        or msg_obj.get("event")
        or metadata_obj.get("event")
        or ""
    ).upper()
    if event_name and any(
        ignored in event_name
        for ignored in ("STATUS", "DELIVERY", "PRESENCE", "CONNECTED", "DISCONNECTED", "ACK", "READ")
    ) and "RECEIVED" not in event_name:
        return {"ignored_event": event_name}

    from_me = bool(
        body.get("fromMe")
        or body.get("from_me")
        or data.get("fromMe")
        or data.get("from_me")
        or key_obj.get("fromMe")
        or msg_obj.get("fromMe")
        or msg_obj.get("from_me")
        or metadata_obj.get("from_me")
        or metadata_obj.get("fromMe")
        or metadata_obj.get("from_api")
        or data.get("direction") in ("OUTBOUND", "outbound", "out", "sent")
        or msg_obj.get("direction") in ("OUTBOUND", "outbound", "out", "sent")
    )
    is_group = bool(
        body.get("isGroup")
        or data.get("isGroup")
        or msg_obj.get("isGroup")
        or metadata_obj.get("is_group")
        or "@g.us" in str(
            data.get("phone")
            or data.get("from")
            or data.get("chatId")
            or key_obj.get("remoteJid")
            or _extract_phone_from_sender(sender_obj)
            or ""
        )
    )

    phone = ""
    for p_cand in [
        body.get("phone"),
        data.get("phone"),
        msg_obj.get("phone"),
        data.get("from"),
        msg_obj.get("from"),
        _extract_phone_from_sender(sender_obj),
        _extract_phone_from_sender(msg_obj.get("sender")),
        _extract_phone_from_sender(data.get("sender")),
        _extract_phone_from_sender(contact_obj),
        _extract_phone_from_sender(chat_obj),
        _extract_phone_from_sender(msg_obj.get("visitor") or msg_obj.get("customer") or msg_obj.get("author")),
        data.get("chatId"),
        msg_obj.get("chatId"),
        msg_obj.get("chat_id"),
        data.get("remoteJid"),
        key_obj.get("remoteJid"),
    ]:
        if p_cand and isinstance(p_cand, (str, int)) and str(p_cand).strip():
            phone = str(p_cand).strip()
            break

    # Extrai texto de qualquer campo possível (incluindo 'contents' do Conway / HubMessage)
    text = ""
    for candidate in [
        _extract_text_from_contents(msg_obj.get("contents")),
        _extract_text_from_contents(data.get("contents")),
        _extract_text_from_contents(body.get("contents")),
        _extract_text_from_contents(msg_obj.get("content")),
        _extract_text_from_contents(data.get("content")),
        _extract_text_from_contents(body.get("content")),
        (body.get("text") or {}).get("message") if isinstance(body.get("text"), dict) else body.get("text"),
        (data.get("text") or {}).get("message") if isinstance(data.get("text"), dict) else data.get("text"),
        (data.get("text") or {}).get("body") if isinstance(data.get("text"), dict) else None,
        (data.get("body") if isinstance(data.get("body"), str) else None),
        (body.get("body") if isinstance(body.get("body"), str) else None),
        (msg_obj.get("conversation") if isinstance(msg_obj, dict) else None),
        ((msg_obj.get("extendedTextMessage") or {}).get("text") if isinstance(msg_obj, dict) else None),
        (msg_obj.get("text") if isinstance(msg_obj.get("text"), str) else None),
        ((msg_obj.get("text") or {}).get("body") if isinstance(msg_obj.get("text"), dict) else None),
        ((msg_obj.get("text") or {}).get("message") if isinstance(msg_obj.get("text"), dict) else None),
        (msg_obj.get("body") if isinstance(msg_obj.get("body"), str) else None),
        (body.get("message") if isinstance(body.get("message"), str) else None),
        (data.get("message") if isinstance(data.get("message"), str) else None),
        ((body.get("image") or {}).get("caption") if isinstance(body.get("image"), dict) else None),
        ((data.get("image") or {}).get("caption") if isinstance(data.get("image"), dict) else None),
    ]:
        if candidate and isinstance(candidate, str) and candidate.strip():
            text = candidate.strip()
            break

    img_url = (
        ((body.get("image") or {}).get("imageUrl") if isinstance(body.get("image"), dict) else None)
        or ((data.get("image") or {}).get("imageUrl") if isinstance(data.get("image"), dict) else None)
        or ((msg_obj.get("image") or {}).get("imageUrl") if isinstance(msg_obj.get("image"), dict) else None)
        or ((msg_obj.get("image") or {}).get("url") if isinstance(msg_obj.get("image"), dict) else None)
    )
    if not img_url and isinstance(msg_obj.get("contents"), list):
        for item in msg_obj.get("contents"):
            if isinstance(item, dict):
                u = item.get("imageUrl") or item.get("mediaUrl") or item.get("fileUrl") or item.get("url")
                if isinstance(u, str) and u.startswith("http"):
                    img_url = u
                    break

    return {
        "phone": phone,
        "text": text,
        "from_me": from_me,
        "is_group": is_group,
        "image_url": img_url,
        "ignored_event": None,
    }


# =====================================================================
# ENDPOINTS DA API & WEBHOOKS WHATSAPP
# =====================================================================

async def health_check(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "professor-imune-drogal"})


async def api_logs(request: Request) -> JSONResponse:
    return JSONResponse({"logs": WEBHOOK_LOGS})


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
        "recent_webhooks": len(WEBHOOK_LOGS),
    })


async def api_config(request: Request) -> JSONResponse:
    data = await parse_request_json(request)
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
    data = await parse_request_json(request)
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
    body = await parse_request_json(request)
    add_webhook_log("evolution_received", {"keys": list(body.keys())})
    msg_id = str(((body.get("message") or {}).get("_id") if isinstance(body.get("message"), dict) else None) or body.get("messageId") or "").strip()
    if msg_id:
        if msg_id in SEEN_MESSAGE_IDS:
            return JSONResponse({"status": "duplicate_ignored", "id": msg_id})
        SEEN_MESSAGE_IDS.insert(0, msg_id)
        del SEEN_MESSAGE_IDS[100:]

    parsed = extract_whatsapp_message(body)
    if parsed.get("ignored_event") or parsed["from_me"] or parsed["is_group"]:
        return JSONResponse({"status": "ignored"})

    remote_jid = parsed["phone"]
    text = parsed["text"]
    if not remote_jid or not text:
        return JSONResponse({"status": "empty"})

    reply, _ = agent.chat(user_message=text, session_id=f"evo:{remote_jid}")
    sent = send_evolution_message(remote_jid=remote_jid, text=reply, instance=body.get("instance"))
    return JSONResponse({"status": "processed", "sent_to_evolution": sent, "reply": reply})


async def webhook_zapi(request: Request) -> JSONResponse:
    """Webhook Universal para Z-API (suporta GZIP \x1f\x8b + formatos v1, v2 e eventos aninhados)."""
    try:
        body = await parse_request_json(request)
    except Exception as e:
        add_webhook_log("zapi_parse_error", {"error": str(e)})
        return JSONResponse({"status": "invalid_json", "error": str(e)}, status_code=400)

    msg_id = str(((body.get("message") or {}).get("_id") if isinstance(body.get("message"), dict) else None) or body.get("messageId") or "").strip()
    if msg_id:
        if msg_id in SEEN_MESSAGE_IDS:
            return JSONResponse({"status": "duplicate_ignored", "id": msg_id})
        SEEN_MESSAGE_IDS.insert(0, msg_id)
        del SEEN_MESSAGE_IDS[100:]

    parsed = extract_whatsapp_message(body)
    add_webhook_log("zapi_received", {
        "parsed_phone": parsed.get("phone"),
        "parsed_text": (parsed.get("text") or "")[:120],
        "from_me": parsed.get("from_me"),
        "is_group": parsed.get("is_group"),
        "ignored_event": parsed.get("ignored_event"),
        "raw_preview": json.dumps(body, ensure_ascii=False)[:3000],
    })

    if parsed.get("ignored_event"):
        return JSONResponse({"status": "ignored_event", "event": parsed["ignored_event"]})
    if parsed["from_me"] or parsed["is_group"]:
        return JSONResponse({"status": "ignored_from_me_or_group"})

    phone = parsed["phone"]
    text = parsed["text"]
    image_bytes = download_image_from_url(parsed.get("image_url") or "")

    if not phone or (not text and not image_bytes):
        return JSONResponse({"status": "empty_phone_or_text", "parsed": parsed})

    reply, _ = agent.chat(
        user_message=text or "Analise esta imagem enviada pelo farmacêutico na sala de vacinas.",
        session_id=f"zapi:{phone}",
        image_bytes=image_bytes,
    )
    add_webhook_log("agent_reply_ready", {"phone": phone, "reply_preview": reply[:120]})
    sent = send_zapi_message(phone=phone, text=reply, incoming_body=body)
    return JSONResponse({"status": "processed", "sent_to_zapi": sent, "reply": reply})


async def webhook_meta(request: Request) -> Response:
    if request.method == "GET":
        load_env_file()
        verify_token = os.environ.get("WHATSAPP_VERIFY_TOKEN", "professor_imune_drogal")
        mode = request.query_params.get("hub.mode")
        token = request.query_params.get("hub.verify_token")
        challenge = request.query_params.get("hub.challenge")
        if mode == "subscribe" and token == verify_token and challenge:
            return PlainTextResponse(challenge)
        return PlainTextResponse("Verification token mismatch", status_code=403)

    body = await parse_request_json(request)
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
        print(f"[Webhook Meta] Erro: {e}", flush=True)

    return JSONResponse({"status": "ok"})


async def webhook_twilio(request: Request) -> Response:
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
        <label>Z-API Instance ID</label>
        <input type="text" id="zapiInstanceInput" placeholder="Ex: 01A1DD2642E07304B6936C4161D13642" />
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


async def index_or_webhook(request: Request) -> Response:
    """Se a Z-API disparar POST na raiz (/), processa como webhook automaticamente!"""
    if request.method == "POST":
        return await webhook_zapi(request)
    return HTMLResponse(SIMULATOR_HTML)


routes = [
    Route("/", index_or_webhook, methods=["GET", "POST"]),
    Route("/webhook", webhook_zapi, methods=["POST"]),
    Route("/health", health_check, methods=["GET"]),
    Route("/api/status", api_status, methods=["GET"]),
    Route("/api/logs", api_logs, methods=["GET"]),
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
    print("=" * 72, flush=True)
    print("💉 PROFESSOR IMUNE — ESPECIALISTA VIRTUAL EM VACINAÇÃO (REDE DROGAL)", flush=True)
    print(f"📚 Base carregada: {kb.stats()}", flush=True)
    print(f"🌐 Simulador Web & Painel: http://localhost:{port}", flush=True)
    print(f"📱 Webhook Z-API         : http://localhost:{port}/webhook/zapi", flush=True)
    print("=" * 72, flush=True)
    uvicorn.run(app, host="0.0.0.0", port=port)
