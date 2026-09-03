import sys
import os
import re
import json
import uuid
import shutil
import asyncio
import functools
import datetime
import time
import subprocess
import PIL.Image

# Forzar flush inmediato en todos los print
print = functools.partial(print, flush=True)

# Configurar codificación UTF-8 para consola en Windows (soporte de emojis)
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Configurar FFmpeg automáticamente para yt-dlp y MoviePy
FFMPEG_PATH = None
try:
    import imageio_ffmpeg
    ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()
    if os.path.exists(ffmpeg_bin):
        FFMPEG_PATH = ffmpeg_bin
        bin_dir = os.path.dirname(ffmpeg_bin)
        if bin_dir not in os.environ.get("PATH", ""):
            os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
        # Asegurar copia local en la carpeta del bot
        local_ffmpeg = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg.exe")
        if not os.path.exists(local_ffmpeg):
            try:
                shutil.copy(ffmpeg_bin, local_ffmpeg)
            except Exception:
                pass
except Exception:
    pass

# Servidor HTTP de salud para compatibilidad con Render Web Service
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"White Pilled Bot is live and running 24/7!")

    def log_message(self, format, *args):
        pass

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    try:
        server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
        print(f"🌐 Servidor de salud activo en el puerto {port} (compatible con Render Web Service)")
        server.serve_forever()
    except Exception as e:
        print(f"⚠️ Nota en servidor HTTP de salud: {e}")

threading.Thread(target=run_health_server, daemon=True).start()

# Compatibilidad de Pillow 10+ con MoviePy 1.0.3 (ANTIALIAS fue reemplazado por LANCZOS)
if not hasattr(PIL.Image, 'ANTIALIAS'):
    PIL.Image.ANTIALIAS = PIL.Image.Resampling.LANCZOS

# Configuración automática de ImageMagick para MoviePy
if sys.platform == "win32":
    magick_path = os.environ.get("IMAGEMAGICK_BINARY") or shutil.which("magick") or r"C:\Users\goiko\AppData\Local\Microsoft\WindowsApps\magick.exe"
    if magick_path:
        os.environ["IMAGEMAGICK_BINARY"] = magick_path
        from moviepy.config import change_settings
        change_settings({"IMAGEMAGICK_BINARY": magick_path})

from dotenv import load_dotenv
load_dotenv()

import numpy as np
import yt_dlp
from google import genai
from google.genai import types
from moviepy.editor import VideoFileClip, ColorClip, TextClip, CompositeVideoClip, VideoClip, vfx
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.request import HTTPXRequest
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

# ================= CONFIGURACIÓN =================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8941001365:AAHNVirChTB66xlkSF1PUdsCmdNkM80rfKU")
TELEGRAM_CHAT_ID = int(os.environ.get("TELEGRAM_CHAT_ID", "6256580462"))

# Horarios diarios de publicación automática (hora peninsular española)
SCHEDULED_HOURS = ["12:00", "15:00", "18:00"]

# Tipografía Franklin Gothic Heavy
LOCAL_FONT_FILE = "franklin.ttf"
ORIGINAL_FONT_FILE = "Franklin Gothic Heavy Regular.ttf"
if not os.path.exists(LOCAL_FONT_FILE) and os.path.exists(ORIGINAL_FONT_FILE):
    try:
        shutil.copy(ORIGINAL_FONT_FILE, LOCAL_FONT_FILE)
    except Exception:
        pass

FONT_NAME = LOCAL_FONT_FILE if os.path.exists(LOCAL_FONT_FILE) else "Franklin-Gothic-Heavy"

# Modelos en orden de preferencia con fallback automático ante sobrecarga (503)
GEMINI_MODELS = ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.1-flash-lite"]
# =================================================

client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

SYSTEM_PROMPT = """
You are a political and social debate trend curator for a critical reflection Instagram account focused on SPAIN.
Your task is to identify viral opinions, street interviews, and hot sociopolitical debates IN SPAIN (español de España / sociedad y política española) from TikTok, Instagram Reels, and YouTube Shorts.

Search the latest debates in Spain and return ONLY a valid JSON object:
{
  "search_query": "Clean, concise search terms in Spanish from Spain (3-4 keywords max, e.g. 'debate alquiler espana' or 'polemica salario espana')",
  "top_title": "UPPERCASE IMPACTFUL HEADLINE IN EXACTLY 2 LINES (MAX 5-6 WORDS TOTAL, separated by \\n, e.g. ¿ALQUILAR ES\\nTIRAR EL DINERO?)",
  "speaker_name": "CONCISE SPEAKER NAME OR TOPIC IN 1-3 WORDS (e.g. SINDICATO INQUILINAS)",
  "caption": "Full Instagram copy in Spanish from Spain with hooks, critical reflection summary, call to comment and 4-5 hashtags"
}
"""

def fetch_trend_data(custom_topic=None):
    print("🔍 Generando titular y búsqueda de tendencia en España...")
    prompt = f"Debate o polémica sociopolítica en España: {custom_topic}" if custom_topic else "Busca el debate o entrevista sociopolítica más viral y comentada de hoy en España (con personajes, temas y español de España)."

    # Si la clave de Gemini es válida (empieza por AIza...), usar IA para buscar debates de última hora
    if GEMINI_API_KEY and GEMINI_API_KEY.startswith("AIza"):
        for model_name in GEMINI_MODELS:
            try:
                print(f"🤖 Consultando {model_name}...")
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        tools=[types.Tool(google_search=types.GoogleSearch())],
                        response_mime_type="application/json"
                    )
                )
                return parse_json_response(response.text)
            except Exception:
                try:
                    response = client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=SYSTEM_PROMPT,
                            response_mime_type="application/json"
                        )
                    )
                    return parse_json_response(response.text)
                except Exception:
                    continue

    if custom_topic:
        clean_top = format_to_two_lines(f"DEBATE SOBRE {custom_topic}".upper())
        return {
            "search_query": f"debate {custom_topic} espana #shorts",
            "top_title": clean_top,
            "speaker_name": custom_topic[:20].upper(),
            "caption": f"🔥 Debate sociopolítico sobre {custom_topic} en España.\n\n¿Qué opinas sobre este tema? Déjanos tu reflexión en comentarios. 👇\n\n#{custom_topic.replace(' ', '')} #Debate #Espana #Actualidad"
        }

    fallback_topics = [
        # Reflexiones profundas y filosofía de vida
        {"search_query": "instagram reel reflexion sobre la vida espana shorts", "top_title": "¿QUÉ ES LO\nQUE IMPORTA?", "speaker_name": "REFLEXIÓN", "caption": "Una reflexión sincera sobre el tiempo y las cosas a las que dedicamos nuestra energía. ¿Qué opinas? 👇\n\n#Reflexion #Vida #España #Pensamientos"},
        {"search_query": "instagram reel reflexion soledad sociedad actual espana shorts", "top_title": "¿CADA VEZ MÁS\nCONECTADOS Y SOLOS?", "speaker_name": "SOCIEDAD", "caption": "Vivimos en la era más hiperconectada de la historia, pero la soledad no deja de crecer. Déjanos tu reflexión. 👇\n\n#Soledad #Sociedad #Reflexion #España"},
        {"search_query": "instagram reel reflexion dinero y felicidad espana shorts", "top_title": "¿EL DINERO DA\nLA TRANQUILIDAD?", "speaker_name": "VALORES", "caption": "¿Hasta qué punto el dinero aporta paz mental o se convierte en una obsesión? Cuéntanos tu experiencia. 👇\n\n#Dinero #Exito #Felicidad #Reflexion"},
        # Opiniones de la gente en la calle
        {"search_query": "instagram reel preguntas por la calle espana sueldos shorts", "top_title": "¿CUÁNTO DEBERÍA\nCOBRAR UN JOVEN?", "speaker_name": "LA CALLE OPINA", "caption": "Salimos a la calle para conocer de primera mano la realidad laboral de la gente en España. ¿Qué opinas? 👇\n\n#LaCalleOpina #Sueldos #España #Opinion"},
        {"search_query": "instagram reel entrevista calle espana vivienda alquiler shorts", "top_title": "¿ALQUILAR ES\nTIRAR EL DINERO?", "speaker_name": "CRISIS VIVIENDA", "caption": "¿Tú qué opinas sobre los precios del alquiler y la vivienda en España? Déjalo en comentarios. 👇\n\n#Vivienda #Alquiler #España #Debate"},
        {"search_query": "instagram reel entrevista calle espana relaciones actuales shorts", "top_title": "¿LAS RELACIONES HOY\nSON MÁS DIFÍCILES?", "speaker_name": "RELACIONES", "caption": "La gente en la calle responde sobre cómo han cambiado el compromiso y los valores hoy en día. ¿Estás de acuerdo? 👇\n\n#Relaciones #Sociedad #Opinion #Espana"},
        # Debates sociopolíticos
        {"search_query": "instagram reel debate jornada laboral 37 horas espana shorts", "top_title": "¿REDUCIR JORNADA\nA 37,5 HORAS?", "speaker_name": "DEBATE LABORAL", "caption": "¿Crees que reducir la jornada aumentará la productividad o dañará a las PYMES? Comenta tu opinión. 👇\n\n#Trabajo #Economia #España"},
        {"search_query": "instagram reel debate pensiones espana futuro shorts", "top_title": "¿HABRÁ PENSIONES\nEN EL FUTURO?", "speaker_name": "SISTEMA PENSIONES", "caption": "¿Crees que el sistema de pensiones actual es sostenible para los jóvenes? Deja tu opinión. 👇\n\n#Pensiones #Jubilacion #España"},
        {"search_query": "instagram reel debate oposiciones o empresa privada espana shorts", "top_title": "¿OPOSITAR O\nEMPRENDER?", "speaker_name": "CULTURA LABORAL", "caption": "¿Merece la pena el esfuerzo de opositar en España o es mejor el sector privado? Comenta tu experiencia. 👇\n\n#Oposiciones #España #Empleo"},
        # Podcasts y momentos virales
        {"search_query": "instagram reel podcast reflexiones espana momentos epicos shorts", "top_title": "¿EL MAYOR ERROR\nDE NUESTRA ÉPOCA?", "speaker_name": "PODCAST", "caption": "Una charla sincera sobre las presiones de nuestra época. ¿Cuál es tu punto de vista? Déjalo abajo. 👇\n\n#Podcast #Reflexion #Espana #Viral"}
    ]
    import random
    return random.choice(fallback_topics)

