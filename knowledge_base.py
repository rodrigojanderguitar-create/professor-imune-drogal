# -*- coding: utf-8 -*-
"""
Módulo de Base de Conhecimento (RAG Local + Protocolos Operacionais)
do Agente Professor Imune — Rede Drogal.

Indexa automaticamente:
1. TREINAMENTO VACINAÇÃO 30.12.25.pptx (pptx_extracted.json)
2. Guia de Bolso Rede Particular - Maio 2026 (pdf_extracted.json)
3. Protocolos Operacionais Padronizados (ClinicarX, SI-PNI/RNDS, Cadeia de Frio,
   Técnicas de Aplicação/Agulhas, Simultaneidade e Emergências/Anafilaxia).
"""

import json
import math
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List

BASE_DIR = Path(__file__).resolve().parent

STOPWORDS_PT = {
    "de", "da", "do", "das", "dos", "em", "no", "na", "nos", "nas", "um", "uma",
    "uns", "umas", "para", "por", "com", "sem", "sob", "sobre", "entre", "ate",
    "apos", "como", "qual", "quais", "quando", "onde", "porque", "que", "se",
    "ou", "mas", "mais", "menos", "muito", "muita", "pode", "posso", "deve",
    "devo", "fazer", "aplicar", "tomar", "indicar", "vacina", "vacinas",
    "vacinacao", "paciente", "hoje", "dia", "mes", "ano", "ter", "tem", "foi",
    "ser", "esta", "estao", "sao", "aos", "as", "os", "ao", "outra", "outro",
}

