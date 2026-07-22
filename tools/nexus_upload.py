#!/usr/bin/env python3
"""Publish a file to a Nexus mod page via the v3 API — the path the GitHub upload-action can't take.

Reusable for ANY of our Nexus mods (pass --mod-id / --domain). Discover a mod's v3 id with:
    curl -H "apikey: $KEY" https://api.nexusmods.com/v3/games/<domain>/mods/<siteModId> | jq .data.id

Why this script exists: the official Nexus upload-action only APPENDS a version to an existing v3
mod-file (POST /mod-files/{id}/versions). A mod whose files were all uploaded through the website
has no v3 file to append to, so the append 404s (this bit us on every workflow run). The v3 API
DOES expose file CREATION (POST /v3/mod-files), which is what this does: multipart-upload the zip
to Nexus's R2 storage, finalise, then create the mod file from that upload.

Flow (mirrors the upload-action's internals, ending in create instead of append):
  1. POST /uploads/multipart {filename, size_bytes}
        -> {id (upload_id), part_size_bytes, part_presigned_urls[], complete_presigned_url}
  2. PUT each part to its presigned R2 URL, capture the (unquoted) ETag
  3. POST the complete_presigned_url with a CompleteMultipartUpload XML of the parts
  4. POST /uploads/{id}/finalise, then poll GET /uploads/{id} until state == "available"
  5. POST /v3/mod-files {upload_id, mod_id, name, version, file_category, ...}

Usage:
  nexus_upload.py <zip> <version> "<file name>" "<description>" \
      [--mod-id <v3ModId>] [--domain <game>] [--category main] [--key <path/to/.nexus.key>]

Defaults target the Shadowrun Returns DMS voice pack. Key is read from games/shadowrun/.nexus.key
(gitignored) unless --key is given.

NOTE: this CREATES a new mod-file each run, which does NOT archive prior "main" files from other
containers. After a release, archive the previous version on the website (Files tab -> edit -> set
category to Archived) — the v3 API exposes no standalone archive operation (only archive_existing_file
when appending a version to the SAME file container).
"""
import os, sys, json, time, argparse, urllib.request, urllib.error, xml.sax.saxutils as sx

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(HERE, "..")
API = os.environ.get("NEXUSMODS_API_BASE", "https://api.nexusmods.com/v3")
UA = "voices4all-releaser/1.0"

def load_key(path):
    with open(path) as f:
        return f.read().strip()

def api(method, path, body=None, apikey=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method, headers={
        "apikey": apikey, "Content-Type": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")

def put_part(url, chunk):
    req = urllib.request.Request(url, data=chunk, method="PUT",
                                 headers={"Content-Type": "application/octet-stream"})
    with urllib.request.urlopen(req, timeout=600) as r:
        etag = r.headers.get("ETag") or r.headers.get("etag")
    if not etag:
        raise RuntimeError("no ETag returned for part")
    return etag.replace('"', '')          # the complete XML wants the raw ETag, unquoted

def complete_multipart(url, parts):
    # parts: list of (part_number, etag)
    xml = ["<CompleteMultipartUpload>"]
    for n, etag in parts:
        xml.append(f"<Part><PartNumber>{n}</PartNumber><ETag>{sx.escape(etag)}</ETag></Part>")
    xml.append("</CompleteMultipartUpload>")
    payload = "".join(xml).encode()
    req = urllib.request.Request(url, data=payload, method="POST",
                                 headers={"Content-Type": "application/xml"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.status, r.read().decode()[:300]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("zip"); ap.add_argument("version")
    ap.add_argument("name"); ap.add_argument("description")
    ap.add_argument("--mod-id", default="438086664474", help="v3 mod id (default: SRR DMS voice pack)")
    ap.add_argument("--domain", default="shadowrunreturns")
    ap.add_argument("--category", default="main")
    ap.add_argument("--key", default=os.path.join(BASE, ".nexus.key"))
    a = ap.parse_args()
    zip_path, version, fname, desc = a.zip, a.version, a.name, a.description
    mod_id = a.mod_id
    k = load_key(a.key)
    size = os.path.getsize(zip_path)
    print(f"file: {zip_path} ({size} bytes)  version: {version}")

    # 1. request multipart upload
    st, r = api("POST", "/uploads/multipart", {
        "filename": os.path.basename(zip_path), "size_bytes": size}, k)
    if st >= 400:
        print("multipart request failed:", st, r); sys.exit(1)
    d = r["data"]
    upload_id = d["id"]; part_size = d["part_size_bytes"]
    urls = d["part_presigned_urls"]; complete_url = d["complete_presigned_url"]
    print(f"upload_id={upload_id}  parts={len(urls)} x {part_size} bytes")

    # 2. upload each part
    parts = []
    with open(zip_path, "rb") as fh:
        for i, url in enumerate(urls, start=1):
            chunk = fh.read(part_size)
            if not chunk:
                break
            etag = put_part(url, chunk)
            parts.append((i, etag))
            print(f"  part {i}/{len(urls)} uploaded ({len(chunk)} bytes) etag={etag}")

    # 3. complete the multipart upload (S3/R2 side)
    cst, ctext = complete_multipart(complete_url, parts)
    print(f"complete (R2): HTTP {cst}")

    # 3b. tell Nexus the upload is done, then poll until it has processed the file. The S3 complete
    #     alone leaves the upload "processing"; creating a mod file before it's "available" fails
    #     with "invalid state".
    st, r = api("POST", f"/uploads/{upload_id}/finalise", None, k)
    if st >= 400:
        print("finalise failed:", st, r); sys.exit(1)
    print("finalise: state =", r.get("data", {}).get("state"))
    for attempt in range(60):
        st, r = api("GET", f"/uploads/{upload_id}", None, k)
        state = r.get("data", {}).get("state")
        print(f"  poll {attempt}: state = {state}")
        if state == "available":
            break
        time.sleep(min(2 * (1.5 ** attempt), 30))
    else:
        print("upload processing timed out"); sys.exit(1)

    # 4. create the mod file from the finished upload
    st, r = api("POST", "/mod-files", {
        "upload_id": upload_id,
        "mod_id": mod_id,
        "name": fname,
        "description": desc,
        "version": version,
        "file_category": a.category,
        "archive_existing_file": True,
        "allow_mod_manager_download": True,
        "update_mod_version": True,
    }, k)
    print("create /mod-files:", st)
    print(json.dumps(r, indent=1)[:800])
    if st >= 400:
        sys.exit(1)

if __name__ == "__main__":
    main()