def parse_json_response(raw_text):
    text = raw_text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return json.loads(text.strip())

def clean_text_for_title(t):
    clean = re.sub(r'[^\w\s¿?¡!ÁÉÍÓÚáéíóúÑñ]', '', t).strip()
    return clean

def is_uninformative_title(title_text):
    """Detecta si un título carece de contexto o es basura automática como 'Video by...'."""
    if not title_text:
        return True
    t = str(title_text).strip().lower()
    junk_patterns = [
        r'\bvideo by\b', r'\breel by\b', r'\bpost by\b', r'\bphoto by\b',
        r'\bclip by\b', r'\btiktok by\b', r'\bshared by\b', r'\baudio by\b',
        r'\bvideo de\b', r'\breel de\b', r'\bpublicaci[oó]n de\b', r'\bpost de\b',
        r'^video\b', r'^reel\b', r'^shorts?\b', r'^tiktok\b', r'^instagram\b'
    ]
    for pattern in junk_patterns:
        if re.search(pattern, t):
            return True
            
    # Contar palabras sustantivas
    words = [w for w in re.findall(r'\w+', t) if len(w) > 2 and w not in ['video', 'reel', 'clip', 'post', 'shorts', 'tiktok', 'instagram', 'by', 'de', 'del', 'en']]
    return len(words) < 2

def extract_from_description(raw_desc, uploader):
    """Analiza la descripción del video para extraer preguntas, citas o frases gancho y el interlocutor."""
    if not raw_desc:
        return None, None
        
    text = str(raw_desc).strip()
    
    # 1. Buscar interlocutor o personaje en la descripción
    speaker = None
    speaker_patterns = [
        r'(?i)(?:entrevista|charla|hablando|podcast)\s+(?:con|a)\s+([A-ZÁÉÍÓÚÑa-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑa-záéíóúñ]+)?)',
        r'(?i)(?:invitado|invitada|protagonista)\s*:\s*([A-ZÁÉÍÓÚÑa-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑa-záéíóúñ]+)?)',
        r'(?i)(?:palabras|reflexi[oó]n|opini[oó]n)\s+de\s+([A-ZÁÉÍÓÚÑa-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑa-záéíóúñ]+)?)',
        r'(?i)@([A-Za-z0-9_.]+)\s+(?:opina|habla|reflexiona|cuenta|dice)',
        r'(?i)^([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)\s*[:\-]'
    ]
    for sp in speaker_patterns:
        m = re.search(sp, text)
        if m:
            cand = m.group(1).replace('@', '').strip().upper()
            if 2 <= len(cand) <= 25 and not any(j in cand.lower() for j in ['video', 'shorts', 'reels', 'tiktok', 'instagram']):
                speaker = cand
                break

    # 2. Buscar pregunta clave en la descripción (ej: "¿Alquilar es tirar el dinero?")
    q_match = re.search(r'¿([^?]+)\?', text)
    if q_match:
        cand_q = f"¿{q_match.group(1).strip()}?"
        cand_q = re.sub(r'https?://\S+|[#@]\w+', '', cand_q).strip(' \n\t"\'«»')
        words = cand_q.split()
        if 3 <= len(words) <= 12 and not is_uninformative_title(cand_q):
            return cand_q, speaker

    # 3. Buscar cita textual entre comillas (ej: “El éxito sin paz mental no sirve de nada”)
    quote_match = re.search(r'["“«]([^"”»]{10,80})["”»]', text)
    if quote_match:
        cand_quote = quote_match.group(1).strip()
        cand_quote = re.sub(r'https?://\S+|[#@]\w+', '', cand_quote).strip(' \n\t"\'«»')
        words = cand_quote.split()
        if 3 <= len(words) <= 12 and not is_uninformative_title(cand_quote):
            return cand_quote, speaker

    # 4. Extraer la primera línea o frase con gancho de la descripción antes de hashtags
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for line in lines[:3]:
        clean_l = re.sub(r'https?://\S+|[#@]\w+', '', line).strip(' -_:|"\'“»«')
        if not clean_l:
            continue
        first_sentence = re.split(r'[.!?]', clean_l)[0].strip()
        words = first_sentence.split()
        if 3 <= len(words) <= 10 and not is_uninformative_title(first_sentence):
            return first_sentence, speaker

    return None, speaker

def extract_punchy_title_and_speaker(raw_title, raw_desc, uploader):
    """Extrae un titular con sentido completo y el interlocutor a partir del título y la descripción del video."""
    # Primero intentar extraer la mejor pregunta, cita o reflexión de la descripción
    desc_title, desc_speaker = extract_from_description(raw_desc, uploader)

    t = str(raw_title or "").strip()
    
    # Si el título del video es genérico, basura ("Video by...") o no existe, priorizar la descripción
    if is_uninformative_title(t) and desc_title:
        t = desc_title

    # Eliminar URLs, menciones y hashtags
    t = re.sub(r'https?://\S+', '', t)
    t = re.sub(r'[#@]\w+', '', t)
    # Limpiar separadores comunes como "|" o "•"
    if '|' in t:
        t = t.split('|')[0]
    if ' - ' in t:
        parts = t.split(' - ')
        t = parts[0] if len(parts[0]) > 10 else parts[1]
    
    t = ' '.join(t.split()).strip('-_: ')
    
    # Determinar el interlocutor para la barra inferior
    speaker = desc_speaker
    if not speaker:
        clean_uploader = (uploader or "").strip()
        clean_uploader = re.sub(r'[@_]', ' ', clean_uploader).strip()
        speaker = clean_uploader.split()[0].upper() if clean_uploader else "REFLEXIÓN"

    # Si tras limpiar sigue careciendo de contexto, intentar una última vez con la descripción
    if is_uninformative_title(t):
        if desc_title:
            t = desc_title
        else:
            return None, speaker

    top_title = format_to_two_lines(t)
    return top_title, speaker

