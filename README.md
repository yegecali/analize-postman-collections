# analize-postman-collections

Script para dividir un backup de Postman (generado desde **Settings > Data > Export** en la app de Postman) en colecciones y ambientes individuales, más manejables que un único archivo gigante.

## Formatos de entrada soportados

Postman puede entregar el backup de dos formas, y el script detecta automáticamente cuál es:

1. **Data Dump** (lo más común al usar *Export Data*): un `.zip` que al descomprimirse trae subcarpetas `collections/` y `environments/`, cada una con un JSON por recurso, más un `archive.json` con el índice de IDs.
2. **Un único JSON gigante**: una sola Postman Collection v2.1 (claves `info` + `item`) donde cada carpeta de primer nivel agrupa en la práctica una "colección" distinta. El script separa cada carpeta de primer nivel en su propia colección v2.1 válida, y agrupa las requests sueltas (sin carpeta) en `misc-sin-carpeta.postman_collection.json`.

## Uso

```bash
python3 split_postman_backup.py <ruta_al_backup> [-o output_dir]
```

`<ruta_al_backup>` puede ser:
- un archivo `.zip` (el dump tal cual lo descarga Postman)
- una carpeta ya descomprimida del dump
- un único archivo `.json`

## Salida

```
output/
  collections/<nombre>.postman_collection.json
  environments/<nombre>.postman_environment.json
  index.md
```

Cada colección generada es un JSON válido en formato **Collection v2.1**, importable directamente en Postman.

## Notas

- No se incluyen datos reales de ningún backup en este repositorio; es solo la herramienta.
- Sin dependencias externas, solo la librería estándar de Python 3.
