import asyncio
import aiohttp
import smtplib
import re
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from aiohttp import web

USER_TOKEN     = os.environ.get("USER_TOKEN")
GMAIL_SENDER   = os.environ.get("GMAIL_SENDER")
GMAIL_PASSWORD = os.environ.get("GMAIL_PASSWORD")
EMAIL_DESTINO  = os.environ.get("EMAIL_DESTINO")

CHANNEL_IDS = {
    "resale-category-1": os.environ.get("CHANNEL_ID_1"),
    "resale-category-2": os.environ.get("CHANNEL_ID_2"),
    "resale-category-3": os.environ.get("CHANNEL_ID_3"),
    "resale-category-4": os.environ.get("CHANNEL_ID_4"),
}

ALERTAS = {
    95:  750,
    70:  750,
    86:  1700,
}

INTERVALO = 60

alertas_enviadas = {}
ultimo_mensaje_id = {}

def enviar_email(match, categoria, precio, umbral):
    asunto = f"ALERTA FIFA WC26 - Match {match} Cat {categoria}: USD {precio}"
    cuerpo = f"""
Aparecio una entrada barata!

Match: {match}
Categoria: {categoria}
Precio actual: USD {precio}
Tu umbral: USD {umbral}
Detectado: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}

Entra rapido a la FIFA Resale Shop:
https://www.fifa.com/tickets/resale
    """
    try:
        msg = MIMEMultipart()
        msg["From"]    = GMAIL_SENDER
        msg["To"]      = EMAIL_DESTINO
        msg["Subject"] = asunto
        msg.attach(MIMEText(cuerpo, "plain"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_SENDER, GMAIL_PASSWORD)
            server.sendmail(GMAIL_SENDER, EMAIL_DESTINO, msg.as_string())
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Email enviado - Match {match} Cat {categoria}: USD {precio}")
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Error enviando email: {e}")

def extraer_precios(texto):
    resultados = {}
    for linea in texto.split("\n"):
        match = re.search(r'\|\s*(\d{1,3})\s*\|\s*[\d,]+\s*\|\s*([\d,]+)', linea)
        if match:
            num_partido = int(match.group(1))
            precio = int(match.group(2).replace(",", ""))
            if num_partido in ALERTAS:
                resultados[num_partido] = precio
    return resultados

async def chequear_canal(session, canal_nombre, channel_id):
    if not channel_id:
        return
    headers = {"Authorization": USER_TOKEN, "Content-Type": "application/json"}
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages?limit=5"
    try:
        async with session.get(url, headers=headers) as resp:
            if resp.status != 200:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Error {resp.status} en {canal_nombre}")
                return
            mensajes = await resp.json()
            if not mensajes:
                return
            ultimo_id = ultimo_mensaje_id.get(channel_id)
            nuevo_ultimo = mensajes[0]["id"]
            for mensaje in mensajes:
                msg_id = mensaje["id"]
                if ultimo_id and msg_id <= ultimo_id:
                    break
                texto = mensaje.get("content", "")
                if "|" not in texto:
                    continue
                categoria = canal_nombre.split("-")[-1]
                precios = extraer_precios(texto)
                for num_partido, precio_actual in precios.items():
                    umbral = ALERTAS[num_partido]
                    clave = f"{num_partido}-{categoria}"
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] {canal_nombre} - Match {num_partido}: USD {precio_actual} (umbral: USD {umbral})")
                    if precio_actual <= umbral:
                        if alertas_enviadas.get(clave) != precio_actual:
                            alertas_enviadas[clave] = precio_actual
                            enviar_email(num_partido, categoria, precio_actual, umbral)
                    else:
                        alertas_enviadas.pop(clave, None)
            ultimo_mensaje_id[channel_id] = nuevo_ultimo
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Error en {canal_nombre}: {e}")

async def health_check(request):
    return web.Response(text="OK")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Servidor web corriendo en puerto {port}")

async def main():
    print("FIFA WC26 Price Alert Bot - Corriendo...")
    print(f"Monitoreando matches: {list(ALERTAS.keys())}")
    print(f"Chequeando cada {INTERVALO} segundos")
    await start_web_server()
    async with aiohttp.ClientSession() as session:
        while True:
            for canal_nombre, channel_id in CHANNEL_IDS.items():
                await chequear_canal(session, canal_nombre, channel_id)
                await asyncio.sleep(2)
            await asyncio.sleep(INTERVALO)

if __name__ == "__main__":
    asyncio.run(main())
