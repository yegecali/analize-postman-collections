#!/usr/bin/env python3
"""
split_postman_backup.py

Divide un backup de Postman (generado desde Settings -> Data -> Export)
en archivos mas pequenos y organizados: colecciones individuales,
ambientes (environments) y un indice legible.

Postman puede entregar el backup en dos formas distintas:

1. "Data Dump" (lo normal al usar Export Data):
   Un .zip que, al descomprimirlo, trae subcarpetas como:
     collections/<id>.json   (cada una ya es una Collection v2.1 valida)
     environments/<id>.json
     archive.json            (indice con los ids/nombres originales)

2. Un unico archivo JSON enorme (p.ej. 120k lineas) que en realidad es
   UNA sola Postman Collection v2.1 (tiene las llaves "info" e "item")
   donde cada carpeta de primer nivel representa, en la practica,
   una "coleccion" distinta agrupada dentro de una sola mega-coleccion.

Este script detecta automaticamente cual de los dos casos aplica y
genera una salida organizada:

    output/
      collections/<nombre-carpeta>.postman_collection.json
      environments/<nombre-ambiente>.postman_environment.json
      index.md

Uso:
    python3 split_postman_backup.py <ruta_al_backup> [-o output_dir]

    <ruta_al_backup> puede ser:
      - un archivo .zip (el dump tal cual lo descarga Postman)
      - un directorio ya descomprimido del dump
      - un unico archivo .json (mega-coleccion o archive.json)
"""

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path


def slugify(name: str) -> str:
    name = name.strip().lower()
    name = re.sub(r"[^a-z0-9]+", "-", name)
    name = re.sub(r"-+", "-", name).strip("-")
    return name or "sin-nombre"


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_postman_collection(data) -> bool:
    return isinstance(data, dict) and "info" in data and "item" in data


def is_postman_environment(data) -> bool:
    return isinstance(data, dict) and "values" in data and (
        "_postman_variable_scope" in data or "environment" in str(data.get("_postman_exported_at", ""))
    ) or (isinstance(data, dict) and "values" in data and "name" in data and "item" not in data)


