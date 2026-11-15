FROM python:3.12-slim

WORKDIR /app

# Copia dependências leves de produção
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o código e a base já extraída (JSONs)
COPY system_prompt.md .
COPY knowledge_base.py .
COPY professor_imune.py .
COPY whatsapp_server.py .
COPY pptx_extracted.json .
COPY pdf_extracted.json .

ENV PORT=8000
ENV PYTHONUTF8=1

EXPOSE 8000

CMD ["python", "-X", "utf8", "whatsapp_server.py"]
