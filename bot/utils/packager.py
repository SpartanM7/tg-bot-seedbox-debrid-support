
import os, zipfile, threading
ZIP_KEYWORDS = ("pic", "pics", "image", "images")
_lock = threading.Lock()

def should_zip(name):
    return any(k in name.lower() for k in ZIP_KEYWORDS)

def zip_folder(folder):
    z = folder + ".zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(folder):
            for f in files:
                full = os.path.join(root, f)
                zipf.write(full, os.path.relpath(full, folder))
    return z

def prepare(base, dest):
    out = []
    with _lock:
        for n in os.listdir(base):
            p = os.path.join(base, n)
            if os.path.isdir(p) and should_zip(n):
                out.append(zip_folder(p))
            else:
                out.append(p)
    return out
