# Data Model — Sentinel-Anubis Forensics Subsystem

**Versión:** 1.0  
**Fecha:** 2026-10-26  
**Autor:** Mariano Bernal (@bernalmariano457)  
**Estado:** Congelable — base para Fase 1 (integridad y custodia)  
**Deriva de:** `docs/forensics/threat-model.md` v1.0, `SECURITY.md` v1.0  

---

## 1. Propósito

Este documento define las **entidades de datos** del subsistema forense de Sentinel-Anubis OS, sus campos, sus relaciones y los **esquemas JSON versionados** que garantizan:

- **Integridad verificable** de cada artefacto (hash en streaming + firma).
- **Cadena de custodia auditable** (append-only + encadenamiento por hash).
- **Reproducibilidad** de capturas y análisis.
- **Interoperabilidad** con herramientas estándar (SigMF, PCAPNG, JSON Schema).
- **Evolución controlada** del formato (versionado con `schema_version`).

Es el contrato técnico que la Fase 1 implementa. Si el código contradice este documento, el código está mal.

---

## 2. Principios de diseño

| ID | Principio | Justificación |
|---|---|---|
| P01 | **Inmutabilidad de evidencia** | Un artefacto, una vez hasheado y firmado, no se modifica. Las correcciones generan un artefacto nuevo con referencia al anterior. |
| P02 | **Append-only en custodia** | El `custody.log` solo crece. Nunca se edita ni se borra una entrada. |
| P03 | **Encadenamiento por hash** | Cada entrada de custodia incluye el hash de la anterior. Romper la cadena es detectable. |
| P04 | **Versionado explícito** | Todo esquema JSON incluye `schema_version`. Cambios incompatibles → nueva versión. |
| P05 | **Trazabilidad total** | Todo evento del timeline referencia el artefacto que lo originó, con su hash. |
| P06 | **Offline-first** | El modelo no requiere servicios externos. La resolución OUI y la geolocalización son locales. |
| P07 | **Determinismo** | Mismo input + mismos parámetros → mismo output (hashes incluidos, salvo timestamps). |
| P08 | **Separación evidencia/logs** | `workspace/evidence/` es inmutable; `workspace/logs/` es operativo y rotativo. Nunca se mezclan. |

---

## 3. Estructura del workspace

workspace/
├── evidence/ # INMUTABLE — solo append
│ ├── artifacts/ # un directorio por artefacto (id)
│ │ └── <artifact_id>/
│ │ ├── data.bin # contenido original (IQ, pcap, etc.)
│ │ ├── data.sigmf-meta # metadatos SigMF (si aplica)
│ │ ├── manifest.json # manifiesto del artefacto
│ │ └── signature.sig # firma Ed25519 del manifiesto
│ ├── packages/ # paquetes .sae exportados
│ │ └── <package_id>.sae
│ └── custody.log # log append-only encadenado
├── logs/ # OPERATIVO — rotativo, NO evidencia
│ ├── sentinel.log
│ └── errors.log
├── reports/ # reportes generados
│ ├── report.json
│ └── report.pdf
└── config/
├── operation.json # metadatos de la operación
└── operator.pub # clave pública del operador

text

**Regla dura:** nada en `evidence/` se modifica después de escrito. Si un artefacto requiere corrección, se crea un artefacto nuevo con `supersedes: <artifact_id_anterior>` en su manifiesto.

---

## 4. Entidades

### 4.1 Resumen

| Entidad | Propósito | Persistencia | Mutabilidad |
|---|---|---|---|
| `Operation` | Contexto de una sesión de trabajo | `config/operation.json` | Inmutable tras cierre |
| `Artifact` | Unidad de evidencia (IQ, PCAP, waterfall, etc.) | `evidence/artifacts/<id>/` | Inmutable |
| `Manifest` | Descripción versionada de un artefacto | `manifest.json` dentro del artefacto | Inmutable |
| `CustodyEntry` | Acción registrada sobre un artefacto | `evidence/custody.log` | Append-only |
| `EvidencePackage` | Empaquetado `.sae` de uno o más artefactos | `evidence/packages/<id>.sae` | Inmutable |
| `TimelineEvent` | Evento correlacionado en el análisis | Base de datos o JSON derivado | Derivado (recalculable) |
| `Operator` | Identidad del operador y su clave pública | `config/operator.pub` | Rotable con historial |

