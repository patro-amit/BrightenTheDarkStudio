# Brighten the Dark Studio

## Start the desktop app on Windows

Double-click **Launch Studio.bat** in this folder. It starts the native Tk desktop app using the local virtual environment when available. The included **Brighten Studio.app** is a macOS bundle and is not used on Windows.

If Python or dependencies are missing, install Python 3.10 or later with Tk support, then run these commands from PowerShell in this folder:

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

You can also start the app with `.venv\Scripts\python.exe -m src.studio`. FFmpeg on PATH enables H.264 and supported source audio in exported benchmark videos. Video preview in Studio is silent.

## Workspaces

- **Image Lab** opens bundled or external images. Adjust manual parameters, view split / difference modes, inspect the histogram and 14 preview measurements, and export a full-resolution PNG or a preview metrics CSV. Live filters include denoise + CLAHE and local illumination. Auto-tuned CLAHE, fixed CLAHE, gamma and global luminance are also available.
- **Video Lab** supports timeline scrubbing, single steps, paired playback, live filters, sampled exposure analysis and a complete fixed / scene-tuned / stabilized benchmark. A new benchmark saves a uniquely named source copy and preserves earlier runs.
- **Scores** indexes the image, frame, scene and benchmark CSVs under `outputs/`. Filter or sort by a column and export the filtered results. PSNR and SSIM compare with the input. Brightness lift and flicker describe luminance change and do not establish improved visual quality by themselves.
- **Project Files** opens media in the labs, CSV tables in Scores, and reports in the default document viewer.
- **Assistant** can explain the selected measurements. Use **API key…** to enter a key for this session, or start with `OPENAI_API_KEY` and optional `OPENAI_MODEL` in the environment. API requests are billed on the API account. Only an explicit Send transmits the question, recent chat and selected context. Source image and video bytes are never attached. Click **Copy edit request** to prepare a prompt with this exact project path, then paste it into the Codex chat for this workspace. The API assistant explains measurements; Codex makes the requested file changes.

The supplied video is the attributed 20-second Golden Gate Bridge recording. See `data/video/FOOTAGE.md`. Existing report and batch metrics are included. Some rapid or high-resolution clips may preview below their source rate, while the batch benchmark processes each frame.

## Existing command-line benchmark and offline viewer

## Run on your computer

Use Python 3.10 or later. The existing eight images are in `data/originals/`.

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python src\run_project.py
python src\build_review.py
Start-Process outputs\review\index.html
```

For the existing results, double-click **Open Dashboard.bat**. It refreshes the offline dashboard and opens it in your default browser. The project also runs with a Python environment that already has NumPy, OpenCV and Matplotlib.

## Process video

```powershell
python src\run_video.py data\video\night_bridge_20s.mp4
python src\run_video.py "C:\path\to\your-video.mp4"
```

Each run exports three MP4s and per-frame CSVs. The modes are fixed luminance CLAHE, scene-tuned shadow CLAHE, and scene-tuned CLAHE with temporal smoothing. The included source is a continuous 20-second recording of traffic on the Golden Gate Bridge at night. See [footage credit and edits](data/video/FOOTAGE.md). FFmpeg on PATH enables H.264 export and carries the first audio track through as AAC. OpenCV alone writes video-only MPEG-4 MP4. Use `--mute` for silent export. The processing assumes fixed resolution and constant frame rate. Convert variable-frame-rate inputs to CFR first if timing or audio sync matters.

For each frame, mean lift is output mean grayscale intensity minus input mean grayscale intensity. Flicker is the absolute change in this lift between adjacent frames inside a detected scene. It measures global brightness fluctuation introduced by enhancement, and may miss localized flicker. Timing includes core enhancement and, for adaptive modes, scene tuning on cut frames. Decoding, encoding, scene detection, common color conversion and metric calculation are excluded.

## Results and demonstration

| Path | Contents |
|---|---|
| `Brighten_the_Dark_Final_Report.docx` | Final report with figures, experiments and results |
| `outputs/review/index.html` | Offline, keyboard-accessible before/after image comparison and selected settings |
| `outputs/metrics.csv` | Twelve methods and six metrics for each processed image |
| `outputs/scene_tuning.csv` | Scores for all 19 candidates per image |
| `outputs/image_run_log.csv`, `outputs/skipped_images.csv` | Input status and failure reasons |
| `outputs/he_verification.csv` | Pixel-wise NumPy versus OpenCV global HE check |
| `outputs/video/night_bridge_20s/` | Recorded-footage benchmark CSVs and playable video outputs |

Run `python src/run_project.py` to regenerate all full-resolution enhanced PNGs and per-image histogram, CDF and parameter sweep figures. For a quicker metrics-only run, use `--no-figures --no-enhanced-images`. Use `--input-dir` and `--output-dir` to run a different set. Run `python src/build_review.py` after a new image or video run to refresh the file and metric index. Put each benchmark source in `data/video/` with the same filename stem as the folder under `outputs/video/` to enable synchronized playback. For fresh results with a custom input set, specify a new output directory.

The 50% review used scikit-image with a nonzero clip limit under the AHE label. The final release uses OpenCV with clip limit zero for unclipped tile-based AHE, then measures all results again. The supplied image sources and permissions were not documented in the original archive. The X-ray is a grayscale processing example. Input-referenced PSNR and SSIM measure fidelity, and the noise penalty is an image-based proxy. The tuning score is a project heuristic.

## Checks

```sh
python -m unittest discover -s tests -v
```

The project keeps the included source photographs and does not overwrite input files. See the final report for the exact scene settings, measured outcomes and limitations.