PROTOCOLOS_OPERACIONAIS: List[Dict[str, str]] = [
    {
        "id": "PROTO-CLINICARX-SIPNI",
        "source": "Protocolo Operacional Rede Drogal — ClinicarX e SI-PNI/RNDS",
        "title": "Procedimento de Registro no ClinicarX e Integração SI-PNI / RNDS",
        "content": (
            "PASSO A PASSO NO CLINICARX E SI-PNI (RNDS):\n"
            "1. Identificação do Paciente: Solicitar documento oficial com foto e CPF (ou CNS). "
            "No ClinicarX, buscar o paciente pelo CPF para evitar duplicidade de cadastro e garantir a integração com a RNDS (Meu SUS Digital / SI-PNI).\n"
            "2. Anamnese e Triagem Clínica: Registrar no sistema a condição atual (febre nas últimas 48h, alergias graves, gestação/lactação, imunossupressão, uso de corticoides ou imunobiológicos, histórico vacinal anterior).\n"
            "3. Conferência de Prescrição (quando exigida): Anexar ou registrar os dados do prescritor (CRM/UF) quando a vacina exigir receita médica (ex.: Arexvy, Typhim Vi, ou vacinas fora da faixa etária padrão como Shingrix <50 anos, Gardasil 9 fora de 9-45 anos, ProQuad fora de 1-12 anos, Qdenga fora de 4-60 anos). Para Bexsero, emitir prescrição farmacêutica se não houver receita médica.\n"
            "4. Registro do Imunobiológico: Selecionar a vacina exata aplicada, informar Fabricante, Lote, Data de Validade, Dose (1ª, 2ª, 3ª, dose única ou reforço), Via de Administração (IM, SC, ID ou Oral) e Local Anatômico exato (ex.: Deltoide Direito/Esquerdo, Vasto Lateral da Coxa Direita/Esquerda).\n"
            "5. Transmissão SI-PNI / RNDS: Ao finalizar o atendimento no ClinicarX, verificar o status de envio para a RNDS/SI-PNI. Em caso de erro, conferir se o CPF e a data de nascimento coincidem com a base do CADSUS.\n"
            "6. Emissão da Declaração de Serviço Farmacêutico (DSF) e Carteira Física: Entregar uma via da DSF ao paciente (RDC 44/2009 e RDC 197/2017) e anotar na carteira física: data, vacina, lote, fabricante, carimbo/CRF e próxima dose a lápis."
        ),
    },
    {
        "id": "PROTO-TECNICAS-APLICACAO-AGULHAS",
        "source": "Manual de Normas e Procedimentos para Vacinação (MS/PNI) & SBIm",
        "title": "Técnicas de Aplicação, Escolha de Local Anatômico e Calibre de Agulhas",
        "content": (
            "TÉCNICAS DE APLICAÇÃO E ESCOLHA DE AGULHAS NA SALA DE VACINAÇÃO:\n"
            "1. Via Intramuscular (IM) — Ângulo de 90°:\n"
            "   • Crianças menores de 2 anos: Músculo Vasto Lateral da Coxa (terço médio da face anterolateral). Agulha: 20 x 5,5 mm (24G) ou 25 x 6,0 mm (23G).\n"
            "   • Crianças ≥ 2 anos, adolescentes e adultos: Músculo Deltoide (3 a 5 cm abaixo do acrômio). Agulha: 25 x 6,0 mm (23G) ou 25 x 7,0 mm (22G); obesos: 30 x 7,0 mm ou 30 x 8,0 mm.\n"
            "   • Nota técnica: NÃO realizar aspiração prévia no deltoide e vasto lateral da coxa.\n"
            "2. Via Subcutânea (SC) — Ângulo de 45° (agulha 20 x 5,5 mm) ou 90° com prega subcutânea (agulha 13 x 4,5 mm):\n"
            "   • Locais: Região posterior do braço (tricipital), deltoide ou face anterolateral da coxa.\n"
            "   • Principais vacinas SC: Tríplice Viral (M-M-R II®), Tetra Viral (ProQuad®), Varicela (Varivax®/Varilrix®), Febre Amarela (Stamaril®) e Dengue (Qdenga® — 0,5 mL exclusivamente SC).\n"
            "3. Via Intradérmica (ID) — Ângulo de 10° a 15°:\n"
            "   • Vacina BCG: inserção inferior do deltoide direito, agulha 13 x 3,8 mm ou 13 x 4,5 mm.\n"
            "4. Via Oral (VO):\n"
            "   • RotaTeq® (6 a 32 semanas de vida): Exclusivamente via oral. NUNCA injetar. Se regurgitar ou vomitar, NÃO repetir a dose.\n"
            "5. Aplicação Simultânea no Mesmo Membro:\n"
            "   • Preferir membros diferentes. No mesmo músculo, manter distância mínima de 2,5 cm entre as aplicações."
        ),
    },
    {
        "id": "PROTO-SIMULTANEIDADE-INTERVALOS",
        "source": "Treinamento Vacinação Rede Drogal & Diretrizes SBIm / PNI",
        "title": "Simultaneidade de Vacinas e Intervalos Mínimos Obrigatórios",
        "content": (
            "REGRAS DE SIMULTANEIDADE E INTERVALOS ENTRE VACINAS:\n"
            "1. QDENGA® (Vacina Dengue Atenuada): PROIBIDO aplicar no mesmo dia com qualquer outra vacina.\n"
            "   • Intervalo com vacinas INATIVADAS / RECOMBINANTES (ex.: Gripe, HPV, Hepatites, dTpa, Meningo, Pneumo): mínimo de 24 horas.\n"
            "   • Intervalo com outras vacinas ATENUADAS (Febre Amarela, Tríplice Viral, Varicela, ProQuad): mínimo de 30 dias.\n"
            "2. ABRYSVO® (Vacina VSR Recombinante) x dTpa (Refortrix®):\n"
            "   • Pode ser aplicada no mesmo dia com a vacina Influenza sazonal.\n"
            "   • Recomenda-se intervalo mínimo de 2 semanas (14 dias) entre Abrysvo® e a vacina dTpa.\n"
            "3. SHINGRIX® (Herpes Zóster Recombinante):\n"
            "   • Pode ser coadministrada com Influenza inativada sem adjuvante, Pneumovax 23 (VPP23) ou dTpa (Refortrix) em locais anatômicos distintos.\n"
            "   • O uso concomitante com outras vacinas não é recomendado por falta de dados.\n"
            "4. FEBRE AMARELA (Stamaril®) x TRÍPLICE VIRAL (M-M-R II®) / TETRA VIRAL (ProQuad®):\n"
            "   • Em menores de 2 anos: NÃO administrar simultaneamente; respeitar intervalo de 30 dias.\n"
            "   • Em ≥ 2 anos e adultos: aplicar no mesmo dia (em locais distintos) ou com intervalo mínimo de 30 dias.\n"
            "5. VACINAS PNEUMOCÓCICAS (VPC13/VPC15 + VPP23 vs VPC20):\n"
            "   • Prevenar 20® (VPC20): dispensa esquema sequencial com VPP23.\n"
            "   • VPC15 (Vaxneuvance) ou VPC13 (Prevenar 13) em grupos de risco/idosos: aplicar VPP23 (Pneumovax 23) 6 a 12 meses depois, e 2ª dose de VPP23 5 anos após a primeira."
        ),
    },
    {
        "id": "PROTO-CADEIA-DE-FRIO",
        "source": "RDC Anvisa nº 197/2017 & Manual de Rede de Frio PNI/MS",
        "title": "Cadeia de Frio, Armazenamento e Conduta em Desvio de Temperatura",
        "content": (
            "BOAS PRÁTICAS DE CADEIA DE FRIO NA FARMÁCIA:\n"
            "1. Temperatura Padrão: Conservar rigorosamente entre +2,0°C e +8,0°C (ponto ideal: +5,0°C).\n"
            "2. Câmara Refrigerada Exclusiva: Uso exclusivo para imunobiológicos, organizada por tipo e validade (PVPS).\n"
            "3. Monitoramento: Registrar temperaturas Atual, Mínima e Máxima no início e fim do turno e resetar o termômetro.\n"
            "4. Conduta em Desvio / Excursão de Temperatura (< +2,0°C ou > +8,0°C):\n"
            "   • Passo 1: Suspender imediatamente a aplicação dos lotes envolvidos. NUNCA descartar por conta própria.\n"
            "   • Passo 2: Segregar os imunobiológicos com identificação 'EM QUARENTENA - NÃO UTILIZAR', mantendo-os refrigerados entre +2°C e +8°C.\n"
            "   • Passo 3: Registrar temperatura mínima, máxima, atual, tempo estimado de exposição e causa do desvio.\n"
            "   • Passo 4: Acionar a coordenação técnica e o SAC dos fabricantes com lote e validade para parecer oficial de estabilidade."
        ),
    },
    {
        "id": "PROTO-EAPV-ANAFILAXIA",
        "source": "Manual de Vigilância Epidemiológica de Eventos Adversos Pós-Vacinação (MS)",
        "title": "Eventos Adversos Pós-Vacinação (EAPV/ESAVI), Síncope e Manejo de Anafilaxia",
        "content": (
            "MANEJO DE INTERCORRÊNCIAS E EVENTOS ADVERSOS PÓS-VACINAÇÃO (EAPV):\n"
            "1. Reações Locais Esperadas (dor, rubor, calor, edema):\n"
            "   • Aplicar compressa FRIA nas primeiras 24 a 48 horas (15 min, 3 a 4x/dia). NUNCA usar compressa quente.\n"
            "2. Diferenciação Rápida — Síncope Vasovagal vs. Anafilaxia:\n"
            "   • Síncope Vasovagal: Imediata (ansiedade/dor), palidez, sudorese fria, pulso lento (bradicardia), SEM urticária e SEM falta de ar. Conduta: Deitar o paciente e elevar as pernas (Trendelenburg).\n"
            "   • Anafilaxia (Emergência): Geralmente em 15–30 min; placas vermelhas/coceira (urticária), inchaço de lábios/língua/glote, falta de ar/chiado (broncoespasmo), queda de pressão e taquicardia.\n"
            "3. Conduta de Emergência na Anafilaxia:\n"
            "   • Passo 1: Acionar imediatamente o SAMU (192) ou Bombeiros (193).\n"
            "   • Passo 2: Deitar o paciente com pernas elevadas (gestantes em decúbito lateral esquerdo; se falta de ar intensa, semi-sentado).\n"
            "   • Passo 3: Administrar Adrenalina (Epinefrina) 1:1000 (1 mg/mL) INTRAMUSCULAR no vasto lateral da coxa: dose de 0,01 mg/kg (0,01 mL/kg), máximo de 0,5 mL em adulto e 0,3 mL em criança (repetir a cada 5–15 min se necessário).\n"
            "   • Passo 4: Registrar no ClinicarX e notificar no VigiMed (Anvisa) / e-SUS Notifica."
        ),
    },
    {
        "id": "PROTO-CALENDARIO-ADULTO-SBIM-DROGAL",
        "source": "Guia de Bolso SBIm 2026 (Calendário Adulto 20 a 59 anos) & Treinamento Rede Drogal",
        "title": "Calendário Adulto (20 a 59 anos) Homem/Mulher e Conduta para Paciente Sem Cartão de Vacina (Sem Comprovação Vacinal)",
        "content": (
            "CALENDÁRIO VACINAL DO ADULTO (20 A 59 ANOS) E CONDUTA SEM CARTÃO DE VACINA (GUIA SBIm 2026 & REDE DROGAL):\n"
            "REGRA DE OURO (PACIENTE SEM CARTÃO / SEM COMPROVAÇÃO VACINAL): Pela diretriz SBIm e PNI, adulto sem carteira de vacinação ou sem registro no Meu SUS Digital/ClinicarX é considerado NÃO VACINADO. Deve-se iniciar os esquemas vacinais do zero (não há risco em revacinar quem já teve doses prévias na infância).\n\n"
            "VACINAS PRIORITÁRIAS DE ROTINA PARA ADULTO (20 A 59 ANOS, EX.: 30, 35, 40 ANOS, SEM COMORBIDADES):\n"
            "1. dTpa (Refortrix® / Boostrix®) ou dTpa-VIP (Refortrix® IPV) — Tríplice Bacteriana Acelular do Adulto:\n"
            "   • Esquema COM comprovação de 3 doses de dT/DTP: 1 dose de dTpa agora e reforço a cada 10 anos.\n"
            "   • Esquema SEM cartão / SEM comprovação vacinal: 3 doses no esquema 0 - 2 - 4 a 8 meses, sendo a 1ª dose obrigatoriamente com dTpa (Refortrix®) na Drogal e as outras duas com dT (ou dTpa). Via IM no deltoide (0,5 mL). Sem necessidade de receita.\n"
            "2. Hepatite B (Engerix® B 20 mcg/1,0 mL) ou Hepatite A+B Combinada (Twinrix®):\n"
            "   • Sem comprovação vacinal: 3 doses no esquema 0 - 1 - 6 meses (via IM no deltoide, 1,0 mL para adulto). Se desejar proteger Hepatite A e B juntas na mesma picada: usar Twinrix® (0 - 1 - 6 meses, IM, sem receita).\n"
            "   • Hepatite A isolada (Vaqta® / Havrix® / Avaxim®): 2 doses no esquema 0 - 6 meses (IM no deltoide, sem receita).\n"
            "3. Tríplice Viral — Sarampo, Caxumba e Rubéola (M-M-R II®):\n"
            "   • Adultos até 29 anos: 2 doses na vida. Adultos de 30 a 59 anos: 1 dose (ou 2 doses pela SBIm/surtos/profissionais de saúde, com intervalo mínimo de 30 dias). Sem cartão de vacina: aplicar M-M-R II® (0,5 mL, via Subcutânea, sem receita). Contraindicada em gestantes e imunossuprimidos graves.\n"
            "4. Dengue Atenuada (Qdenga® — 4 a 60 anos):\n"
            "   • Indicada para adultos (soropositivos ou soronegativos para dengue): 2 doses com intervalo de 3 meses (0 e 3 meses), 0,5 mL via Subcutânea (SC), sem receita.\n"
            "   • ATENÇÃO CRÍTICA DROGAL: A Qdenga® NÃO pode ser aplicada no mesmo dia com nenhuma outra vacina! Respeitar intervalo mínimo de 24 horas para vacinas inativadas (ex.: dTpa, Hepatite B, Gripe, HPV) e 30 dias para outras vacinas atenuadas (ex.: Tríplice Viral, Febre Amarela, Varicela).\n"
            "5. Influenza Quadrivalente (Influvac Tetra®):\n"
            "   • Dose única anual (0,5 mL, via IM no deltoide, sem receita). Pode ser aplicada no mesmo dia com dTpa, Hepatite B, Tríplice Viral e HPV.\n"
            "6. HPV Nonavalente (Gardasil 9® — 9 a 45 anos):\n"
            "   • Recomendada para homens e mulheres adultos (inclusive 35 anos): 3 doses no esquema 0 - 2 - 6 meses (0,5 mL, via IM no deltoide, sem receita até 45 anos).\n"
            "7. Febre Amarela (Stamaril®):\n"
            "   • Sem comprovação vacinal: Dose única (0,5 mL, via Subcutânea, sem receita), ou 2ª dose após 10 anos conforme recomendação SBIm.\n"
            "   • Atenção: Pode ser feita no mesmo dia que a Tríplice Viral (M-M-R II®) em adultos, OU com intervalo mínimo de 30 dias entre elas. Com a Qdenga®, exige 30 dias de intervalo.\n"
            "8. Meningocócica ACWY (Menveo® / Nimenrix®) e Meningocócica B (Bexsero®):\n"
            "   • Menveo®/Nimenrix®: dose única (0,5 mL IM, sem receita).\n"
            "   • Bexsero®: 2 doses com intervalo de 30 a 60 dias (0,5 mL IM; prescrição farmacêutica/médica).\n"
            "9. Varicela (Varivax® / Varilrix®):\n"
            "   • Para adultos sem histórico de catapora e sem cartão: 2 doses com intervalo de 1 a 2 meses (0,5 mL SC, sem receita).\n"
            "10. Herpes Zóster Inativada (Shingrix®):\n"
            "   • Rotina a partir de 50 anos (sem receita) ou a partir de 18 anos para imunocomprometidos/risco aumentado (com receita médica abaixo de 50 anos): 2 doses (0 e 2 meses, 0,5 mL IM).\n\n"
            "SUGESTÃO PRÁTICA DE CONDUTA NO BALCÃO HOJE (ADULTO DE 35 ANOS SEM CARTÃO E SEM VACINAS RECENTES):\n"
            "• Opção A (Combo Proteção Imediata no mesmo dia): Aplicar hoje no mesmo atendimento dTpa (Refortrix®), Hepatite A+B (Twinrix® ou Engerix® B), Influenza (Influvac Tetra®), HPV9 (Gardasil 9®) e Tríplice Viral (M-M-R II®) — todas compatíveis no mesmo dia! E agendar a Qdenga® (Dengue) para 30 dias depois (por causa da Tríplice Viral atenuada).\n"
            "• Opção B (Prioridade Dengue hoje): Aplicar a 1ª dose da Qdenga® hoje isolada, e agendar as vacinas inativadas (dTpa, Hepatite A+B, Gripe, HPV9) para 24 a 48 horas depois, deixando a Tríplice Viral/Febre Amarela para 30 dias após a Qdenga®."
        ),
    },
]

