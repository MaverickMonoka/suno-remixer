from pathlib import Path
import json, os, shutil, subprocess, uuid
from datetime import datetime, timezone
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

app = FastAPI(title="FusionVoice Engine", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "*").split(","), allow_methods=["*"], allow_headers=["*"])
ROOT = Path(os.getenv("FUSIONVOICE_DATA", "/tmp/fusionvoice")); ROOT.mkdir(parents=True, exist_ok=True)
VOICES = ROOT / "voices"; VOICES.mkdir(exist_ok=True)

def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode: raise HTTPException(500, p.stderr[-3000:] or "Audio process failed")
    return p

def safe_id(value: str):
    if not value or any(c not in "0123456789abcdef" for c in value.lower()): raise HTTPException(400, "Invalid identifier")
    return value

def meta_path(job): return ROOT / safe_id(job) / "job.json"
def write_meta(job, **updates):
    p=meta_path(job); data=json.loads(p.read_text()) if p.exists() else {"job_id":job,"created_at":datetime.now(timezone.utc).isoformat()}
    data.update(updates); p.write_text(json.dumps(data, indent=2)); return data

@app.get("/health")
def health():
    return {"ok":True,"engine":"FusionVoice","version":"1.0.0","demucs":shutil.which("demucs") is not None,"ffmpeg":shutil.which("ffmpeg") is not None,"converter":bool(os.getenv("FUSIONVOICE_CONVERTER"))}

@app.post("/api/stems")
async def stems(track: UploadFile = File(...)):
    job=uuid.uuid4().hex; d=ROOT/job; d.mkdir()
    src=d/(Path(track.filename or "track.wav").name)
    with src.open("wb") as f: shutil.copyfileobj(track.file,f)
    write_meta(job,status="separating",track=src.name)
    run(["demucs","--two-stems=vocals","-o",str(d),str(src)])
    model=d/"htdemucs"/src.stem; vocals=model/"vocals.wav"; instrumental=model/"no_vocals.wav"
    if not vocals.exists() or not instrumental.exists(): raise HTTPException(500,"Demucs output missing")
    write_meta(job,status="stems_ready")
    return {"job_id":job,"status":"stems_ready","vocals_url":f"/api/file/{job}/vocals","instrumental_url":f"/api/file/{job}/instrumental"}

@app.post("/api/voice/enrol")
async def enrol_voice(sample: UploadFile=File(...), consent: bool=Form(...), name: str=Form("My Voice Is Dope")):
    if not consent: raise HTTPException(400,"Voice ownership/permission confirmation is required")
    voice_id=uuid.uuid4().hex; d=VOICES/voice_id; d.mkdir(parents=True)
    raw=d/Path(sample.filename or "sample.wav").name
    with raw.open("wb") as f: shutil.copyfileobj(sample.file,f)
    clean=d/"reference.wav"
    run(["ffmpeg","-y","-i",str(raw),"-ac","1","-ar","48000","-af","highpass=f=70,lowpass=f=16000,loudnorm",str(clean)])
    profile={"voice_id":voice_id,"name":name,"consent":True,"created_at":datetime.now(timezone.utc).isoformat(),"status":"enrolled"}
    (d/"profile.json").write_text(json.dumps(profile,indent=2)); return profile

@app.get("/api/voice/{voice_id}")
def voice_profile(voice_id:str):
    p=VOICES/safe_id(voice_id)/"profile.json"
    if not p.exists(): raise HTTPException(404,"Voice profile not found")
    return json.loads(p.read_text())

@app.delete("/api/voice/{voice_id}")
def delete_voice(voice_id:str):
    d=VOICES/safe_id(voice_id)
    if not d.exists(): raise HTTPException(404,"Voice profile not found")
    shutil.rmtree(d); return {"deleted":True,"voice_id":voice_id}

