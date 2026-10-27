# Threat Model — Sentinel-Anubis Forensics Subsystem

**Versión:** 1.0  
**Fecha:** 2026-10-26  
**Autor:** Mariano Bernal (@bernalmariano457)  
**Estado:** Borrador   
**Alcance:** Subsistema forense + capa de radiofrecuencia  

---

## 1. Alcance

### 1.1 Qué cubre este documento

Este threat model cubre el **subsistema forense** de Sentinel-Anubis OS y la **capa de radiofrecuencia**:

- Captura de artefactos (IQ, waterfall, barrido de espectro).
- Integridad (hashing, firma, timestamping).
- Cadena de custodia (`custody.log` encadenado).
- Empaquetado y verificación (`.sae`, `sentinel verify`).
- Análisis básico (clasificación de señales, timeline).
- Reportes (JSON, PDF, exportación geoespacial).

### 1.2 Qué NO cubre (v1.0)

- Wi-Fi y BLE (documento separado: `threats/wifi.md`, futuro).
- Autenticación y gestión de sesiones (documento separado: `threats/auth.md`).
- Seguridad del OS base (Debian / Kali / Termux): responsabilidad del sistema operativo.
- Validez legal por jurisdicción: vive en `LEGAL.md`.
- Hardware comprometido a nivel de firmware (ver Sección 8).

### 1.3 Contexto de uso

| Contexto | Cubierto v1.0 |
|---|---|
| Auditorías internas de seguridad | ✅ Sí |
| Investigación de incidentes | ✅ Sí |
| Operaciones de campo (consultoría, inspectores) | ✅ Sí |
| Peritajes judiciales formales | ⚠️ Parcial — v2.0 |
| Uso educativo / aprendizaje | ➖ No primario |

### 1.4 Jurisdicción

**México** como jurisdicción primaria. `LEGAL.md` cubre LFPDPPP (datos personales) e IFT (espectro radioeléctrico). Multi-jurisdicción es objetivo de v2.0.

### 1.5 Audiencia

Documento interno y para colaboradores técnicos del proyecto. Se endurecerá el lenguaje cuando existan clientes profesionales, auditores externos o peritos como lectores.

---

## 2. Activos

Prioridad: **C** = Confidencialidad, **I** = Integridad, **D** = Disponibilidad.  
Escala: Baja / Media / Alta / Crítica.

### 2.1 Artefactos de evidencia

| Activo | C | I | D | Justificación |
|---|---|---|---|---|
| Captura IQ (SigMF) | Media | **Crítica** | Alta | Evidencia primaria. Su alteración invalida el análisis y el peritaje. |
| Waterfall / espectrograma | Baja | **Alta** | Media | Representación reproducible de la captura; debe coincidir con el IQ. |
| Barrido de espectro (CSV/JSON) | Baja | **Alta** | Media | Base para análisis de interferencias y ocupación. |
| Clasificación de señales | Baja | **Alta** | Baja | Deriva de los artefactos; debe ser reproducible. |
| Timeline unificado | Baja | **Crítica** | Media | Correlación multi-fuente; si se altera, la narrativa del incidente cambia. |

### 2.2 Metadatos

| Activo | C | I | D | Justificación |
|---|---|---|---|---|
| Timestamps de captura | Baja | **Crítica** | Media | Un timestamp manipulado invalida la cronología. |
| Ubicación de captura | **Alta** | Alta | Baja | Puede revelar instalaciones sensibles o ubicación del operador. |
| Parámetros de captura (freq, ganancia, antena) | Baja | **Crítica** | Media | Necesarios para reproducibilidad; su alteración invalida el método. |
| Identidad del operador | Media | Alta | Baja | Atribución legal y responsabilidad. |

### 2.3 Cadena de custodia

