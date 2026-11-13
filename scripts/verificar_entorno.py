"""Verifica que el entorno (MongoDB replica set + Redis) quedó bien levantado.

Uso: make verificar   (o: python scripts/verificar_entorno.py)
Sale con código 1 si algún paso falla.
"""

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from farmared import config  # noqa: E402
from farmared.db import get_mongo_client, get_mongo_db, get_redis  # noqa: E402


def paso_mongo_conexion() -> str:
    get_mongo_client().admin.command("ping")
    return f"ping OK ({config.MONGO_URI})"


def paso_replica_set() -> str:
    status = get_mongo_client().admin.command("replSetGetStatus")
    primarios = [m["name"] for m in status["members"] if m["stateStr"] == "PRIMARY"]
    if not primarios:
        raise RuntimeError(f"replica set '{status['set']}' sin PRIMARY")
    return f"replica set '{status['set']}' activo, PRIMARY = {primarios[0]}"


def paso_transaccion() -> str:
    client = get_mongo_client()
    db = get_mongo_db()
    nombre = f"_verificacion_tx_{uuid.uuid4().hex[:8]}"
    coll = db.create_collection(nombre)
    try:
        # 1) Transacción confirmada: los dos inserts deben quedar.
        with client.start_session() as s:
            with s.start_transaction():
                coll.insert_one({"n": 1}, session=s)
                coll.insert_one({"n": 2}, session=s)
        if coll.count_documents({}) != 2:
            raise RuntimeError("commit: se esperaban 2 documentos")

        # 2) Transacción abortada: el insert no debe quedar.
        with client.start_session() as s:
            s.start_transaction()
            coll.insert_one({"n": 3}, session=s)
            s.abort_transaction()
        if coll.count_documents({}) != 2:
            raise RuntimeError("abort: el insert no se revirtió")
    finally:
        coll.drop()
    return f"commit y abort OK en '{config.MONGO_DB}.{nombre}' (colección eliminada)"


def paso_redis() -> str:
    r = get_redis()
    r.ping()
    clave = f"verificacion:{uuid.uuid4().hex[:8]}"
    r.set(clave, "ok", ex=30)
    valor = r.get(clave)
    r.delete(clave)
    if valor != "ok":
        raise RuntimeError(f"SET/GET devolvió {valor!r}")
    return f"ping y SET/GET OK ({config.REDIS_URL})"


PASOS = [
    ("MongoDB: conexión", paso_mongo_conexion),
    ("MongoDB: replica set", paso_replica_set),
    ("MongoDB: transacción de prueba", paso_transaccion),
    ("Redis: conexión", paso_redis),
]


def main() -> int:
    fallos = 0
    for nombre, paso in PASOS:
        try:
            print(f"[OK]    {nombre}: {paso()}")
        except Exception as e:  # noqa: BLE001 - queremos reportar cualquier error
            fallos += 1
            print(f"[ERROR] {nombre}: {type(e).__name__}: {e}")
    print()
    print("Entorno OK" if not fallos else f"{fallos} paso(s) fallaron")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
