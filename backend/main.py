from pathlib import Path
import os, shutil, subprocess, uuid
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

app = FastAPI(title="FusionVoice Engine", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "*").split(","), allow_methods=["*"], allow_headers=["*"])
ROOT = Path(os.getenv("FUSIONVOICE_DATA", "/tmp/fusionvoice"))
ROOT.mkdir(parents=True, exist_ok=True)


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode:
        raise HTTPException(500, p.stderr[-3000:] or "Audio process failed")
    return p

@app.get("/health")
def health():
    return {"ok": True, "engine": "FusionVoice", "demucs": shutil.which("demucs") is not None}

@app.post("/api/stems")
async def stems(track: UploadFile = File(...)):
    job = uuid.uuid4().hex
    d = ROOT / job; d.mkdir()
    src = d / (track.filename or "track.wav")
    with src.open("wb") as f: shutil.copyfileobj(track.file, f)
    run(["demucs", "--two-stems=vocals", "-o", str(d), str(src)])
    model = d / "htdemucs" / src.stem
    vocals, instrumental = model / "vocals.wav", model / "no_vocals.wav"
    if not vocals.exists(): raise HTTPException(500, "Demucs output missing")
    return {"job_id": job, "vocals_url": f"/api/file/{job}/vocals", "instrumental_url": f"/api/file/{job}/instrumental"}

@app.post("/api/voice/enrol")
async def enrol_voice(sample: UploadFile = File(...), consent: bool = Form(...), name: str = Form("My Voice Is Dope")):
    if not consent: raise HTTPException(400, "Voice ownership/permission confirmation is required")
    voice_id = uuid.uuid4().hex
    d = ROOT / "voices" / voice_id; d.mkdir(parents=True)
    raw = d / (sample.filename or "sample.wav")
    with raw.open("wb") as f: shutil.copyfileobj(sample.file, f)
    clean = d / "reference.wav"
    run(["ffmpeg", "-y", "-i", str(raw), "-ac", "1", "-ar", "48000", "-af", "highpass=f=70,lowpass=f=16000,loudnorm", str(clean)])
    return {"voice_id": voice_id, "name": name, "status": "enrolled", "reference": f"/api/file/voice/{voice_id}"}

@app.post("/api/fuse")
async def fuse(job_id: str = Form(...), voice_id: str = Form(...), similarity: int = Form(85)):
    """Queue boundary for the authorised voice-to-voice model.
    Set FUSIONVOICE_CONVERTER to an executable accepting: input.wav reference.wav output.wav similarity.
    This keeps provider/model choice replaceable while the rest of the pipeline is already functional.
    """
    vocals = ROOT / job_id / "htdemucs"
    candidates = list(vocals.glob("*/vocals.wav"))
    reference = ROOT / "voices" / voice_id / "reference.wav"
    if not candidates or not reference.exists(): raise HTTPException(404, "Track stems or enrolled voice not found")
    converter = os.getenv("FUSIONVOICE_CONVERTER")
    if not converter: raise HTTPException(503, "Voice conversion model is not configured")
    out = ROOT / job_id / "fused_vocals.wav"
    run([converter, str(candidates[0]), str(reference), str(out), str(max(0,min(100,similarity)))])
    return {"status":"complete", "fused_vocals_url":f"/api/file/{job_id}/fused"}

@app.post("/api/master")
async def master(job_id: str = Form(...)):
    fused = ROOT / job_id / "fused_vocals.wav"
    inst = list((ROOT / job_id / "htdemucs").glob("*/no_vocals.wav"))
    if not fused.exists() or not inst: raise HTTPException(404, "Converted vocal or instrumental missing")
    out = ROOT / job_id / "fusionvoice_master.wav"
    run(["ffmpeg","-y","-i",str(inst[0]),"-i",str(fused),"-filter_complex","[0:a][1:a]amix=inputs=2:normalize=0,alimiter=limit=0.95,loudnorm=I=-14:TP=-1.0:LRA=11","-ar","48000",str(out)])
    return {"status":"complete", "master_url":f"/api/file/{job_id}/master"}

@app.get("/api/file/{job_id}/{kind}")
def get_file(job_id: str, kind: str):
    d = ROOT / job_id
    mapping = {"fused": d/"fused_vocals.wav", "master":d/"fusionvoice_master.wav"}
    if kind in ("vocals","instrumental"):
        n = "vocals.wav" if kind == "vocals" else "no_vocals.wav"
        found = list((d/"htdemucs").glob(f"*/{n}")); path = found[0] if found else Path("/missing")
    else: path = mapping.get(kind, Path("/missing"))
    if not path.exists(): raise HTTPException(404, "Audio file not found")
    return FileResponse(path, media_type="audio/wav", filename=path.name)

@app.get("/api/file/voice/{voice_id}")
def voice_file(voice_id: str):
    path = ROOT/"voices"/voice_id/"reference.wav"
    if not path.exists(): raise HTTPException(404, "Voice not found")
    return FileResponse(path, media_type="audio/wav")
