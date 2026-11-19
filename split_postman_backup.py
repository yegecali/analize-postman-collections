#!/usr/bin/env python3
"""
split_postman_backup.py

Divide un backup de Postman (generado desde Settings -> Data -> Export)
en archivos mas pequenos y organizados: colecciones individuales,
ambientes (environments) y un indice legible.

Postman puede entregar el backup en varias formas distintas segun la
version de la app:

1. "Data Dump" nuevo (apps recientes, Settings > Account > Export Data):
   Un .zip que, al descomprimirlo, trae subcarpetas como:
     collections/<id>.json   (cada una ya es una Collection v2.1 valida)
     environments/<id>.json
     archive.json            (indice con los ids/nombres originales)

2. "Backup.postman_dump.json" (apps viejas, p.ej. 9.x, Settings > Data >
   Export): UN SOLO archivo JSON con claves de primer nivel del tipo:
     { "collections": [...], "environments": [...], "globals": {...},
       "headerPresets": [...] }
   donde "collections" es un arreglo y cada elemento ya es una Postman
   Collection completa (v2.1: tiene "info" + "item").

3. Un unico archivo JSON que es UNA sola Postman Collection v2.1 enorme
   (tiene las llaves "info" e "item" directamente en la raiz), donde cada
   carpeta de primer nivel representa, en la practica, una "coleccion"
   distinta agrupada dentro de una sola mega-coleccion.

Este script detecta automaticamente cual de los casos aplica. Ademas,
para cada coleccion que encuentra (venga del caso 2 o 3), tambien la
divide por carpeta de primer nivel, por si esa coleccion en si misma es
una mega-coleccion. Salida:

    output/
      collections/<nombre-coleccion>.postman_collection.json
      collections/<nombre-coleccion>/<nombre-carpeta>.postman_collection.json
      environments/<nombre-ambiente>.postman_environment.json
      globals.postman_globals.json       (si el backup trae globals)
      header_presets.json                (si el backup trae headerPresets)
      index.md

Uso:
    python3 split_postman_backup.py <ruta_al_backup> [-o output_dir]
    python3 split_postman_backup.py <ruta_al_backup> --inspect

    <ruta_al_backup> puede ser:
      - un archivo .zip (data dump nuevo)
      - un directorio ya descomprimido del data dump nuevo
      - un unico archivo .json (Backup.postman_dump.json o mega-coleccion)

    --inspect imprime solo la forma del JSON (claves de primer nivel,
    tipos, cantidades y nombres) sin escribir nada a disco. Util para
    confirmar el formato real antes de decidir como dividirlo.
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
    stats = {}

    coll_dir = root / "collections"
    if coll_dir.is_dir():
        for jf in coll_dir.glob("*.json"):
            try:
                data = json.loads(jf.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if is_postman_collection(data):
                export_collection(data, out_dir, stats)

    env_dir = root / "environments"
    if env_dir.is_dir():
        for jf in env_dir.glob("*.json"):
            try:
                data = json.loads(jf.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            export_environment(data, out_dir, stats)

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


def split_collection_by_top_folders(collection: dict, dest_subdir: Path) -> int:
    """Divide una Postman Collection v2.1 en una coleccion por cada carpeta
    de primer nivel, escribiendolas dentro de dest_subdir. Las requests
    sueltas (sin carpeta) van a 'misc-sin-carpeta'. Devuelve cuantos
    archivos escribio. Si la coleccion no tiene ninguna carpeta (son todo
    requests sueltas, o esta vacia), no escribe nada."""
    top_items = collection.get("item", [])
    collection_level_vars = collection.get("variable")
    collection_level_auth = collection.get("auth")

    folders = [e for e in top_items if isinstance(e, dict) and isinstance(e.get("item"), list)]
    if not folders:
        return 0

    misc_requests = [e for e in top_items if not (isinstance(e, dict) and isinstance(e.get("item"), list))]

    written = 0
    for entry in folders:
        folder_name = entry.get("name", "sin-nombre")
        new_collection = base_collection_shell(collection.get("info", {}), folder_name)
        new_collection["item"] = entry["item"]
        if "auth" in entry:
            new_collection["auth"] = entry["auth"]
        elif collection_level_auth:
            new_collection["auth"] = collection_level_auth
        if collection_level_vars:
            new_collection["variable"] = collection_level_vars

        dest = dest_subdir / f"{slugify(folder_name)}.postman_collection.json"
        write_json(dest, new_collection)
        written += 1

    if misc_requests:
        misc_collection = base_collection_shell(collection.get("info", {}), "misc-sin-carpeta")
        misc_collection["item"] = misc_requests
        if collection_level_vars:
            misc_collection["variable"] = collection_level_vars
        write_json(dest_subdir / "misc-sin-carpeta.postman_collection.json", misc_collection)
        written += 1

    return written


def collection_name(collection: dict) -> str:
    info = collection.get("info")
    if isinstance(info, dict) and info.get("name"):
        return info["name"]
    return collection.get("name", "sin-nombre")


def is_legacy_flat_collection(data) -> bool:
    """Formato viejo de Postman (p.ej. apps 9.x): la coleccion trae 'folders'
    y 'requests' como listas planas con ids, en vez del arbol anidado 'item'
    de la Collection v2.1."""
    return (
        isinstance(data, dict)
        and "requests" in data
        and "folders" in data
        and "item" not in data
    )


def convert_legacy_headers(headers) -> list:
    """Headers viejos pueden venir como string 'Key: value\\nKey2: value2'
    o ya como lista de {key, value}. Normaliza a la lista v2.1."""
    if isinstance(headers, list):
        out = []
        for h in headers:
            if isinstance(h, dict):
                out.append({
                    "key": h.get("key", h.get("name", "")),
                    "value": h.get("value", ""),
                    "disabled": h.get("disabled", False),
                })
        return out
    if isinstance(headers, str):
        out = []
        for line in headers.splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                out.append({"key": key.strip(), "value": value.strip()})
        return out
    return []


def convert_legacy_url(url) -> dict:
    if isinstance(url, dict):
        raw = url.get("raw", "")
    else:
        raw = url or ""
    return {"raw": raw}


def convert_legacy_body(req: dict) -> dict:
    data_mode = req.get("dataMode")
    if data_mode == "raw":
        return {"mode": "raw", "raw": req.get("rawModeData", req.get("data", ""))}
    if data_mode in ("urlencoded", "params"):
        rows = req.get("data", [])
        values = []
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    values.append({
                        "key": row.get("key", ""),
                        "value": row.get("value", ""),
                        "disabled": not row.get("enabled", True),
                    })
        mode = "urlencoded" if data_mode == "urlencoded" else "formdata"
        return {"mode": mode, mode: values}
    return {}


def convert_legacy_request_item(req: dict) -> dict:
    item = {
        "name": req.get("name", "sin-nombre"),
        "request": {
            "method": req.get("method", "GET"),
            "header": convert_legacy_headers(req.get("headers")),
            "url": convert_legacy_url(req.get("url")),
        },
    }
    body = convert_legacy_body(req)
    if body:
        item["request"]["body"] = body
    if req.get("description"):
        item["request"]["description"] = req["description"]
    if req.get("auth"):
        item["request"]["auth"] = req["auth"]
    return item


def convert_legacy_flat_collection(collection: dict) -> dict:
    """Reconstruye una Collection v2.1 valida (arbol 'item') a partir del
    formato viejo (folders + requests planos con ids)."""
    requests_by_id = {r.get("id"): r for r in collection.get("requests", []) if isinstance(r, dict)}
    folders_by_id = {f.get("id"): f for f in collection.get("folders", []) if isinstance(f, dict)}

    # A que carpeta pertenece cada request: el campo 'folder' en el request
    # (si existe) manda; si no, usamos el 'order' de cada carpeta.
    request_folder = {}
    for fid, folder in folders_by_id.items():
        for rid in folder.get("order", []) or []:
            request_folder.setdefault(rid, fid)
    for rid, req in requests_by_id.items():
        if req.get("folder"):
            request_folder[rid] = req["folder"]

    def build_folder_item(fid: str) -> dict:
        folder = folders_by_id[fid]
        child_ids = folder.get("order", []) or [
            rid for rid, parent in request_folder.items() if parent == fid
        ]
        children = [convert_legacy_request_item(requests_by_id[rid]) for rid in child_ids if rid in requests_by_id]
        return {"name": folder.get("name", "sin-nombre"), "item": children}

    root_order = collection.get("order", []) or []
    folders_order = collection.get("folders_order", []) or list(folders_by_id.keys())

    top_items = []
    seen_folder_ids = set()
    for fid in folders_order:
        if fid in folders_by_id:
            top_items.append(build_folder_item(fid))
            seen_folder_ids.add(fid)

    root_request_ids = [rid for rid in root_order if rid in requests_by_id and rid not in request_folder]
    if not root_request_ids:
        root_request_ids = [rid for rid in requests_by_id if rid not in request_folder]
    for rid in root_request_ids:
        top_items.append(convert_legacy_request_item(requests_by_id[rid]))

    new_collection = {
        "info": {
            "name": collection_name(collection),
            "description": collection.get("description", ""),
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": top_items,
    }
    if collection.get("auth"):
        new_collection["auth"] = collection["auth"]
    if collection.get("variables"):
        new_collection["variable"] = collection["variables"]
    return new_collection


def export_collection(collection: dict, out_dir: Path, stats: dict) -> None:
    """Escribe una coleccion completa en collections/, y ademas, si tiene
    carpetas de primer nivel, la vuelve a dividir dentro de
    collections/<nombre>/ por si en si misma es una mega-coleccion."""
    if is_legacy_flat_collection(collection):
        collection = convert_legacy_flat_collection(collection)
        stats["convertidas_formato_viejo"] = stats.get("convertidas_formato_viejo", 0) + 1

    name = collection_name(collection)
    slug = slugify(name)

    write_json(out_dir / "collections" / f"{slug}.postman_collection.json", collection)
    stats["collections"] = stats.get("collections", 0) + 1

    sub_written = split_collection_by_top_folders(collection, out_dir / "collections" / slug)
    stats["sub_colecciones"] = stats.get("sub_colecciones", 0) + sub_written


def export_environment(env: dict, out_dir: Path, stats: dict) -> None:
    name = env.get("name", "sin-nombre")
    write_json(out_dir / "environments" / f"{slugify(name)}.postman_environment.json", env)
    stats["environments"] = stats.get("environments", 0) + 1


def handle_legacy_single_file_dump(data: dict, out_dir: Path) -> dict:
    """Maneja el formato viejo de Backup.postman_dump.json (apps ~9.x):
    un unico JSON con arreglos 'collections' / 'environments' y,
    opcionalmente, 'globals' / 'headerPresets' en el nivel superior."""
    stats = {}

    for coll in data.get("collections", []) or []:
        if isinstance(coll, dict):
            export_collection(coll, out_dir, stats)

    for env in data.get("environments", []) or []:
        if isinstance(env, dict):
            export_environment(env, out_dir, stats)

    if data.get("globals"):
        write_json(out_dir / "globals.postman_globals.json", data["globals"])
        stats["globals"] = 1

    if data.get("headerPresets"):
        write_json(out_dir / "header_presets.json", data["headerPresets"])
        stats["header_presets"] = len(data["headerPresets"])

    return stats


def write_index(out_dir: Path, stats: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = ["# Indice del backup de Postman dividido", ""]
    if stats.get("convertidas_formato_viejo"):
        lines.append(
            f"- Colecciones convertidas desde el formato viejo (folders+requests planos): {stats['convertidas_formato_viejo']}"
        )
    lines.append(f"- Colecciones generadas: {stats.get('collections', 0)}")
    if stats.get("sub_colecciones"):
        lines.append(f"- Sub-colecciones generadas al dividir por carpeta: {stats.get('sub_colecciones', 0)}")
    if "environments" in stats:
        lines.append(f"- Ambientes generados: {stats.get('environments', 0)}")
    if "globals" in stats:
        lines.append("- Globals exportados: si")
    if "header_presets" in stats:
        lines.append(f"- Header presets exportados: {stats.get('header_presets', 0)}")
    lines.append("")
    lines.append("## Colecciones")
    coll_dir = out_dir / "collections"
    if coll_dir.is_dir():
        for f in sorted(coll_dir.glob("*.json")):
            lines.append(f"- `collections/{f.name}`")
        for sub in sorted(p for p in coll_dir.iterdir() if p.is_dir()):
            lines.append(f"  - carpeta `collections/{sub.name}/` (dividida por carpetas de primer nivel):")
            for f in sorted(sub.glob("*.json")):
                lines.append(f"    - `collections/{sub.name}/{f.name}`")
    env_dir = out_dir / "environments"
    if env_dir.is_dir() and any(env_dir.glob("*.json")):
        lines.append("")
        lines.append("## Ambientes")
        for f in sorted(env_dir.glob("*.json")):
            lines.append(f"- `environments/{f.name}`")
    (out_dir / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def inspect_json(data) -> None:
    """Imprime solo la FORMA del JSON (claves, tipos, cantidades, nombres),
    nunca el contenido completo de las requests. Pensado para correr en la
    maquina donde esta el backup real y pegar la salida aqui, sin exponer
    datos sensibles de las requests (urls, headers, bodies, tokens, etc.)."""
    if not isinstance(data, dict):
        print(f"El JSON raiz no es un objeto, es: {type(data).__name__}")
        return

    print("Claves de primer nivel:")
    for key, value in data.items():
        if isinstance(value, list):
            print(f"  - {key}: lista con {len(value)} elemento(s)")
            if value and isinstance(value[0], dict):
                sample_keys = list(value[0].keys())
                print(f"      claves del primer elemento: {sample_keys}")
                name = value[0].get("name") or value[0].get("info", {}).get("name") if isinstance(value[0].get("info"), dict) else value[0].get("name")
                if name:
                    print(f"      nombre del primer elemento: {name!r}")
        elif isinstance(value, dict):
            print(f"  - {key}: objeto con claves {list(value.keys())}")
        else:
            print(f"  - {key}: {type(value).__name__} = {value!r}"[:120])

    if is_postman_collection(data):
        print("\n=> Esto es directamente UNA Postman Collection v2.1 (raiz con 'info' + 'item').")
        top = data.get("item", [])
        folders = sum(1 for e in top if isinstance(e, dict) and isinstance(e.get("item"), list))
        print(f"   Tiene {len(top)} elemento(s) de primer nivel, de los cuales {folders} son carpetas.")
    elif "collections" in data or "environments" in data:
        print("\n=> Esto parece el formato viejo de Backup.postman_dump.json (collections/environments como arrays).")

        colls = data.get("collections", [])
        if colls and isinstance(colls[0], dict):
            first = colls[0]
            if is_legacy_flat_collection(first):
                print("   Cada coleccion usa el formato PLANO viejo (folders + requests con ids), no 'item' anidado.")
            print(f"\n   Detalle de la primera coleccion ({collection_name(first)!r}):")
            for sub_key in ("folders", "requests"):
                sub_list = first.get(sub_key)
                if isinstance(sub_list, list):
                    print(f"     - {sub_key}: {len(sub_list)} elemento(s)")
                    if sub_list and isinstance(sub_list[0], dict):
                        sample = sub_list[0]
                        print(f"         claves: {list(sample.keys())}")
                        for field in ("url", "headers", "data", "dataMode", "rawModeData", "order", "folder"):
                            if field in sample:
                                print(f"           {field}: tipo {type(sample[field]).__name__}")

        envs = data.get("environments", [])
        if envs and isinstance(envs[0], dict):
            vals = envs[0].get("values")
            if isinstance(vals, list) and vals and isinstance(vals[0], dict):
                print(f"\n   Detalle del primer ambiente ({envs[0].get('name')!r}): values[0] claves = {list(vals[0].keys())}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Divide un backup de Postman en colecciones/ambientes individuales.")
    parser.add_argument("input_path", help="Ruta al .zip, carpeta descomprimida o .json del backup de Postman")
    parser.add_argument("-o", "--output", default="output", help="Carpeta de salida (default: ./output)")
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="No escribe nada: solo imprime la forma del JSON (claves, tipos, cantidades) para confirmar el formato.",
    )
    args = parser.parse_args()

    input_path = Path(args.input_path).expanduser().resolve()
    out_dir = Path(args.output).expanduser().resolve()

    if not input_path.exists():
        print(f"No existe la ruta: {input_path}", file=sys.stderr)
        return 1

    if args.inspect:
        if input_path.suffix.lower() != ".json":
            print("--inspect solo aplica a un archivo .json (no a .zip ni a una carpeta).", file=sys.stderr)
            return 1
        data = json.loads(input_path.read_text(encoding="utf-8"))
        inspect_json(data)
        return 0

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
            stats = {}
            export_collection(data, out_dir, stats)
        elif isinstance(data, dict) and ("collections" in data or "environments" in data):
            # Formato viejo: Backup.postman_dump.json con arrays en el nivel superior
            stats = handle_legacy_single_file_dump(data, out_dir)
        else:
            print(
                "El JSON no parece ser ni una Postman Collection v2.1 ni un Backup.postman_dump.json reconocible. "
                "Corre con --inspect para ver su forma real.",
                file=sys.stderr,
            )
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
