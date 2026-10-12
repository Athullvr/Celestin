import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from dataset import DOCS, DOC_QUERIES
from orbit.pageindex.tree import build_sections

root = Path(__file__).resolve().parents[1]
secs = {d: build_sections((root / d).read_text(), Path(d).stem) for d in DOCS}
print({d: len(s) for d, s in secs.items()}, sum(len(s) for s in secs.values()), "sections")
for q, ev, docs in DOC_QUERIES:
    hits = [(d, " > ".join(s.path)) for d in DOCS for s in secs[d] if ev.lower() in s.text.lower()]
    bad = [h for h in hits if h[0] not in docs]
    print(f"\n{q!r} evidence={ev!r}\n  gold: {hits}\n  OUTSIDE listed docs: {bad}")