| Activo | C | I | D | Justificación |
|---|---|---|---|---|
| `custody.log` | Baja | **Crítica** | **Crítica** | Sin cadena de custodia no hay evidencia defendible. |
| Firmas de entradas de custodia | Baja | **Crítica** | Alta | Garantizan autenticidad y no repudio. |
| Encadenamiento por hash | Baja | **Crítica** | Alta | Detecta manipulación, borrado o reordenamiento. |

### 2.4 Claves criptográficas

| Activo | C | I | D | Justificación |
|---|---|---|---|---|
| Clave privada del operador (Ed25519) | **Crítica** | **Crítica** | Alta | Su compromiso permite firmar evidencia falsa. |
| Clave de firma de releases | **Crítica** | **Crítica** | Alta | Su compromiso permite distribuir binarios maliciosos. |
| Claves públicas de operadores | Baja | **Crítica** | Media | Necesarias para verificación por terceros. |

### 2.5 Dispositivo y almacenamiento

| Activo | C | I | D | Justificación |
|---|---|---|---|---|
| uConsole / dispositivo de campo | Media | Alta | Alta | Robo o pérdida expone evidencia y claves. |
| Almacenamiento (SD / eMMC) | **Alta** | **Crítica** | Alta | Contiene evidencia y claves; cifrado en reposo es requisito. |
| SDR (RTL-SDR) | Baja | Media | Alta | Su compromiso afecta la validez de la captura. |

### 2.6 Reputación del proyecto

| Activo | C | I | D | Justificación |
|---|---|---|---|---|
| Credibilidad técnica del proyecto | N/A | **Crítica** | Alta | Una demostración pública de manipulación de evidencia mata el proyecto. |

---

## 3. Actores y vectores

| ID | Actor | Descripción | Capacidades |
|---|---|---|---|
| A1 | Operador malicioso | Usuario legítimo que quiere falsificar evidencia | Acceso total al dispositivo; conoce el sistema |
| A2 | Operador negligente | Usuario legítimo que comete errores | Acceso total; sin intención maliciosa |
| A3 | Atacante físico | Roba o intercepta el dispositivo en campo | Acceso físico; posible extracción de almacenamiento |
| A4 | Atacante de software | Compromete una dependencia (PyPI, librería SDR, parser) | Ejecución en el dispositivo vía supply chain |
| A5 | Atacante de red | Intercepta transferencia de evidencia | Man-in-the-middle en red |
| A6 | Servicio externo comprometido | NTP falso, API de OUI manipulada, autoridad de timestamp corrupta | Control sobre respuestas externas |
| A7 | Contraparte legal | Cuestiona la validez de la evidencia | No técnico; puede invalidar procedimentalmente |
| A8 | Hardware comprometido | Firmware del SDR o del dispositivo manipulado | Control a nivel de hardware/firmware |

---

## 4. Amenazas identificadas

Categorías: **S**poofing, **T**ampering, **R**epudiation, **I**nfo disclosure, **D**oS, **E**levation, **L**egal admissibility.  
Riesgo = Probabilidad × Impacto (matriz 3×3 simplificada).

