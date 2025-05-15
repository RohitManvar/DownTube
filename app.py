from flask import Flask, render_template, request, send_file, jsonify
import yt_dlp
import os
import json
import threading
import time
import pathlib

app = Flask(__name__)

# Use the default Downloads folder for the current user
DOWNLOAD_DIR = str(pathlib.Path.home() / "Downloads")
print(f"Files will be downloaded to: {DOWNLOAD_DIR}")

# Dictionary to store download progress
download_progress = {}

def progress_hook(d):
    """Track download progress"""
    if d['status'] == 'downloading':
        download_id = d.get('info_dict', {}).get('id', 'unknown')

        # Calculate percentage
        if 'total_bytes' in d:
            total = d['total_bytes']
        elif 'total_bytes_estimate' in d:
            total = d['total_bytes_estimate']
        else:
            total = 0
            
        downloaded = d.get('downloaded_bytes', 0)
        
        if total > 0:
            percentage = (downloaded / total) * 100
        else:
            percentage = 0
            
        speed = d.get('speed', 0)
        if speed:
            speed = speed / 1024 / 1024  # Convert to MB/s
            
        # Update progress info
        download_progress[download_id] = {
            'percentage': round(percentage, 1),
            'speed': round(speed, 2) if speed else 0,
            'filename': d.get('filename', ''),
            'eta': d.get('eta', 0),
            'status': 'downloading'
        }
    elif d['status'] == 'finished':
        download_id = d.get('info_dict', {}).get('id', 'unknown')
        if download_id in download_progress:
            download_progress[download_id]['status'] = 'processing'
            download_progress[download_id]['percentage'] = 100
    elif d['status'] == 'error':
        download_id = d.get('info_dict', {}).get('id', 'unknown')
        if download_id in download_progress:
            download_progress[download_id]['status'] = 'error'

@app.route("/", methods=["GET", "POST"])
def index():
    video_info = None
    error = None
    if request.method == "POST":
        url = request.form["url"]
        try:
            # Get the best available formats
            ydl_opts = {
                'quiet': True,
                'skip_download': True,
                'format': 'best',
                'verbose': True  # Enable verbose output for debugging
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Extract info first to check video availability
                info = ydl.extract_info(url, download=False)
                
                # Define quality presets with better format selector strings
                quality_presets = [
                    {
                        "name": "4K (2160p)",
                        "height": 2160,
                        "format_id": "bestvideo[height<=2160][ext=mp4]+bestaudio[ext=m4a]/best[height<=2160]"
                    },
                    {
                        "name": "1440p",
                        "height": 1440,
                        "format_id": "bestvideo[height<=1440][ext=mp4]+bestaudio[ext=m4a]/best[height<=1440]"
                    },
                    {
                        "name": "1080p Full HD",
                        "height": 1080,
                        "format_id": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]"
                    },
                    {
                        "name": "720p HD",
                        "height": 720,
                        "format_id": "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]"
                    },
                    {
                        "name": "480p",
                        "height": 480,
                        "format_id": "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480]"
                    },
                    {
                        "name": "360p",
                        "height": 360,
                        "format_id": "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360]"
                    }
                ]
                
                # Create a list of available formats based on video height
                available_formats = []
                max_height = 0
                
                # Find max height available in the video
                for f in info.get("formats", []):
                    if f.get("height") and f.get("height") > max_height:
                        max_height = f.get("height")
                
                print(f"Maximum available height: {max_height}p")
                
                # Only add presets that are available for this video
                for preset in quality_presets:
                    if preset["height"] <= max_height:
                        available_formats.append(preset)
                
                # Add audio-only option
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
                    "video_id": info.get("id", "unknown")  # Add video ID for progress tracking
                }
                
                print(f"Found {len(available_formats)} available quality options")
                
        except Exception as e:
            error = f"Error: {str(e)}"
            print(f"Exception occurred: {str(e)}")
            
    return render_template("index.html", video=video_info, error=error)

def download_video(url, format_id, video_id):
    try:
        # Set download path to user's Downloads folder
        download_path = os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s")

        ydl_opts = {
            "format": format_id,
            "outtmpl": download_path,
            "merge_output_format": "mp4",  # Force MP4 output
            "progress_hooks": [progress_hook],
            "postprocessors": [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',  # Ensure output is MP4
            }]
        }
        
        # For audio-only downloads
        if "audio" in format_id.lower() and "bestvideo" not in format_id:
            ydl_opts["postprocessors"] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'm4a',
                'preferredquality': '192',
            }]

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info_dict)
            
            # Handle potential filename extension changes due to post-processing
            base_filename = os.path.splitext(filename)[0]
            potential_files = [
                f"{base_filename}.mp4",
                f"{base_filename}.m4a",
                filename
            ]
            
            # Find the actual file that was created
            actual_file = None
            for file in potential_files:
                if os.path.exists(file):
                    actual_file = file
                    break
            
            # Update progress to indicate completion
            if video_id in download_progress:
                download_progress[video_id]['status'] = 'complete'
                download_progress[video_id]['percentage'] = 100
                download_progress[video_id]['filepath'] = actual_file

    except Exception as e:
        print(f"Download failed: {str(e)}")
        if video_id in download_progress:
            download_progress[video_id]['status'] = 'error'
            download_progress[video_id]['error_message'] = str(e)

@app.route("/download", methods=["POST"])
def download():
    url = request.form["url"]
    format_id = request.form["format_id"]
    video_id = request.form.get("video_id", "unknown")

    # Initialize the progress entry
    download_progress[video_id] = {
        'percentage': 0,
        'speed': 0,
        'filename': '',
        'eta': 0,
        'status': 'starting'
    }

    # Start the download in a background thread
    download_thread = threading.Thread(target=download_video, args=(url, format_id, video_id))
    download_thread.daemon = True
    download_thread.start()

    # Inform the user where files will be downloaded
    return render_template(
        "download_progress.html", 
        video_id=video_id,
        url=url,
        format_id=format_id,
        download_dir=DOWNLOAD_DIR
    )

@app.route("/get_progress/<video_id>")
def get_progress(video_id):
    """API endpoint to check download progress"""
    if video_id in download_progress:
        return jsonify(download_progress[video_id])
    return jsonify({'status': 'not_found', 'percentage': 0})

@app.route("/get_file/<video_id>")
def get_file(video_id):
    """Serve the downloaded file"""
    if video_id in download_progress:
        progress_data = download_progress[video_id]
        if progress_data.get('status') == 'complete' and 'filepath' in progress_data:
            filepath = progress_data['filepath']
            if os.path.exists(filepath):
                # Clean up the progress entry after serving the file
                # We use a copy to avoid modifying while iterating
                download_copy = download_progress.copy()
                if video_id in download_copy:
                    del download_progress[video_id]

                return send_file(filepath, as_attachment=True)

    return "File not found or download not complete", 404

if __name__ == "__main__":
    app.run(debug=True)