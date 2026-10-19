
#!/usr/bin/env python3
"""Importa os dados mensais de diesel S10 e S500 da ANP."""

import csv
import hashlib
import io
import json
import re
import time

from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urljoin
from urllib.error import HTTPError, URLError


PAGE = (
    "https://www.gov.br/anp/pt-br/centrais-de-conteudo/"
    "dados-abertos/serie-historica-de-precos-de-combustiveis"
)

OUT = Path("data")
ARCHIVE = OUT / "archive"


def fetch(url):
    """Baixa uma página ou arquivo, repetindo tentativas em caso de falha."""

    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; DieselInteligencia/1.0)",
            "Accept": "text/csv,text/html,*/*",
        },
    )

    for tentativa in range(4):
        try:
            print(
                f"Baixando: {url} "
                f"(tentativa {tentativa + 1}/4)",
                flush=True,
            )

            with urlopen(req, timeout=90) as response:
                return response.read()

        except (HTTPError, URLError, TimeoutError) as erro:
            print(f"Falha no download: {erro}", flush=True)

            if tentativa == 3:
                raise

            espera = 10 * (tentativa + 1)
            print(f"Nova tentativa em {espera} segundos.", flush=True)
            time.sleep(espera)


def clean(value):
    """Remove espaços extras e caracteres invisíveis comuns."""

    return re.sub(
        r"\s+",
        " ",
        (value or "").replace("\ufeff", ""),
    ).strip()


def norm(value):
    return clean(value).casefold()


def parse_price(raw):
    """Converte preços brasileiros, como 6,89, para números."""

    raw = clean(raw).replace("R$", "").replace(" ", "")

    if not raw:
        return None

    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")

    try:
        number = float(raw)
        return round(number, 3) if number > 0 else None
    except ValueError:
        return None


def parse_date(value):
    """Converte datas reconhecidas para o formato AAAA-MM-DD."""

    value = clean(value)

    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue

    return value


def main():
    # 1. Consulta a página oficial da ANP.
    html = fetch(PAGE).decode("utf-8", errors="replace")

    # 2. Localiza os links para arquivos CSV.
    links = re.findall(
        r"""href=["']([^"']+\.csv(?:\?[^"']*)?)["']""",
        html,
        flags=re.IGNORECASE,
    )

    candidates = []

    for raw in links:
        raw = raw.replace("&amp;", "&")
        url = urljoin(PAGE, raw)
        filename = url.rsplit("/", 1)[-1].split("?", 1)[0]
        name = filename.lower()

        # Seleciona arquivos mensais de diesel e GNV.
        if "diesel" not in name or "gnv" not in name:
            continue

        match = re.search(
            r"(20\d{2})[-.](0[1-9]|1[0-2])",
            name,
        )

        if match:
            year = int(match.group(1))
            month = int(match.group(2))
            candidates.append((year, month, url, filename))

    if not candidates:
        raise RuntimeError(
            "Nenhum CSV mensal de Diesel/GNV foi encontrado "
            "na página oficial da ANP. Nenhum dado foi sobrescrito."
        )

    # Escolhe o arquivo do mês mais recente encontrado.
    year, month, url, filename = sorted(candidates)[-1]

    print(f"Arquivo selecionado: {filename}", flush=True)

    # 3. Baixa o CSV com novas tentativas automáticas.
    blob = fetch(url)

    # 4. Tenta identificar a codificação do arquivo.
    decoded = None

    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            decoded = blob.decode(encoding)
            break
        except UnicodeDecodeError:
            continue

    if decoded is None:
        raise RuntimeError("Não foi possível decodificar o CSV da ANP.")

    # 5. Detecta o separador do CSV.
    try:
        dialect = csv.Sniffer().sniff(
            decoded[:10000],
            delimiters=";,\t",
        )
    except csv.Error:
        dialect = csv.excel
        dialect.delimiter = ";"

    reader = csv.DictReader(
        io.StringIO(decoded),
        dialect=dialect,
    )

    if not reader.fieldnames:
        raise RuntimeError("O CSV baixado não possui cabeçalhos.")

    fields = {
        norm(field): field
        for field in reader.fieldnames
        if field
    }

    def find(*parts):
        for normalized, original in fields.items():
            if all(part in normalized for part in parts):
                return original
        return None

    product_col = find("produto")
    price_col = find("valor de venda") or find("preco de venda")
    date_col = find("data da coleta") or find("data coleta")
    state_col = find("estado", "sigla") or find("uf")
    city_col = find("municipio") or find("município")
    seller_col = find("revenda")
    brand_col = find("bandeira")

    if not all((product_col, price_col, state_col, city_col)):
        raise RuntimeError(
            "Os cabeçalhos do CSV não foram reconhecidos: "
            + ", ".join(reader.fieldnames)
        )

    # 6. Filtra os registros de Diesel S10 e S500.
    records = []

    for row in reader:
        product_name = clean(row.get(product_col, "")).upper()

        if "DIESEL" not in product_name:
            continue

        if "S-10" in product_name or "S10" in product_name:
            product = "DIESEL S10"
        elif "S-500" in product_name or "S500" in product_name:
            product = "DIESEL S500"
        else:
            continue

        price = parse_price(row.get(price_col, ""))

        if price is None:
            continue

        date_value = (
            clean(row.get(date_col, ""))
            if date_col
            else ""
        )

        records.append(
            {
                "date": parse_date(date_value),
                "state": clean(row.get(state_col, "")).upper(),
                "city": clean(row.get(city_col, "")),
                "seller": (
                    clean(row.get(seller_col, ""))
                    if seller_col
                    else ""
                ),
                "product": product,
                "price": price,
                "source": "ANP",
                "brand": (
                    clean(row.get(brand_col, ""))
                    if brand_col
                    else ""
                ),
            }
        )

    if not records:
        raise RuntimeError(
            "O CSV foi baixado, mas nenhum registro válido de "
            "Diesel S10 ou S500 foi encontrado."
        )

    # 7. Salva os dados e os metadados.
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    meta = {
        "source": "ANP",
        "source_page": PAGE,
        "source_url": url,
        "source_file": filename,
        "source_sha256": hashlib.sha256(blob).hexdigest(),
        "reference_month": f"{year:04d}-{month:02d}",
        "checked_at_utc": now,
        "record_count": len(records),
        "note": (
            "Verificação diária. A ANP não necessariamente publica "
            "novos preços todos os dias."
        ),
    }

    OUT.mkdir(parents=True, exist_ok=True)
    ARCHIVE.mkdir(parents=True, exist_ok=True)

    archive_file = ARCHIVE / f"{year:04d}-{month:02d}.json"

    archive_file.write_text(
        json.dumps(
            {"meta": meta, "records": records},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # 8. Reúne os meses arquivados para formar o histórico.
    all_records = []
    months = []

    for path in sorted(ARCHIVE.glob("????-??.json")):
        item = json.loads(path.read_text(encoding="utf-8"))
        all_records.extend(item.get("records", []))
        months.append(path.stem)

    (OUT / "prices.json").write_text(
        json.dumps(
            {
                "meta": {
                    **meta,
                    "archive_months": len(months),
                    "combined_record_count": len(all_records),
                },
                "records": all_records,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    (OUT / "status.json").write_text(
        json.dumps(
            {
                "status": "success",
                "checked_at_utc": now,
                "source_url": url,
                "source_file": filename,
                "record_count": len(records),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        f"Sucesso: {filename}; {len(records)} registros; "
        f"{len(months)} mês(es) no histórico.",
        flush=True,
    )


if __name__ == "__main__":
    main()
