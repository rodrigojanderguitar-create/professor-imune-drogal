# -*- coding: utf-8 -*-
"""
Motor Principal do Agente "Professor Imune" — Especialista Virtual em Vacinação da Rede Drogal.
- Interação fluida, direta ao ponto, rica em detalhes técnicos e investigativa/questionadora
- Baseada integralmente nos arquivos da pasta Vacina (Guia de Bolso SBIm 2026 + Treinamento Vacinação Drogal)
- Integração com Google Gemini (gemini-3.8-flash / auto-detecção sem erro 404)
"""

import base64
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from knowledge_base import kb, normalize_text

BASE_DIR = Path(__file__).resolve().parent
SYSTEM_PROMPT_PATH = BASE_DIR / "system_prompt.md"
ENV_PATH = BASE_DIR / ".env"
SESSIONS_PATH = BASE_DIR / "sessions_memory.json"


def load_env_file() -> Dict[str, str]:
    env_vars: Dict[str, str] = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            env_vars[k] = v
            if v:
                os.environ[k] = v
    return env_vars


load_env_file()


def get_system_prompt() -> str:
    if SYSTEM_PROMPT_PATH.exists():
        return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    return "Você é o Professor Imune, Especialista Virtual em Vacinação da Rede Drogal."


def check_safety_alerts(user_message: str) -> List[str]:
    """Gatilhamento imediato quando há risco de erro de imunização."""
    norm = normalize_text(user_message)
    alerts: List[str] = []

    if ("qdenga" in norm or "dengue" in norm) and any(
        w in norm for w in ["junto", "juntas", "mesmo dia", "concomitante", "simultanea", "gripe", "influenza", "hpv", "febre amarela", "triplice", "outra vacina"]
    ):
        alerts.append(
            "🚨 *Atenção crítica sobre a Qdenga®:* Ela *não pode* ser aplicada no mesmo dia com nenhuma outra vacina. "
            "Pelo protocolo oficial da Rede Drogal, precisamos respeitar no mínimo *24 horas* de intervalo para vacinas inativadas/recombinantes e *30 dias* para outras vacinas atenuadas."
        )

    if any(w in norm for w in ["gestante", "gravida", "gravidez", "gestacao"]):
        if any(v in norm for v in ["qdenga", "dengue", "mmr", "m-m-r", "triplice viral", "sarampo", "varicela", "varivax", "varilrix", "proquad", "catapora"]):
            alerts.append(
                "🚨 *Cuidado crítico na gestação:* Vacinas vivas atenuadas (*Qdenga®*, *Tríplice Viral M-M-R II®*, *Varicela*, *ProQuad®*) "
                "são estritamente *contraindicadas em gestantes* (e a *Qdenga®* também é contraindicada durante a amamentação)."
            )
        if "arexvy" in norm:
            alerts.append(
                "🚨 *Alerta de segurança (VSR):* A *Arexvy®* é contraindicada em gestantes e lactantes (uso exclusivo para ≥60 anos). "
                "Para gestantes (entre 24 e 36 semanas), a única vacina VSR aprovada é a *Abrysvo®*!"
            )

    if any(w in norm for w in ["imunossuprimido", "imunossupressao", "quimioterapia", "hiv", "corticoide", "prednisona", "leucemia", "linfoma"]):
        if any(v in norm for v in ["qdenga", "dengue", "stamaril", "febre amarela", "mmr", "triplice viral", "varicela", "varivax", "proquad", "rotateq", "bcg"]):
            alerts.append(
                "🚨 *Alerta para paciente imunossuprimido:* Vacinas vivas atenuadas (*Qdenga®*, *Stamaril®*, *M-M-R II®*, *Varivax®/Varilrix®*, *ProQuad®*, *RotaTeq®*, *BCG*) "
                "são contraindicadas em casos de imunossupressão ou uso de corticoides em doses imunossupressoras (ex.: prednisona ≥20 mg/dia ou 2 mg/kg/dia por ≥14 dias)."
            )

    if ("rotateq" in norm or "rotavirus" in norm) and any(w in norm for w in ["intramuscular", "subcutanea", "injetar", "agulha", "1 ano", "9 meses", "8 meses"]):
        alerts.append(
            "🚨 *Cuidado com a RotaTeq®:* Ela é de administração *exclusivamente oral* (jamais injetar!) e tem janela rígida de idade entre *6 e 32 semanas* de vida."
        )

    if any(w in norm for w in ["desvio", "temperatura", "geladeira", "camara", "energia", "congelou", "graus"]) and any(
        w in norm for w in ["jogar fora", "descartar", "descarte", "lixo", "aplicar assim mesmo"]
    ):
        alerts.append(
            "🚨 *Alerta de Cadeia de Frio:* Não descarte os frascos nem aplique antes da avaliação técnica! "
            "Mantenha os imunobiológicos segregados em *QUARENTENA* sob refrigeração (+2°C a +8°C) e acione o suporte técnico/fabricantes."
        )

    return alerts