def condense_or_rewrite_if_long(text):
    """Reescribe o sintetiza la frase si es demasiado larga para entrar holgadamente en 2 líneas."""
    clean = ' '.join(text.replace('\n', ' ').split())
    words = clean.split()
    
    # Si ya entra perfectamente en 2 líneas (hasta 7 palabras y <= 45 letras), conservarla tal cual
    if len(words) <= 7 and len(clean) <= 45:
        return clean
        
    print(f"✍️ Texto superior largo ({len(words)} palabras, {len(clean)} letras). Reescribiendo para que encaje...")
    
    # 1. Si Gemini está disponible con clave AIza, sintetizarla con IA
    if GEMINI_API_KEY and GEMINI_API_KEY.startswith("AIza"):
        try:
            prompt = f"Reescribe esta frase en un titular muy corto, polémico y con gancho en español de España de MÁXIMO 5-6 PALABRAS en total para un Reel. Devuelve ÚNICAMENTE el titular sin comillas ni explicaciones:\n\n{clean}"
            response = client.models.generate_content(
                model="gemini-3.5-flash",
                contents=prompt
            )
            rewritten = response.text.strip().strip('"\'')
            if rewritten and len(rewritten.split()) <= 7:
                return rewritten
        except Exception:
            pass
            
    # 2. Respaldo inteligente: eliminar muletillas y recortar a la idea clave
    fillers = [
        r'\bhoy en día\b', r'\ben mi opinión\b', r'\bla verdad es que\b',
        r'\bcreo que\b', r'\byo creo que\b', r'\bme parece que\b',
        r'\bes evidente que\b', r'\bcomo todos sabemos\b', r'\bpor otra parte\b',
        r'\ben este video\b', r'\bvamos a ver\b'
    ]
    condensed = clean
    for f in fillers:
        condensed = re.sub(f, '', condensed, flags=re.IGNORECASE)
    condensed = ' '.join(condensed.split())
    
    c_words = condensed.split()
    if len(c_words) > 7:
        condensed = ' '.join(c_words[:7])
        
    return condensed

def analyze_video_content(metadata_info, fallback_data, custom_top=None, custom_bottom=None):
    """Analiza la información del video para generar el titular en 2 líneas y el copy de Instagram."""
    print("🧠 Analizando contenido para redactar titulares fieles...")
    
    # Si el usuario especificó arriba y/o abajo explícitamente
    if custom_top or custom_bottom:
        formatted_top = None
        if custom_top:
            synthesized_top = condense_or_rewrite_if_long(custom_top)
            formatted_top = format_to_two_lines(synthesized_top)
            
        speaker = custom_bottom.strip().upper()[:25] if custom_bottom else None
        
        # Si falta alguno de los dos campos, extraerlo de los metadatos del video
        if not formatted_top or not speaker:
            auto_top, auto_speaker = extract_punchy_title_and_speaker(
                metadata_info.get("title") or fallback_data.get("top_title"),
                metadata_info.get("description") or fallback_data.get("caption"),
                metadata_info.get("uploader") or metadata_info.get("channel") or fallback_data.get("speaker_name")
            )
            if not formatted_top:
                formatted_top = auto_top
            if not speaker:
                speaker = auto_speaker

        clean_top_disp = formatted_top.replace('\n', ' ') if formatted_top else ""
        return {
            "top_title": formatted_top,
            "speaker_name": speaker,
            "caption": f"🔥 {clean_top_disp}\n\n¿Qué opinas sobre este debate? Déjalo en comentarios. 👇\n\n#Debate #España #Viral #Reflexion" if clean_top_disp else ""
        }

    real_title = metadata_info.get("title") or fallback_data.get("top_title") or ""
    real_uploader = metadata_info.get("uploader") or metadata_info.get("channel") or metadata_info.get("uploader_id") or fallback_data.get("speaker_name") or "DEBATE"
    real_desc = metadata_info.get("description") or metadata_info.get("caption") or fallback_data.get("caption") or ""

    # 1. Intentar con IA de Gemini
    analysis_prompt = f"""
Eres editor de una cuenta viral de Instagram Reels de reflexión sociopolítica en España.
Clip compartido:
Título: "{real_title}"
Autor: "{real_uploader}"
Descripción completa del post: "{real_desc[:1500]}"

Tu tarea:
1. "top_title": Titular polémico en MAYÚSCULAS en EXACTAMENTE 2 LÍNEAS (separadas por \\n, máximo 5-6 palabras en total) que plantee el conflicto o la pregunta clave del video basándote en lo que dice la descripción o el título.
2. "speaker_name": Nombre de la persona, autor o tema clave en MAYÚSCULAS (1-3 palabras máximo).
3. "caption": Copy para Instagram en español de España reflexionando sobre el video, invitando a comentar, con 4-5 hashtags.

Devuelve ÚNICAMENTE un objeto JSON:
{{
  "top_title": "LÍNEA 1\\nLÍNEA 2",
  "speaker_name": "NOMBRE O TEMA",
  "caption": "Copy completo..."
}}
"""
    if client:
        for model_name in GEMINI_MODELS:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=analysis_prompt,
                    config=types.GenerateContentConfig(response_mime_type="application/json")
                )
                parsed = parse_json_response(response.text)
                top_t = parsed.get("top_title")
                if top_t and not is_uninformative_title(top_t):
                    print(f"✅ Titular generado con IA: {top_t}")
                    return parsed
            except Exception:
                pass

    # 2. Extracción inteligente de la metadata real del video
    punchy_title, speaker = extract_punchy_title_and_speaker(real_title, real_desc, real_uploader)
    if not punchy_title or is_uninformative_title(punchy_title):
        # El bot carece de contexto suficiente para poner un titular de calidad
        return {
            "top_title": None,
            "speaker_name": speaker,
            "caption": ""
        }

    display_title = format_to_two_lines(punchy_title)
    return {
        "top_title": display_title,
        "speaker_name": speaker,
        "caption": f"🔥 {display_title.replace(chr(10), ' ')}\n\n¿Qué opinas sobre este tema? Déjanos tu reflexión en los comentarios. 👇\n\n#Debate #España #Viral #Opinion"
    }

def clean_search_query(q):
    words = [w for w in re.split(r'\s+', q.strip()) if w.lower() not in ['tiktok', 'clip', 'video', 'shorts']]
    core = " ".join(words[:5])
    if "espana" not in core.lower() and "españa" not in core.lower():
        core = f"{core} espana"
    # Priorizar Instagram Reels como fuente primaria de búsqueda
    if "instagram" not in core.lower() and "reel" not in core.lower():
        core = f"instagram reel {core}"
    return f"{core} #shorts"

def duration_and_year_filter(info_dict, *, incomplete):
    # 1. Duración adecuada para formato vertical corto (5s - 600s)
    dur = info_dict.get('duration')
    if dur is not None and (dur > 600 or dur < 5):
        return f"Video duration {dur}s not in [5, 600]"

    # 2. Filtrar fecha: ESTRICTAMENTE a partir de 2020 (rechazar todo lo anterior)
    upload_date = str(info_dict.get('upload_date') or "")
    if upload_date and len(upload_date) >= 4 and upload_date[:4].isdigit():
        year = int(upload_date[:4])
        if year < 2020:
            return f"Video de {year} es anterior a 2020 (rechazado)"

    release_year = info_dict.get('release_year')
    if release_year and int(release_year) < 2020:
        return f"Año {release_year} es anterior a 2020 (rechazado)"

    return None

GUARANTEED_FALLBACK_QUERIES = [
    "instagram reel reflexion sobre la vida espana shorts",
    "instagram reels preguntas por la calle espana shorts",
    "instagram reel entrevista callejera espana shorts",
    "instagram reel reflexion soledad sociedad actual espana shorts",
    "instagram reels virales espana reflexion shorts",
    "instagram reel opinion de la gente espana shorts",
    "instagram reel microfono en la calle espana shorts",
    "instagram reel debate espana shorts",
    "instagram reel alquiler jovenes espana shorts",
    "instagram reels podcast reflexiones espana shorts"
]