| ID | Activo | Actor | Cat. | Amenaza | Prob. | Impacto | Riesgo | Mitigación | Estado |
|---|---|---|---|---|---|---|---|---|---|
| T01 | Captura IQ | A1 | T | Operador modifica IQ después de capturar | Media | Alto | **Alto** | Hash en streaming + firma Ed25519 + custody log encadenado | Mitigada (Fase 1) |
| T02 | Custody log | A1 | T/R | Operador borra o reordena entradas | Media | Alto | **Alto** | Append-only + encadenamiento por `prev_hash` + firma por entrada | Mitigada (Fase 1) |
| T03 | Timestamps | A6 | T | NTP falso altera hora de captura | Media | Alto | **Alto** | Registro de fuente de tiempo + GPS preferente + RFC 3161 opcional | Parcial (Fase 1/3) |
| T04 | Clave privada | A3 | I | Robo del dispositivo expone clave privada | Baja | **Crítico** | **Alto** | `keyring` + passphrase + cifrado en reposo + rotación documentada | Mitigada (Fase 1) |
| T05 | Ubicación | A4/A5 | I | Dependencia o red filtra coordenadas a tercero | Media | Medio | Medio | Offline-first; sin APIs externas por defecto; geolocalización explícita | Mitigada (Fase 3) |
| T06 | Captura IQ | A4 | T | Dependencia comprometida altera archivo al escribir | Baja | Alto | Medio | Hash en streaming + SBOM + `pip-audit` en CI | Parcial (Fase 7) |
| T07 | Manifiesto `.sae` | A2 | L | Operador olvida firmar paquete | Media | Medio | Medio | Firma obligatoria en `pack()` + verificación bloqueante | Mitigada (Fase 1) |
| T08 | Evidencia | A7 | L | Defecto procedural invalida evidencia | Media | **Crítico** | **Alto** | `docs/forensics/methods/` completo + `sentinel verify` reproducible | Pendiente (Fase 6) |
| T09 | Manifiesto | A1 | T | Operador edita manifiesto para ocultar artefacto | Baja | Alto | Medio | Firma del manifiesto + verificación de hashes contra artefactos | Mitigada (Fase 1) |
| T10 | Waterfall | A1 | T | Waterfall no coincide con el IQ capturado | Media | Medio | Medio | Parámetros FFT preservados + hash del PNG + test de determinismo | Mitigada (Fase 2) |
| T11 | Timeline | A1 | T | Eventos eliminados o reordenados en timeline | Baja | Alto | Medio | Timeline derivado de artefactos hasheados + trazabilidad por `artifact_ref` | Mitigada (Fase 4) |
| T12 | Claves | A2 | D | Pérdida de clave privada impide firmar | Media | Medio | Medio | Exportación de clave pública + backup documentado + rotación | Mitigada (Fase 1) |
| T13 | Dispositivo | A3 | I | Robo del dispositivo expone evidencia | Media | **Crítico** | **Alto** | Cifrado en reposo (Fernet/LUKS) + passphrase + bloqueo persistente | Mitigada (Fase 1) |
| T14 | Releases | A4 | S | Binario malicioso distribuido como release oficial | Baja | **Crítico** | **Alto** | Firma de releases (sigstore/GPG) + checksums SHA-256 publicados | Pendiente (Fase 7) |
| T15 | Reportes | A2 | L | Reporte PDF sin hash ni referencia al paquete | Media | Medio | Medio | PDF hasheado e incluido en `.sae` + portada con hash del paquete | Mitigada (Fase 5) |
| T16 | Clasificación | A4 | T | Clasificador manipulado reporta protocolo falso | Baja | Medio | Bajo | Clasificador determinista + tests con IQ sintético + confianza explícita | Aceptada (residual) |
| T17 | Identidad | A1 | R | Operador niega haber capturado un artefacto | Media | Medio | Medio | Firma de cada entrada de custodia con clave del operador | Mitigada (Fase 1) |
| T18 | Espectro | A6 | T | Barrido de espectro alterado para ocultar interferencia | Baja | Alto | Medio | Hash del CSV/JSON + parámetros de barrido en custodia | Mitigada (Fase 2) |

---

## 5. Mitigaciones implementadas

Cada mitigación referencia las amenazas que cubre y cómo se verifica.

