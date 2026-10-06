"""El catálogo de nodos del mapa curricular — `docs/ESPEC_catalogo_nodos.md`.

  - `mapa.py`      lee y valida el archivo generado (puro, sin base).
  - `carga.py`     lo guarda en `curriculum_nodes`, todo o nada.
  - `reapuntar.py` pasa las referencias de un nodo fusionado a su vigente.
  - `service.py`   `canonicos`: la ÚNICA función que dice si un id vale.
  - `router.py`    `GET /teachers/curriculo/nodos`, para el selector del profe.
"""
