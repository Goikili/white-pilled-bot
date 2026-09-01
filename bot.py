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

import numpy as np
import yt_dlp
from google import genai
from google.genai import types
from moviepy.editor import VideoFileClip, ColorClip, TextClip, CompositeVideoClip, VideoClip, vfx
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

# ================= CONFIGURACIÓN =================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AQ.Ab8RN6LY_aEHSb8Hxj8jzdwLUCHNJB5-qN5remU3zOpGDSUfWw")
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

client = genai.Client(api_key=GEMINI_API_KEY)

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
        {"search_query": "debate alquiler espana #shorts", "top_title": "¿ALQUILAR ES\nTIRAR EL DINERO?", "speaker_name": "CRISIS VIVIENDA", "caption": "¿Tú qué opinas sobre el precio de la vivienda y el alquiler en España? Déjalo en comentarios. 👇\n\n#Vivienda #Alquiler #España #Debate"},
        {"search_query": "debate jornada laboral 37 horas espana #shorts", "top_title": "¿REDUCIR JORNADA\nA 37,5 HORAS?", "speaker_name": "DEBATE LABORAL", "caption": "¿Crees que reducir la jornada aumentará la productividad o dañará a las PYMES? Comenta tu opinión. 👇\n\n#Trabajo #Economia #España"},
        {"search_query": "debate pensiones espana futuro #shorts", "top_title": "¿HABRÁ PENSIONES\nEN EL FUTURO?", "speaker_name": "SISTEMA PENSIONES", "caption": "¿Crees que el sistema de pensiones actual es sostenible para los jóvenes? Deja tu opinión. 👇\n\n#Pensiones #Jubilacion #España"},
        {"search_query": "debate oposiciones o empresa privada espana #shorts", "top_title": "¿OPOSITAR O\nEMPRENDER?", "speaker_name": "CULTURA LABORAL", "caption": "¿Merece la pena el esfuerzo de opositar en España o es mejor el sector privado? Comenta tu experiencia. 👇\n\n#Oposiciones #España #Empleo"},
        {"search_query": "debate impuestos espana sueldos #shorts", "top_title": "¿PAGAMOS DEMASIADOS\nIMPUESTOS?", "speaker_name": "FISCALIDAD", "caption": "¿Crees que los impuestos en España se gestionan bien o asfixian a la clase trabajadora? 👇\n\n#Impuestos #Economia #España"}
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

def extract_punchy_title_and_speaker(raw_title, raw_desc, uploader):
    """Extrae un titular con sentido completo a partir del título real del video."""
    t = str(raw_title or "").strip()
    if is_uninformative_title(t):
        t = str(raw_desc or "").strip()

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
    
    clean_uploader = (uploader or "").strip()
    clean_uploader = re.sub(r'[@_]', ' ', clean_uploader).strip()
    speaker = clean_uploader.split()[0].upper() if clean_uploader else "DEBATE"

    # Si tras limpiar sigue careciendo de contexto, devolver None para preguntar al usuario
    if is_uninformative_title(t):
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

        clean_top_disp = formatted_top.replace('\n', ' ')
        return {
            "top_title": formatted_top,
            "speaker_name": speaker,
            "caption": f"🔥 {clean_top_disp}\n\n¿Qué opinas sobre este debate? Déjalo en comentarios. 👇\n\n#Debate #España #Viral #Reflexion"
        }

    real_title = metadata_info.get("title") or fallback_data.get("top_title") or ""
    real_uploader = metadata_info.get("uploader") or metadata_info.get("channel") or fallback_data.get("speaker_name") or "DEBATE"
    real_desc = metadata_info.get("description") or fallback_data.get("caption") or ""

    # 1. Intentar con IA de Gemini
    analysis_prompt = f"""
Eres editor de una cuenta viral de Instagram Reels de reflexión sociopolítica en España.
Clip compartido:
Título: "{real_title}"
Autor: "{real_uploader}"
Descripción: "{real_desc[:400]}"

Tu tarea:
1. "top_title": Titular polémico en MAYÚSCULAS en EXACTAMENTE 2 LÍNEAS (separadas por \\n, máximo 5-6 palabras en total) que plantee el conflicto o la pregunta clave del video.
2. "speaker_name": Nombre de la persona o tema clave en MAYÚSCULAS (1-3 palabras máximo).
3. "caption": Copy para Instagram en español de España reflexionando sobre el video, invitando a comentar, con 4-5 hashtags.

Devuelve ÚNICAMENTE un objeto JSON:
{{
  "top_title": "LÍNEA 1\\nLÍNEA 2",
  "speaker_name": "NOMBRE O TEMA",
  "caption": "Copy completo..."
}}
"""
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
    words = [w for w in re.split(r'\s+', q.strip()) if w.lower() not in ['tiktok', 'instagram', 'reels', 'clip', 'video', 'shorts']]
    core = " ".join(words[:4])
    if "espana" not in core.lower() and "españa" not in core.lower():
        core = f"{core} espana"
    return f"{core} #shorts"

