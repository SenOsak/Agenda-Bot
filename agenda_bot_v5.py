"""
╔══════════════════════════════════════════════════════╗
║       BOT DE AGENDA DIARIA v5 - TELEGRAM             ║
║                                                      ║
║  Todo lo de v4 más:                                  ║
║   🗄️  Supabase como base de datos en la nube         ║
║   ☁️  Listo para correr 24/7 en Railway              ║
║                                                      ║
║  Variables de entorno necesarias:                    ║
║    BOT_TOKEN                                         ║
║    TU_CHAT_ID                                        ║
║    OPENROUTER_API_KEY                                ║
║    SUPABASE_URL                                      ║
║    SUPABASE_KEY                                      ║
╚══════════════════════════════════════════════════════╝
"""

import json
import os
import re
import requests
import schedule
import time
import threading
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ─────────────────────────────────────────
#  CONFIGURACIÓN — variables de entorno
# ─────────────────────────────────────────
BOT_TOKEN          = os.environ.get("BOT_TOKEN", "")
TU_CHAT_ID         = int(os.environ.get("TU_CHAT_ID", "0"))
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
SUPABASE_URL       = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY       = os.environ.get("SUPABASE_KEY", "")
HORA_MENSAJE       = os.environ.get("HORA_MENSAJE", "08:00")
HORA_RESUMEN_NOCHE = os.environ.get("HORA_RESUMEN_NOCHE", "21:00")
HORA_REPORTE       = os.environ.get("HORA_REPORTE", "20:00")
# ─────────────────────────────────────────

EMOJIS_PRIORIDAD = {"urgente": "🔴", "normal": "🟡", "baja": "🟢"}
DIAS_ES = {
    "Monday": "Lunes", "Tuesday": "Martes", "Wednesday": "Miércoles",
    "Thursday": "Jueves", "Friday": "Viernes", "Saturday": "Sábado", "Sunday": "Domingo"
}


# ══════════════════════════════════════
#  SUPABASE — funciones base
# ══════════════════════════════════════

def sb_headers() -> dict:
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }


def sb_get(tabla: str, filtros: str = "") -> list:
    url  = f"{SUPABASE_URL}/rest/v1/{tabla}?{filtros}"
    resp = requests.get(url, headers=sb_headers(), timeout=10)
    resp.raise_for_status()
    return resp.json()


def sb_post(tabla: str, datos: dict) -> dict:
    url  = f"{SUPABASE_URL}/rest/v1/{tabla}"
    resp = requests.post(url, headers=sb_headers(), json=datos, timeout=10)
    resp.raise_for_status()
    result = resp.json()
    return result[0] if isinstance(result, list) else result


def sb_patch(tabla: str, filtros: str, datos: dict):
    url  = f"{SUPABASE_URL}/rest/v1/{tabla}?{filtros}"
    resp = requests.patch(url, headers=sb_headers(), json=datos, timeout=10)
    resp.raise_for_status()


def sb_delete(tabla: str, filtros: str):
    url  = f"{SUPABASE_URL}/rest/v1/{tabla}?{filtros}"
    resp = requests.delete(url, headers=sb_headers(), timeout=10)
    resp.raise_for_status()


# ══════════════════════════════════════
#  FECHAS
# ══════════════════════════════════════

def obtener_fecha(delta_dias: int = 0) -> str:
    return (datetime.now() + timedelta(days=delta_dias)).strftime("%Y-%m-%d")


# ══════════════════════════════════════
#  LÓGICA DE TAREAS
# ══════════════════════════════════════

def obtener_tareas(fecha: str = None) -> list:
    fecha = fecha or obtener_fecha()
    return sb_get("tareas", f"fecha=eq.{fecha}&order=id.asc")


def agregar_tarea(texto: str, prioridad: str = "normal", hora: str = None, fecha: str = None) -> dict:
    return sb_post("tareas", {
        "texto": texto,
        "prioridad": prioridad,
        "hora": hora,
        "fecha": fecha or obtener_fecha(),
        "hecho": False,
        "recordatorio_enviado": False
    })


def completar_tarea(id_tarea: int) -> bool:
    try:
        sb_patch("tareas", f"id=eq.{id_tarea}", {"hecho": True})
        return True
    except:
        return False


