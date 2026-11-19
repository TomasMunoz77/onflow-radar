"""Radar de Compra Ágil: descarga todas las Compra Ágil publicadas y abiertas
(API v2 de Mercado Público), trae su detalle y escribe radar.json + meta.json.

El detalle se guarda en detalle_cache.json: cada corrida solo pide lo nuevo.
Uso:  MP_TICKET=...  [OUT_DIR=datos]  [MAX_DETALLE=2500]  python radar_compra_agil.py
"""
import json, os, sys, time, unicodedata, urllib.request, urllib.error
from datetime import datetime
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor

CHILE = ZoneInfo("America/Santiago")  # las fechas de la API vienen en hora de Chile

HILOS = 5
HILOS_DETALLE = 8
PAUSA = 0.55
TICKET = os.environ.get("MP_TICKET", "").strip()
if not TICKET:
    sys.exit("Falta la variable de entorno MP_TICKET")
MAX_DETALLE = int(os.environ.get("MAX_DETALLE", "100000"))

BASE = "https://api2.mercadopublico.cl/v2/compra-agil"
DATOS = os.environ.get("OUT_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "datos")
os.makedirs(DATOS, exist_ok=True)
OUT = os.path.join(DATOS, "radar.json")
CACHE = os.path.join(DATOS, "detalle_cache.json")

# Etiquetas de ayuda visual; no filtran nada.
ETIQUETAS = {
    "Plásticos": ["plastic", "bolsa", "desechable", "vaso", "envase", "contenedor", "film", "polietileno", "bidon"],
    "Oficina": ["oficina", "papel", "resma", "carpeta", "lapiz", "archivador", "toner", "tinta", "cartucho", "utiles", "corchete", "sobre", "timbre", "agenda"],
    "Ferretería": ["ferreter", "herramienta", "tornillo", "pintura", "cemento", "candado", "cerradura", "manguera", "pvc", "gasfiter", "brocha", "taladro", "construccion", "madera", "perno", "soldadura", "fierro"],
    "Eléctrico": ["luminaria", "iluminacion", "ampolleta", "foco", "led", "electric", "cable", "enchufe", "alargador", "reflector", "interruptor"],
    "Tecnología": ["computador", "notebook", "impresora", "monitor", "teclado", "mouse", "disco duro", "pendrive", "router", "switch", "proyector", "tablet", "audifono", "camara", "informatic", "cargador", "parlante"],
    "Aseo": ["aseo", "limpieza", "detergente", "cloro", "jabon", "higienico", "toalla", "desinfect", "basura", "escoba", "trapero"],
    "Mobiliario": ["mueble", "silla", "mesa", "estante", "locker", "mobiliario", "kardex", "escritorio"],
    "Seguridad/EPP": ["epp", "zapato de seguridad", "casco", "chaleco", "antiparra", "extintor", "senaletica", "proteccion personal", "guante"],
    "Alimentos": ["alimento", "cafe", "azucar", "galleta", "abarrote", "colacion", "cocina", "loza", "hervidor", "microonda", "agua purificada"],
    "Salud": ["medicamento", "farmac", "reactivo", "laboratorio", "dental", "quirurg", "clinic", "insumos medicos", "jeringa"],
    "Servicio": ["servicio", "arriendo", "mantencion", "reparacion", "capacitacion", "curso", "consultoria", "asesoria", "transporte de", "traslado", "instalacion"],
}


def norm(s):
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


ETQ_N = {k: [norm(x) for x in v] for k, v in ETIQUETAS.items()}


def etiquetar(texto):
    t = norm(texto)
    return [k for k, kws in ETQ_N.items() if any(x in t for x in kws)]


def get(url, intentos=4):
    for i in range(intentos):
        req = urllib.request.Request(url, headers={"ticket": TICKET, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(20 * (i + 1)); continue
            if e.code == 404 or i == intentos - 1:
                raise
        except Exception:
            if i == intentos - 1:
                raise
        time.sleep(3 * (i + 1))


def recorta(s, n):
    s = (s or "").strip()
    return s if len(s) <= n else s[:n].rstrip() + "…"


def escribir(abiertas, cache, listado, ahora):
    salida, regiones = [], {}
    for cod, base in abiertas.items():
        det = cache.get(cod) or {}
        prods = [{k: v for k, v in {
            "nombre": x.get("nombre"), "descripcion": recorta(x.get("descripcion"), 140),
            "cantidad": x.get("cantidad"), "unidad": x.get("unidad"), "unspsc": x.get("unspsc"),
        }.items() if v not in (None, "")} for x in (det.get("productos") or [])[:25]]
        texto = base.get("nombre", "") + " " + " ".join((x.get("nombre") or "") for x in prods)
        inst = base.get("institucion") or {}
        if inst.get("region") is not None:
            regiones[str(inst["region"])] = inst.get("nombre_region")
        o = {
            "codigo": cod,
            "nombre": base.get("nombre"),
            "descripcion": recorta(det.get("descripcion"), 350),
            "rubros": etiquetar(texto),
            "organismo": inst.get("organismo_comprador"),
            "unidad": inst.get("unidad_compra"),
            "rut_organismo": inst.get("rut"),
            "region": inst.get("region"),
            "monto": (base.get("montos") or {}).get("monto_disponible_clp"),
            "tipo_presupuesto": det.get("tipo_presupuesto"),
            "publicacion": base["fechas"].get("fecha_publicacion"),
            "cierre": base["fechas"].get("fecha_cierre"),
            "ofertas": (base.get("resumen") or {}).get("total_ofertas_recibidas"),
            "cotizando": det.get("cotizando"),
            "entrega_direccion": det.get("entrega_direccion"),
            "entrega_dias": det.get("entrega_dias"),
            "documentos": [x.get("nombre") for x in base.get("documentos") or []][:6],
            "productos": prods,
            "con_detalle": cod in cache,
            "req_medioambiental": det.get("req_medioambiental") or None,
        }
        salida.append({k: v for k, v in o.items() if v not in (None, "", [])})
    salida.sort(key=lambda o: o.get("cierre") or "")
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"generado": ahora.strftime("%Y-%m-%d %H:%M"), "total_publicadas": len(listado),
                   "regiones": regiones, "oportunidades": salida}, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(DATOS, "meta.json"), "w", encoding="utf-8") as f:
        json.dump({"generado": ahora.strftime("%Y-%m-%d %H:%M"), "abiertas": len(salida),
                   "con_detalle": sum(1 for o in salida if o.get("con_detalle"))}, f)
    mb = os.path.getsize(OUT) / 1e6
    print(f"OK {len(salida)} oportunidades ({sum(1 for o in salida if o.get('con_detalle'))} con detalle), {mb:.1f} MB -> {OUT}", flush=True)


def main():
    ahora = datetime.now(CHILE).replace(tzinfo=None)

    def pagina_n(n):
        time.sleep(PAUSA)
        return get(f"{BASE}?estado=publicada&tamano_pagina=50&numero_pagina={n}").get("payload") or {}

    p1 = pagina_n(1)
    total_pag = (p1.get("paginacion") or {}).get("total_paginas") or 1
    listado = list(p1.get("items") or [])
    with ThreadPoolExecutor(HILOS) as ex:
        for i, p in enumerate(ex.map(pagina_n, range(2, total_pag + 1)), 2):
            listado += p.get("items") or []
            if i % 25 == 0:
                print(f"pagina {i}/{total_pag}: {len(listado)}", flush=True)

    abiertas = {}
    for it in listado:
        try:
            cierre = datetime.strptime(it["fechas"]["fecha_cierre"], "%Y-%m-%d %H:%M")
        except Exception:
            continue
        if cierre > ahora:
            abiertas[it["codigo"]] = it
    print(f"publicadas {len(listado)} / abiertas {len(abiertas)}", flush=True)

    try:
        with open(CACHE, encoding="utf-8") as f:
            cache = json.load(f)
    except Exception:
        cache = {}
    cache = {k: v for k, v in cache.items() if k in abiertas}  # limpia cerradas
    faltan = sorted((c for c in abiertas if c not in cache),
                    key=lambda c: -((abiertas[c].get("montos") or {}).get("monto_disponible_clp") or 0))[:MAX_DETALLE]
    print(f"detalle en cache {len(cache)} / por pedir {len(faltan)}", flush=True)
    escribir(abiertas, cache, listado, ahora)

    def detalle(cod):
        time.sleep(PAUSA)
        try:
            return cod, (get(f"{BASE}/{cod}") or {}).get("payload") or {}
        except Exception as e:
            return cod, None

    hechos = 0
    with ThreadPoolExecutor(HILOS_DETALLE) as ex:
        for cod, det in ex.map(detalle, faltan):
            hechos += 1
            if det is not None:
                cache[cod] = {
                    "descripcion": recorta(det.get("descripcion"), 500),
                    "productos": [{
                        "nombre": x.get("nombre"),
                        "descripcion": recorta(x.get("descripcion"), 220) if norm(x.get("descripcion")) != norm(x.get("nombre")) else "",
                        "cantidad": x.get("cantidad"), "unidad": x.get("unidad_medida"), "unspsc": x.get("codigo_producto"),
                    } for x in det.get("productos_solicitados") or []][:40],
                    "tipo_presupuesto": (det.get("presupuesto") or {}).get("tipo_presupuesto"),
                    "cotizando": len(det.get("proveedores_cotizando") or []),
                    "entrega_direccion": (det.get("entrega") or {}).get("direccion_entrega"),
                    "entrega_dias": (det.get("entrega") or {}).get("plazo_entrega_dias"),
                    "req_medioambiental": (det.get("flags") or {}).get("considera_requisitos_medioambientales"),
                }
            if hechos % 250 == 0:
                print(f"detalle {hechos}/{len(faltan)}", flush=True)
                with open(CACHE, "w", encoding="utf-8") as f:
                    json.dump(cache, f, ensure_ascii=False)
            if hechos % 1000 == 0:
                escribir(abiertas, cache, listado, ahora)

    os.makedirs(DATOS, exist_ok=True)
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)

    escribir(abiertas, cache, listado, ahora)


if __name__ == "__main__":
    main()
