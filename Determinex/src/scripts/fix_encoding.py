import pathlib

# Was two hardcoded absolute paths, so this only ran on one machine. The script
# sits in the same directory as the file it rewrites.
_QS = str(pathlib.Path(__file__).resolve().parent / "quickstart.ps1")


with open(_QS, encoding="utf-8") as f:
    content = f.read()

# Replace any fancy quotes with standard quotes
content = (
    content.replace("\u201c", '"')
    .replace("\u201d", '"')
    .replace("\u2018", "'")
    .replace("\u2019", "'")
)
# Replace em-dashes
content = content.replace("\u2014", "-")
# Strip any stray non-ascii
content = content.encode("ascii", "ignore").decode("ascii")

with open(_QS, "w", encoding="ascii") as f:
    f.write(content)