def eliminar_tarea(id_tarea: int) -> bool:
    try:
        sb_delete("tareas", f"id=eq.{id_tarea}")
        return True
    except:
        return False


def mover_tarea(id_tarea: int, fecha_destino: str) -> bool:
    try:
        sb_patch("tareas", f"id=eq.{id_tarea}", {
            "fecha": fecha_destino,
            "recordatorio_enviado": False
        })
        return True
    except:
        return False


def obtener_repetidas() -> list:
    return sb_get("repetidas", "order=id.asc")


def agregar_repetida(texto: str, prioridad: str = "normal", hora: str = None):
    sb_post("repetidas", {"texto": texto, "prioridad": prioridad, "hora": hora})


def inyectar_repetidas():
    repetidas = obtener_repetidas()
    if not repetidas:
        return
    tareas_hoy = obtener_tareas()
    textos_existentes = {t["texto"] for t in tareas_hoy}
    for r in repetidas:
        if r["texto"] not in textos_existentes:
            agregar_tarea(r["texto"], r.get("prioridad", "normal"), r.get("hora"))


# ══════════════════════════════════════
#  ESTADÍSTICAS
# ══════════════════════════════════════

def obtener_stats_semana() -> dict:
    stats = {
        "total": 0, "completadas": 0, "por_dia": {},
        "por_prioridad": {
            "urgente": {"total": 0, "completadas": 0},
            "normal":  {"total": 0, "completadas": 0},
            "baja":    {"total": 0, "completadas": 0}
        }
    }
    for i in range(7):
        fecha  = obtener_fecha(-i)
        tareas = sb_get("tareas", f"fecha=eq.{fecha}")
        if not tareas:
            continue
        total_dia  = len(tareas)
        hechas_dia = sum(1 for t in tareas if t["hecho"])
        stats["total"]      += total_dia
        stats["completadas"] += hechas_dia
        stats["por_dia"][fecha] = {"total": total_dia, "completadas": hechas_dia}
        for t in tareas:
            p = t.get("prioridad", "normal")
            if p in stats["por_prioridad"]:
                stats["por_prioridad"][p]["total"] += 1
                if t["hecho"]:
                    stats["por_prioridad"][p]["completadas"] += 1
    return stats


def formatear_stats(stats: dict) -> str:
    total       = stats["total"]
    completadas = stats["completadas"]
    pct         = round(completadas / total * 100) if total > 0 else 0
    bloques     = round(pct / 10)
    barra       = "█" * bloques + "░" * (10 - bloques)

    msg  = f"📊 *Estadísticas de la semana*\n\n"
    msg += f"Tareas totales: *{total}*\n"
    msg += f"Completadas: *{completadas}* ({pct}%)\n"
    msg += f"`[{barra}]`\n\n"

    if stats["por_dia"]:
        mejor_fecha = max(
            stats["por_dia"].items(),
            key=lambda x: x[1]["completadas"] / max(x[1]["total"], 1)
        )
        fecha_dt   = datetime.strptime(mejor_fecha[0], "%Y-%m-%d")
        dia_nombre = DIAS_ES.get(fecha_dt.strftime("%A"), fecha_dt.strftime("%A"))
        msg += f"🏆 *Día más productivo:* {dia_nombre}\n"
        msg += f"   {mejor_fecha[1]['completadas']}/{mejor_fecha[1]['total']} tareas\n\n"

    msg += "⚡ *Por prioridad:*\n"
    for p, emoji in EMOJIS_PRIORIDAD.items():
        datos = stats["por_prioridad"][p]
        if datos["total"] > 0:
            pct_p = round(datos["completadas"] / datos["total"] * 100)
            msg  += f"  {emoji} {p.capitalize()}: {datos['completadas']}/{datos['total']} ({pct_p}%)\n"

    if pct >= 80:
        msg += "\n_¡Semana excelente! Eres una máquina. 🚀_"
    elif pct >= 50:
        msg += "\n_Buen ritmo, sigue así. 💪_"
    else:
        msg += "\n_La próxima semana será mejor. ¡Tú puedes! 🌱_"

    return msg


# ══════════════════════════════════════
#  FORMATO DE MENSAJES
# ══════════════════════════════════════