| ID | Mitigación | Cubre | Implementación | Verificación |
|---|---|---|---|---|
| M01 | Hash en streaming | T01, T06 | `integrity/hashing.py`: `hash_stream()` durante escritura | Test unitario + test E2E |
| M02 | Firma Ed25519 de artefactos | T01, T09 | `integrity/signing.py`: `sign()` / `verify()` | Test unitario + verificación en `sentinel verify` |
| M03 | Custody log append-only encadenado | T02, T17 | `custody/log.py`: `append()` con `prev_hash` + firma | Test de cadena válida / manipulada / reordenada |
| M04 | Registro de fuente de tiempo | T03 | `integrity/timestamp.py`: GPS → NTP → sistema, con incertidumbre | Test de cada fuente + campo obligatorio en manifiesto |
| M05 | `keyring` + passphrase | T04, T12 | `integrity/keys.py`: nunca clave en archivo plano | Revisión de código + test de rotación |
| M06 | Offline-first para OUI/geo | T05 | `analysis/device_inventory.py`: base local `manuf` | Test sin red + revisión de dependencias |
| M07 | SBOM + `pip-audit` en CI | T06 | `.github/workflows/ci.yml`: `cyclonedx-py` + `pip-audit` | CI bloqueante en cada PR |
| M08 | Firma obligatoria en `pack()` | T07 | `packaging/sae.py`: falla si no hay firma | Test de `pack()` sin clave → error |
| M09 | `docs/forensics/methods/` | T08 | Un documento por módulo con procedimiento reproducible | Revisión manual + checklist por release |
| M10 | Firma del manifiesto | T09 | `packaging/sae.py`: `signature.sig` sobre hash del manifiesto | `sentinel verify` recalcula y valida |
| M11 | Parámetros FFT preservados | T10 | `acquisition/spectrum.py`: PNG + JSON con `fft_size`, `window`, `overlap` | Test de determinismo (mismo input → mismo output) |
| M12 | Trazabilidad timeline | T11 | `analysis/timeline.py`: cada evento con `artifact_ref` + hash | Test de ingestión multi-fuente |
| M13 | Cifrado en reposo | T13 | Almacenamiento cifrado (LUKS o Fernet a nivel de paquete) | Test de acceso sin clave → falla |
| M14 | Firma de releases | T14 | `sigstore` o GPG en tags + checksums publicados | Verificación manual en release checklist |
| M15 | PDF hasheado en `.sae` | T15 | `reporting/pdf_report.py`: hash del PDF incluido en manifiesto | `sentinel verify` incluye PDF |
| M16 | Clasificador determinista | T16 | Reglas + features FFT; sin ML en v1.0 | Test con IQ sintético por protocolo |
| M17 | Parámetros de barrido en custodia | T18 | `acquisition/spectrum_sweep.py`: metadata completa + hash | Test de reproducibilidad |

---

## 6. Riesgos aceptados

Amenazas no mitigadas total o parcialmente, con justificación explícita.

| ID | Amenaza | Decisión | Justificación |
|---|---|---|---|
| R01 | T06 — Dependencia comprometida altera archivo | Aceptado parcialmente | SBOM + `pip-audit` detectan CVEs conocidos, no ataques de día cero. Mitigación total requiere reproducibilidad de builds y atestación, fuera de alcance v1.0. |
| R02 | T16 — Clasificador manipulable | Aceptado | El clasificador es determinista y las reglas son auditables. Un atacante con acceso al código puede alterarlo, pero eso requiere modificar el binario (cubierto por T14 en releases). |
| R03 | Ataques de canal lateral sobre SDR | Aceptado | Fuera de alcance. Requiere laboratorio de análisis electromagnético. |
| R04 | Firmware del SDR manipulado | Aceptado | Asumimos hardware confiable (ver Sección 7). |
| R05 | Operador con root manipula evidencia directamente | Aceptado | Si el operador tiene root, puede modificar el binario, las claves y el custody log. Mitigación requiere atestación de hardware (TPM), fuera de alcance v1.0. Documentado en `LEGAL.md` como limitación. |
| R06 | Pérdida total del dispositivo sin backup | Aceptado | Se documenta procedimiento de backup en `docs/forensics/methods/`. La pérdida de evidencia no respaldada es responsabilidad del operador. |

---

## 7. Supuestos y dependencias externas

### 7.1 Supuestos

