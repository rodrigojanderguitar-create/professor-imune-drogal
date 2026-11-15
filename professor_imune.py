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
        return os.environ.get("GEMINI_MODEL", "gemini-3.6-flash").strip()

    @staticmethod
    def _format_for_whatsapp(text: str) -> str:
        """Padroniza negrito (** -> *) e títulos markdown para leitura limpa no WhatsApp."""
        if not text:
            return ""
        # Converte **texto** em *texto* (padrão WhatsApp)
        cleaned = re.sub(r"\*\*([^*\n]+)\*\*", r"*\1*", text)
        # Converte títulos ### Título em *Título*
        cleaned = re.sub(r"(?m)^#{1,4}\s*(.+)$", r"*\1*", cleaned)
        return cleaned.strip()

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

        # Combina as últimas mensagens do usuário na query de busca para preservar o perfil do paciente na conversa
        search_query = user_message
        prev_user_msgs: List[str] = []
        if history:
            prev_user_msgs = [m["text"] for m in history if m.get("role") == "user" and m.get("text")]
            if prev_user_msgs:
                search_query = " ".join(prev_user_msgs[-3:] + [user_message])

        retrieved_docs = kb.search(search_query or "calendario vacinal", top_k=6)
        rag_context = kb.format_context_for_prompt(search_query or "calendario vacinal", top_k=6)
        safety_alerts = check_safety_alerts(search_query)

        key = self.get_api_key(api_key)
        model = self.get_model_name(model_name)

        reply: Optional[str] = None
        if key:
            reply = self._call_gemini_api(
                user_message=user_message,
                prev_user_msgs=prev_user_msgs,
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

        reply = self._format_for_whatsapp(reply)

        history.append({"role": "user", "text": user_message or "[Imagem enviada]"})
        history.append({"role": "model", "text": reply})
        self.sessions[session_id] = history[-12:]
        self._save_sessions()

        return reply, retrieved_docs

    def _discover_available_models(self, api_key: str) -> List[str]:
        try:
            r = requests.get(
                f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}",
                timeout=8,
            )
            if r.status_code == 200:
                models_data = r.json().get("models", [])
                available = []
                for m in models_data:
                    methods = m.get("supportedGenerationMethods", [])
                    name = (m.get("name") or "").replace("models/", "")
                    if "generateContent" in methods and "gemini" in name and "tts" not in name and "image" not in name:
                        available.append(name)
                preferred = sorted(
                    available,
                    key=lambda x: (
                        x in ("gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-3-flash-preview"),
                        "flash" in x and "lite" not in x,
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
        prev_user_msgs: List[str],
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

        convo_summary_block = ""
        if prev_user_msgs:
            convo_summary_block = (
                "\nCONTEXTO ACUMULADO DO CASO ATUAL (MENSAGENS ANTERIORES DO FARMACÊUTICO NESTA CONVERSA):\n"
                + "\n".join(f"- {m}" for m in prev_user_msgs[-3:])
                + "\n"
            )

        augmented_user_prompt = (
            f"TRECHOS DOS MATERIAIS OFICIAIS DO DIRETÓRIO 'VACINA' (GUIA DE BOLSO SBIm 2026 & TREINAMENTO REDE DROGAL):\n"
            f"{rag_context}"
            f"{alerts_block}\n"
            f"{convo_summary_block}\n"
            f"NOVA MENSAGEM DO FARMACÊUTICO:\n{user_message}\n\n"
            f"INSTRUÇÕES PARA SUA RESPOSTA:\n"
            f"- Mantenha total continuidade com o paciente que já está sendo avaliado na conversa (nunca mude a idade do paciente nem despeje texto bruto de tabela/OCR).\n"
            f"- Se esta já for uma mensagem de continuação da conversa, NÃO repita toda a explicação que você já enviou no turno anterior; responda diretamente ao novo dado trazido pelo farmacêutico (ex.: 'não tem cartão de vacina') avançando para o fechamento prático das doses de hoje.\n"
            f"- Se o farmacêutico informar que o paciente 'não tem cartão de vacina' (sem comprovação vacinal), explique de forma clara que pela diretriz SBIm/PNI ele é considerado não vacinado e monte a conduta prática de quais vacinas aplicar hoje na loja e como agendar as próximas.\n"
            f"- Responda de forma fluida, conversacional e direta ao ponto, usando apenas um asterisco (*texto*) para negrito no padrão WhatsApp.\n"
            f"- Preserve todos os detalhes técnicos relevantes (nomes comerciais na Drogal, número de doses, intervalos, via/local de aplicação, volume, coadministração/intervalo da Qdenga® e necessidade de receita).\n"
            f"- Ao final, faça uma pergunta curta e prática para ajudar o farmacêutico a fechar o atendimento no balcão."
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

        base_payload = {
            "system_instruction": {"parts": [{"text": system_instruction}]},
            "contents": contents,
            "generationConfig": {
                "temperature": 0.3,
                "topP": 0.9,
                "maxOutputTokens": 8192,
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }

        # Prioriza os modelos Gemini 3.x rápidos e estáveis na API generativelanguage
        candidates_to_try: List[str] = []
        if self._working_model_cache:
            candidates_to_try.append(self._working_model_cache)
        for fallback_m in [
            "gemini-3.6-flash",
            "gemini-3.5-flash",
            "gemini-3.1-flash-lite",
            "gemini-3-flash-preview",
            "gemini-flash-latest",
            model,
        ]:
            if fallback_m and fallback_m not in candidates_to_try:
                candidates_to_try.append(fallback_m)

        tried = set()
        dead_hosts = set()
        idx = 0
        while idx < len(candidates_to_try):
            m_name = candidates_to_try[idx].replace("models/", "").strip()
            idx += 1
            if not m_name or m_name in tried:
                continue
            tried.add(m_name)

            endpoints = [
                ("generativelanguage", f"https://generativelanguage.googleapis.com/v1beta/models/{m_name}:generateContent?key={api_key}"),
            ]
            if api_key.startswith("AQ."):
                endpoints.append(
                    ("aiplatform", f"https://aiplatform.googleapis.com/v1/publishers/google/models/{m_name}:generateContent?key={api_key}"),
                )

            for host_tag, url in endpoints:
                if host_tag in dead_hosts:
                    continue
                try:
                    resp = requests.post(url, json=base_payload, timeout=14)
                    # Caso algum modelo específico não aceite thinkingConfig (HTTP 400), tenta sem thinkingConfig
                    if resp.status_code == 400 and "thinking" in resp.text.lower():
                        fallback_payload = {
                            "system_instruction": base_payload["system_instruction"],
                            "contents": base_payload["contents"],
                            "generationConfig": {
                                "temperature": 0.3,
                                "topP": 0.9,
                                "maxOutputTokens": 8192,
                            },
                        }
                        resp = requests.post(url, json=fallback_payload, timeout=14)

                    if resp.status_code == 200:
                        data = resp.json()
                        cands = data.get("candidates", [])
                        if cands:
                            parts = cands[0].get("content", {}).get("parts", [])
                            text_out = "\n".join(
                                p.get("text", "")
                                for p in parts
                                if "text" in p and not p.get("thought")
                            ).strip()
                            if text_out:
                                self._working_model_cache = m_name
                                return text_out
                    elif resp.status_code in (401, 403):
                        dead_hosts.add(host_tag)
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
        Motor Conversacional Local Fluido: responde de forma 100% natural, clínica
        e contextualizada (sem jamais despejar OCR bruto de páginas do PDF).
        """
        norm = normalize_text(search_query)
        norm_msg = normalize_text(user_message)
        paragraphs: List[str] = []

        if safety_alerts:
            paragraphs.extend(safety_alerts)

        age_months_match = re.search(r"\b(\d+)\s*mes(?:es)?\b", norm)
        age_years_matches = [int(m) for m in re.findall(r"\b(\d+)\s*anos?\b", norm)]
        is_gestante = any(w in norm for w in ["gestante", "gravida", "gravidez", "gestacao"])
        is_adulto = (
            any(w in norm for w in ["adulto", "adulta", "homem", "mulher"])
            or any(20 <= y <= 59 for y in age_years_matches)
        )
        is_idoso = (
            any(w in norm for w in ["idoso", "idosa", "terceira idade"])
            or any(y >= 60 for y in age_years_matches)
        )
        is_crianca = (
            bool(age_months_match)
            or any(w in norm for w in ["bebe", "crianca", "recem nascido", "lactente"])
            or any(0 <= y <= 10 for y in age_years_matches)
        )
        sem_cartao = any(
            expr in norm
            for expr in [
                "nao tem o cartao",
                "nao tem cartao",
                "sem cartao",
                "sem carteira",
                "nao tem carteira",
                "perdeu o cartao",
                "sem comprovacao",
            ]
        )

        # 1. Diálogo fluido sobre GESTANTE
        if is_gestante:
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
                "Para uma gestante no terceiro trimestre (*~28 semanas / 7 meses*), ela está justamente na janela mais importante do Calendário da Gestante (Guia SBIm 2026 e Treinamento Rede Drogal):"
            )
            paragraphs.append(
                "• *Abrysvo® (VSR — Vírus Sincicial Respiratório):* Indicada entre *24 e 36 semanas* de gestação (preferencialmente a partir da *28ª semana* pela SBIm 2026) para proteger o bebê contra bronquiolite. É *dose única* (0,5 mL, via *IM no deltoide*), *sem necessidade de receita* na Drogal, com *15 minutos de observação* pós-aplicação.\n"
                "• *dTpa (Refortrix® / Refortrix® IPV):* Recomendada em *todas as gestações* a partir da *20ª semana* (0,5 mL IM no deltoide, *sem receita*). ⚠️ *Regra de ouro Drogal:* respeitar *intervalo mínimo de 14 dias (2 semanas)* entre a *Abrysvo®* e a *dTpa*.\n"
                "• *Influenza Quadrivalente (Influvac Tetra®):* Dose única anual (0,5 mL IM no deltoide, *sem receita*), podendo ser aplicada no mesmo dia com a *Abrysvo®* ou *dTpa*.\n"
                "• *Hepatite B (Engerix® B)* e *Covid-19:* Completar ou iniciar esquema de 3 doses (0-1-6 meses, IM) se não comprovado."
            )
            paragraphs.append(
                "Lembrando que na gestação são *estritamente contraindicadas as vacinas vivas atenuadas* (*Qdenga®*, *Tríplice Viral M-M-R II®*, *Varicela*, *ProQuad®* e *Febre Amarela*), e nunca usamos *Arexvy®* em gestante."
            )
            paragraphs.append(
                "Para definirmos qual aplicar hoje: *com quantas semanas exatas ela está e ela já tomou a dTpa nesta gestação?*"
            )
            return "\n\n".join(paragraphs)

        # 2. Diálogo fluido sobre ADULTO (20 a 59 anos) — incluindo caso SEM CARTÃO DE VACINA
        if is_adulto and not is_crianca:
            idade_txt = f"de {age_years_matches[0]} anos" if age_years_matches else "adulto (20 a 59 anos)"
            if sem_cartao:
                paragraphs.append(
                    f"Perfeito, colega! Como esse paciente *{idade_txt} não tem o cartão de vacina* (sem comprovação vacinal), não tem comorbidades e não tomou vacinas recentemente, a regra oficial da *SBIm 2026 e do PNI* é clara: *paciente sem registro comprovado é considerado não vacinado*, e iniciamos o esquema de proteção do zero com total segurança."
                )
                paragraphs.append(
                    "Aqui está o plano prático das vacinas recomendadas para ele na *Rede Drogal* (todas *sem necessidade de receita* para essa faixa etária):\n\n"
                    "1. *dTpa (Refortrix® — Tríplice Bacteriana Acelular):* Sem comprovação vacinal, o esquema completo são 3 doses (*0 - 2 - 4 a 8 meses*), sendo a *1ª dose hoje com dTpa (Refortrix®)* (0,5 mL, *IM no deltoide*) e as seguintes com dT/dTpa.\n"
                    "2. *Hepatite B (Engerix® B) ou Hepatite A+B (Twinrix®):* 3 doses no esquema *0 - 1 - 6 meses* (1,0 mL, *IM no deltoide*). Na Drogal, a *Twinrix®* é excelente opção por já cobrir Hepatite A e B numa única aplicação.\n"
                    "3. *Tríplice Viral — Sarampo, Caxumba e Rubéola (M-M-R II®):* Para adulto de 35 anos sem cartão, aplicar *1 a 2 doses* (intervalo mínimo de 30 dias entre doses), *0,5 mL via Subcutânea (SC)*.\n"
                    "4. *Dengue (Qdenga®):* 2 doses com intervalo de *3 meses (0 e 3 meses)*, *0,5 mL via Subcutânea (SC)*. ⚠️ *Regra crítica na Drogal:* a *Qdenga® não pode ser feita no mesmo dia com nenhuma outra vacina* (exige *24h de intervalo* para vacinas inativadas e *30 dias* para vacinas atenuadas como Tríplice Viral e Febre Amarela).\n"
                    "5. *Influenza Quadrivalente (Influvac Tetra®)* e *HPV Nonavalente (Gardasil 9®):* A Gripe é *dose única anual* (0,5 mL IM) e a *Gardasil 9®* (licenciada de 9 a 45 anos sem receita) são *3 doses (0 - 2 - 6 meses, 0,5 mL IM)*.\n"
                    "6. *Febre Amarela (Stamaril®):* 1 dose (*0,5 mL SC*) caso ele não tenha comprovante e resida ou viaje para área com recomendação."
                )
                paragraphs.append(
                    "💡 *Como organizar a aplicação dele hoje no balcão (2 opções práticas):*\n"
                    "• *Opção 1 (Combo Proteção Ampla hoje):* Aplicar hoje no mesmo dia *Refortrix® (dTpa)* + *Twinrix® (Hep A+B)* + *M-M-R II® (Tríplice Viral)* + *Influvac Tetra® (Gripe)* (e/ou *Gardasil 9®*), que podem ser feitas juntas em locais anatômicos diferentes, e agendar a *Qdenga®* para daqui a *30 dias* (respeitando o intervalo da M-M-R II®).\n"
                    "• *Opção 2 (Prioridade Dengue hoje):*Se o foco principal dele hoje for começar a *Qdenga®*, aplique *apenas a Qdenga® hoje*, agende as inativadas (*Refortrix®*, *Twinrix®*, *Influvac Tetra®*, *Gardasil 9®*) para daqui a *24 a 48 horas*, e deixe a *Tríplice Viral (M-M-R II®)* para *30 dias depois*."
                )
                paragraphs.append(
                    "Qual dessas duas opções faz mais sentido para o perfil e preferência dele hoje na loja: começar pelo *Combo de atualização geral* ou fazer a *Qdenga® isolada hoje*?"
                )
                return "\n\n".join(paragraphs)

            paragraphs.append(
                f"Fala, colega! Para um paciente *{idade_txt}*, o *Calendário do Adulto (20 a 59 anos) do Guia SBIm 2026* na *Rede Drogal* foca nas seguintes vacinas principais (todas *sem necessidade de receita médica* nessa idade):"
            )
            paragraphs.append(
                "• *dTpa (Refortrix®):* 1 dose de reforço a cada 10 anos (ou iniciar esquema de 3 doses *0 - 2 - 6 meses* se não tiver comprovação prévia). Via *IM no deltoide (0,5 mL)*.\n"
                "• *Tríplice Viral (M-M-R II®):* Garante proteção contra Sarampo, Caxumba e Rubéola (até 29 anos são 2 doses; de 30 a 59 anos, 1 a 2 doses na vida com intervalo mínimo de 30 dias). Via *Subcutânea (0,5 mL)*.\n"
                "• *Hepatite B (Engerix® B — 3 doses: 0-1-6 meses)* e *Hepatite A (Vaqta®/Havrix® — 2 doses: 0-6 meses)*, ou a combinada *Hepatite A+B (Twinrix® — 3 doses: 0-1-6 meses)*, via *IM no deltoide*.\n"
                "• *Dengue (Qdenga® — 4 a 60 anos):* 2 doses com intervalo de *3 meses (0 e 3 meses)*, via *Subcutânea (0,5 mL)*. ⚠️ *Atenção:* não pode ser coadministrada no mesmo dia com nenhuma outra vacina (intervalo de *24h para inativadas* e *30 dias para atenuadas*).\n"
                "• *HPV Nonavalente (Gardasil 9® — até 45 anos):* 3 doses (*0 - 2 - 6 meses*), *0,5 mL IM no deltoide*.\n"
                "• *Influenza Quadrivalente (Influvac Tetra®):* Dose única anual (*0,5 mL IM*).\n"
                "• *Febre Amarela (Stamaril® — 0,5 mL SC)* e *Meningocócicas ACWY (Menveo®/Nimenrix® — dose única IM)* / *B (Bexsero® — 2 doses IM)*."
            )
            paragraphs.append(
                "Para montarmos o esquema exato de hoje: *ele trouxe o cartão de vacinas (ou tem registro no Meu SUS Digital), possui alguma comorbidade e tomou alguma vacina nos últimos 30 dias?*"
            )
            return "\n\n".join(paragraphs)

        # 3. Diálogo fluido sobre IDOSO (60+ anos)
        if is_idoso:
            paragraphs.append(
                "Para o paciente *idoso (60+ anos)*, o *Calendário do Idoso SBIm 2026* na *Rede Drogal* prioriza a proteção respiratória e contra Herpes Zóster:"
            )
            paragraphs.append(
                "• *Influenza Quadrivalente de Alta Dose (Efluelda®):* Preferencial para ≥60 anos (dose única anual, *0,7 mL IM no deltoide*, *sem receita*), ou *Influvac Tetra®* (0,5 mL IM).\n"
                "• *Herpes Zóster Inativada (Shingrix®):* Rotina para ≥50 anos, em *2 doses* com intervalo de *2 meses (0 e 2 meses)*, *0,5 mL IM no deltoide*, *sem necessidade de receita*. Pode ser aplicada no mesmo dia com *Influvac Tetra®*, *Pneumovax 23®* ou *dTpa (Refortrix®)*.\n"
                "• *Pneumocócicas:* *Prevenar 20® (VPC20)* em *dose única (0,5 mL IM)* (dispensa VPP23 posterior), OU esquema sequencial iniciando com *Vaxneuvance® (VPC15)* / *Prevenar 13®* seguida de *Pneumovax 23® (VPP23)* após 6 a 12 meses.\n"
                "• *VSR (Arexvy® ou Abrysvo®):* Dose única (*0,5 mL IM no deltoide*) para prevenção de doença respiratória inferior por VSR (na Drogal, a *Arexvy®* pede prescrição médica).\n"
                "• *dTpa (Refortrix®)* e *Hepatite B (Engerix® B):* Reforço de dTpa a cada 10 anos e esquema de Hepatite B (0-1-6 meses) se não vacinado."
            )
            paragraphs.append(
                "Qual é a idade exata do paciente, quais vacinas ele já tomou recentemente e ele tem alguma prescrição médica em mãos?"
            )
            return "\n\n".join(paragraphs)

        # 4. Perguntas clínicas investigativas contextuais sem despejar OCR bruto
        if any(w in norm for w in ["qdenga", "dengue"]):
            paragraphs.append(
                "A *Qdenga®* (vacina dengue atenuada, licenciada de *4 a 60 anos*, *sem receita* na Drogal) é aplicada em *2 doses com intervalo de 3 meses (0 e 3 meses)*, volume de *0,5 mL exclusivamente por via Subcutânea (SC)*."
            )
            paragraphs.append(
                "🚨 *Regra de ouro da Rede Drogal:* A *Qdenga® não pode ser administrada no mesmo dia com nenhuma outra vacina*. Respeite o intervalo mínimo de *24 horas* para vacinas inativadas/recombinantes e *30 dias* para outras vacinas vivas atenuadas (*Tríplice Viral*, *Febre Amarela*, *Varicela*, *ProQuad®*). Ela é contraindicada em gestantes, lactantes e imunossuprimidos."
            )
            paragraphs.append(
                "Qual é a idade do paciente e ele tomou ou pretende tomar alguma outra vacina nesta semana?"
            )
        elif is_crianca or any(w in norm for w in ["atraso", "prevenar", "bexsero", "hexaxim", "infanrix", "rotateq", "proquad", "menveo"]):
            paragraphs.append(
                "No calendário pediátrico da *SBIm 2026* na *Rede Drogal*, trabalhamos com as vacinas combinadas acelulares (*Hexaxim® / Infanrix® Hexa* aos 2, 4 e 6 meses e *Infanrix® Penta* aos 12–18 meses), *RotaTeq®* (oral aos 2, 4 e 6 meses, respeitando a idade máxima de 32 semanas para a 3ª dose), *Prevenar 13®/15®/20®*, *Bexsero®* (aos 3, 5 e 12–15 meses) e *Menveo®/Nimenrix®* (aos 3, 5 e 12 meses), além de *M-M-R II® / ProQuad®*, *Varivax®* e *Hepatite A* a partir de 12 meses."
            )
            paragraphs.append(
                "Para eu te passar o esquema exato de hoje: *qual é a idade exata da criança (em meses ou anos) e quais vacinas já constam na carteirinha?*"
            )
        elif any(w in norm for w in ["geladeira", "temperatura", "camara", "cadeia de frio", "energia"]):
            paragraphs.append(
                "Em caso de excursão de temperatura fora da faixa de *+2,0°C a +8,0°C*, o protocolo oficial da *Rede Drogal (RDC 197/2017)* determina:\n"
                "1. *Suspender imediatamente* o uso dos lotes envolvidos (jamais descartar por conta própria e jamais aplicar antes do parecer);\n"
                "2. *Segregar em QUARENTENA* dentro da câmara refrigerada (+2°C a +8°C) com identificação visível;\n"
                "3. *Anotar temperaturas mínima, máxima, atual e tempo de exposição* e acionar a coordenação técnica e o SAC dos fabricantes com lote e validade."
            )
            paragraphs.append(
                "Qual foi a *temperatura mínima e máxima* registrada no termômetro e por quanto tempo a câmara ficou fora da faixa?"
            )
        else:
            paragraphs.append(
                "Estou com o *Guia de Bolso SBIm 2026* e o *Treinamento Oficial de Vacinação da Rede Drogal* prontos aqui. "
                "Me conte a *idade do paciente*, se ele *tem cartão de vacina em mãos*, se há alguma *comorbidade/gestação* e qual vacina vocês estão avaliando que já fechamos a conduta completa!"
            )

        return "\n\n".join(paragraphs)


agent = ProfessorImuneAgent()

if __name__ == "__main__":
    r, _ = agent.chat("Qual vacina aplicar em gestante com 7 meses de gestação?", session_id="teste-fluido")
    print(r)
