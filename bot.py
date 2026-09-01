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

# Compatibilidad de Pillow 10+ con MoviePy 1.0.3 (ANTIALIAS fue reemplazado por LANCZOS)
if not hasattr(PIL.Image, 'ANTIALIAS'):
    PIL.Image.ANTIALIAS = PIL.Image.Resampling.LANCZOS

# Configuración automática de ImageMagick para MoviePy en Windows
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
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

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

    last_error = None
    for model_name in GEMINI_MODELS:
        try:
            print(f"🤖 Probando modelo {model_name}...")
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
        except Exception as e_search:
            err_str = str(e_search)
            print(f"⚠️ Nota con {model_name} y búsqueda en vivo: {err_str[:120]}")
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
            except Exception as e_direct:
                print(f"❌ Falló {model_name} directo: {str(e_direct)[:120]}")
                last_error = e_direct
                time.sleep(1)
                continue

    raise RuntimeError(f"No se pudo generar con ningún modelo de Gemini: {last_error}")

def parse_json_response(raw_text):
    text = raw_text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return json.loads(text.strip())

def analyze_video_content(video_path, fallback_data):
    """Sube el clip descargado a Gemini para que lo escuche/vea y genere textos 100% fieles a lo que se dice."""
    print("🧠 Analizando contenido real del video con Gemini multimodal...")
    try:
        uploaded_file = client.files.upload(file=video_path)
        for _ in range(10):
            if uploaded_file.state.name == "ACTIVE":
                break
            time.sleep(1)
            uploaded_file = client.files.get(name=uploaded_file.name)

        analysis_prompt = """
Escucha y analiza con atención lo que se dice y debate en este clip de video (en español).

Tu tarea es redactar los textos para maquetar este video en Instagram, garantizando que sean 100% acordes y fieles a lo que la persona realmente dice o debate en el video:
1. "top_title": Titular polémico e impactante en MAYÚSCULAS en EXACTAMENTE 2 LÍNEAS (separadas por \\n, máximo 5-6 palabras en total) que resuma la idea principal o la pregunta clave de lo que se dice en el video.
2. "speaker_name": Nombre de la persona que habla o etiqueta concisa del tema en MAYÚSCULAS (1-3 palabras máximo, ej: DANIEL LACALLE o CULTURA DEL ESFUERZO).
3. "caption": Copy completo para Instagram en español de España explicando fielmente el punto de vista expresado en el video, invitando a comentar, con 4-5 hashtags relevantes.

Devuelve ÚNICAMENTE un objeto JSON:
{
  "top_title": "LÍNEA 1\\nLÍNEA 2",
  "speaker_name": "NOMBRE O TEMA",
  "caption": "Copy completo para Instagram..."
}
"""
        response = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=[uploaded_file, analysis_prompt],
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        parsed = parse_json_response(response.text)

        try:
            client.files.delete(name=uploaded_file.name)
        except Exception:
            pass

        print(f"✅ Análisis completado. Titular fiel: {parsed.get('top_title')}")
        return parsed
    except Exception as e:
        print(f"⚠️ Nota en análisis multimodal ({e}), usando datos iniciales de tendencia...")
        return fallback_data

def clean_search_query(q):
    words = [w for w in re.split(r'\s+', q.strip()) if w.lower() not in ['tiktok', 'instagram', 'reels', 'clip', 'video', 'shorts']]
    core = " ".join(words[:4])
    if "espana" not in core.lower() and "españa" not in core.lower():
        core = f"{core} espana"
    return f"{core} #shorts"

def duration_filter(info_dict, *, incomplete):
    dur = info_dict.get('duration')
    if dur is not None and (dur > 90 or dur < 5):
        return f"Video duration {dur}s not in [5, 90]"
    return None

