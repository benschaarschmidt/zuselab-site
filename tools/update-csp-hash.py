#!/usr/bin/env python3
"""Recompute the CSP sha256 for the inline <script> in index.html and rewrite script-src.
Run after any change to the inline script text. Exit 0 always; prints whether it changed."""
import base64, hashlib, re, sys, pathlib
p = pathlib.Path(__file__).resolve().parent.parent / "index.html"
s = p.read_text(encoding="utf8")
inline = [m.group(1) for m in re.finditer(r'<script>(.*?)</script>', s, re.S)]
if len(inline) != 1:
    sys.exit(f"expected exactly 1 inline <script>, found {len(inline)}")
h = "sha256-" + base64.b64encode(hashlib.sha256(inline[0].encode("utf8")).digest()).decode()
new, n = re.subn(r"(script-src 'self')( 'sha256-[^']*')?", lambda m: f"{m.group(1)} '{h}'", s, count=1)
if n != 1:
    sys.exit("script-src not found")
if new != s:
    p.write_text(new, encoding="utf8"); print("CSP hash updated:", h)
else:
    print("CSP hash already correct:", h)