def handle_dump_dir(root: Path, out_dir: Path) -> dict:
    """Procesa un dump de Postman ya descomprimido (carpetas collections/ environments/)."""
    stats = {"collections": 0, "environments": 0}

    for sub in ("collections", "environments"):
        src_dir = root / sub
        if not src_dir.is_dir():
            continue
        for jf in src_dir.glob("*.json"):
            try:
                data = json.loads(jf.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            name = None
            if sub == "collections" and is_postman_collection(data):
                name = data["info"].get("name", jf.stem)
                dest = out_dir / "collections" / f"{slugify(name)}.postman_collection.json"
                write_json(dest, data)
                stats["collections"] += 1
            elif sub == "environments":
                name = data.get("name", jf.stem)
                dest = out_dir / "environments" / f"{slugify(name)}.postman_environment.json"
                write_json(dest, data)
                stats["environments"] += 1
    return stats


def base_collection_shell(original_info: dict, folder_name: str) -> dict:
    """Crea el esqueleto de una Collection v2.1 valida a partir de los datos
    de info originales, pero con su propio nombre/_postman_id derivados de la carpeta."""
    schema = original_info.get(
        "schema",
        "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
    )
    return {
        "info": {
            "name": folder_name,
            "schema": schema,
        },
        "item": [],
    }


def split_mega_collection(data: dict, out_dir: Path) -> dict:
    """Divide una unica Postman Collection v2.1 gigante en una coleccion por
    cada carpeta de primer nivel. Las requests sueltas (sin carpeta) quedan
    en una coleccion 'misc'."""
    stats = {"collections": 0, "requests_sueltas": 0}
    top_items = data.get("item", [])

    collection_level_vars = data.get("variable")
    collection_level_auth = data.get("auth")

    misc_requests = []

    for entry in top_items:
        is_folder = isinstance(entry, dict) and "item" in entry and isinstance(entry["item"], list)
        if is_folder:
            folder_name = entry.get("name", "sin-nombre")
            new_collection = base_collection_shell(data.get("info", {}), folder_name)
            new_collection["item"] = entry["item"]
            if "auth" in entry:
                new_collection["auth"] = entry["auth"]
            elif collection_level_auth:
                new_collection["auth"] = collection_level_auth
            if collection_level_vars:
                new_collection["variable"] = collection_level_vars

            dest = out_dir / "collections" / f"{slugify(folder_name)}.postman_collection.json"
            write_json(dest, new_collection)
            stats["collections"] += 1
        else:
            misc_requests.append(entry)
            stats["requests_sueltas"] += 1

    if misc_requests:
        misc_collection = base_collection_shell(data.get("info", {}), "misc-sin-carpeta")
        misc_collection["item"] = misc_requests
        if collection_level_vars:
            misc_collection["variable"] = collection_level_vars
        dest = out_dir / "collections" / "misc-sin-carpeta.postman_collection.json"
        write_json(dest, misc_collection)
        stats["collections"] += 1

    return stats


def handle_archive_json(data: dict, root: Path, out_dir: Path) -> dict:
    """Si el input es el archive.json de un data dump, usamos los ids listados
    para localizar los JSON reales en las carpetas hermanas collections/ environments/."""
    return handle_dump_dir(root, out_dir)


def write_index(out_dir: Path, stats: dict) -> None:
    lines = ["# Indice del backup de Postman dividido", ""]
    lines.append(f"- Colecciones generadas: {stats.get('collections', 0)}")
    if "environments" in stats:
        lines.append(f"- Ambientes generados: {stats.get('environments', 0)}")
    if "requests_sueltas" in stats:
        lines.append(f"- Requests sueltas (sin carpeta, agrupadas en misc): {stats.get('requests_sueltas', 0)}")
    lines.append("")
    lines.append("## Colecciones")
    coll_dir = out_dir / "collections"
    if coll_dir.is_dir():
        for f in sorted(coll_dir.glob("*.json")):
            lines.append(f"- `collections/{f.name}`")
    env_dir = out_dir / "environments"
    if env_dir.is_dir() and any(env_dir.glob("*.json")):
        lines.append("")
        lines.append("## Ambientes")
        for f in sorted(env_dir.glob("*.json")):
            lines.append(f"- `environments/{f.name}`")
    (out_dir / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Divide un backup de Postman en colecciones/ambientes individuales.")
    parser.add_argument("input_path", help="Ruta al .zip, carpeta descomprimida o .json del backup de Postman")
    parser.add_argument("-o", "--output", default="output", help="Carpeta de salida (default: ./output)")
    args = parser.parse_args()

    input_path = Path(args.input_path).expanduser().resolve()
    out_dir = Path(args.output).expanduser().resolve()

    if not input_path.exists():
        print(f"No existe la ruta: {input_path}", file=sys.stderr)
        return 1

    stats = {}

    if input_path.is_dir():
        stats = handle_dump_dir(input_path, out_dir)

    elif input_path.suffix.lower() == ".zip":
        extract_dir = out_dir / "_extracted"
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(input_path) as zf:
            zf.extractall(extract_dir)
        # El zip puede extraerse con una subcarpeta raiz o directo
        candidates = [extract_dir] + [p for p in extract_dir.iterdir() if p.is_dir()]
        found = False
        for cand in candidates:
            if (cand / "collections").is_dir() or (cand / "environments").is_dir():
                stats = handle_dump_dir(cand, out_dir)
                found = True
                break
        if not found:
            print("No se encontraron carpetas 'collections' ni 'environments' dentro del zip.", file=sys.stderr)
            return 1

    elif input_path.suffix.lower() == ".json":
        data = json.loads(input_path.read_text(encoding="utf-8"))
        if is_postman_collection(data):
            stats = split_mega_collection(data, out_dir)
        elif isinstance(data, dict) and ("collections" in data or "environments" in data):
            # Variante de archive.json con listas de metadatos
            stats = handle_archive_json(data, input_path.parent, out_dir)
        else:
            print("El JSON no parece ser ni una Postman Collection v2.1 ni un archive.json reconocible.", file=sys.stderr)
            return 1
    else:
        print("Formato de entrada no soportado. Usa un .zip, una carpeta o un .json.", file=sys.stderr)
        return 1

    write_index(out_dir, stats)
    print(f"Listo. Salida en: {out_dir}")
    print(stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
