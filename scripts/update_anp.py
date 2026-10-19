#!/usr/bin/env python3
"""Importa o CSV mensal mais recente de diesel/GNV publicado pela ANP."""
import csv, hashlib, io, json, re
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urljoin

PAGE = "https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/serie-historica-de-precos-de-combustiveis"
OUT = Path("data")
ARCHIVE = OUT / "archive"

def fetch(url):
    req = Request(url, headers={"User-Agent":"DieselInteligencia/1.0"})
    with urlopen(req, timeout=60) as response:
        return response.read()

def clean(x):
    return re.sub(r"\s+", " ", (x or "").replace("\ufeff","")).strip()

def parse_price(raw):
    raw = clean(raw).replace("R$","").replace(" ","")
    if not raw: return None
    if "," in raw: raw = raw.replace(".","").replace(",",".")
    try:
        n = float(raw)
        return round(n, 3) if n > 0 else None
    except ValueError: return None

def norm(s):
    return clean(s).casefold()

def main():
    html = fetch(PAGE).decode("utf-8", errors="replace")
    links = re.findall(r"""href=["']([^"']+\.csv(?:\?[^"']*)?)["']""", html, flags=re.I)
    candidates = []
    for raw in links:
        url = urljoin(PAGE, raw.replace("&amp;","&"))
        name = url.rsplit("/",1)[-1].lower()
        if "diesel" not in name or "gnv" not in name: continue
        match = re.search(r"(20\d{2})[-.](0[1-9]|1[0-2])", name)
        if match: candidates.append((int(match.group(1)), int(match.group(2)), url, name))
    if not candidates:
        raise RuntimeError("Não encontrei CSV mensal Diesel/GNV na página oficial da ANP; nenhum dado foi sobrescrito.")
    year, month, url, filename = sorted(candidates)[-1]
    blob = fetch(url)
    decoded = None
    for encoding in ("utf-8-sig","cp1252","latin-1"):
        try:
            decoded = blob.decode(encoding); break
        except UnicodeDecodeError: pass
    if decoded is None: raise RuntimeError("Não foi possível decodificar o CSV.")
    try: dialect = csv.Sniffer().sniff(decoded[:10000], delimiters=";,\t")
    except csv.Error:
        dialect = csv.excel; dialect.delimiter = ";"
    reader = csv.DictReader(io.StringIO(decoded), dialect=dialect)
    if not reader.fieldnames: raise RuntimeError("CSV sem cabeçalhos.")
    fields = {norm(f):f for f in reader.fieldnames if f}
    def find(*parts):
        return next((original for normalized,original in fields.items() if all(p in normalized for p in parts)),None)
    product_col = find("produto")
    price_col = find("valor de venda") or find("preco de venda")
    date_col = find("data da coleta") or find("data coleta")
    state_col = find("estado","sigla")
    city_col = find("municipio") or find("município")
    seller_col = find("revenda")
    brand_col = find("bandeira")
    if not all((product_col,price_col,state_col,city_col)):
        raise RuntimeError("Cabeçalhos do CSV não reconhecidos: "+", ".join(reader.fieldnames))
    records=[]
    for row in reader:
        prod=clean(row.get(product_col,"")).upper()
        if "DIESEL" not in prod: continue
        if "S-10" in prod or "S10" in prod: product="DIESEL S10"
        elif "S-500" in prod or "S500" in prod: product="DIESEL S500"
        else: continue
        price=parse_price(row.get(price_col,""))
        if price is None: continue
        date=clean(row.get(date_col,"")) if date_col else ""
        for fmt in ("%d/%m/%Y","%d/%m/%y","%Y-%m-%d"):
            try: date=datetime.strptime(date,fmt).date().isoformat(); break
            except ValueError: pass
        records.append({"date":date,"state":clean(row.get(state_col,"")).upper(),"city":clean(row.get(city_col,"")),"seller":clean(row.get(seller_col,"")) if seller_col else "","product":product,"price":price,"source":"ANP","brand":clean(row.get(brand_col,"")) if brand_col else ""})
    if not records: raise RuntimeError("CSV baixado, mas nenhum registro S10/S500 válido foi encontrado.")
    now=datetime.now(timezone.utc).isoformat(timespec="seconds")
    meta={"source":"ANP","source_page":PAGE,"source_url":url,"source_file":filename,"source_sha256":hashlib.sha256(blob).hexdigest(),"reference_month":f"{year:04d}-{month:02d}","checked_at_utc":now,"record_count":len(records),"note":"Verificação diária; a pesquisa de preços da ANP não é necessariamente publicada diariamente."}
    OUT.mkdir(exist_ok=True); ARCHIVE.mkdir(parents=True,exist_ok=True)
    (ARCHIVE/f"{year:04d}-{month:02d}.json").write_text(json.dumps({"meta":meta,"records":records},ensure_ascii=False),encoding="utf-8")
    all_records=[]; months=[]
    for path in sorted(ARCHIVE.glob("????-??.json")):
        item=json.loads(path.read_text(encoding="utf-8")); all_records.extend(item.get("records",[])); months.append(path.stem)
    (OUT/"prices.json").write_text(json.dumps({"meta":{**meta,"archive_months":len(months),"combined_record_count":len(all_records)},"records":all_records},ensure_ascii=False),encoding="utf-8")
    (OUT/"status.json").write_text(json.dumps({"status":"success","checked_at_utc":now,"source_url":url,"source_file":filename,"record_count":len(records)},ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"ANP: {filename}; {len(records)} registros; {len(months)} mês(es) no histórico.")
if __name__=="__main__": main()
