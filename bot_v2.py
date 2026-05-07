import sys
sys.stdout.reconfigure(line_buffering=True)

import asyncio
import aiohttp
import re
import os
import json
import base64
from datetime import datetime
from aiohttp import web

USER_TOKEN        = os.environ.get("USER_TOKEN")
SENDGRID_API_KEY  = os.environ.get("SENDGRID_API_KEY")
EMAIL_DESTINO     = os.environ.get("EMAIL_DESTINO")
GOOGLE_CREDS_B64  = os.environ.get("GOOGLE_CREDS_B64")
SHEET_ID          = "1-BA4LQuxOMHliftrp9PluyieXyah-RdOOjWwkUWV6V0"

CHANNEL_IDS = {
    "resale-category-1": os.environ.get("CHANNEL_ID_1"),
    "resale-category-2": os.environ.get("CHANNEL_ID_2"),
    "resale-category-3": os.environ.get("CHANNEL_ID_3"),
    "resale-category-4": os.environ.get("CHANNEL_ID_4"),
}

ALERTAS = {
    70:  799,
    84:  500,
    86:  1999,
    95:  800,
    102: 1500,
    104: 2000,
}

INTERVALO = 60
alertas_enviadas = {}
google_token = None
google_token_expiry = 0

async def get_google_token():
    global google_token, google_token_expiry
    now = datetime.utcnow().timestamp()
    if google_token and now < google_token_expiry - 60:
        return google_token
    try:
        creds_json = base64.b64decode(GOOGLE_CREDS_B64).decode()
        creds = json.loads(creds_json)
        import time, math
        iat = int(time.time())
        exp = iat + 3600
        header = base64.urlsafe_b64encode(json.dumps({"alg":"RS256","typ":"JWT"}).encode()).rstrip(b'=').decode()
        payload = base64.urlsafe_b64encode(json.dumps({
            "iss": creds["client_email"],
            "scope": "https://www.googleapis.com/auth/spreadsheets",
            "aud": "https://oauth2.googleapis.com/token",
            "exp": exp, "iat": iat
        }).encode()).rstrip(b'=').decode()
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.backends import default_backend
        private_key = serialization.load_pem_private_key(
            creds["private_key"].encode(), password=None, backend=default_backend()
        )
        signing_input = f"{header}.{payload}".encode()
        signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
        sig_b64 = base64.urlsafe_b64encode(signature).rstrip(b'=').decode()
        jwt = f"{header}.{payload}.{sig_b64}"
        async with aiohttp.ClientSession() as s:
            async with s.post("https://oauth2.googleapis.com/token", data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": jwt
            }) as resp:
                data = await resp.json()
                google_token = data.get("access_token")
                google_token_expiry = iat + data.get("expires_in", 3600)
                return google_token
    except Exception as e:
        print(f"Error obteniendo token Google: {e}")
        return None

async def guardar_en_sheets(match, categoria, precio, umbral):
    try:
        token = await get_google_token()
        if not token:
            return
        timestamp = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        values = [[timestamp, str(match), str(categoria), str(precio), str(umbral)]]
        url = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/A:E:append?valueInputOption=USER_ENTERED"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        async with aiohttp.ClientSession() as s:
            async with s.post(url, json={"values": values}, headers=headers) as resp:
                if resp.status == 200:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Guardado en Sheets: Match {match} Cat {categoria}: USD {precio}")
                else:
                    text = await resp.text()
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Error Sheets {resp.status}: {text}")
    except Exception as e:
        print(f"Error guardando en Sheets: {e}")

async def enviar_email(match, categoria, precio, umbral):
    asunto = f"ALERTA FIFA WC26 - Match {match} Cat {categoria}: USD {precio}"
    cuerpo = f"""Aparecio una entrada barata!

Match: {match}
Categoria: {categoria}
Precio actual: USD {precio}
Tu umbral: USD {umbral}
Detectado: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}

Entra rapido a la FIFA Resale Shop:
https://www.fifa.com/tickets/resale"""

    payload = {
        "personalizations": [{"to": [{"email": EMAIL_DESTINO}]}],
        "from": {"email": EMAIL_DESTINO},
        "subject": asunto,
        "content": [{"type": "text/plain", "value": cuerpo}]
    }
    headers = {"Authorization": f"Bearer {SENDGRID_API_KEY}", "Content-Type": "application/json"}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post("https://api.sendgrid.com/v3/mail/send",
                              json=payload, headers=headers) as resp:
                if resp.status == 202:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Email enviado - Match {match} Cat {categoria}: USD {precio}")
                else:
                    text = await resp.text()
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Error SendGrid {resp.status}: {text}")
    except Exception as e:
        print(f"Error enviando email: {e}")

def extraer_precios(texto):
    resultados = {}
    for linea in texto.split("\n"):
        limpia = re.sub(r'[│┃|┤├┼╪╫╬╭╮╯╰┌┐└┘┬┴─━╌╍╎╏\s]', ' ', linea)
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
            for embed in mensaje.get("embeds", []):
                desc = embed.get("description", "")
                if desc:
                    precios.update(extraer_precios(desc))
                for field in embed.get("fields", []):
                    precios.update(extraer_precios(field.get("value", "")))
            if not precios:
                texto = mensaje.get("content", "")
                if texto:
                    precios.update(extraer_precios(texto))

            for num_partido, precio_actual in precios.items():
                umbral = ALERTAS[num_partido]
                clave = f"{num_partido}-{categoria}"
                # Siempre guardar en Sheets
                await guardar_en_sheets(num_partido, categoria, precio_actual, umbral)
                # Solo alertar si cambió el precio y está bajo el umbral
                if precio_actual <= umbral:
                    if alertas_enviadas.get(clave) != precio_actual:
                        alertas_enviadas[clave] = precio_actual
                        await enviar_email(num_partido, categoria, precio_actual, umbral)
                        print(f"   ALERTA Match {num_partido} Cat {categoria}: USD {precio_actual}")
                else:
                    alertas_enviadas.pop(clave, None)

    except Exception as e:
        print(f"Error en {canal_nombre}: {e}")

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