def download_clip(query_or_url):
    unique_id = f"{int(time.time())}_{uuid.uuid4().hex[:6]}"
    output_file = f"raw_temp_{unique_id}.mp4"
    print(f"📥 Buscando y descargando clip: {query_or_url}")

    is_direct_url = query_or_url.startswith("http")
    is_youtube = ("youtube.com" in query_or_url) or ("youtu.be" in query_or_url) or (not is_direct_url)
    cookie_path = "cookies.txt" if (os.path.exists("cookies.txt") and not is_youtube) else None
    extractor_args = {
        'youtube': {
            'player_client': ['android'],
            'player_skip': ['webpage', 'configs']
        }
    } if is_youtube else {}

    meta_info = {}

    # Caso 1: Descarga directa por URL (Instagram Reel, TikTok, YouTube)
    if is_direct_url:
        opts = {
            'format': '18/bestvideo*+bestaudio/best',
            'outtmpl': output_file,
            'merge_output_format': 'mp4',
            'extractor_args': extractor_args,
            'cookiefile': cookie_path,
            'ffmpeg_location': FFMPEG_PATH,
            'quiet': True,
            'no_warnings': True
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            meta_info = ydl.extract_info(query_or_url, download=True) or {}
        if not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
            raise RuntimeError(f"No se pudo descargar el video desde la URL: {query_or_url}")

        # Rechazar videos anteriores a 2020 en URL directa
        upload_date = str(meta_info.get('upload_date') or "")
        if upload_date and len(upload_date) >= 4 and upload_date[:4].isdigit():
            year = int(upload_date[:4])
            if year < 2020:
                try:
                    os.remove(output_file)
                except Exception:
                    pass
                raise RuntimeError(f"El video proporcionado es del año {year} (anterior a 2020). Solo se procesan videos a partir del año 2020.")

        return output_file, meta_info

    # Caso 2: Búsqueda inteligente imparable de videos (Instagram Reels como fuente primaria)
    opts_search = {
        'format': '18/bestvideo*+bestaudio/best',
        'merge_output_format': 'mp4',
        'outtmpl': output_file,
        'extractor_args': extractor_args,
        'match_filter': duration_and_year_filter,
        'dateafter': '20200101',
        'ffmpeg_location': FFMPEG_PATH,
        'max_downloads': 1,
        'quiet': True,
        'no_warnings': True
    }

    errors_log = []
    # 1. Probar la consulta original adaptada (Instagram Reels prioritario)
    clean_q = clean_search_query(query_or_url)
    print(f"🎯 Intento 1: Búsqueda para '{clean_q}' (a partir de 2020)...")
    try:
        with yt_dlp.YoutubeDL(opts_search) as ydl:
            search_res = ydl.extract_info(f"ytsearch15:{clean_q}", download=True)
            if search_res and 'entries' in search_res and search_res['entries']:
                meta_info = search_res['entries'][0] or {}
    except yt_dlp.utils.MaxDownloadsReached:
        pass
    except Exception as e:
        err_msg = str(e)
        errors_log.append(f"Intento 1: {err_msg[:120]}")
        print(f"⚠️ Nota en intento 1: {err_msg}")

    # 2. Si no descargó, probar búsqueda alternativa de Reels de España
    if not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
        words = [w for w in re.findall(r'\w+', query_or_url) if w.lower() not in ['shorts', 'tiktok', 'espana', 'instagram', 'reel', 'reels']]
        alt_q = f"instagram reel {' '.join(words[:2])} espana shorts"
        print(f"🔄 Intento 2: Búsqueda Reels simplificada: '{alt_q}'...")
        try:
            with yt_dlp.YoutubeDL(opts_search) as ydl:
                search_res = ydl.extract_info(f"ytsearch15:{alt_q}", download=True)
                if search_res and 'entries' in search_res and search_res['entries']:
                    meta_info = search_res['entries'][0] or {}
        except yt_dlp.utils.MaxDownloadsReached:
            pass
        except Exception as e:
            err_msg = str(e)
            errors_log.append(f"Intento 2: {err_msg[:120]}")
            print(f"⚠️ Nota en intento 2: {err_msg}")

    # 3. Si aún no hay video, recorrer la lista de temas virales garantizados de España
    if not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
        for fallback_q in GUARANTEED_FALLBACK_QUERIES:
            print(f"🔥 Intento garantizado: '{fallback_q}'...")
            try:
                with yt_dlp.YoutubeDL(opts_search) as ydl:
                    search_res = ydl.extract_info(f"ytsearch15:{fallback_q}", download=True)
                    if search_res and 'entries' in search_res and search_res['entries']:
                        meta_info = search_res['entries'][0] or {}
            except yt_dlp.utils.MaxDownloadsReached:
                pass
            except Exception as e:
                err_msg = str(e)
                errors_log.append(f"{fallback_q}: {err_msg[:120]}")
                print(f"⚠️ Nota en fallback: {err_msg}")

            if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
                print(f"✅ Video encontrado y descargado con éxito desde '{fallback_q}'!")
                break

    # 4. Último recurso absoluto: descargar cualquier clip corto de debate sin filtro de duración
    if not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
        print("🚨 Último recurso: Descargando clip sin restricción de filtro...")
        opts_relaxed = {
            'format': '18/bestvideo*+bestaudio/best',
            'merge_output_format': 'mp4',
            'outtmpl': output_file,
            'extractor_args': extractor_args,
            'ffmpeg_location': FFMPEG_PATH,
            'max_downloads': 1,
            'quiet': True,
            'no_warnings': True
        }
        try:
            with yt_dlp.YoutubeDL(opts_relaxed) as ydl:
                search_res = ydl.extract_info("ytsearch5:debate espana shorts", download=True)
                if search_res and 'entries' in search_res and search_res['entries']:
                    meta_info = search_res['entries'][0] or {}
        except yt_dlp.utils.MaxDownloadsReached:
            pass
        except Exception as e:
            err_msg = str(e)
            errors_log.append(f"Último recurso: {err_msg[:120]}")
            print(f"⚠️ Nota en último recurso: {err_msg}")

    # 5. Red de seguridad infalible: canales verificados de Shorts de debate y actualidad en España
    # (Los canales de Shorts NUNCA requieren búsqueda ni activan detección de bots por IP)
    GUARANTEED_CHANNELS = [
        "https://www.youtube.com/@el_pais/shorts",
        "https://www.youtube.com/@elmundo/shorts",
        "https://www.youtube.com/@laSextaNoticias/shorts",
        "https://www.youtube.com/@rtvenoticias/shorts"
    ]

    if not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
        print("🛡️ Nivel 5: Descargando debate verificado desde canal oficial...")
        opts_channel = {
            'format': '18/bestvideo*+bestaudio/best',
            'merge_output_format': 'mp4',
            'outtmpl': output_file,
            'extractor_args': extractor_args,
            'playlist_items': '1',
            'ffmpeg_location': FFMPEG_PATH,
            'max_downloads': 1,
            'quiet': True,
            'no_warnings': True
        }
        for ch_url in GUARANTEED_CHANNELS:
            try:
                with yt_dlp.YoutubeDL(opts_channel) as ydl:
                    search_res = ydl.extract_info(ch_url, download=True)
                    if search_res and 'entries' in search_res and search_res['entries']:
                        meta_info = search_res['entries'][0] or {}
            except yt_dlp.utils.MaxDownloadsReached:
                pass
            except Exception as e:
                print(f"⚠️ Nota canal {ch_url}: {e}")

            if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
                print(f"✅ Video verificado descargado desde {ch_url}!")
                break

    if not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
        det = " | ".join(errors_log[-2:]) if errors_log else "Filtros de duración"
        raise RuntimeError(f"No se pudo descargar ningún video en Render. Detalle: {det}")

    return output_file, meta_info

def format_to_two_lines(text):
    """Formatea cualquier frase para que tenga exactamente 2 líneas con sentido completo, sin cortar palabras bruscamente."""
    clean = ' '.join(text.replace('\n', ' ').split())
    words = clean.split()
    if len(words) <= 2:
        return clean.upper()
    if len(words) == 3:
        return f"{words[0].upper()}\n{' '.join(words[1:]).upper()}"
    
    # Preposiciones, conjunciones y artículos donde es natural hacer la pausa de lectura
    split_connectors = {
        'de', 'del', 'en', 'por', 'para', 'con', 'sin', 'sobre', 'tras',
        'es', 'son', 'ser', 'era', 'fue',
        'que', 'y', 'o', 'pero', 'mas', 'si', 'ni',
        'el', 'la', 'los', 'las', 'un', 'una', 'unos', 'unas',
        'vs', 'contra'
    }
    
    # Limitar longitud máxima a 9-10 palabras para no saturar la pantalla, pero sin cortar el sentido
    if len(words) > 10:
        words = words[:10]
        
    n = len(words)
    best_split = n // 2
    best_score = float('inf')
    
    for i in range(1, n):
        l1 = ' '.join(words[:i])
        l2 = ' '.join(words[i:])
        diff = abs(len(l1) - len(l2))
        
        bonus = 0
        # Es natural empezar la segunda línea con un conector
        if words[i].lower() in split_connectors:
            bonus -= 12
        # Evitar dejar una palabra diminuta suelta al final de la primera línea
        if len(words[i-1]) <= 2:
            bonus += 10
            
        score = diff + bonus
        if score < best_score:
            best_score = score
            best_split = i
            
    line1 = ' '.join(words[:best_split]).upper()
    line2 = ' '.join(words[best_split:]).upper()
    return f"{line1}\n{line2}"

def create_scaled_two_line_clip(text, max_w, max_h, font_path, initial_fontsize=88, min_fontsize=38):
    """Genera un TextClip asegurando que no sobrepase exactamente 2 líneas y quepa en max_w y max_h."""
    formatted = format_to_two_lines(text)
    best_clip = None
    for fs in range(initial_fontsize, min_fontsize - 1, -4):
        t_clip = TextClip(
            formatted.upper(),
            fontsize=fs,
            color="white",
            font=font_path,
            size=(max_w, None),
            method="caption",
            align="center"
        )
        if t_clip.h <= fs * 2.6 and t_clip.h <= max_h:
            best_clip = t_clip
            break
        t_clip.close()

    if not best_clip:
        best_clip = TextClip(
            formatted.upper(),
            fontsize=min_fontsize,
            color="white",
            font=font_path,
            size=(max_w, None),
            method="caption",
            align="center"
        )
    return best_clip

def edit_whitepilled_style(raw_path, top_title, speaker_name, output_path=None):
    if not output_path:
        output_path = f"final_reel_{int(time.time())}_{uuid.uuid4().hex[:6]}.mp4"
    print("🎬 Editando video (B/N, Encuadre inteligente, Barra inferior completa)...")
    if not os.path.exists(raw_path) or os.path.getsize(raw_path) == 0:
        raise FileNotFoundError(f"El archivo fuente {raw_path} no existe o está vacío.")

    clip = VideoFileClip(raw_path).fx(vfx.blackwhite)
    print(f"⏱️ Duración del video a editar: {clip.duration:.1f} segundos.")

    target_w, target_h = 1080, 1920
    MAX_WINDOW_H = 1050

    if clip.w < clip.h:
        # CASO VIDEO VERTICAL (Reels de Instagram / TikToks / Shorts 9:16)
        scale = target_w / clip.w
        scaled_w = target_w
        scaled_h = int(clip.h * scale)
        clip_scaled = clip.resize((scaled_w, scaled_h))

        if scaled_h > MAX_WINDOW_H:
            excess_h = scaled_h - MAX_WINDOW_H
            # Centrar en el rostro/pecho del interlocutor en el tercio superior
            crop_y1 = int(excess_h * 0.22)
            main_video = (
                clip_scaled
                .crop(x1=0, y1=crop_y1, width=target_w, height=MAX_WINDOW_H)
                .set_position(("center", "center"))
            )
            video_h = MAX_WINDOW_H
            video_w = target_w
        else:
            main_video = clip_scaled.set_position(("center", "center"))
            video_h = scaled_h
            video_w = scaled_w
    else:
        # CASO VIDEO HORIZONTAL (16:9)
        base_scale = target_w / clip.w
        enlarge_factor = 1.16
        video_w = int(clip.w * base_scale * enlarge_factor)
        video_h = int(clip.h * base_scale * enlarge_factor)

        if video_h > MAX_WINDOW_H:
            video_h = MAX_WINDOW_H
            video_w = int(clip.w * (video_h / clip.h))

        main_video = clip.resize((video_w, video_h)).set_position(("center", "center"))

    video_y_start = (target_h - video_h) // 2
    video_y_bottom = video_y_start + video_h

    # Fondo negro
    background = ColorClip(size=(target_w, target_h), color=(0, 0, 0)).set_duration(clip.duration)

    # 1. TEXTO SUPERIOR ESTRICTAMENTE EN 2 LÍNEAS (Dinámico según espacio del video)
    top_margin = 75
    bottom_limit = video_y_start - 20
    available_top_h = max(60, bottom_limit - top_margin)
    max_text_w = 940

    initial_top_fs = min(98, max(74, int(available_top_h * 0.35)))

    top_text_clip = create_scaled_two_line_clip(
        top_title,
        max_w=max_text_w,
        max_h=available_top_h,
        font_path=FONT_NAME,
        initial_fontsize=initial_top_fs,
        min_fontsize=38
    )
    top_y = top_margin + (available_top_h - top_text_clip.h) // 2
    top_text = (
        top_text_clip
        .set_position(("center", top_y))
        .set_duration(clip.duration)
    )

    # 2. BARRA DE PROGRESO AL FONDO (Pegada a abajo, ancho 1080px, 88px de alto)
    bar_height = 88
    bar_total_w = target_w
    bar_y = target_h - bar_height

    def make_progress_frame(t):
        w = max(1, int(bar_total_w * (t / clip.duration)))
        return np.full((bar_height, w, 3), 255, dtype=np.uint8)

    progress_bar = (
        VideoClip(make_frame=make_progress_frame)
        .set_duration(clip.duration)
        .set_position((0, bar_y))
    )

    # 3. TEXTO INFERIOR (10% más pequeño, estrictamente 2 líneas)
    bottom_start = video_y_bottom + 20
    bottom_end = bar_y - 20
    available_bottom_h = max(80, bottom_end - bottom_start)

    clean_speaker = " ".join(speaker_name.replace('\n', ' ').split())
    bottom_caption = f"{clean_speaker}\n¿QUÉ OPINAS?"

    bottom_text_clip = None
    for fs in range(80, 40, -4):
        t_clip = TextClip(
            bottom_caption.upper(),
            fontsize=fs,
            color="white",
            font=FONT_NAME,
            size=(max_text_w, None),
            method="caption",
            align="center"
        )
        if t_clip.h <= fs * 2.6 and t_clip.h <= available_bottom_h:
            bottom_text_clip = t_clip
            break
        t_clip.close()

    if not bottom_text_clip:
        bottom_text_clip = TextClip(
            bottom_caption.upper(),
            fontsize=40,
            color="white",
            font=FONT_NAME,
            size=(max_text_w, None),
            method="caption",
            align="center"
        )

    bottom_y = bottom_start + (available_bottom_h - bottom_text_clip.h) // 2
    bottom_text = (
        bottom_text_clip
        .set_position(("center", bottom_y))
        .set_duration(clip.duration)
    )

    final = CompositeVideoClip([background, main_video, progress_bar, top_text, bottom_text], size=(target_w, target_h))
    if clip.audio is not None:
        final = final.set_audio(clip.audio)

    # Configurar bitrate inteligente para que el video NUNCA supere 20-25MB
    dur = max(1.0, float(clip.duration))
    # Tamaño objetivo de seguridad: ~18-20 MB (garantiza subida instantánea en cualquier red)
    max_target_bytes = 18 * 1024 * 1024
    target_total_kbps = int((max_target_bytes * 8) / (dur * 1000))
    video_kbps = max(380, min(1600, target_total_kbps - 96))

    # Renderizado optimizado multi-hilo para Reels
    threads_count = min(12, os.cpu_count() or 4)
    final.write_videofile(
        output_path,
        fps=25,
        codec="libx264",
        audio_codec="aac",
        preset="veryfast",
        threads=threads_count,
        bitrate=f"{video_kbps}k",
        audio_bitrate="96k",
        ffmpeg_params=[
            "-pix_fmt", "yuv420p",
            "-maxrate", f"{int(video_kbps * 1.2)}k",
            "-bufsize", f"{int(video_kbps * 2)}k"
        ],
        logger=None
    )
    clip.close()
    final.close()

    # Garantía absoluta: si el archivo supera 25MB, recomprimir de inmediato con FFmpeg
    output_path = ensure_under_telegram_limit(output_path, max_bytes=25 * 1024 * 1024)
    return output_path

def ensure_under_telegram_limit(file_path, max_bytes=25 * 1024 * 1024):
    """Comprueba el tamaño del video y si supera el límite de seguridad lo comprime con FFmpeg."""
    if not file_path or not os.path.exists(file_path):
        return file_path

    size = os.path.getsize(file_path)
    if size <= max_bytes:
        return file_path

    print(f"⚠️ Video pesa {size / (1024*1024):.2f} MB. Comprimiendo a <20MB para asegurar envío sin cortes...")

    ffmpeg_exe = FFMPEG_PATH or "ffmpeg"
    temp_comp = f"comp_{int(time.time())}_{uuid.uuid4().hex[:6]}.mp4"

    # Estimar duración
    try:
        from moviepy.editor import VideoFileClip
        with VideoFileClip(file_path) as tmp_c:
            dur = max(1.0, float(tmp_c.duration))
    except Exception:
        dur = 120.0

    target_kbps = max(300, int((16 * 1024 * 1024 * 8) / (dur * 1000)) - 96)

    cmd = [
        ffmpeg_exe, "-y",
        "-i", file_path,
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-b:v", f"{target_kbps}k",
        "-maxrate", f"{int(target_kbps * 1.2)}k",
        "-bufsize", f"{int(target_kbps * 2)}k",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "96k",
        temp_comp
    ]

    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        if os.path.exists(temp_comp) and os.path.getsize(temp_comp) > 0:
            try:
                os.remove(file_path)
            except Exception:
                pass
            os.rename(temp_comp, file_path)
            print(f"✅ Video comprimido con éxito a {os.path.getsize(file_path) / (1024*1024):.2f} MB.")
    except Exception as e:
        print(f"⚠️ Nota al recomprimir: {e}")
        if os.path.exists(temp_comp):
            try:
                os.remove(temp_comp)
            except Exception:
                pass

    return file_path

async def safe_send_video(context, chat_id, final_video, caption_text):
    """Envía el video a Telegram con reintentos robustos y soporte para fallbacks."""
    final_video = ensure_under_telegram_limit(final_video, max_bytes=25 * 1024 * 1024)
    clean_caption = caption_text[:997] + "..." if len(caption_text) > 1000 else caption_text

    # Intento 1: Envío normal como video optimizado
    try:
        with open(final_video, "rb") as f:
            await context.bot.send_video(
                chat_id=chat_id,
                video=f,
                caption=clean_caption,
                parse_mode="Markdown",
                supports_streaming=True,
                write_timeout=300,
                read_timeout=300
            )
        return True
    except Exception as e:
        print(f"⚠️ Intento 1 de subida falló ({e}). Recomprimiendo a 12MB y reintentando...")

    # Intento 2: Recomprimir a 12MB y reintentar send_video
    try:
        final_video = ensure_under_telegram_limit(final_video, max_bytes=12 * 1024 * 1024)
        await asyncio.sleep(1.5)
        with open(final_video, "rb") as f:
            await context.bot.send_video(
                chat_id=chat_id,
                video=f,
                caption=clean_caption,
                parse_mode="Markdown",
                supports_streaming=True,
                write_timeout=300,
                read_timeout=300
            )
        return True
    except Exception as e:
        print(f"⚠️ Intento 2 de subida falló ({e}). Probando envío alternativo como documento...")

    # Intento 3: Envío como documento
    try:
        with open(final_video, "rb") as f:
            await context.bot.send_document(
                chat_id=chat_id,
                document=f,
                caption=clean_caption,
                parse_mode="Markdown",
                write_timeout=300,
                read_timeout=300
            )
        return True
    except Exception as e:
        print(f"❌ Error crítico en subida a Telegram: {e}")
        raise

ACTIVE_TASKS = {}
PENDING_VIDEOS = {}
CANCEL_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("🛑 Cancelar acción", callback_data="abort_process")]
])