1. **El operador es confiable pero falible.** No asumimos intención maliciosa por defecto, pero implementamos defensa en profundidad contra negligencia y contra manipulación oportunista.
2. **El hardware del SDR no está comprometido a nivel de firmware.** Si lo está, la captura puede ser manipulada en origen y ninguna mitigación de software lo detecta.
3. **El sistema operativo base (Debian / Kali / Termux) está actualizado y es confiable.** Sentinel-Anubis no endurece el OS.
4. **El reloj del sistema puede ser impreciso.** Por eso registramos la fuente de tiempo y su incertidumbre en cada artefacto.
5. **El usuario tiene acceso físico al dispositivo.** No asumimos un modelo de servidor remoto.

### 7.2 Dependencias externas

| Dependencia | Uso | Riesgo | Mitigación |
|---|---|---|---|
| FreeTSA (RFC 3161) | Timestamp confiable opcional | Servicio externo; puede caer o ser manipulado | Opcional; se documenta como "no vinculante" en el manifiesto |
| NTP | Sincronización de reloj | NTP falso (T03) | GPS preferente + registro de fuente + incertidumbre |
| `manuf` (base OUI) | Resolución offline de fabricantes | Base desactualizada | Actualización documentada + versión registrada en inventario |
| `pyrtlsdr` | Interfaz con RTL-SDR | Dependencia de terceros | SBOM + `pip-audit` |
| `sigmf` | Formato de metadatos IQ | Dependencia de terceros | SBOM + tests de compatibilidad |
| `cryptography` | Ed25519, Fernet | Dependencia crítica de seguridad | Versión pinneada + `pip-audit` + revisión de CVEs |

---

## 8. Fuera de alcance explícito

Los siguientes temas **no** son cubiertos por este threat model y se declaran como limitaciones conocidas:

- **(A) Compromiso físico con acceso root.** Si un atacante tiene root en el dispositivo, puede manipular evidencia, claves y custody log. Mitigación futura: atestación de hardware (TPM 2.0), fuera de alcance v1.0.
- **(B) Firmware del SDR manipulado.** Asumimos hardware confiable.
- **(C) Ataques de canal lateral** (consumo de energía, emisiones electromagnéticas).
- **(D) Seguridad del OS base.** Responsabilidad de Debian / Kali / Termux.
- **(F) Validez legal por jurisdicción.** Vive en `LEGAL.md`; este documento cubre integridad técnica, no admisibilidad procesal.
- **(G) Wi-Fi y BLE.** Documento separado (`threats/wifi.md`, futuro).
- **(H) Autenticación y sesiones.** Documento separado (`threats/auth.md`, futuro).
- **(I) Flipper Zero.** Excluido del alcance v1.0 por indisponibilidad de hardware.

---

## 9. Revisión y actualización

- **Frecuencia mínima:** una revisión por release mayor (v0.x → v1.0 → v2.0).
- **Triggers de revisión obligatoria:**
  - Cambio de arquitectura del subsistema forense.
  - Adición de un nuevo tipo de artefacto.
  - Adición de una nueva dependencia externa.
  - Descubrimiento de una vulnerabilidad que afecte una mitigación declarada.
  - Cambio de jurisdicción o de contexto de uso.
- **Aprobación:** el autor del proyecto revisa y congela cada versión. Cuando existan colaboradores técnicos, se requiere revisión por al menos uno de ellos.
- **Historial de cambios:** ver `CHANGELOG.md` del repositorio, sección "Threat model".

---

## Apéndice A — Glosario

- **Artefacto:** archivo generado por una captura (IQ, PCAP, waterfall, inventario).
- **Cadena de custodia:** registro append-only de todas las acciones sobre un artefacto, con firmas y encadenamiento por hash.
- **`.sae`:** formato de paquete de evidencia de Sentinel-Anubis (ZIP + manifiesto + custodia + firma).
- **Manifiesto:** JSON versionado que describe el contenido de un paquete y sus hashes.
- **SigMF:** estándar abierto para metadatos de señales IQ.
- **STRIDE:** marco de categorización de amenazas (Spoofing, Tampering, Repudiation, Info disclosure, DoS, Elevation).
- **RFC 3161:** estándar de sellado de tiempo confiable.