### 4.2 Relaciones
Operation 1 ──── N Artifact
Artifact 1 ──── 1 Manifest
Artifact 1 ──── N CustodyEntry (vía artifact_id)
Artifact N ──── 1 EvidencePackage (un paquete puede incluir varios artefactos)
Artifact 1 ──── N TimelineEvent (vía artifact_ref)
Operator 1 ──── N CustodyEntry (vía operator_id)
Operator 1 ──── N Artifact (vía operator_id en el manifiesto)

text

---

## 5. Entidades en detalle

### 5.1 `Operation`

Contexto de una sesión de trabajo. Agrupa artefactos bajo un mismo propósito, operador y ventana temporal.

**Campos:**

| Campo | Tipo | Obligatorio | Descripción |
|---|---|---|---|
| `operation_id` | `string` (UUID v4) | Sí | Identificador único |
| `schema_version` | `string` | Sí | `"1.0"` |
| `name` | `string` | Sí | Nombre legible (ej. "Auditoría RF sitio norte") |
| `description` | `string` | No | Descripción libre |
| `operator_id` | `string` | Sí | FK a `Operator` |
| `started_at` | `string` (ISO 8601 UTC) | Sí | Inicio de la operación |
| `ended_at` | `string` (ISO 8601 UTC) | No | Cierre (null si activa) |
| `time_source` | `enum` | Sí | `gps` / `ntp` / `system` |
| `time_uncertainty_ms` | `integer` | Sí | Incertidumbre del reloj en ms |
| `location` | `object` | No | `{lat, lon, alt_m, source}` |
| `jurisdiction` | `string` | Sí | `"MX"` por defecto |
| `legal_basis` | `string` | Sí | Base legal documentada (contrato, autorización, lab) |
| `device` | `object` | Sí | `{model, serial, os_version}` |
| `tags` | `array[string]` | No | Etiquetas libres |

**Ejemplo:**