async def update_status(msg, text, show_cancel=True):
    try:
        reply_markup = CANCEL_KEYBOARD if show_cancel else None
        await msg.edit_text(text, parse_mode="Markdown", reply_markup=reply_markup)
    except Exception:
        pass

async def abort_task_for_chat(chat_id):
    """Cancela la tarea activa para este chat y limpia los archivos temporales."""
    chat_key = str(chat_id)
    print(f"🛑 Solicitud de cancelación recibida para chat: {chat_key}")
    info = ACTIVE_TASKS.pop(chat_key, None)
    if not info and chat_key.lstrip('-').isdigit():
        info = ACTIVE_TASKS.pop(int(chat_key), None)
        
    if info:
        info["cancelled"] = True
        task = info.get("task")
        if task and not task.done():
            print(f"🛑 Cancelando tarea activa: {task}")
            task.cancel()
        for p in [info.get("raw_clip"), info.get("final_video")]:
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass
        msg = info.get("msg")
        if msg:
            try:
                await msg.edit_text("🛑 *Acción cancelada.*\n\n_Se ha detenido la descarga y edición del video y se han liberado los recursos._", parse_mode="Markdown")
            except Exception:
                pass
        return True
    print(f"ℹ️ No se encontró tarea activa para {chat_key}. Tareas registradas: {list(ACTIVE_TASKS.keys())}")
    return False