@app.post("/api/fuse")
async def fuse(job_id:str=Form(...),voice_id:str=Form(...),similarity:int=Form(85),warmth:int=Form(60),depth:int=Form(55),clarity:int=Form(70),presence:int=Form(65)):
    job_id=safe_id(job_id); voice_id=safe_id(voice_id); similarity=max(0,min(100,similarity))
    candidates=list((ROOT/job_id/"htdemucs").glob("*/vocals.wav")); reference=VOICES/voice_id/"reference.wav"
    if not candidates or not reference.exists(): raise HTTPException(404,"Track stems or enrolled voice not found")
    converter=os.getenv("FUSIONVOICE_CONVERTER")
    if not converter: raise HTTPException(503,"Voice conversion model is not configured. Set FUSIONVOICE_CONVERTER to the authorised voice-to-voice inference executable.")
    out=ROOT/job_id/"fused_vocals.wav"; write_meta(job_id,status="converting",voice_id=voice_id,similarity=similarity)
    run([converter,str(candidates[0]),str(reference),str(out),str(similarity)])
    if not out.exists(): raise HTTPException(500,"Converter completed without an output file")
    # Studio polish controls are intentionally post-conversion and do not impersonate a non-consenting voice.
    polished=ROOT/job_id/"polished_vocals.wav"
    bass=(depth-50)/10; treble=(clarity-50)/10; gain=(presence-50)/20
    run(["ffmpeg","-y","-i",str(out),"-af",f"bass=g={bass:.1f},treble=g={treble:.1f},volume={10**(gain/20):.3f},acompressor=threshold=-18dB:ratio=2.5:attack=15:release=180,alimiter=limit=0.95",str(polished)])
    shutil.move(polished,out); write_meta(job_id,status="converted",warmth=warmth,depth=depth,clarity=clarity,presence=presence)
    return {"status":"complete","fused_vocals_url":f"/api/file/{job_id}/fused"}

@app.post("/api/master")
async def master(job_id:str=Form(...)):
    job_id=safe_id(job_id); fused=ROOT/job_id/"fused_vocals.wav"; inst=list((ROOT/job_id/"htdemucs").glob("*/no_vocals.wav"))
    if not fused.exists() or not inst: raise HTTPException(404,"Converted vocal or instrumental missing")
    out=ROOT/job_id/"fusionvoice_master.wav"; write_meta(job_id,status="mastering")
    run(["ffmpeg","-y","-i",str(inst[0]),"-i",str(fused),"-filter_complex","[0:a][1:a]amix=inputs=2:normalize=0,acompressor=threshold=-16dB:ratio=2:attack=20:release=200,alimiter=limit=0.95,loudnorm=I=-14:TP=-1.0:LRA=11","-ar","48000",str(out)])
    write_meta(job_id,status="complete"); return {"status":"complete","master_url":f"/api/file/{job_id}/master"}

@app.get("/api/job/{job_id}")
def job_status(job_id:str):
    p=meta_path(job_id)
    if not p.exists(): raise HTTPException(404,"Job not found")
    return json.loads(p.read_text())

@app.delete("/api/job/{job_id}")
def delete_job(job_id:str):
    d=ROOT/safe_id(job_id)
    if not d.exists(): raise HTTPException(404,"Job not found")
    shutil.rmtree(d); return {"deleted":True,"job_id":job_id}

@app.get("/api/file/{job_id}/{kind}")
def get_file(job_id:str,kind:str):
    d=ROOT/safe_id(job_id); mapping={"fused":d/"fused_vocals.wav","master":d/"fusionvoice_master.wav"}
    if kind in ("vocals","instrumental"):
        n="vocals.wav" if kind=="vocals" else "no_vocals.wav"; found=list((d/"htdemucs").glob(f"*/{n}")); path=found[0] if found else Path("/missing")
    else: path=mapping.get(kind,Path("/missing"))
    if not path.exists(): raise HTTPException(404,"Audio file not found")
    return FileResponse(path,media_type="audio/wav",filename=path.name)

@app.get("/api/file/voice/{voice_id}")
def voice_file(voice_id:str):
    path=VOICES/safe_id(voice_id)/"reference.wav"
    if not path.exists(): raise HTTPException(404,"Voice not found")
    return FileResponse(path,media_type="audio/wav")
