import base64
import os
import subprocess
import tempfile
from pathlib import Path

import runpod


def _decode_audio(value, path):
    if not value:
        raise ValueError("missing audio input")
    path.write_bytes(base64.b64decode(value))


def handler(event):
    data = event.get("input") or {}
    source_b64 = data.get("source_audio")
    reference_b64 = data.get("reference_audio")
    similarity = max(0, min(100, int(data.get("similarity", 85))))
    converter = os.getenv("FUSIONVOICE_CONVERTER")

    if not converter:
        return {"error": "FUSIONVOICE_CONVERTER is not configured"}

    try:
        with tempfile.TemporaryDirectory(prefix="fusionvoice-") as tmp:
            root = Path(tmp)
            source = root / "source.wav"
            reference = root / "reference.wav"
            output = root / "output.wav"
            _decode_audio(source_b64, source)
            _decode_audio(reference_b64, reference)

            process = subprocess.run(
                [converter, str(source), str(reference), str(output), str(similarity)],
                capture_output=True,
                text=True,
            )
            if process.returncode != 0:
                return {"error": (process.stderr or "voice conversion failed")[-3000:]}
            if not output.exists():
                return {"error": "converter completed without an output file"}

            return {
                "audio": base64.b64encode(output.read_bytes()).decode("ascii"),
                "format": "wav",
                "similarity": similarity,
            }
    except Exception as exc:
        return {"error": str(exc)}


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