class SimpleBotContext:
    def __init__(self, bot):
        self.bot = bot

async def resume_editing_pending(chat_id, context, pending, custom_top, custom_bottom):
    """Reanuda la edición de un video que ya fue descargado tras recibir el titular del usuario."""
    raw_clip = pending["raw_clip"]
    meta_info = pending["meta_info"]
    data = pending["data"]

    msg = await context.bot.send_message(
        chat_id=chat_id,
        text="🎬 *[1/2]* Titular recibido. Maquetando video en estilo White Pilled...",
        parse_mode="Markdown",
        reply_markup=CANCEL_KEYBOARD
    )
    final_video = None
    current_task = asyncio.current_task()
    chat_key = str(chat_id)
    ACTIVE_TASKS[chat_key] = {
        "task": current_task,
        "msg": msg,
        "raw_clip": raw_clip,
        "final_video": None
    }

    try:
        video_data = await asyncio.to_thread(analyze_video_content, meta_info, data, custom_top, custom_bottom)
        clean_top_title = video_data['top_title'].replace('\n', ' ')

        await update_status(
            msg,
            f"🎬 *[1/2]* Maquetando video:\n*{clean_top_title}*\n\n_Encuadrando vertical, aplicando B/N y barra inferior completa..._"
        )

        final_video = await asyncio.to_thread(
            edit_whitepilled_style, raw_clip, video_data["top_title"], video_data["speaker_name"]
        )
        if chat_key in ACTIVE_TASKS:
            ACTIVE_TASKS[chat_key]["final_video"] = final_video

        await update_status(
            msg,
            "📤 *[2/2]* ¡Edición completada!\n\n_Subiendo video a Telegram..._",
            show_cancel=False
        )

        caption_text = f"🔥 *{clean_top_title}*\n\n{video_data['caption']}"
        await safe_send_video(context, chat_id, final_video, caption_text)

        try:
            await msg.delete()
        except Exception:
            pass
    except asyncio.CancelledError:
        print(f"🛑 Reanudación cancelada por el usuario para chat_id {chat_id}")
        if raw_clip and os.path.exists(raw_clip):
            try:
                os.remove(raw_clip)
            except Exception:
                pass
        if final_video and os.path.exists(final_video):
            try:
                os.remove(final_video)
            except Exception:
                pass
        return
    except Exception as e:
        print(f"❌ Error en resume_editing_pending: {e}")
        await context.bot.send_message(chat_id=chat_id, text=f"⚠️ Error al reanudar: {e}")
    finally:
        ACTIVE_TASKS.pop(chat_key, None)
        if raw_clip and os.path.exists(raw_clip):
            try:
                os.remove(raw_clip)
            except Exception:
                pass
        if final_video and os.path.exists(final_video):
            try:
                os.remove(final_video)
            except Exception:
                pass