SINONIMOS_VACINAS = {
    "hexavalente": ["hexaxim", "infanrix hexa", "hexa", "dtpa", "hib", "vip", "hepatite b"],
    "pentavalente": ["infanrix penta", "penta", "dtpa", "hib", "vip"],
    "triplice bacteriana": ["refortrix", "dtpa", "boostrix", "coqueluche", "tetano", "difteria"],
    "dtpa": ["refortrix", "triplice bacteriana", "coqueluche", "tetano", "difteria", "abrysvo"],
    "pneumo": ["prevenar", "prevenar 13", "prevenar 20", "vaxneuvance", "pneumovax", "pneumovax 23", "vpc13", "vpc15", "vpc20", "vpp23", "pneumonia", "pneumococica"],
    "meningo": ["menveo", "nimenrix", "bexsero", "acwy", "meningite", "meningococica"],
    "bexsero": ["meningo b", "meningococica b", "meningite b"],
    "acwy": ["menveo", "nimenrix", "meningococica acwy", "meningite"],
    "gripe": ["influenza", "influvac", "influvac tetra", "efluelda"],
    "influenza": ["gripe", "influvac", "influvac tetra", "efluelda"],
    "efluelda": ["gripe idoso", "influenza alta dose", "60 anos"],
    "herpes": ["shingrix", "herpes zoster", "zoster", "cobreiro"],
    "zoster": ["shingrix", "herpes zoster"],
    "dengue": ["qdenga", "aedes"],
    "qdenga": ["dengue", "atenuada"],
    "hpv": ["gardasil", "gardasil 9", "papilomavirus"],
    "gardasil": ["hpv", "gardasil 9"],
    "vsr": ["abrysvo", "arexvy", "sincicial", "bronquiolite", "nirsevimabe", "beyfortus"],
    "rsv": ["abrysvo", "arexvy", "vsr", "sincicial", "nirsevimabe", "beyfortus"],
    "abrysvo": ["vsr", "gestante", "sincicial"],
    "arexvy": ["vsr", "sincicial", "idoso"],
    "beyfortus": ["nirsevimabe", "vsr", "ao nascer"],
    "febre amarela": ["stamaril", "amarela"],
    "stamaril": ["febre amarela"],
    "triplice viral": ["mmr", "m-m-r", "sarampo", "caxumba", "rubeola", "proquad"],
    "tetra viral": ["proquad", "sarampo", "caxumba", "rubeola", "varicela"],
    "varicela": ["catapora", "varivax", "varilrix", "proquad"],
    "catapora": ["varicela", "varivax", "varilrix", "proquad"],
    "hepatite a": ["vaqta", "havrix", "avaxim", "twinrix"],
    "hepatite b": ["engerix", "twinrix", "hexaxim", "infanrix hexa"],
    "hepatite": ["engerix", "twinrix", "vaqta", "havrix", "avaxim"],
    "rotavirus": ["rotateq", "diarreia", "oral", "vrh5"],
    "febre tifoide": ["typhim", "typhim vi", "salmonella"],
    "bcg": ["tuberculose"],
    "clinicarx": ["si-pni", "rnds", "registro", "sistema", "declaracao", "cpf"],
    "sipni": ["clinicarx", "si-pni", "rnds", "registro"],
    "geladeira": ["cadeia de frio", "temperatura", "desvio", "camara", "termometro", "quarentena", "excursao"],
    "temperatura": ["cadeia de frio", "desvio", "quarentena", "excursao"],
    "anafilaxia": ["adrenalina", "epinefrina", "emergencia", "choque", "alergia", "reacao", "desmaio", "sincope"],
    "agulha": ["intramuscular", "subcutanea", "deltoide", "vasto lateral", "calibre", "aplicacao"],
}