def download_clip(query_or_url):
    unique_id = f"{int(time.time())}_{uuid.uuid4().hex[:6]}"
    output_file = f"raw_temp_{unique_id}.mp4"
    print(f"📥 Buscando y descargando clip: {query_or_url}")

    is_direct_url = query_or_url.startswith("http")
    is_youtube = ("youtube.com" in query_or_url) or ("youtu.be" in query_or_url) or (not is_direct_url)
    cookie_path = "cookies.txt" if (os.path.exists("cookies.txt") and not is_youtube) else None
    extractor_args = {'youtube': {'player_client': ['android']}} if is_youtube else {}

    # Caso 1: Descarga directa por URL
    if is_direct_url:
        opts = {
            'format': 'bestvideo*+bestaudio/best',
            'outtmpl': output_file,
            'merge_output_format': 'mp4',
            'extractor_args': extractor_args,
            'cookiefile': cookie_path,
            'quiet': True,
            'no_warnings': True
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([query_or_url])
        if not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
            raise RuntimeError(f"No se pudo descargar el video desde la URL: {query_or_url}")
        return output_file

    # Caso 2: Búsqueda inteligente de Shorts en España (<90s)
    clean_q = clean_search_query(query_or_url)
    print(f"🎯 Búsqueda optimizada para Shorts (España): '{clean_q}'")

    opts_search = {
        'format': 'bestvideo*+bestaudio/best',
        'merge_output_format': 'mp4',
        'outtmpl': output_file,
        'extractor_args': extractor_args,
        'match_filter': duration_filter,
        'max_downloads': 1,
        'quiet': True,
        'no_warnings': True
    }

    try:
        with yt_dlp.YoutubeDL(opts_search) as ydl:
            ydl.download([f"ytsearch15:{clean_q}"])
    except yt_dlp.utils.MaxDownloadsReached:
        pass
    except Exception as e:
        print(f"⚠️ Nota en búsqueda: {e}")

    # Fallback si no se encontró en la primera pasada
    if not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
        words = re.findall(r'\w+', query_or_url)
        alt_q = " ".join([w for w in words if w.lower() not in ['shorts', 'tiktok', 'debate']][:3]) + " debate espana shorts"
        print(f"🔄 Reintentando con consulta alternativa: '{alt_q}'...")
        try:
            with yt_dlp.YoutubeDL(opts_search) as ydl:
                ydl.download([f"ytsearch15:{alt_q}"])
        except yt_dlp.utils.MaxDownloadsReached:
            pass
        except Exception as e:
            print(f"⚠️ Nota en reintento: {e}")

    if not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
        raise RuntimeError(f"No se pudo descargar ningún video corto (<90s) para la búsqueda: '{query_or_url}'")

    return output_file

def format_to_two_lines(text):
    """Formatea cualquier texto para que tenga exactamente 2 líneas equilibradas."""
    words = [w for w in text.replace('\n', ' ').split() if w]
    if len(words) <= 2:
        return " ".join(words)
    mid = (len(words) + 1) // 2
    return f"{' '.join(words[:mid])}\n{' '.join(words[mid:])}"

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
    print("🎬 Editando video (B/N, Barra inferior completa, Franklin Gothic)...")
    if not os.path.exists(raw_path) or os.path.getsize(raw_path) == 0:
        raise FileNotFoundError(f"El archivo fuente {raw_path} no existe o está vacío.")

    clip = VideoFileClip(raw_path).fx(vfx.blackwhite)

    # Limitar duración a 75 segundos máximo para Shorts/Reels y acelerar renderizado
    MAX_DURATION = 75
    if clip.duration > MAX_DURATION:
        print(f"✂️ Acortando clip de {clip.duration:.1f}s a {MAX_DURATION}s para formato Reel...")
        clip = clip.subclip(0, MAX_DURATION)

    target_w, target_h = 1080, 1920

    # AMPLIACIÓN UNIFORME CENTRADA DEL VIDEO
    base_scale = target_w / clip.w
    aspect_ratio = clip.w / clip.h
    enlarge_factor = 1.16 if aspect_ratio >= 1.3 else 1.05

    video_w = int(clip.w * base_scale * enlarge_factor)
    video_h = int(clip.h * base_scale * enlarge_factor)

    MAX_VIDEO_H = 1120
    if video_h > MAX_VIDEO_H:
        video_h = MAX_VIDEO_H
        video_w = int(clip.w * (video_h / clip.h))

    main_video = clip.resize((video_w, video_h)).set_position(("center", "center"))
    video_y_start = (target_h - video_h) // 2
    video_y_bottom = video_y_start + video_h

    # Fondo negro
    background = ColorClip(size=(target_w, target_h), color=(0, 0, 0)).set_duration(clip.duration)

    # 1. TEXTO SUPERIOR ESTRICTAMENTE EN 2 LÍNEAS (Dinámico según el espacio del video)
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

    # 2. BARRA DE PROGRESO AL FONDO (Pegada a abajo, ancho completo 1080px, doble de alta: 88px)
    bar_height = 88
    bar_total_w = target_w  # 1080px
    bar_y = target_h - bar_height  # Pegada exactamente a la parte inferior

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

async def update_status(msg, text):
    try:
        await msg.edit_text(text, parse_mode="Markdown")
    except Exception:
        pass

class SimpleBotContext:
    def __init__(self, bot):
        self.bot = bot

async def process_and_send(chat_id, context, custom_topic=None, direct_url=None, is_scheduled=False):
    header = "⏰ *[ENVÍO DIARIO PROGRAMADO]*\n\n" if is_scheduled else ""
    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"{header}🔍 *[1/5]* Buscando debate en España con IA...",
        parse_mode="Markdown"
    )
    raw_clip = None
    final_video = None
    try:
        if direct_url:
            data = {"search_query": direct_url, "top_title": "VIDEO ENLACE", "speaker_name": "DEBATE", "caption": ""}
            target = direct_url
            await update_status(
                msg,
                f"{header}📥 *[2/5]* Enlace recibido:\n`{direct_url[:50]}...`\n\n_Descargando clip de video..._"
            )
        else:
            data = await asyncio.to_thread(fetch_trend_data, custom_topic)
            target = data["search_query"]
            await update_status(
                msg,
                f"{header}📥 *[2/5]* Búsqueda seleccionada:\n_{data['search_query']}_\n\n_Descargando el clip más viral de España..._"
            )

        raw_clip = await asyncio.to_thread(download_clip, target)

        await update_status(
            msg,
            f"{header}🧠 *[3/5]* Analizando audio y contenido real del clip para redactar textos fieles..."
        )

        video_data = await asyncio.to_thread(analyze_video_content, raw_clip, data)

        clean_top_title = video_data['top_title'].replace('\n', ' ')
        await update_status(
            msg,
            f"{header}🎬 *[4/5]* Maquetando video:\n*{clean_top_title}*\n\n_Ampliando video, aplicando B/N y barra completa al fondo..._"
        )

        final_video = await asyncio.to_thread(
            edit_whitepilled_style, raw_clip, video_data["top_title"], video_data["speaker_name"]
        )

        await update_status(
            msg,
            f"{header}📤 *[5/5]* ¡Edición completada!\n\n_Subiendo video a Telegram..._"
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
    except Exception as e:
        print(f"❌ Error en process_and_send: {e}")
        await context.bot.send_message(chat_id=chat_id, text=f"⚠️ Error: {e}")
    finally:
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

            # Limpiar llaves de días anteriores
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
    await process_and_send(update.effective_chat.id, context, custom_topic=topic)

async def cmd_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: `/link https://...`", parse_mode="Markdown")
        return
    await process_and_send(update.effective_chat.id, context, direct_url=context.args[0])

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

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ *Bot Activo (White Pilled Edition)*\n\n"
        "Comandos disponibles:\n"
        "• `/video` — Busca y maqueta un debate viral de España al instante.\n"
        "• `/video [tema]` — Busca y maqueta un clip sobre un tema concreto (ej. `/video pensiones`).\n"
        "• `/horarios` — Consulta los horarios automáticos de envío diario (12:00, 15:00, 18:00).\n\n"
        "🔗 *Pegado directo de enlace:*\n"
        "Puedes simplemente pegar cualquier enlace de TikTok, Instagram Reel o YouTube Shorts en este chat y el bot lo maquetará automáticamente.",
        parse_mode="Markdown"
    )

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    urls = re.findall(r'https?://[^\s]+', text)
    if urls:
        target_url = urls[0]
        await process_and_send(update.effective_chat.id, context, direct_url=target_url)
    else:
        await update.message.reply_text(
            "💡 Envíame un enlace de TikTok, Instagram Reel o YouTube Shorts para maquetarlo, o usa el comando /video para generar un debate viral de hoy."
        )

async def post_init(application):
    # Iniciar el bucle de envíos programados sin bloquear el polling de Telegram
    asyncio.create_task(scheduled_dispatcher(application))

def main():
    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .connect_timeout(60)
        .read_timeout(120)
        .write_timeout(180)
        .build()
    )
    app.add_handler(CommandHandler("video", cmd_video))
    app.add_handler(CommandHandler("link", cmd_link))
    app.add_handler(CommandHandler("horarios", cmd_horarios))
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text_message))
    
    print("🚀 Bot iniciado correctamente y conectado a Telegram...")
    app.run_polling()

if __name__ == "__main__":
    main()