async def process_and_send(chat_id, context, custom_topic=None, direct_url=None, custom_top=None, custom_bottom=None, is_scheduled=False, batch_info=None, is_batch_item=False):
    header = "⏰ *[ENVÍO DIARIO PROGRAMADO]*\n\n" if is_scheduled else ""
    batch_prefix = f"📦 *[Video {batch_info['index']}/{batch_info['total']}]*\n" if batch_info else ""
    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"{header}{batch_prefix}🔍 *[1/5]* Localizando clip de video...",
        parse_mode="Markdown",
        reply_markup=CANCEL_KEYBOARD
    )
    raw_clip = None
    final_video = None
    
    current_task = asyncio.current_task()
    chat_key = str(chat_id)
    if not is_batch_item or chat_key not in ACTIVE_TASKS:
        ACTIVE_TASKS[chat_key] = {
            "task": current_task,
            "msg": msg,
            "raw_clip": None,
            "final_video": None
        }
    else:
        ACTIVE_TASKS[chat_key]["msg"] = msg
        ACTIVE_TASKS[chat_key]["raw_clip"] = None
        ACTIVE_TASKS[chat_key]["final_video"] = None

    try:
        if direct_url:
            data = {"search_query": direct_url, "top_title": "DEBATE VIRAL", "speaker_name": "DEBATE", "caption": ""}
            target = direct_url
            disp_url = direct_url[:45] + "..." if len(direct_url) > 45 else direct_url
            await update_status(
                msg,
                f"{header}{batch_prefix}📥 *[2/5]* Enlace detectado:\n`{disp_url}`\n\n_Descargando clip en alta calidad..._"
            )
        else:
            data = await asyncio.to_thread(fetch_trend_data, custom_topic)
            target = data["search_query"]
            await update_status(
                msg,
                f"{header}{batch_prefix}📥 *[2/5]* Búsqueda seleccionada:\n_{data['search_query']}_\n\n_Descargando clip de España..._"
            )

        raw_clip, meta_info = await asyncio.to_thread(download_clip, target)
        if chat_key in ACTIVE_TASKS:
            ACTIVE_TASKS[chat_key]["raw_clip"] = raw_clip

        await update_status(
            msg,
            f"{header}{batch_prefix}🧠 *[3/5]* Interpretando contenido del video para redactar titulares fieles..."
        )

        video_data = await asyncio.to_thread(analyze_video_content, meta_info, data, custom_top, custom_bottom)

        # Si el video carece de contexto identificable y el usuario no especificó titular, preguntarle
        if not video_data.get("top_title"):
            PENDING_VIDEOS[chat_key] = {
                "raw_clip": raw_clip,
                "meta_info": meta_info,
                "data": data,
                "custom_bottom": custom_bottom,
                "timestamp": time.time()
            }
            # Evitar que finally borre raw_clip ya que queda guardado esperando la respuesta del usuario
            raw_clip = None
            try:
                await msg.delete()
            except Exception:
                pass
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    "❓ *No he podido identificar el tema o contexto de este video automáticamente* (los metadatos no traen un titular claro).\n\n"
                    "👉 *¿Qué titular quieres poner arriba?*\n"
                    "Escríbemelo ahora en este chat (ejemplo: `arriba: Tu titular` y opcionalmente `abajo: Nombre`, o directamente el titular) y te lo maqueto al instante."
                ),
                parse_mode="Markdown"
            )
            return False

        clean_top_title = video_data['top_title'].replace('\n', ' ')
        await update_status(
            msg,
            f"{header}{batch_prefix}🎬 *[4/5]* Maquetando video:\n*{clean_top_title}*\n\n_Encuadrando interlocutor vertical, aplicando B/N y barra completa al fondo..._"
        )

        final_video = await asyncio.to_thread(
            edit_whitepilled_style, raw_clip, video_data["top_title"], video_data["speaker_name"]
        )
        if chat_key in ACTIVE_TASKS:
            ACTIVE_TASKS[chat_key]["final_video"] = final_video

        await update_status(
            msg,
            f"{header}{batch_prefix}📤 *[5/5]* ¡Edición completada!\n\n_Subiendo video a Telegram..._",
            show_cancel=False
        )

        caption_text = f"🔥 *{clean_top_title}*\n\n{video_data['caption']}"
        await safe_send_video(context, chat_id, final_video, caption_text)

        try:
            await msg.delete()
        except Exception:
            pass
        return True
    except asyncio.CancelledError:
        print(f"🛑 Tarea cancelada por el usuario para chat_id {chat_id}")
        if raw_clip and os.path.exists(raw_clip):
            try:
                os.remove(raw_clip)
            except Exception:
                pass
        if final_video and os.path.exists(final_video):
            try:
                os.remove(final_video)
            except Exception:
                pass
        raise
    except Exception as e:
        print(f"❌ Error en process_and_send: {e}")
        try:
            await msg.delete()
        except Exception:
            pass
        await context.bot.send_message(chat_id=chat_id, text=f"⚠️ Error procesando video: {e}")
        return False
    finally:
        if not is_batch_item:
            ACTIVE_TASKS.pop(chat_key, None)
        if raw_clip and os.path.exists(raw_clip):
            try:
                os.remove(raw_clip)
            except Exception:
                pass
        if final_video and os.path.exists(final_video):
            try:
                os.remove(final_video)
            except Exception:
                pass

async def process_batch(chat_id, context, jobs):
    """Procesa una lista de videos de forma estrictamente secuencial y los envía en orden."""
    total = len(jobs)
    chat_key = str(chat_id)
    
    current_task = asyncio.current_task()
    ACTIVE_TASKS[chat_key] = {
        "task": current_task,
        "msg": None,
        "raw_clip": None,
        "final_video": None
    }
    
    if total > 1:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"📋 *Lote de {total} videos recibido.*\n_Se irán editando en orden y enviando uno a uno a medida que estén listos..._",
            parse_mode="Markdown"
        )
        
    success_count = 0
    try:
        for idx, job in enumerate(jobs, 1):
            batch_info = {"index": idx, "total": total} if total > 1 else None
            ok = await process_and_send(
                chat_id=chat_id,
                context=context,
                direct_url=job["url"],
                custom_top=job["custom_top"],
                custom_bottom=job["custom_bottom"],
                batch_info=batch_info,
                is_batch_item=True
            )
            if ok:
                success_count += 1
                
        if total > 1 and success_count == total:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"🎉 *¡Lote completado!*\nSe han editado y enviado los *{total} videos* en orden con éxito.",
                parse_mode="Markdown"
            )
    except asyncio.CancelledError:
        print(f"🛑 Lote cancelado para chat_id {chat_id}")
    finally:
        ACTIVE_TASKS.pop(chat_key, None)

async def scheduled_dispatcher(application):
    """Bucle en segundo plano que comprueba los horarios (12:00, 15:00, 18:00) y envía automáticamente."""
    print("⏰ Programador automático activado para las 12:00, 15:00 y 18:00 (hora local)...")
    sent_dispatches = set()
    while True:
        try:
            now = datetime.datetime.now()
            current_time = now.strftime("%H:%M")
            current_date = now.strftime("%Y-%m-%d")

            keys_to_delete = [k for k in sent_dispatches if not k.startswith(current_date)]
            for k in keys_to_delete:
                sent_dispatches.remove(k)

            if current_time in SCHEDULED_HOURS:
                dispatch_key = f"{current_date}_{current_time}"
                if dispatch_key not in sent_dispatches:
                    sent_dispatches.add(dispatch_key)
                    print(f"🚀 Disparando envío programado de las {current_time}...")
                    ctx = SimpleBotContext(application.bot)
                    await process_and_send(TELEGRAM_CHAT_ID, ctx, is_scheduled=True)
        except Exception as e:
            print(f"⚠️ Error en programador automático: {e}")

        await asyncio.sleep(25)

async def cmd_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic = " ".join(context.args) if context.args else None
    asyncio.create_task(process_and_send(update.effective_chat.id, context, custom_topic=topic))

