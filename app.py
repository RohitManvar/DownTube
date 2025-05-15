from flask import Flask, render_template, request, send_file, jsonify
import yt_dlp
import os
import json
import threading
import time
import pathlib

app = Flask(__name__)

# Use /tmp/downloads for cloud platforms like Render
DOWNLOAD_DIR = "/tmp/downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

download_progress = {}

def progress_hook(d):
    """Track download progress"""
    video_id = d.get('info_dict', {}).get('id', 'unknown')

    if d['status'] == 'downloading':
        total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
        downloaded = d.get('downloaded_bytes', 0)
        percentage = (downloaded / total) * 100 if total else 0
        speed = d.get('speed', 0)
        speed = speed / 1024 / 1024 if speed else 0  # Convert to MB/s

        download_progress[video_id] = {
            'percentage': round(percentage, 1),
            'speed': round(speed, 2),
            'filename': d.get('filename', ''),
            'eta': d.get('eta', 0),
            'status': 'downloading'
        }

    elif d['status'] == 'finished':
        if video_id in download_progress:
            download_progress[video_id]['status'] = 'processing'
            download_progress[video_id]['percentage'] = 100

    elif d['status'] == 'error':
        if video_id in download_progress:
            download_progress[video_id]['status'] = 'error'

@app.route("/", methods=["GET", "POST"])
def index():
    video_info = None
    error = None
    if request.method == "POST":
        url = request.form["url"]
        try:
            ydl_opts = {
                'quiet': True,
                'skip_download': True,
                'format': 'best',
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                try:
                    info = ydl.extract_info(url, download=False)
                except yt_dlp.utils.DownloadError as e:
                    error = f"Video unavailable or restricted: {str(e)}"
                    return render_template("index.html", error=error)

                quality_presets = [
                    {"name": "4K (2160p)", "height": 2160, "format_id": "bestvideo[height<=2160][ext=mp4]+bestaudio[ext=m4a]/best[height<=2160]"},
                    {"name": "1440p", "height": 1440, "format_id": "bestvideo[height<=1440][ext=mp4]+bestaudio[ext=m4a]/best[height<=1440]"},
                    {"name": "1080p Full HD", "height": 1080, "format_id": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]"},
                    {"name": "720p HD", "height": 720, "format_id": "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]"},
                    {"name": "480p", "height": 480, "format_id": "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480]"},
                    {"name": "360p", "height": 360, "format_id": "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360]"}
                ]

                available_formats = []
                max_height = max((f.get("height", 0) for f in info.get("formats", [])), default=0)

                for preset in quality_presets:
                    if preset["height"] <= max_height:
                        available_formats.append(preset)

                available_formats.append({
                    "name": "Audio Only (M4A)",
                    "height": 0,
                    "format_id": "bestaudio[ext=m4a]/best"
                })

                video_info = {
                    "title": info.get("title", "Unknown Title"),
                    "thumbnail": info.get("thumbnail", ""),
                    "formats": available_formats,
                    "url": url,
                    "duration": info.get("duration"),
                    "uploader": info.get("uploader", "Unknown Uploader"),
                    "video_id": info.get("id", "unknown")
                }

        except Exception as e:
            error = f"Error: {str(e)}"
    return render_template("index.html", video=video_info, error=error)

def download_video(url, format_id, video_id):
    try:
        download_path = os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s")
        ydl_opts = {
            "format": format_id,
            "outtmpl": download_path,
            "merge_output_format": "mp4",
            "progress_hooks": [progress_hook],
            "postprocessors": [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }]
        }

        if "audio" in format_id.lower() and "bestvideo" not in format_id:
            ydl_opts["postprocessors"] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'm4a',
                'preferredquality': '192',
            }]

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info_dict)
            base_filename = os.path.splitext(filename)[0]
            potential_files = [f"{base_filename}.mp4", f"{base_filename}.m4a", filename]

            actual_file = next((f for f in potential_files if os.path.exists(f)), None)

            if video_id in download_progress:
                download_progress[video_id]['status'] = 'complete'
                download_progress[video_id]['percentage'] = 100
                download_progress[video_id]['filepath'] = actual_file

    except Exception as e:
        if video_id in download_progress:
            download_progress[video_id]['status'] = 'error'
            download_progress[video_id]['error_message'] = str(e)

@app.route("/download", methods=["POST"])
def download():
    url = request.form["url"]
    format_id = request.form["format_id"]
    video_id = request.form.get("video_id", "unknown")

    download_progress[video_id] = {
        'percentage': 0,
        'speed': 0,
        'filename': '',
        'eta': 0,
        'status': 'starting'
    }

    thread = threading.Thread(target=download_video, args=(url, format_id, video_id))
    thread.daemon = True
    thread.start()

    return render_template("download_progress.html", video_id=video_id, url=url, format_id=format_id)

@app.route("/get_progress/<video_id>")
def get_progress(video_id):
    return jsonify(download_progress.get(video_id, {'status': 'not_found', 'percentage': 0}))

@app.route("/get_file/<video_id>")
def get_file(video_id):
    progress_data = download_progress.get(video_id)
    if progress_data and progress_data.get('status') == 'complete' and 'filepath' in progress_data:
        filepath = progress_data['filepath']
        if os.path.exists(filepath):
            # Clean up after serving
            del download_progress[video_id]
            return send_file(filepath, as_attachment=True)
    return "File not found or download not complete", 404

if __name__ == "__main__":
    app.run(debug=True)
