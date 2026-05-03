import sys
sys.stdout.reconfigure(line_buffering=True)

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
    """
    Extrae números de cualquier línea que contenga exactamente
    un número de partido seguido de dos precios.
    Funciona con tablas Unicode, pipes o espacios.
    """
    resultados = {}
    for linea in texto.split("\n"):
        # Limpia caracteres de tabla Unicode y pipes
        limpia = re.sub(r'[│┃|┤├┼╪╫╬╭╮╯╰┌┐└┘┬┴─━╌╍╎╏\s]', ' ', linea)
        # Busca exactamente 3 números consecutivos
        nums = re.findall(r'\b(\d+)\b', limpia)
        if len(nums) >= 3:
            try:
                num_partido = int(nums[0])
                precio_resale = int(nums[2])
                if num_partido in ALERTAS and 1 <= num_partido <= 110:
                    resultados[num_partido] = precio_resale
            except:
                pass
    return resultados

async def chequear_canal(session, canal_nombre, channel_id):
    if not channel_id:
        return
    headers = {"Authorization": USER_TOKEN, "Content-Type": "application/json"}
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages?limit=1"
    try:
        async with session.get(url, headers=headers) as resp:
            if resp.status != 200:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Error {resp.status} en {canal_nombre}")
                return
            mensajes = await resp.json()
            if not mensajes:
                return

            mensaje = mensajes[0]
            categoria = canal_nombre.split("-")[-1]
            precios = {}

            # Lee embeds
            for embed in mensaje.get("embeds", []):
                desc = embed.get("description", "")
                if desc:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] {canal_nombre} embed desc (primeros 100 chars): {repr(desc[:100])}")
                    precios.update(extraer_precios(desc))
                for field in embed.get("fields", []):
                    precios.update(extraer_precios(field.get("value", "")))

            # Si no hay embeds, lee texto plano
            if not precios:
                texto = mensaje.get("content", "")
                if texto:
                    precios.update(extraer_precios(texto))

            if precios:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] {canal_nombre} precios encontrados: {precios}")
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] {canal_nombre}: sin precios detectados")

            for num_partido, precio_actual in precios.items():
                umbral = ALERTAS[num_partido]
                clave = f"{num_partido}-{categoria}"
                print(f"   Match {num_partido}: USD {precio_actual} (umbral: USD {umbral})")
                if precio_actual <= umbral:
                    if alertas_enviadas.get(clave) != precio_actual:
                        alertas_enviadas[clave] = precio_actual
                        enviar_email(num_partido, categoria, precio_actual, umbral)
                else:
                    alertas_enviadas.pop(clave, None)

    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Error en {canal_nombre}: {e}")

async def health_check(request):
    return web.Response(text="OK")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
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