def formatear_agenda(tareas: list, titulo: str = None, fecha_label: str = None) -> str:
    if not fecha_label:
        fecha_label = datetime.now().strftime("%A %d de %B").capitalize()
    encabezado = titulo or f"📅 *Agenda — {fecha_label}*"

    if not tareas:
        return f"{encabezado}\n\n_No hay tareas. Escríbeme para añadir una._"

    pendientes  = [t for t in tareas if not t["hecho"]]
    completadas = [t for t in tareas if t["hecho"]]
    msg = f"{encabezado}\n\n"

    if pendientes:
        orden = {"urgente": 0, "normal": 1, "baja": 2}
        pendientes.sort(key=lambda t: (orden.get(t.get("prioridad", "normal"), 1), t.get("hora") or "99:99"))
        msg += "🔲 *Pendientes:*\n"
        for t in pendientes:
            emoji = EMOJIS_PRIORIDAD.get(t.get("prioridad", "normal"), "🟡")
            hora  = f" `{t['hora']}`" if t.get("hora") else ""
            msg  += f"  {emoji} `{t['id']}.`{hora} {t['texto']}\n"

    if completadas:
        msg += "\n✅ *Completadas:*\n"
        for t in completadas:
            msg += f"  ~{t['texto']}~\n"

    hechas = len(completadas)
    total  = len(tareas)
    msg   += f"\n_Progreso: {hechas}/{total}_"
    return msg


def extraer_hora(texto: str):
    patron_24 = re.search(r'\b(\d{1,2}):(\d{2})\b', texto)
    patron_12 = re.search(r'\b(\d{1,2})(am|pm)\b', texto, re.IGNORECASE)
    if patron_24:
        h, m = int(patron_24.group(1)), int(patron_24.group(2))
        if 0 <= h <= 23 and 0 <= m <= 59:
            return f"{h:02d}:{m:02d}"
    if patron_12:
        h = int(patron_12.group(1))
        meridiem = patron_12.group(2).lower()
        if meridiem == "pm" and h != 12:
            h += 12
        if meridiem == "am" and h == 12:
            h = 0
        return f"{h:02d}:00"
    return None


def parsear_fecha_destino(texto: str):
    texto = texto.strip().lower()
    if texto in ("manana", "mañana", "tomorrow"):
        return obtener_fecha(1)
    if texto == "pasado":
        return obtener_fecha(2)
    try:
        datetime.strptime(texto, "%Y-%m-%d")
        return texto
    except ValueError:
        pass
    try:
        dt = datetime.strptime(texto, "%d-%m-%Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        pass
    return None


# ══════════════════════════════════════
#  IA — OPENROUTER
# ══════════════════════════════════════

def consultar_ia(mensaje_usuario: str, tareas_hoy: list) -> dict:
    hoy       = obtener_fecha()
    manana    = obtener_fecha(1)
    dia_semana = DIAS_ES.get(datetime.now().strftime("%A"), "")

    tareas_str = ""
    if tareas_hoy:
        for t in tareas_hoy:
            estado = "✅" if t["hecho"] else "⬜"
            tareas_str += f"  ID {t['id']}: {estado} {t['texto']} (prioridad: {t['prioridad']}, hora: {t.get('hora') or 'sin hora'})\n"
    else:
        tareas_str = "  (sin tareas hoy)"

    prompt = f"""Eres el asistente de agenda de un usuario de Telegram. Hoy es {dia_semana} {hoy}.

El usuario tiene estas tareas hoy:
{tareas_str}

El usuario te escribió: "{mensaje_usuario}"

Analiza el mensaje y responde SOLO con un JSON válido (sin texto extra, sin markdown) con esta estructura:

{{
  "accion": "agregar" | "completar" | "eliminar" | "mover" | "ver_agenda" | "ver_stats" | "ver_manana" | "chat",
  "texto": "descripción de la tarea (solo para agregar)",
  "prioridad": "urgente" | "normal" | "baja",
  "hora": "HH:MM o null",
  "fecha": "YYYY-MM-DD o null",
  "id": numero o null,
  "respuesta": "mensaje amigable confirmando lo que harás"
}}

Reglas:
- Si el usuario dice "mañana" usa la fecha {manana}
- urgente/importante/crítico → prioridad urgente
- cuando pueda/sin prisa/baja → prioridad baja
- Para saludos o conversación usa accion "chat"
- Respuesta en español, amigable, máx 2 líneas"""

    url     = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "google/gemini-2.0-flash-lite-001",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 512
    }

    try:
        resp      = requests.post(url, headers=headers, json=payload, timeout=15)
        resp.raise_for_status()
        data      = resp.json()
        texto     = data["choices"][0]["message"]["content"].strip()
        texto     = re.sub(r"```json|```", "", texto).strip()
        resultado = json.loads(texto)
        return resultado
    except Exception as e:
        print(f"Error IA: {e}")
        return {"accion": "chat", "respuesta": "No pude entender eso, ¿puedes repetirlo de otra forma?"}