def get_pdf_age_section(page_num: int) -> str:
    if 7 <= page_num <= 97:
        return "Calendário Criança (0 a 10 anos)"
    if 98 <= page_num <= 121:
        return "Calendário Adolescentes (11 a 19 anos)"
    if 122 <= page_num <= 153:
        return "Calendário Adulto (20 a 59 anos)"
    if 154 <= page_num <= 165:
        return "Calendário Gestante"
    if 166 <= page_num <= 181:
        return "Calendário Idoso (60+ anos)"
    return "Apresentação / Geral"


def normalize_text(text: str) -> str:
    """Remove acentos, padroniza números (02 -> 2) e converte para minúsculas."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    no_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    cleaned = re.sub(r"[^a-z0-9\s\-]", " ", no_accents)
    # Normaliza 02 -> 2, 03 -> 3 etc. para casar '2 meses' com '02 meses'
    cleaned = re.sub(r"\b0+([1-9]\d*)\b", r"\1", cleaned)
    return cleaned


def tokenize(text: str, remove_stopwords: bool = True) -> List[str]:
    norm = normalize_text(text)
    tokens = [t for t in norm.split() if len(t) >= 2 or t.isdigit()]
    if remove_stopwords:
        filtered = [t for t in tokens if t not in STOPWORDS_PT]
        return filtered if filtered else tokens
    return tokens


class KnowledgeBase:
    """Motor de busca híbrido (BM25 + Sinônimos + Pareamento de Páginas + Filtro de Ruído)."""

    def __init__(self) -> None:
        self.documents: List[Dict[str, Any]] = []
        self.doc_by_id: Dict[str, Dict[str, Any]] = {}
        self.doc_freqs: Dict[str, int] = {}
        self.avg_dl: float = 1.0
        self._pdf_mtime: float = 0.0
        self.reload()

    def reload(self) -> None:
        docs: List[Dict[str, Any]] = []

        for proto in PROTOCOLOS_OPERACIONAIS:
            docs.append({
                "id": proto["id"],
                "source": proto["source"],
                "title": proto["title"],
                "content": proto["content"],
                "type": "protocolo",
            })

        pptx_path = BASE_DIR / "pptx_extracted.json"
        if pptx_path.exists():
            try:
                slides = json.loads(pptx_path.read_text(encoding="utf-8-sig"))
                for s in slides:
                    content = (s.get("content") or "").strip()
                    if not content or len(content) < 15:
                        continue
                    first_line = content.splitlines()[0][:80]
                    docs.append({
                        "id": f"PPTX-SLIDE-{s['slide']}",
                        "source": f"Treinamento Vacinação Rede Drogal — Slide {s['slide']}",
                        "title": f"Slide {s['slide']}: {first_line}",
                        "content": content,
                        "type": "pptx",
                        "num": int(s["slide"]),
                    })
            except Exception as e:
                print(f"[KnowledgeBase] Aviso ao ler pptx_extracted.json: {e}")

        pdf_path = BASE_DIR / "pdf_extracted.json"
        if pdf_path.exists():
            try:
                self._pdf_mtime = pdf_path.stat().st_mtime
                pages = json.loads(pdf_path.read_text(encoding="utf-8-sig"))
                if isinstance(pages, dict):
                    pages = [pages]
                for p in pages:
                    content = (p.get("content") or "").strip()
                    if not content or len(content) < 15:
                        continue
                    page_num = int(p["page"])
                    section = get_pdf_age_section(page_num)
                    lines = [ln.strip() for ln in content.splitlines() if len(ln.strip()) > 2]
                    header_preview = " - ".join(lines[:3])[:90]
                    docs.append({
                        "id": f"PDF-PAG-{page_num}",
                        "source": f"Guia de Bolso SBIm 2026 ({section}) — Pág. {page_num}",
                        "title": f"[{section}] Pág. {page_num}: {header_preview}",
                        "content": f"[{section}]\n{content}",
                        "type": "pdf",
                        "num": page_num,
                    })
            except Exception as e:
                print(f"[KnowledgeBase] Aviso ao ler pdf_extracted.json: {e}")

        self.documents = docs
        self.doc_by_id = {d["id"]: d for d in docs}
        self.doc_freqs = {}
        total_len = 0
        for d in self.documents:
            full_txt = f"{d['title']} {d['title']} {d['content']}"
            tokens = tokenize(full_txt, remove_stopwords=True)
            d["_tokens"] = tokens
            d["_norm_text"] = normalize_text(full_txt)
            total_len += len(tokens)
            for tok in set(tokens):
                self.doc_freqs[tok] = self.doc_freqs.get(tok, 0) + 1

        self.avg_dl = (total_len / len(self.documents)) if self.documents else 1.0

    def _check_pdf_update(self) -> None:
        pdf_path = BASE_DIR / "pdf_extracted.json"
        if pdf_path.exists():
            mtime = pdf_path.stat().st_mtime
            if mtime != self._pdf_mtime:
                self.reload()

    def expand_query(self, query: str) -> List[str]:
        norm_q = normalize_text(query)
        tokens = tokenize(query, remove_stopwords=True)
        extra: List[str] = []
        for key, syns in SINONIMOS_VACINAS.items():
            if key in norm_q:
                for syn in syns:
                    extra.extend(tokenize(syn, remove_stopwords=True))
        return tokens + extra

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Retorna apenas os documentos realmente relevantes para a pergunta."""
        self._check_pdf_update()
        if not self.documents:
            return []

        q_tokens = self.expand_query(query)
        if not q_tokens:
            return self.documents[:top_k]

        N = len(self.documents)
        k1 = 1.5
        b = 0.75
        scored: List[tuple[float, Dict[str, Any]]] = []
        norm_query = normalize_text(query)

        # Detecta faixa etária / perfil do paciente na consulta
        age_months_match = re.search(r"\b(\d+)\s*mes(?:es)?\b", norm_query)
        age_years_matches = [int(m) for m in re.findall(r"\b(\d+)\s*anos?\b", norm_query)]
        is_gestante = any(w in norm_query for w in ["gestante", "gravida", "gravidez", "gestacao", "pre natal", "pre-natal"])
        is_crianca = (
            bool(age_months_match)
            or any(w in norm_query for w in ["bebe", "crianca", "recem nascido", "recem-nascido", "lactente", "pediatrico"])
            or any(0 <= y <= 10 for y in age_years_matches)
        )
        is_adolescente = (
            any(w in norm_query for w in ["adolescente", "jovem"])
            or any(11 <= y <= 19 for y in age_years_matches)
        )
        is_adulto = (
            any(w in norm_query for w in ["adulto", "adulta", "homem", "mulher"])
            or any(20 <= y <= 59 for y in age_years_matches)
        )
        is_idoso = (
            any(w in norm_query for w in ["idoso", "idosa", "terceira idade"])
            or any(y >= 60 for y in age_years_matches)
        )
        asks_vsr = any(w in norm_query for w in ["vsr", "rsv", "sincicial", "abrysvo", "arexvy", "bronquiolite"])

        for doc in self.documents:
            tokens = doc["_tokens"]
            dl = len(tokens) or 1
            score = 0.0
            tf_map: Dict[str, int] = {}
            for t in tokens:
                tf_map[t] = tf_map.get(t, 0) + 1

            for qt in q_tokens:
                # Evita que o número de anos (ex.: "35" em "35 anos") pontue pelo número da página ("Pág. 35")
                if qt.isdigit() and int(qt) in age_years_matches and doc.get("type") == "pdf" and doc.get("num") == int(qt):
                    continue
                tf = tf_map.get(qt, 0)
                if tf == 0:
                    continue
                df = self.doc_freqs.get(qt, 0)
                idf = math.log(1.0 + (N - df + 0.5) / (df + 0.5))
                denom = tf + k1 * (1.0 - b + b * (dl / self.avg_dl))
                score += idf * ((tf * (k1 + 1.0)) / denom)

            # Remove "Pág. X" e "Slide X" antes de pontuar match no título para não confundir idade com página
            raw_title_clean = re.sub(r"p[aá]g\.\s*\d+|slide\s*\d+", "", doc["title"], flags=re.IGNORECASE)
            title_norm = normalize_text(raw_title_clean)
            for qt in set(tokenize(query, remove_stopwords=True)):
                if len(qt) >= 3 and not qt.isdigit() and qt in title_norm:
                    score += 4.0

            doc_norm = doc["_norm_text"]

            # Bônus se for exatamente a página de rotina da idade em meses (ex.: "rotina de 2 meses")
            if age_months_match and not is_gestante:
                m_num = age_months_match.group(1)
                if f"rotina de {m_num} meses" in doc_norm or f"{m_num} meses" in title_norm:
                    score += 12.0

            if is_gestante:
                if "calendario gestante" in doc_norm:
                    score += 10.0
                elif "calendario crianca" in doc_norm or "calendario idoso" in doc_norm:
                    score -= 6.0

            if is_adulto and not is_gestante and not is_crianca:
                if doc["id"] == "PROTO-CALENDARIO-ADULTO-SBIM-DROGAL":
                    score += 18.0
                elif "calendario adulto" in doc_norm:
                    score += 8.0
                    if "nao recomendada como rotina" in doc_norm and not asks_vsr:
                        score -= 10.0
                elif "calendario crianca" in doc_norm or "uso pediatrico" in doc_norm:
                    score -= 15.0

            if is_idoso and not is_crianca:
                if "calendario idoso" in doc_norm:
                    score += 10.0
                elif "calendario crianca" in doc_norm or "uso pediatrico" in doc_norm:
                    score -= 15.0

            if is_adolescente and not is_crianca:
                if "calendario adolescentes" in doc_norm:
                    score += 10.0
                elif "calendario crianca" in doc_norm:
                    score -= 10.0

            if is_crianca and not is_adulto and not is_idoso and not is_gestante:
                if "calendario crianca" in doc_norm:
                    score += 6.0

            if doc["type"] in ("pptx", "protocolo") and score > 0:
                score *= 1.15

            if score > 0:
                scored.append((score, doc))

        scored.sort(key=lambda x: x[0], reverse=True)
        if not scored:
            return []

        top_score = scored[0][0]
        min_threshold = top_score * 0.40

        results: List[Dict[str, Any]] = []
        seen_ids = set()

        if is_adulto and not is_gestante and not is_crianca:
            proto_adulto = self.doc_by_id.get("PROTO-CALENDARIO-ADULTO-SBIM-DROGAL")
            if proto_adulto:
                results.append(proto_adulto)
                seen_ids.add(proto_adulto["id"])

        if any(w in norm_query for w in ["junto", "juntas", "simultanea", "mesmo dia", "concomitante", "intervalo"]):
            proto = self.doc_by_id.get("PROTO-SIMULTANEIDADE-INTERVALOS")
            if proto and proto["id"] not in seen_ids:
                results.append(proto)
                seen_ids.add(proto["id"])

        for score, doc in scored:
            if len(results) >= top_k or score < min_threshold:
                break
            if doc["id"] not in seen_ids:
                results.append(doc)
                seen_ids.add(doc["id"])

                if doc["type"] == "pdf" and len(results) < top_k:
                    next_id = f"PDF-PAG-{doc['num'] + 1}"
                    next_doc = self.doc_by_id.get(next_id)
                    if next_doc and next_id not in seen_ids and "observac" in next_doc["_norm_text"]:
                        results.append(next_doc)
                        seen_ids.add(next_id)

        return results[:top_k]

    def format_context_for_prompt(self, query: str, top_k: int = 5) -> str:
        hits = self.search(query, top_k=top_k)
        if not hits:
            return "Nenhum trecho específico adicional encontrado na base local."
        blocks = []
        for idx, h in enumerate(hits, 1):
            blocks.append(f"--- FONTE [{idx}]: {h['source']} ---\n{h['content']}\n")
        return "\n".join(blocks)

    def stats(self) -> Dict[str, int]:
        self._check_pdf_update()
        return {
            "total_documentos": len(self.documents),
            "slides_pptx": sum(1 for d in self.documents if d["type"] == "pptx"),
            "paginas_pdf": sum(1 for d in self.documents if d["type"] == "pdf"),
            "protocolos_operacionais": sum(1 for d in self.documents if d["type"] == "protocolo"),
        }


kb = KnowledgeBase()
