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

## Agente de refactor para VS Code (GitHub Copilot)

`.github/agents/postman-refactor.agent.md` define un agente ("custom agent") para GitHub Copilot en VS Code que:

- Detecta valores hardcodeados en las colecciones (`output/collections/**/*.postman_collection.json`) —URLs, tokens, IDs de ambiente— y los convierte en variables.
- Mantiene 3 ambientes: `local`, `desarrollo` y `calidad` (sin producción, por falta de acceso).
- Divide colecciones demasiado grandes (más de 40 requests, más de 6 carpetas de primer nivel, o >1MB) reutilizando `split_postman_backup.py`.

Para usarlo en VS Code: abre el chat de Copilot, selecciona el agente **Postman Refactor** en el dropdown de agentes (o `Chat: Open Customizations` si no aparece listado), y pídele que revise una colección.