# ══════════════════════════════════════
#  COMANDOS
# ══════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "👋 *¡Hola! Soy tu asistente de agenda v5.*\n\n"
        "Escríbeme en lenguaje natural:\n"
        "  _\"recuérdame llamar al médico mañana a las 10\"_\n"
        "  _\"marca la tarea 2 como completada\"_\n"
        "  _\"¿qué tengo hoy?\"_\n\n"
        "O usa los comandos:\n"
        "📋 /agenda — Ver tareas de hoy\n"
        "➕ /agregar `<tarea>` — Añadir tarea\n"
        "✅ /listo `<número>` — Marcar completada\n"
        "🗑️ /eliminar `<número>` — Eliminar tarea\n"
        "📦 /mover `<número>` `<destino>` — Mover tarea\n"
        "🔁 /repetir `<tarea>` — Tarea diaria fija\n"
        "📋 /repetidas — Ver tareas fijas\n"
        "🌙 /manana — Agenda de mañana\n"
        "📊 /stats — Estadísticas de la semana\n"
        "ℹ️ /ayuda — Ver esta ayuda"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def cmd_agenda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    inyectar_repetidas()
    tareas = obtener_tareas()
    await update.message.reply_text(formatear_agenda(tareas), parse_mode="Markdown")


async def cmd_manana(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fecha  = obtener_fecha(1)
    tareas = obtener_tareas(fecha)
    label  = (datetime.now() + timedelta(days=1)).strftime("%A %d de %B").capitalize()
    titulo = f"🌅 *Agenda de mañana — {label}*"
    await update.message.reply_text(formatear_agenda(tareas, titulo=titulo, fecha_label=label), parse_mode="Markdown")


async def cmd_agregar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Ejemplo: `/agregar Reunión a las 14:00`", parse_mode="Markdown")
        return
    texto = " ".join(context.args)
    if texto.startswith("!"):
        prioridad = "urgente"; texto = texto[1:].strip()
    elif texto.startswith("~"):
        prioridad = "baja"; texto = texto[1:].strip()
    else:
        prioridad = "normal"
    hora  = extraer_hora(texto)
    tarea = agregar_tarea(texto, prioridad, hora)
    emoji = EMOJIS_PRIORIDAD[prioridad]
    hora_txt = f" a las `{hora}`" if hora else ""
    await update.message.reply_text(
        f"✅ Tarea #{tarea['id']} añadida:\n{emoji} _{texto}_{hora_txt}",
        parse_mode="Markdown"
    )


async def cmd_listo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("⚠️ Ejemplo: `/listo 1`", parse_mode="Markdown")
        return
    numero = int(context.args[0])
    if completar_tarea(numero):
        await update.message.reply_text(f"🎉 ¡Tarea #{numero} completada!")
    else:
        await update.message.reply_text(f"❌ No encontré la tarea #{numero}.")


async def cmd_eliminar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("⚠️ Ejemplo: `/eliminar 1`", parse_mode="Markdown")
        return
    numero = int(context.args[0])
    if eliminar_tarea(numero):
        await update.message.reply_text(f"🗑️ Tarea #{numero} eliminada.")
    else:
        await update.message.reply_text(f"❌ No encontré la tarea #{numero}.")


async def cmd_mover(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2 or not context.args[0].isdigit():
        await update.message.reply_text(
            "⚠️ Uso: `/mover 1 manana` o `/mover 2 2025-06-15`",
            parse_mode="Markdown"
        )
        return
    numero  = int(context.args[0])
    destino = parsear_fecha_destino(context.args[1])
    if not destino:
        await update.message.reply_text("❌ Fecha no reconocida. Usa `manana`, `pasado` o `YYYY-MM-DD`.", parse_mode="Markdown")
        return
    if mover_tarea(numero, destino):
        fecha_dt   = datetime.strptime(destino, "%Y-%m-%d")
        dia_nombre = DIAS_ES.get(fecha_dt.strftime("%A"), fecha_dt.strftime("%A"))
        await update.message.reply_text(f"📦 Tarea #{numero} movida al *{dia_nombre} {fecha_dt.strftime('%d/%m')}*.", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ No encontré la tarea #{numero}.")


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = obtener_stats_semana()
    await update.message.reply_text(formatear_stats(stats), parse_mode="Markdown")


async def cmd_repetir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Ejemplo: `/repetir Tomar vitaminas a las 8:00`", parse_mode="Markdown")
        return
    texto = " ".join(context.args)
    if texto.startswith("!"):
        prioridad = "urgente"; texto = texto[1:].strip()
    elif texto.startswith("~"):
        prioridad = "baja"; texto = texto[1:].strip()
    else:
        prioridad = "normal"
    hora = extraer_hora(texto)
    agregar_repetida(texto, prioridad, hora)
    emoji = EMOJIS_PRIORIDAD[prioridad]
    await update.message.reply_text(f"🔁 Tarea diaria añadida:\n{emoji} _{texto}_", parse_mode="Markdown")


async def cmd_repetidas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    repetidas = obtener_repetidas()
    if not repetidas:
        await update.message.reply_text("_No tienes tareas repetidas._", parse_mode="Markdown")
        return
    msg = "🔁 *Tareas diarias fijas:*\n\n"
    for r in repetidas:
        emoji = EMOJIS_PRIORIDAD.get(r.get("prioridad", "normal"), "🟡")
        hora  = f" `{r['hora']}`" if r.get("hora") else ""
        msg  += f"  {emoji} `{r['id']}.`{hora} {r['texto']}\n"
    await update.message.reply_text(msg, parse_mode="Markdown")


async def cmd_ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update, context)


async def procesar_lenguaje_natural(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mensaje = update.message.text
    tareas  = obtener_tareas()
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    resultado = consultar_ia(mensaje, tareas)
    accion    = resultado.get("accion", "chat")
    respuesta = resultado.get("respuesta", "")

    if accion == "agregar":
        texto     = resultado.get("texto", mensaje)
        prioridad = resultado.get("prioridad", "normal")
        hora      = resultado.get("hora")
        fecha     = resultado.get("fecha") or obtener_fecha()
        tarea     = agregar_tarea(texto, prioridad, hora, fecha)
        emoji     = EMOJIS_PRIORIDAD[prioridad]
        hora_txt  = f" a las `{hora}`" if hora else ""
        await update.message.reply_text(f"{emoji} {respuesta}\n\n_Tarea #{tarea['id']} guardada_{hora_txt}", parse_mode="Markdown")

    elif accion == "completar":
        id_tarea = resultado.get("id")
        if id_tarea and completar_tarea(int(id_tarea)):
            await update.message.reply_text(f"🎉 {respuesta}")
        else:
            await update.message.reply_text("❌ No encontré esa tarea. Usa /agenda para ver los números.")

    elif accion == "eliminar":
        id_tarea = resultado.get("id")
        if id_tarea and eliminar_tarea(int(id_tarea)):
            await update.message.reply_text(f"🗑️ {respuesta}")
        else:
            await update.message.reply_text("❌ No encontré esa tarea.")

    elif accion == "mover":
        id_tarea = resultado.get("id")
        fecha    = resultado.get("fecha")
        if id_tarea and fecha and mover_tarea(int(id_tarea), fecha):
            await update.message.reply_text(f"📦 {respuesta}")
        else:
            await update.message.reply_text("❌ No pude mover la tarea.")

    elif accion == "ver_agenda":
        inyectar_repetidas()
        tareas = obtener_tareas()
        await update.message.reply_text(formatear_agenda(tareas), parse_mode="Markdown")

    elif accion == "ver_manana":
        fecha  = obtener_fecha(1)
        tareas = obtener_tareas(fecha)
        label  = (datetime.now() + timedelta(days=1)).strftime("%A %d de %B").capitalize()
        titulo = f"🌅 *Agenda de mañana — {label}*"
        await update.message.reply_text(formatear_agenda(tareas, titulo=titulo, fecha_label=label), parse_mode="Markdown")

    elif accion == "ver_stats":
        stats = obtener_stats_semana()
        await update.message.reply_text(formatear_stats(stats), parse_mode="Markdown")

    else:
        await update.message.reply_text(respuesta)


# ══════════════════════════════════════
#  SCHEDULER
# ══════════════════════════════════════

def enviar_msg_sync(app, texto):
    import asyncio
    asyncio.run_coroutine_threadsafe(
        app.bot.send_message(chat_id=TU_CHAT_ID, text=texto, parse_mode="Markdown"),
        app._loop
    )


def job_mensaje_matutino(app):
    inyectar_repetidas()
    tareas = obtener_tareas()
    hoy    = datetime.now().strftime("%A %d de %B").capitalize()
    titulo = f"🌅 *Buenos días — {hoy}*"
    enviar_msg_sync(app, formatear_agenda(tareas, titulo=titulo))


def job_resumen_nocturno(app):
    fecha  = obtener_fecha(1)
    tareas = obtener_tareas(fecha)
    label  = (datetime.now() + timedelta(days=1)).strftime("%A %d de %B").capitalize()
    titulo = f"🌙 *Resumen nocturno — mañana: {label}*"
    msg    = formatear_agenda(tareas, titulo=titulo, fecha_label=label)
    msg   += "\n\n_¡Buenas noches! 💤_"
    enviar_msg_sync(app, msg)


def job_reporte_semanal(app):
    stats = obtener_stats_semana()
    msg   = "📊 *Reporte semanal — Domingo*\n\n" + formatear_stats(stats)
    enviar_msg_sync(app, msg)


def job_recordatorios(app):
    ahora      = datetime.now()
    hora_30    = (ahora + timedelta(minutes=30)).strftime("%H:%M")
    try:
        tareas = sb_get("tareas", f"fecha=eq.{obtener_fecha()}&hecho=eq.false&recordatorio_enviado=eq.false")
    except:
        return
    for t in tareas:
        if t.get("hora") == hora_30:
            msg = (
                f"⏰ *Recordatorio*\n\n"
                f"{EMOJIS_PRIORIDAD.get(t.get('prioridad','normal'),'🟡')} "
                f"_{t['texto']}_ en 30 minutos (`{t['hora']}`)"
            )
            enviar_msg_sync(app, msg)
            sb_patch("tareas", f"id=eq.{t['id']}", {"recordatorio_enviado": True})


def iniciar_scheduler(app):
    schedule.every().day.at(HORA_MENSAJE).do(job_mensaje_matutino, app=app)
    schedule.every().day.at(HORA_RESUMEN_NOCHE).do(job_resumen_nocturno, app=app)
    schedule.every().sunday.at(HORA_REPORTE).do(job_reporte_semanal, app=app)
    schedule.every(1).minutes.do(job_recordatorios, app=app)

    def loop():
        while True:
            schedule.run_pending()
            time.sleep(30)

    threading.Thread(target=loop, daemon=True).start()
    print("✅ Scheduler activo")


# ══════════════════════════════════════
#  ARRANQUE
# ══════════════════════════════════════

def main():
    print("🤖 Iniciando bot de agenda v5 con Supabase...")
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("agenda",    cmd_agenda))
    app.add_handler(CommandHandler("agregar",   cmd_agregar))
    app.add_handler(CommandHandler("listo",     cmd_listo))
    app.add_handler(CommandHandler("eliminar",  cmd_eliminar))
    app.add_handler(CommandHandler("mover",     cmd_mover))
    app.add_handler(CommandHandler("stats",     cmd_stats))
    app.add_handler(CommandHandler("repetir",   cmd_repetir))
    app.add_handler(CommandHandler("repetidas", cmd_repetidas))
    app.add_handler(CommandHandler("manana",    cmd_manana))
    app.add_handler(CommandHandler("ayuda",     cmd_ayuda))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, procesar_lenguaje_natural))

    iniciar_scheduler(app)
    print("✅ Bot corriendo 24/7. Presiona Ctrl+C para detener.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