class ProfessorImuneAgent:
    """Agente Conversacional Fluido do Professor Imune."""

    def __init__(self) -> None:
        self.sessions: Dict[str, List[Dict[str, Any]]] = self._load_sessions()
        self._working_model_cache: Optional[str] = None

    def _load_sessions(self) -> Dict[str, List[Dict[str, Any]]]:
        if SESSIONS_PATH.exists():
            try:
                return json.loads(SESSIONS_PATH.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save_sessions(self) -> None:
        try:
            SESSIONS_PATH.write_text(
                json.dumps(self.sessions, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def reset_session(self, session_id: str) -> None:
        if session_id in self.sessions:
            del self.sessions[session_id]
            self._save_sessions()

    def get_api_key(self, override_key: Optional[str] = None) -> str:
        if override_key and override_key.strip():
            return override_key.strip()
        load_env_file()
        return (
            os.environ.get("GEMINI_API_KEY", "").strip()
            or os.environ.get("GOOGLE_API_KEY", "").strip()
        )

    def get_model_name(self, override_model: Optional[str] = None) -> str:
        if self._working_model_cache:
            return self._working_model_cache
        if override_model and override_model.strip():
            return override_model.strip()
        load_env_file()
        return os.environ.get("GEMINI_MODEL", "gemini-3.8-flash").strip()

    def chat(
        self,
        user_message: str,
        session_id: str = "default",
        image_bytes: Optional[bytes] = None,
        image_mime: str = "image/jpeg",
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        user_message = (user_message or "").strip()
        if not user_message and not image_bytes:
            return ("Olá! Aqui é o *Professor Imune*. Qual caso ou vacina estamos avaliando agora na loja?", [])

        if user_message.lower() in ("/reset", "/limpar", "limpar conversa", "reiniciar"):
            self.reset_session(session_id)
            return ("🔄 Conversa reiniciada! Pode mandar o próximo caso ou dúvida da sala de vacinas.", [])

        history = self.sessions.get(session_id, [])[-8:]

        # Combina a última mensagem do histórico na query de busca para manter o contexto em continuações de conversa
        search_query = user_message
        if history:
            prev_user_msgs = [m["text"] for m in history if m.get("role") == "user"]
            if prev_user_msgs:
                search_query = f"{prev_user_msgs[-1]} {user_message}"

        retrieved_docs = kb.search(search_query or "calendario vacinal", top_k=6)
        rag_context = kb.format_context_for_prompt(search_query or "calendario vacinal", top_k=6)
        safety_alerts = check_safety_alerts(user_message)

        key = self.get_api_key(api_key)
        model = self.get_model_name(model_name)

        reply: Optional[str] = None
        if key:
            reply = self._call_gemini_api(
                user_message=user_message,
                rag_context=rag_context,
                safety_alerts=safety_alerts,
                history=history,
                image_bytes=image_bytes,
                image_mime=image_mime,
                api_key=key,
                model=model,
            )

        if not reply:
            reply = self._generate_fluid_local_response(
                user_message=user_message,
                search_query=search_query,
                retrieved_docs=retrieved_docs,
                safety_alerts=safety_alerts,
                history=history,
            )

        history.append({"role": "user", "text": user_message or "[Imagem enviada]"})
        history.append({"role": "model", "text": reply})
        self.sessions[session_id] = history[-12:]
        self._save_sessions()

        return reply, retrieved_docs

    def _discover_available_models(self, api_key: str) -> List[str]:
        try:
            r = requests.get(
                f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}",
                timeout=10,
            )
            if r.status_code == 200:
                models_data = r.json().get("models", [])
                available = []
                for m in models_data:
                    methods = m.get("supportedGenerationMethods", [])
                    name = (m.get("name") or "").replace("models/", "")
                    if "generateContent" in methods and "gemini" in name:
                        available.append(name)
                preferred = sorted(
                    available,
                    key=lambda x: (
                        "flash" in x and "lite" not in x,
                        "3.8" in x or "3" in x or "2.5" in x,
                        x,
                    ),
                    reverse=True,
                )
                return preferred
        except Exception:
            pass
        return []

    def _call_gemini_api(
        self,
        user_message: str,
        rag_context: str,
        safety_alerts: List[str],
        history: List[Dict[str, Any]],
        image_bytes: Optional[bytes],
        image_mime: str,
        api_key: str,
        model: str,
    ) -> Optional[str]:
        system_instruction = get_system_prompt()

        alerts_block = ""
        if safety_alerts:
            alerts_block = (
                "\n\nPONTO CRÍTICO DE SEGURANÇA PARA DESTACAR:\n"
                + "\n".join(safety_alerts)
            )

        augmented_user_prompt = (
            f"TRECHOS DOS MATERIAIS OFICIAIS DO DIRETÓRIO 'VACINA' (GUIA DE BOLSO SBIm 2026 & TREINAMENTO REDE DROGAL):\n"
            f"{rag_context}"
            f"{alerts_block}\n\n"
            f"MENSAGEM DO FARMACÊUTICO:\n{user_message}\n\n"
            f"INSTRUÇÕES PARA SUA RESPOSTA:\n"
            f"- Responda de forma fluida, conversacional e direta ao ponto, sem usar templates engessados ou blocos numerados fixos.\n"
            f"- Preserve todos os detalhes técnicos relevantes dos materiais acima (nomes comerciais, doses, intervalos, via/local de aplicação, volume, coadministração e necessidade de receita na Rede Drogal).\n"
            f"- Seja questionador quando convém: faça perguntas clínicas naturais ao final para entender melhor o histórico ou condição do paciente e ajudar o farmacêutico a fechar a conduta com segurança."
        )

        contents: List[Dict[str, Any]] = []
        for msg in history:
            role = "user" if msg.get("role") == "user" else "model"
            contents.append({"role": role, "parts": [{"text": msg.get("text", "")}]})

        user_parts: List[Dict[str, Any]] = [{"text": augmented_user_prompt}]
        if image_bytes:
            b64_img = base64.b64encode(image_bytes).decode("ascii")
            user_parts.append({"inline_data": {"mime_type": image_mime, "data": b64_img}})

        contents.append({"role": "user", "parts": user_parts})

        payload = {
            "system_instruction": {"parts": [{"text": system_instruction}]},
            "contents": contents,
            "generationConfig": {
                "temperature": 0.3,
                "topP": 0.9,
                "maxOutputTokens": 2048,
            },
        }

        candidates_to_try = [model]
        for fallback_m in [
            "gemini-3.8-flash",
            "gemini-3.8-pro",
            "gemini-3-flash-preview",
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-2.0-flash",
        ]:
            if fallback_m not in candidates_to_try:
                candidates_to_try.append(fallback_m)

        tried = set()
        idx = 0
        while idx < len(candidates_to_try):
            m_name = candidates_to_try[idx].replace("models/", "").strip()
            idx += 1
            if not m_name or m_name in tried:
                continue
            tried.add(m_name)

            endpoints = [
                f"https://generativelanguage.googleapis.com/v1beta/models/{m_name}:generateContent?key={api_key}"
            ]
            if api_key.startswith("AQ."):
                endpoints.insert(
                    0,
                    f"https://aiplatform.googleapis.com/v1/publishers/google/models/{m_name}:generateContent?key={api_key}",
                )

            for url in endpoints:
                try:
                    resp = requests.post(url, json=payload, timeout=35)
                    if resp.status_code == 200:
                        data = resp.json()
                        cands = data.get("candidates", [])
                        if cands:
                            parts = cands[0].get("content", {}).get("parts", [])
                            text_out = "\n".join(p.get("text", "") for p in parts if "text" in p).strip()
                            if text_out:
                                self._working_model_cache = m_name
                                return text_out
                    elif resp.status_code == 404:
                        match = re.search(r"use\s+models/([a-zA-Z0-9\.\-_]+)", resp.text)
                        if match:
                            suggested = match.group(1).strip()
                            if suggested not in tried:
                                candidates_to_try.insert(idx, suggested)
                        elif len(tried) == 2:
                            for disc in self._discover_available_models(api_key)[:3]:
                                if disc not in tried:
                                    candidates_to_try.append(disc)
                except Exception:
                    continue

        return None

    def _generate_fluid_local_response(
        self,
        user_message: str,
        search_query: str,
        retrieved_docs: List[Dict[str, Any]],
        safety_alerts: List[str],
        history: List[Dict[str, Any]],
    ) -> str:
        """
        Motor Conversacional Local Fluido: responde de forma natural, rica em detalhes
        e investigativa com base no Guia de Bolso SBIm 2026 e no Treinamento Drogal,
        sem usar blocos padronizados engessados.
        """
        norm = normalize_text(search_query)
        norm_msg = normalize_text(user_message)
        paragraphs: List[str] = []

        if safety_alerts:
            paragraphs.extend(safety_alerts)

        # 1. Diálogo fluido sobre GESTANTE
        if any(w in norm for w in ["gestante", "gravida", "gravidez", "gestacao"]):
            # Verifica se é uma continuação sobre já ter tomado dTpa ou semana gestacional
            if any(w in norm_msg for w in ["ja tomou", "tomou dtpa", "tomou a dtpa", "fez dtpa"]):
                paragraphs.append(
                    "Ótimo! Se ela já tomou a *dTpa (Refortrix®)* nesta gestação, basta conferir na carteirinha a data da aplicação: "
                    "pelo protocolo do nosso Treinamento da Rede Drogal, respeitamos um intervalo mínimo de *2 semanas (14 dias)* entre a *dTpa* e a *Abrysvo® (VSR)*."
                )
                paragraphs.append(
                    "Passados esses 14 dias (e estando ela entre *24 e 36 semanas* de gestação, sendo ideal a partir de *28 semanas* pelo Guia SBIm 2026), você já pode aplicar a *Abrysvo®* (dose única de 0,5 mL IM no deltoide, *sem necessidade de receita*, mantendo ela em observação por 15 minutos na loja). "
                    "Se ela ainda não tiver tomado a vacina da gripe este ano, a *Influvac Tetra®* (0,5 mL IM) pode ser feita no mesmo dia da *Abrysvo®*, em braços diferentes."
                )
                paragraphs.append(
                    "Faz mais de 14 dias que ela aplicou a dTpa? E como está o esquema dela de *Hepatite B* e *Influenza*?"
                )
                return "\n\n".join(paragraphs)

            paragraphs.append(
                "Para uma gestante com *7 meses (~28 a 31 semanas)*, ela está justamente no momento mais estratégico do calendário da gestante (Guia de Bolso SBIm 2026 e Treinamento Rede Drogal):"
            )
            paragraphs.append(
                "• *Abrysvo® (VSR — Vírus Sincicial Respiratório):* É o período ideal para aplicar! Na bula/Anvisa ela é licenciada de *24 a 36 semanas*, e a SBIm 2026 recomenda preferencialmente a partir da *28ª semana* (7º mês) para transferir anticorpos ao bebê contra bronquiolite. É *dose única* (0,5 mL, via *Intramuscular no deltoide*), *não precisa de receita* na Rede Drogal e pede-se *15 minutos de observação* após a aplicação. Vale lembrar que, se o parto acontecer menos de 14 dias após a dose, o recém-nascido pode precisar do anticorpo monoclonal *Nirsevimabe (Beyfortus®)*.\n"
                "• *dTpa (Refortrix® / Refortrix® IPV):* Recomendada em *todas as gestações* a partir da *20ª semana* (0,5 mL IM no deltoide, *sem necessidade de receita*), mesmo que tenha tomado em gestação anterior. ⚠️ *Detalhe importante do treinamento Drogal:* respeite um *intervalo mínimo de 2 semanas (14 dias)* entre a *Abrysvo®* e a *dTpa*.\n"
                "• *Influenza Quadrivalente (Influvac Tetra®):* Dose única anual (0,5 mL IM no deltoide, *sem receita*). Pode ser coadministrada no mesmo dia com a *Abrysvo®* ou com a *dTpa* (em membros distintos).\n"
                "• *Hepatite B (Engerix® B)* e *Covid-19:* A Hepatite B entra no esquema de 3 doses (0-1-6 meses, IM) caso ela não seja vacinada ou tenha esquema incompleto; e a Covid-19 é recomendada 1 dose por gestação."
            )
            paragraphs.append(
                "Lembre-se apenas que na gestação são *proibidas as vacinas atenuadas* (*Qdenga®*, *Tríplice Viral M-M-R II®*, *Varicela*, *ProQuad®* e *Febre Amarela Stamaril®*), e que para VSR em gestante *nunca usamos Arexvy®* (que é exclusiva para ≥60 anos)."
            )
            paragraphs.append(
                "Para a gente definir qual aplicar hoje nela: *com quantas semanas exatas ela está no cartão de pré-natal e quais vacinas (como dTpa ou Gripe) ela já tomou nesta gestação?*"
            )
            return "\n\n".join(paragraphs)

        # 2. Diálogo fluido baseado nos documentos específicos recuperados do diretório Vacina
        if retrieved_docs:
            intro_parts: List[str] = []
            for doc in retrieved_docs[:3]:
                linhas = [ln.strip() for ln in doc["content"].splitlines() if ln.strip()]
                if linhas and linhas[0].startswith("[Calendário"):
                    linhas = linhas[1:]
                texto_limpo = "\n".join(linhas[:14])
                intro_parts.append(f"*{doc['source']}:*\n{texto_limpo}")

            paragraphs.append("\n\n".join(intro_parts))

        # 3. Perguntas clínicas investigativas contextuais (baseadas no tema da pergunta)
        if any(w in norm for w in ["qdenga", "dengue"]):
            paragraphs.append(
                "Para validarmos a aplicação com segurança: *qual é a idade do paciente, ele tomou alguma outra vacina nas últimas 24 horas (inativada) ou nos últimos 30 dias (atenuada)? E se for mulher em idade fértil, confirmou que não está gestante nem amamentando?*"
            )
        elif any(w in norm for w in ["bebe", "crianca", "meses", "anos", "atraso", "prevenar", "bexsero", "hexaxim", "infanrix", "rotateq", "proquad", "menveo"]):
            paragraphs.append(
                "Para eu te ajudar a fechar o esquema exato e o aprazamento das próximas doses: *qual é a idade exata da criança hoje e quais doses anteriores dessa vacina (ou vacinas nos últimos 30 dias) já constam na carteirinha?*"
            )
        elif any(w in norm for w in ["idoso", "shingrix", "efluelda", "arexvy", "pneumovax"]):
            paragraphs.append(
                "Me conta um detalhe para ajustarmos a recomendação: *qual a idade exata do paciente, ele já tomou alguma pneumocócica antes (como Prevenar 13, Vaxneuvance ou Pneumovax 23) e pretende aplicar mais de uma vacina hoje?*"
            )
        elif any(w in norm for w in ["geladeira", "temperatura", "camara", "cadeia de frio", "energia"]):
            paragraphs.append(
                "Qual foi a *temperatura mínima e máxima* registrada no termômetro e por quanto tempo aproximadamente a câmara ficou fora da faixa de +2°C a +8°C?"
            )
        else:
            paragraphs.append(
                "Se quiser, me passe a *idade do paciente*, se há alguma *comorbidade/alergia* e quais *vacinas ele tomou recentemente* que fechamos juntos a conduta para esse atendimento!"
            )

        return "\n\n".join(paragraphs)


agent = ProfessorImuneAgent()

if __name__ == "__main__":
    r, _ = agent.chat("Qual vacina aplicar em gestante com 7 meses de gestação?", session_id="teste-fluido")
    print(r)