def duration_filter(info_dict, *, incomplete):
    dur = info_dict.get('duration')
    if dur is not None and (dur > 200 or dur < 5):
        return f"Video duration {dur}s not in [5, 200]"
    return None

GUARANTEED_FALLBACK_QUERIES = [
    "debate espana shorts",
    "entrevista calle espana shorts",
    "polemica espana shorts",
    "alquiler jovenes espana shorts",
    "cultura esfuerzo espana shorts",
    "politicos debate espana shorts"
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
        return output_file, meta_info

    # Caso 2: Búsqueda inteligente imparable de videos
    opts_search = {
        'format': '18/bestvideo*+bestaudio/best',
        'merge_output_format': 'mp4',
        'outtmpl': output_file,
        'extractor_args': extractor_args,
        'match_filter': duration_filter,
        'ffmpeg_location': FFMPEG_PATH,
        'max_downloads': 1,
        'quiet': True,
        'no_warnings': True
    }

    errors_log = []
    # 1. Probar la consulta original adaptada
    clean_q = clean_search_query(query_or_url)
    print(f"🎯 Intento 1: Búsqueda para '{clean_q}'...")
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

    # 2. Si no descargó, probar búsqueda simplificada con 'debate shorts'
    if not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
        words = [w for w in re.findall(r'\w+', query_or_url) if w.lower() not in ['shorts', 'tiktok', 'debate', 'espana']]
        alt_q = f"{' '.join(words[:2])} debate espana shorts"
        print(f"🔄 Intento 2: Búsqueda simplificada: '{alt_q}'...")
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

    MAX_DURATION = 75
    if clip.duration > MAX_DURATION:
        print(f"✂️ Acortando clip de {clip.duration:.1f}s a {MAX_DURATION}s para formato Reel...")
        clip = clip.subclip(0, MAX_DURATION)

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

    # Renderizado ultrarrápido multi-hilo optimizado para Reels
    threads_count = min(12, os.cpu_count() or 4)
    final.write_videofile(
        output_path,
        fps=25,
        codec="libx264",
        audio_codec="aac",
        preset="ultrafast",
        threads=threads_count,
        ffmpeg_params=["-pix_fmt", "yuv420p", "-crf", "23"],
        logger=None
    )
    clip.close()
    final.close()
    return output_path

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

        with open(final_video, "rb") as f:
            await context.bot.send_video(
                chat_id=chat_id,
                video=f,
                caption=caption_text,
                parse_mode="Markdown",
                supports_streaming=True,
                write_timeout=180,
                read_timeout=120
            )

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

async def process_and_send(chat_id, context, custom_topic=None, direct_url=None, custom_top=None, custom_bottom=None, is_scheduled=False):
    header = "⏰ *[ENVÍO DIARIO PROGRAMADO]*\n\n" if is_scheduled else ""
    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"{header}🔍 *[1/5]* Localizando clip de video...",
        parse_mode="Markdown",
        reply_markup=CANCEL_KEYBOARD
    )
    raw_clip = None
    final_video = None
    
    current_task = asyncio.current_task()
    chat_key = str(chat_id)
    ACTIVE_TASKS[chat_key] = {
        "task": current_task,
        "msg": msg,
        "raw_clip": None,
        "final_video": None
    }

    try:
        if direct_url:
            data = {"search_query": direct_url, "top_title": "DEBATE VIRAL", "speaker_name": "DEBATE", "caption": ""}
            target = direct_url
            await update_status(
                msg,
                f"{header}📥 *[2/5]* Enlace detectado:\n`{direct_url[:50]}...`\n\n_Descargando clip en alta calidad..._"
            )
        else:
            data = await asyncio.to_thread(fetch_trend_data, custom_topic)
            target = data["search_query"]
            await update_status(
                msg,
                f"{header}📥 *[2/5]* Búsqueda seleccionada:\n_{data['search_query']}_\n\n_Descargando clip de España..._"
            )

        raw_clip, meta_info = await asyncio.to_thread(download_clip, target)
        if chat_key in ACTIVE_TASKS:
            ACTIVE_TASKS[chat_key]["raw_clip"] = raw_clip

        await update_status(
            msg,
            f"{header}🧠 *[3/5]* Interpretando contenido del video para redactar titulares fieles..."
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
            return

        clean_top_title = video_data['top_title'].replace('\n', ' ')
        await update_status(
            msg,
            f"{header}🎬 *[4/5]* Maquetando video:\n*{clean_top_title}*\n\n_Encuadrando interlocutor vertical, aplicando B/N y barra completa al fondo..._"
        )

        final_video = await asyncio.to_thread(
            edit_whitepilled_style, raw_clip, video_data["top_title"], video_data["speaker_name"]
        )
        if chat_key in ACTIVE_TASKS:
            ACTIVE_TASKS[chat_key]["final_video"] = final_video

        await update_status(
            msg,
            f"{header}📤 *[5/5]* ¡Edición completada!\n\n_Subiendo video a Telegram..._",
            show_cancel=False
        )

        caption_text = f"🔥 *{clean_top_title}*\n\n{video_data['caption']}"

        with open(final_video, "rb") as f:
            await context.bot.send_video(
                chat_id=chat_id,
                video=f,
                caption=caption_text,
                parse_mode="Markdown",
                supports_streaming=True,
                write_timeout=180,
                read_timeout=120
            )

        try:
            await msg.delete()
        except Exception:
            pass
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
        return
    except Exception as e:
        print(f"❌ Error en process_and_send: {e}")
        await context.bot.send_message(chat_id=chat_id, text=f"⚠️ Error: {e}")
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
    """Extrae inteligentemente 'arriba:' y 'abajo:' del mensaje."""
    clean_text = text.replace(target_url, "").strip()
    
    arriba_match = re.search(r'(?i)\barriba\s*:\s*(.*?)(?=\b(?:abajo)\s*:|$)', clean_text, re.DOTALL)
    abajo_match = re.search(r'(?i)\babajo\s*:\s*(.*?)(?=\b(?:arriba)\s*:|$)', clean_text, re.DOTALL)
    
    custom_top = arriba_match.group(1).strip() if arriba_match else None
    custom_bottom = abajo_match.group(1).strip() if abajo_match else None
    
    # Si no usó las etiquetas "arriba:" o "abajo:", pero escribió texto junto al enlace
    if not custom_top and not custom_bottom and clean_text:
        if ":" in clean_text:
            parts = clean_text.split(":", 1)
            custom_bottom = parts[0].strip()
            custom_top = parts[1].strip()
        elif " - " in clean_text:
            parts = clean_text.split(" - ", 1)
            if len(parts[0]) <= 20 and len(parts[1]) > len(parts[0]):
                custom_bottom = parts[0].strip()
                custom_top = parts[1].strip()
            else:
                custom_top = parts[0].strip()
                custom_bottom = parts[1].strip()
        else:
            custom_top = clean_text
            
    return custom_top, custom_bottom

async def cmd_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: `/link https://... [arriba: ...] [abajo: ...]`", parse_mode="Markdown")
        return
    url = context.args[0]
    rest = " ".join(context.args[1:]) if len(context.args) > 1 else ""
    custom_top, custom_bottom = parse_custom_texts(rest)
    asyncio.create_task(process_and_send(update.effective_chat.id, context, direct_url=url, custom_top=custom_top, custom_bottom=custom_bottom))

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
        "🔗 *Pegado de enlaces con textos personalizados:*\n"
        "Puedes pegar cualquier enlace indicando `arriba:` y `abajo:`:\n"
        "```text\n"
        "https://... arriba: Frase para arriba abajo: Nombre interlocutor\n"
        "```\n"
        "💡 _Si la frase de arriba es demasiado larga, el bot la reescribirá automáticamente para que encaje perfecta en dos líneas._",
        parse_mode="Markdown"
    )

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    urls = re.findall(r'https?://[^\s]+', text)
    chat_id = update.effective_chat.id
    chat_key = str(chat_id)

    if urls:
        target_url = urls[0]
        custom_top, custom_bottom = parse_custom_texts(text, target_url)
        asyncio.create_task(process_and_send(chat_id, context, direct_url=target_url, custom_top=custom_top, custom_bottom=custom_bottom))
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
            "💡 Envíame un enlace de TikTok, Instagram Reel o YouTube Shorts para maquetarlo.\n\n"
            "📝 *Personalizar textos:*\n"
            "```text\n"
            "https://... arriba: Tu titular aquí abajo: Tu personaje\n"
            "```\n"
            "*(Si el video no tiene título claro, te preguntaré qué titular poner antes de maquetarlo).* ",
            parse_mode="Markdown"
        )

async def post_init(application):
    asyncio.create_task(scheduled_dispatcher(application))

def main():
    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .concurrent_updates(True)
        .post_init(post_init)
        .connect_timeout(60)
        .read_timeout(120)
        .write_timeout(180)
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