```json
{
  "schema_version": "1.0",
  "operation_id": "6f8a2c1e-4b3d-4e9a-9c7f-1a2b3c4d5e6f",
  "name": "Auditoría RF sitio norte",
  "description": "Barrido 100-1000 MHz, 2 horas",
  "operator_id": "op-0001",
  "started_at": "2026-10-26T14:00:00Z",
  "ended_at": null,
  "time_source": "gps",
  "time_uncertainty_ms": 50,
  "location": {"lat": 19.4326, "lon": -99.1332, "alt_m": 2240, "source": "gps"},
  "jurisdiction": "MX",
  "legal_basis": "Contrato de auditoría #2026-042, firmado 2026-10-20",
  "device": {"model": "ClockworkPi uConsole", "serial": "UC-XXXX", "os_version": "Sentinel-Anubis 0.1.0"},
  "tags": ["rf", "audit", "sitio-norte"]
}
5.2 Artifact
Unidad de evidencia. Cada artefacto vive en su propio directorio y es inmutable tras su creación.

Campos del manifiesto del artefacto (manifest.json):

Campo	Tipo	Obligatorio	Descripción
artifact_id	string (UUID v4)	Sí	Identificador único
schema_version	string	Sí	"1.0"
type	enum	Sí	iq / pcap / waterfall / spectrum_sweep / device_inventory / signal_classification
operation_id	string	Sí	FK a Operation
operator_id	string	Sí	FK a Operator
created_at	string (ISO 8601 UTC)	Sí	Timestamp de creación
time_source	enum	Sí	gps / ntp / system
time_uncertainty_ms	integer	Sí	Incertidumbre
location	object	No	Igual que en Operation
file	object	Sí	{name, size_bytes, sha256}
capture_params	object	Sí	Depende del tipo (ver 5.2.1)
hardware	object	Sí	{model, serial, firmware} del SDR/adaptador
annotations	array[object]	No	Anotaciones SigMF-style {start_index, end_index, label, comment}
supersedes	string	No	artifact_id que este artefacto reemplaza
parent_artifact	string	No	artifact_id del que deriva (ej. waterfall deriva de IQ)
signature	object	Sí	{algorithm: "ed25519", value: "<base64>", pubkey_fingerprint: "<hex>"}
5.2.1 capture_params por tipo
iq (SigMF):

json
{
  "center_freq_hz": 1090000000,
  "sample_rate_hz": 2400000,
  "gain_db": 40,
  "antenna": "RX",
  "duration_s": 60.0,
  "format": "cf32_le",
  "sigmf_version": "1.2.0"
}
pcap:

json
{
  "interface": "wlan0",
  "channel": 6,
  "mode": "monitor",
  "duration_s": 300.0,
  "link_type": 127,
  "pcapng_version": "1.0"
}
waterfall:

json
{
  "fft_size": 2048,
  "window": "hann",
  "overlap_pct": 50,
  "n_averages": 10,
  "freq_start_hz": 108000000,
  "freq_end_hz": 110000000,
  "source_artifact_id": "<uuid del IQ>"
}
spectrum_sweep:

json
{
  "freq_start_hz": 100000000,
  "freq_end_hz": 1000000000,
  "step_hz": 100000,
  "dwell_ms": 10,
  "gain_db": 40,
  "duration_s": 120.0
}
device_inventory:

json
{
  "source_artifact_id": "<uuid del pcap>",
  "oui_db_version": "2026-09-01",
  "total_devices": 47
}
signal_classification:

json
{
  "source_artifact_id": "<uuid del IQ>",
  "classifier_version": "0.1.0",
  "protocols_detected": ["adsb", "fm_broadcast"],
  "confidence_threshold": 0.7
}
5.3 CustodyEntry
Cada acción sobre un artefacto (creación, verificación, empaquetado, exportación) genera una entrada en custody.log. El log es append-only y encadenado por hash.

Campos:

Campo	Tipo	Obligatorio	Descripción
entry_id	string (UUID v4)	Sí	Identificador único
schema_version	string	Sí	"1.0"
seq	integer	Sí	Número secuencial (0-indexed)
timestamp	string (ISO 8601 UTC)	Sí	Cuándo ocurrió la acción
time_source	enum	Sí	gps / ntp / system
operator_id	string	Sí	Quién ejecutó la acción
action	enum	Sí	create / verify / pack / unpack / export / sign / rotate_key
artifact_id	string	No	FK al artefacto (null para acciones de paquete)
package_id	string	No	FK al paquete (null para acciones de artefacto)
details	object	No	Metadatos específicos de la acción
prev_hash	string (hex)	Sí	SHA-256 de la entrada anterior ("" si seq=0)
entry_hash	string (hex)	Sí	SHA-256 de esta entrada (sin el campo entry_hash ni signature)
signature	object	Sí	{algorithm: "ed25519", value: "<base64>", pubkey_fingerprint: "<hex>"}
Reglas del encadenamiento:

entry_hash se calcula sobre la serialización canónica de la entrada excluyendo entry_hash y signature.

La serialización canónica es JSON con claves ordenadas alfabéticamente, sin espacios, UTF-8.

prev_hash de la entrada seq=0 es "" (string vacío).

prev_hash de la entrada seq=N es el entry_hash de la entrada seq=N-1.

La verificación (sentinel verify) recalcula entry_hash de cada entrada y comprueba que prev_hash coincida con el entry_hash anterior.

Ejemplo de entrada:

json
{
  "schema_version": "1.0",
  "entry_id": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
  "seq": 0,
  "timestamp": "2026-10-26T14:00:05Z",
  "time_source": "gps",
  "operator_id": "op-0001",
  "action": "create",
  "artifact_id": "6f8a2c1e-4b3d-4e9a-9c7f-1a2b3c4d5e6f",
  "package_id": null,
  "details": {
    "artifact_type": "iq",
    "file_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "size_bytes": 1048576
  },
  "prev_hash": "",
  "entry_hash": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
  "signature": {
    "algorithm": "ed25519",
    "value": "MEUCIQD...base64...",
    "pubkey_fingerprint": "SHA256:abc123..."
  }
}
5.4 Manifest (paquete .sae)
El manifiesto de un paquete .sae describe su contenido completo. Es el documento que sentinel verify valida.

Campos (manifest.json dentro del .sae):

Campo	Tipo	Obligatorio	Descripción
schema_version	string	Sí	"1.0"
package_id	string (UUID v4)	Sí	Identificador del paquete
operation_id	string	Sí	FK a Operation
created_at	string (ISO 8601 UTC)	Sí	Cuándo se creó el paquete
operator_id	string	Sí	Quién empaquetó
artifacts	array[object]	Sí	Lista de artefactos incluidos
artifacts[].artifact_id	string	Sí	FK al artefacto
artifacts[].type	string	Sí	Tipo de artefacto
artifacts[].file_sha256	string	Sí	Hash del archivo dentro del .sae
artifacts[].manifest_sha256	string	Sí	Hash del manifest.json del artefacto
artifacts[].size_bytes	integer	Sí	Tamaño del archivo
custody_log_sha256	string	Sí	Hash del custody.log incluido
custody_entries_count	integer	Sí	Número de entradas del custody log
timeline_sha256	string	No	Hash del timeline (si se incluye)
report_sha256	string	No	Hash del reporte PDF (si se incluye)
signature	object	Sí	Firma del manifiesto (Ed25519)
verification	object	No	Resultado de la verificación al empaquetar
Estructura del .sae (ZIP):


<package_id>.sae
├── manifest.json
├── manifest.sig
├── artifacts/
│   ├── <artifact_id_1>/
│   │   ├── data.bin
│   │   ├── data.sigmf-meta
│   │   ├── manifest.json
│   │   └── signature.sig
│   └── <artifact_id_2>/
│       └── ...
├── custody.log
├── timeline.json          (opcional)
└── report.pdf             (opcional)
Reglas del paquete:

El manifest.json se firma con la clave del operador → manifest.sig.

El hash del manifest.json se incluye en el nombre del paquete (ej. <package_id>-<sha256_prefix>.sae) para detección de corrupción.

sentinel verify <paquete>.sae:

Descomprime en memoria.

Valida manifest.json contra el esquema JSON.

Recalcula custody_log_sha256 y file_sha256 de cada artefacto.

Verifica la firma del manifiesto.

Verifica la cadena de custodia (encadenamiento por hash).

Verifica las firmas de cada artefacto.

Reporta OK o el primer fallo con detalle.

5.5 TimelineEvent
Evento correlacionado en el análisis. Derivado (recalculable) de los artefactos. No es evidencia primaria; es análisis.

Campos:

Campo	Tipo	Obligatorio	Descripción
event_id	string (UUID v4)	Sí	Identificador único
schema_version	string	Sí	"1.0"
timestamp	string (ISO 8601 UTC)	Sí	Cuándo ocurrió el evento
time_uncertainty_ms	integer	Sí	Incertidumbre
source	enum	Sí	rf / wifi / ble / system / manual
type	string	Sí	Tipo de evento (ej. signal_detected, device_seen, artifact_created)
artifact_ref	string	Sí	FK al artefacto que lo originó
artifact_hash	string	Sí	Hash del artefacto (trazabilidad)
description	string	Sí	Descripción legible
location	object	No	Coordenadas si aplica
metadata	object	No	Datos específicos del evento
correlation_id	string	No	Agrupa eventos correlacionados
Ejemplo:

json
{
  "schema_version": "1.0",
  "event_id": "11111111-2222-3333-4444-555555555555",
  "timestamp": "2026-10-26T14:00:30Z",
  "time_uncertainty_ms": 50,
  "source": "rf",
  "type": "signal_detected",
  "artifact_ref": "6f8a2c1e-4b3d-4e9a-9c7f-1a2b3c4d5e6f",
  "artifact_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "description": "Señal ADS-B detectada en 1090 MHz",
  "location": {"lat": 19.4326, "lon": -99.1332, "alt_m": 2240},
  "metadata": {"protocol": "adsb", "confidence": 0.95, "freq_hz": 1090000000},
  "correlation_id": null
}
5.6 Operator
Identidad del operador y su clave pública. La clave privada nunca se almacena en el workspace; vive en keyring del sistema.

Campos (config/operator.pub):

Campo	Tipo	Obligatorio	Descripción
operator_id	string	Sí	Identificador único
display_name	string	Sí	Nombre legible
pubkey	string (base64)	Sí	Clave pública Ed25519
pubkey_fingerprint	string (hex)	Sí	SHA-256 de la clave pública
created_at	string (ISO 8601 UTC)	Sí	Cuándo se generó
rotated_from	string	No	operator_id anterior (si es rotación)
revoked_at	string	No	Cuándo se revocó (si aplica)
Rotación de claves:

La clave vieja se conserva en config/operator.pub.history/<fingerprint>.pub para verificar artefactos antiguos.

Un CustodyEntry con action: "rotate_key" registra el cambio.

Los artefactos nuevos se firman con la clave nueva; los antiguos siguen verificables con la vieja.

6. Esquemas JSON
Todos los esquemas viven en schemas/ y se validan en CI con jsonschema o pydantic.


schemas/
├── operation.v1.json
├── artifact-manifest.v1.json
├── custody-entry.v1.json
├── package-manifest.v1.json
├── timeline-event.v1.json
└── operator.v1.json
Reglas de versionado:

schema_version es obligatorio en toda entidad.

Cambio incompatible (campo removido, tipo cambiado, semántica alterada) → nueva versión mayor (v2).

Cambio compatible (campo nuevo opcional) → misma versión, schema_version menor ("1.1").

sentinel verify valida contra la versión declarada en el manifiesto. Si no soporta esa versión, falla con mensaje claro.

Nunca se rompe la compatibilidad hacia atrás de v1.

7. Serialización canónica
Para que los hashes sean reproducibles, toda serialización sigue estas reglas:

JSON con claves ordenadas alfabéticamente (sort_keys=True en Python).

Sin espacios en blanco (separators=(',', ':')).

UTF-8 sin BOM.

Números en formato canónico (sin +, sin ceros a la izquierda, punto decimal solo si es necesario).

Strings sin escapes innecesarios (ensure_ascii=False).

null explícito para campos opcionales ausentes, no omitidos.

Función de referencia (Python):

python
import json, hashlib

def canonical_json(obj: dict) -> bytes:
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")

def sha256_canonical(obj: dict) -> str:
    return hashlib.sha256(canonical_json(obj)).hexdigest()
Esta función es la única autorizada para calcular hashes de entidades. Cualquier otra implementación es un bug.

8. Reglas de integridad
Regla	Descripción	Verificación
I01	Todo artefacto tiene file.sha256 calculado en streaming durante la escritura	Test: escribir 1GB, hash coincide con sha256sum
I02	Todo manifest.json de artefacto está firmado	sentinel verify falla si falta signature
I03	Toda CustodyEntry está firmada y encadenada	verify_chain() recorre todo el log
I04	El custody.log no se modifica tras escribirse	Permisos de solo-append en el filesystem + verificación de hashes
I05	El manifiesto .sae incluye hashes de todos los artefactos	sentinel verify recalcula y compara
I06	Ningún artefacto se sobrescribe	Si existe artifact_id, create falla
I07	La clave privada nunca toca el filesystem del workspace	Revisión de código + test de que no hay archivos con permisos de clave
9. Migración y compatibilidad
9.1 De schema_version "1.0" a futuro
Cuando se necesite una versión nueva:

Crear schemas/<entidad>.v2.json.

Mantener el validador de v1 en el código.

sentinel verify acepta v1 y v2, pero no versiones desconocidas.

Documentar la migración en docs/forensics/migrations/v1-to-v2.md.

Los artefactos v1 siguen siendo válidos; no se reescriben.

9.2 Compatibilidad con herramientas externas
SigMF: el campo data.sigmf-meta dentro del artefacto IQ es SigMF v1.2.0 estándar. Cualquier herramienta SigMF puede leerlo.

PCAPNG: los archivos .pcapng son estándar. El manifiesto añade metadatos encima, pero el archivo es legible por Wireshark.

GeoJSON/KML: exportación estándar, sin extensiones propietarias en v1.0.

10. Checklist de implementación (Fase 1)
La Fase 1 del roadmap implementa este modelo. Checklist mínima:

□ Módulo integrity/hashing.py con hash_stream() y sha256_canonical().
□ Módulo integrity/keys.py con keyring, generación Ed25519, rotación.
□ Módulo integrity/signing.py con sign() / verify().
□ Módulo integrity/timestamp.py con fuentes GPS/NTP/system.
□ Módulo custody/log.py con append() encadenado y verify_chain().
□ Módulo packaging/sae.py con pack() / unpack() / verify().
□ Esquemas JSON en schemas/ validados en CI.
□ Comando sentinel verify <paquete>.sae con salida legible y exit code.
□ Test E2E: crear artefacto dummy → hashear → firmar → empaquetar → verificar → manipular → verificar que falla.

Apéndice A — Glosario
Artefacto: unidad de evidencia (IQ, PCAP, waterfall, etc.).

Manifiesto: JSON versionado que describe un artefacto o paquete.

.sae: formato de paquete de evidencia de Sentinel-Anubis (ZIP + manifiesto + custodia + firmas).

Custody log: registro append-only de acciones sobre artefactos, encadenado por hash.

Serialización canónica: JSON con claves ordenadas, sin espacios, UTF-8, usado para hashes reproducibles.

schema_version: versión del esquema JSON de una entidad.

Ed25519: algoritmo de firma digital usado para autenticar artefactos y entradas de custodia