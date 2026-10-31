"""Imprime a última data de dados embutida numa página gerada (ou vazio)."""
import json, re, sys, pathlib
p = pathlib.Path(sys.argv[1])
if not p.exists():
    sys.exit(0)
m = re.search(r'id="data">(.*?)</script>', p.read_text(), re.S)
print(json.loads(m.group(1).replace("<\\/", "</"))["tdates"][-1] if m else "")
