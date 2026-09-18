#!/usr/bin/env python3
"""FusionVoice HTTP inference adapter.
Usage: http_converter.py source.wav reference.wav output.wav similarity
Environment:
  FUSIONVOICE_INFERENCE_URL - authorised voice-to-voice inference endpoint
  FUSIONVOICE_INFERENCE_TOKEN - optional bearer token
The provider must return WAV audio bytes or JSON containing output_url.
"""
import json, os, sys, urllib.request, urllib.error
from pathlib import Path

def fail(message, code=1):
    print(message, file=sys.stderr); raise SystemExit(code)

def main():
    if len(sys.argv) != 5: fail("expected source, reference, output, similarity", 2)
    source, reference, output, similarity = map(str, sys.argv[1:])
    url=os.getenv("FUSIONVOICE_INFERENCE_URL","").strip()
    if not url: fail("FUSIONVOICE_INFERENCE_URL is not configured")
    boundary="----FusionVoiceBoundary7MA4YWxk"
    parts=[]
    def field(name,value):
        parts.extend([f"--{boundary}\r\n".encode(),f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),str(value).encode(),b"\r\n"])
    def filepart(name,path):
        p=Path(path); parts.extend([f"--{boundary}\r\n".encode(),f'Content-Disposition: form-data; name="{name}"; filename="{p.name}"\r\n'.encode(),b"Content-Type: audio/wav\r\n\r\n",p.read_bytes(),b"\r\n"])
    field("similarity",similarity); filepart("source",source); filepart("reference",reference); parts.append(f"--{boundary}--\r\n".encode())
    headers={"Content-Type":f"multipart/form-data; boundary={boundary}","Accept":"audio/wav, application/json"}
    token=os.getenv("FUSIONVOICE_INFERENCE_TOKEN","").strip()
    if token: headers["Authorization"]="Bearer "+token
    req=urllib.request.Request(url,data=b"".join(parts),headers=headers,method="POST")
    try:
        with urllib.request.urlopen(req,timeout=int(os.getenv("FUSIONVOICE_INFERENCE_TIMEOUT","900"))) as r:
            body=r.read(); ctype=r.headers.get("Content-Type","")
    except urllib.error.HTTPError as e: fail(f"inference HTTP {e.code}: {e.read().decode(errors='replace')[-2000:]}")
    except Exception as e: fail(f"inference request failed: {e}")
    if "application/json" in ctype:
        data=json.loads(body.decode()); out_url=data.get("output_url") or data.get("url")
        if not out_url: fail("inference JSON did not contain output_url")
        try: body=urllib.request.urlopen(out_url,timeout=300).read()
        except Exception as e: fail(f"failed to download inference output: {e}")
    Path(output).write_bytes(body)
    if Path(output).stat().st_size < 1024: fail("inference output is unexpectedly small")

if __name__ == "__main__": main()