def parse_custom_texts(text, target_url=""):
    """Extrae inteligentemente 'arriba:' y 'abajo:' del texto para un video."""
    clean_text = text.replace(target_url, "").strip()
    
    # Limpiar numeración o viñetas iniciales y finales (ej: "1.", "2)", "-", "•")
    clean_text = re.sub(r'^\s*(?:\d+[\.\)]|[-•*])\s*', '', clean_text)
    clean_text = re.sub(r'\s*(?:\d+[\.\)]|[-•*])\s*$', '', clean_text).strip()

    arriba_match = re.search(r'(?i)\b(?:arriba|titulo|titular)\s*:\s*(.*?)(?=\b(?:abajo|interlocutor|autor|personaje|nombre)\s*:|$)', clean_text, re.DOTALL)
    abajo_match = re.search(r'(?i)\b(?:abajo|interlocutor|autor|personaje|nombre)\s*:\s*(.*?)(?=\b(?:arriba|titulo|titular)\s*:|$)', clean_text, re.DOTALL)
    
    custom_top = arriba_match.group(1).strip() if arriba_match else None
    custom_bottom = abajo_match.group(1).strip() if abajo_match else None
    
    if custom_bottom:
        custom_bottom = re.sub(r'\s*(?:\d+[\.\)]|[-•*])\s*$', '', custom_bottom).strip()
    if custom_top:
        custom_top = re.sub(r'\s*(?:\d+[\.\)]|[-•*])\s*$', '', custom_top).strip()
    
    # Si no usó etiquetas explícitas (arriba: / abajo:)
    if not custom_top and not custom_bottom and clean_text:
        lines = [l.strip() for l in clean_text.splitlines() if l.strip()]
        lines = [re.sub(r'^\s*(?:\d+[\.\)]|[-•*])\s*', '', l).strip() for l in lines if l.strip()]
        lines = [l for l in lines if l]
        
        if len(lines) >= 2:
            custom_top = lines[0]
            custom_bottom = lines[1]
        elif len(lines) == 1:
            line = lines[0]
            if ":" in line:
                parts = line.split(":", 1)
                custom_bottom = parts[0].strip()
                custom_top = parts[1].strip()
            elif " - " in line:
                parts = line.split(" - ", 1)
                if len(parts[0]) <= 20 and len(parts[1]) > len(parts[0]):
                    custom_bottom = parts[0].strip()
                    custom_top = parts[1].strip()
                else:
                    custom_top = parts[0].strip()
                    custom_bottom = parts[1].strip()
            else:
                custom_top = line
                
    return custom_top, custom_bottom

def extract_video_jobs(text):
    """Extrae todos los enlaces y sus respectivos textos 'arriba' y 'abajo' de un mensaje."""
    if not text:
        return []

    url_matches = list(re.finditer(r'https?://[^\s]+', text))
    if not url_matches:
        return []

    jobs = []
    n = len(url_matches)

    for i, match in enumerate(url_matches):
        raw_url = match.group(0).rstrip('.,;:)]}')
        if n == 1:
            segment = text
        else:
            start_idx = 0 if i == 0 else match.start()
            end_idx = url_matches[i + 1].start() if i < n - 1 else len(text)
            segment = text[start_idx:end_idx]

        custom_top, custom_bottom = parse_custom_texts(segment, target_url=raw_url)
        jobs.append({
            "url": raw_url,
            "custom_top": custom_top,
            "custom_bottom": custom_bottom
        })

    return jobs

async def cmd_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    text_args = re.sub(r'^/link\s*', '', text, flags=re.IGNORECASE).strip()
    if not text_args and not context.args:
        await update.message.reply_text("Uso: `/link https://... [arriba: ...] [abajo: ...]`", parse_mode="Markdown")
        return
        
    jobs = extract_video_jobs(text_args)
    if not jobs and context.args:
        url = context.args[0]
        rest = " ".join(context.args[1:]) if len(context.args) > 1 else ""
        top, bot = parse_custom_texts(rest)
        jobs = [{"url": url, "custom_top": top, "custom_bottom": bot}]

    if jobs:
        asyncio.create_task(process_batch(update.effective_chat.id, context, jobs))

async def cmd_horarios(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.datetime.now().strftime("%H:%M:%S")
    hours_str = ", ".join([f"*{h}*" for h in SCHEDULED_HOURS])
    await update.message.reply_text(
        f"⏰ *Programación Automática Activa*\n\n"
        f"El bot te enviará un reel completamente listo todos los días a las:\n{hours_str} (hora peninsular española).\n\n"
        f"🕒 Hora actual del servidor: `{now}`\n"
        f"🎯 Chat ID configurado: `{TELEGRAM_CHAT_ID}`",
        parse_mode="Markdown"
    )

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    aborted = await abort_task_for_chat(chat_id)
    if aborted:
        await update.message.reply_text("🛑 *Acción cancelada con éxito.* Se ha detenido el proceso.", parse_mode="Markdown")
    else:
        await update.message.reply_text("ℹ️ No hay ningún proceso de descarga o edición activo en este momento.")

async def handle_callback_abort(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id
    print(f"🔘 Botón [Cancelar] pulsado por chat_id: {chat_id}")
    await abort_task_for_chat(chat_id)
    try:
        await query.edit_message_text(
            "🛑 *Acción cancelada.*\n\n_Se ha detenido la descarga y edición del video y se han liberado los recursos._",
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Error al editar mensaje de callback: {e}")

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ *Bot Activo (White Pilled Edition)*\n\n"
        "Comandos disponibles:\n"
        "• `/video` — Busca y maqueta un debate viral de España al instante.\n"
        "• `/video [tema]` — Busca y maqueta un clip sobre un tema concreto (ej. `/video pensiones`).\n"
        "• `/cancelar` (o `/abort`) — Cancela inmediatamente la descarga o maquetación en curso.\n"
        "• `/horarios` — Consulta los horarios automáticos de envío diario (12:00, 15:00, 18:00).\n\n"
        "🔗 *Pegado de enlaces (individuales o en lote):*\n"
        "Puedes pegar uno o varios enlaces en el mismo mensaje, indicando sus textos `arriba:` y `abajo:`:\n"
        "```text\n"
        "https://... arriba: Titular video 1 abajo: Personaje 1\n\n"
        "https://... arriba: Titular video 2 abajo: Personaje 2\n"
        "```\n"
        "⚡ _El bot editará los videos en orden y te los irá mandando según terminen. Admite videos de cualquier duración (> 1:30 min)._",
        parse_mode="Markdown"
    )

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    chat_id = update.effective_chat.id
    chat_key = str(chat_id)

    jobs = extract_video_jobs(text)
    if jobs:
        asyncio.create_task(process_batch(chat_id, context, jobs))
    elif chat_key in PENDING_VIDEOS or chat_id in PENDING_VIDEOS:
        # El usuario está respondiendo a la pregunta sobre qué titular poner en el video descargado
        pending = PENDING_VIDEOS.pop(chat_key, None) or PENDING_VIDEOS.pop(chat_id, None)
        # Verificar que la sesión no haya caducado (15 minutos)
        if time.time() - pending.get("timestamp", 0) > 900:
            if pending.get("raw_clip") and os.path.exists(pending["raw_clip"]):
                try:
                    os.remove(pending["raw_clip"])
                except Exception:
                    pass
            await update.message.reply_text("⚠️ La sesión de ese video ha caducado. Por favor, vuelve a enviar el enlace junto a tu titular.")
            return

        custom_top, custom_bottom = parse_custom_texts(text)
        if not custom_bottom and pending.get("custom_bottom"):
            custom_bottom = pending["custom_bottom"]

        asyncio.create_task(resume_editing_pending(chat_id, context, pending, custom_top, custom_bottom))
    else:
        await update.message.reply_text(
            "💡 Envíame uno o varios enlaces de TikTok, Instagram Reel o YouTube Shorts para maquetarlos.\n\n"
            "📝 *Ejemplo con varios enlaces en el mismo mensaje:*\n"
            "```text\n"
            "https://... arriba: Titular 1 abajo: Autor 1\n\n"
            "https://... arriba: Titular 2 abajo: Autor 2\n"
            "```\n"
            "*(Se editarán en orden y se te irán enviando uno a uno).* ",
            parse_mode="Markdown"
        )

async def post_init(application):
    asyncio.create_task(scheduled_dispatcher(application))

def main():
    request = HTTPXRequest(
        connection_pool_size=20,
        connect_timeout=60.0,
        read_timeout=300.0,
        write_timeout=300.0,
        pool_timeout=60.0,
        http_version="1.1"
    )
    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .request(request)
        .concurrent_updates(True)
        .post_init(post_init)
        .build()
    )
    app.add_handler(CommandHandler("video", cmd_video))
    app.add_handler(CommandHandler("link", cmd_link))
    app.add_handler(CommandHandler(["cancel", "cancelar", "abort", "parar"], cmd_cancel))
    app.add_handler(CallbackQueryHandler(handle_callback_abort, pattern="^abort_process$"))
    app.add_handler(CommandHandler("horarios", cmd_horarios))
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text_message))
    
    print("🚀 Bot iniciado correctamente y conectado a Telegram...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
