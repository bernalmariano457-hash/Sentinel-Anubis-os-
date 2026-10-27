# Security Policy — Sentinel-Anubis OS

**Versión:** 1.0  
**Última actualización:** 2026-10-26  
**Contacto de seguridad:** bernalmariano457@gmail.com

---

## 1. Compromiso del proyecto

Sentinel-Anubis OS es una herramienta de seguridad ofensiva y forense. Tratamos la seguridad de nuestra propia herramienta con la misma seriedad que esperamos que nuestros usuarios traten la evidencia que capturan.

Este documento describe:

- Qué versiones reciben parches de seguridad.
- Cómo reportar una vulnerabilidad de forma responsable.
- Qué esperamos de un reporte y qué puedes esperar de nosotros.
- Qué está en alcance y qué no.
- Los principios de diseño de seguridad del proyecto.
- Las limitaciones conocidas y aceptadas.

Si encuentras un problema de seguridad, **no abras un issue público**. Sigue el proceso de la Sección 3.

---

## 2. Versiones soportadas

| Versión | Estado | Soporte de seguridad |
|---|---|---|
| `main` (desarrollo) | Activa | ✅ Sí — parches en el día |
| `v0.1.x` (forense) | Activa | ✅ Sí — parches dentro de 14 días |
| `v0.0.x` (pre-forense) | EOL | ❌ No |
| Forks / modificaciones | No oficial | ❌ No |

Solo las versiones publicadas oficialmente en el repositorio reciben soporte. Si usas un fork, eres responsable de aplicar los parches tú mismo.

---

## 3. Cómo reportar una vulnerabilidad

### 3.1 Canal privado (preferido)

Envía un correo a **security@sentinel-anubis.dev** con el asunto:

Si prefieres cifrar el reporte, usa nuestra clave PGP:

- **Fingerprint:** `XXXX XXXX XXXX XXXX XXXX  XXXX XXXX XXXX XXXX XXXX` *(reemplazar con fingerprint real)*
- **Clave pública:** disponible en `docs/security/pgp-key.asc` y en keyservers públicos.

### 3.2 Canal alternativo

Si el correo falla o no recibes respuesta en 5 días hábiles, abre un **Security Advisory privado** en GitHub:

`Security` → `Advisories` → `New draft security advisory`

### 3.3 Qué NO hacer

- ❌ No abras un issue público con detalles de la vulnerabilidad.
- ❌ No publiques un PoC en redes sociales o blogs antes de coordinarlo con nosotros.
- ❌ No explotes la vulnerabilidad contra sistemas de terceros.
- ❌ No accedas a datos que no te pertenecen.

Estas acciones pueden resultar en bloqueo del reporte y, en jurisdicciones aplicables, en acciones legales.

---

## 4. Qué incluir en un reporte

Un buen reporte nos permite reproducir y corregir el problema rápido. Incluye, en lo posible:

1. **Descripción** del problema en lenguaje claro.
2. **Versión afectada** (`git describe --tags` o hash del commit).
3. **Componente afectado** (ej. `forensics/packaging/sae.py`, `integrity/hashing.py`).
4. **Pasos para reproducir** (comandos exactos, hardware, versión de dependencias).
5. **Impacto** que estimas (confidencialidad, integridad, disponibilidad, legal).
6. **PoC** mínimo si es posible (sin datos sensibles reales).
7. **Mitigación sugerida** si la tienes (opcional).
8. **Si quieres crédito público**, nombre o handle (opcional).

Si no tienes todos los datos, envía lo que tengas. Preferimos un reporte incompleto a un reporte que nunca llega.

---

## 5. Nuestro compromiso (qué puedes esperar)

| Etapa | Plazo objetivo |
|---|---|
| Acuse de recibo | 3 días hábiles |
| Evaluación inicial (severidad, alcance) | 7 días hábiles |
| Plan de mitigación comunicado | 14 días hábiles |
| Parche para severidad crítica | 30 días |
| Parche para severidad alta | 60 días |
| Parche para severidad media/baja | 90 días |
| Divulgación pública coordinada | 90 días desde el reporte, o antes si hay acuerdo |

Si el plazo no se puede cumplir, te lo comunicamos antes de que expire y explicamos por qué.

### Severidad

Usamos **CVSS v4.0** como base, ajustada al contexto forense:

- **Crítica:** compromiso de integridad de evidencia, ejecución remota de código, filtración de claves privadas.
- **Alta:** bypass de cadena de custodia, manipulación de artefactos sin detección, elevación de privilegios.
- **Media:** denegación de servicio local, filtración de metadatos no críticos, debilidad criptográfica menor.
- **Baja:** mejores prácticas, hardening, información revelada de bajo impacto.

---

## 6. Alcance

### 6.1 En alcance

- **Subsistema forense:** captura, integridad, custodia, empaquetado, verificación, reportes.
- **Capa RF:** captura IQ, SigMF, waterfall, barrido de espectro, clasificación de señales.
- **Módulos de análisis:** timeline, correlación, inventario.
- **CLI y autenticación:** `sentinel verify`, gestión de claves, bloqueo.
- **Empaquetado `.sae`** y su verificación.
- **Dependencias declaradas** en `pyproject.toml` / `requirements.txt`.
- **Scripts de instalación y despliegue** en `scripts/`.
- **CI/CD** (GitHub Actions) y releases firmadas.

### 6.2 Fuera de alcance

Los siguientes temas **no** se consideran vulnerabilidades del proyecto y no recibirán parche por nuestra parte (ver `docs/forensics/threat-model.md`, Sección 8):

- **Compromiso físico con acceso root** al dispositivo. Si tienes root, puedes manipular el binario, las claves y la evidencia. Mitigación futura: atestación de hardware (TPM 2.0).
- **Firmware del SDR manipulado.** Asumimos hardware confiable.
- **Ataques de canal lateral** (consumo de energía, emisiones electromagnéticas).
- **Vulnerabilidades del OS base** (Debian / Kali / Termux). Repórtalas a su proyecto correspondiente.
- **Validez legal por jurisdicción.** No es un problema técnico; ver `LEGAL.md`.
- **Wi-Fi y BLE.** Documento de seguridad separado (futuro).
- **Flipper Zero.** Excluido del alcance v1.0.
- **Configuraciones inseguras del usuario** (ej. contraseñas débiles, claves en texto plano fuera del sistema).
- **Ataques de ingeniería social** contra el operador.
- **Problemas en herramientas de terceros** que no podamos mitigar en nuestro código (repórtalos upstream y avísanos para documentarlo).

Si tu hallazgo está en esta lista, avísanos igualmente: queremos documentarlo como limitación conocida y, si es grave, reevaluar el alcance.

---

## 7. Principios de diseño de seguridad

Derivados del threat model v1.0 (`docs/forensics/threat-model.md`, Sección 5). Estos son los invariantes que el código debe respetar. Si encuentras código que los viola, es un bug de seguridad.

### 7.1 Integridad de evidencia

- **Todo artefacto se hashea en streaming durante su escritura**, nunca al final. (`integrity/hashing.py`)
- **Todo artefacto se firma con Ed25519** antes de incluirse en un paquete. (`integrity/signing.py`)
- **El `custody.log` es append-only y encadenado por hash.** Cada entrada incluye `prev_hash` y firma del operador. (`custody/log.py`)
- **El manifiesto `.sae` se firma**; su hash y el de cada artefacto son verificables con `sentinel verify`. (`packaging/sae.py`)

### 7.2 Gestión de claves

- **Nunca se almacenan claves privadas en archivos planos.** Se usa `keyring` del sistema. (`integrity/keys.py`)
- **La rotación de claves está documentada** y el custody log permite verificar con claves antiguas. (`docs/forensics/methods/key-rotation.md`)
- **La clave pública es exportable** para verificación por terceros.

### 7.3 Tiempo y ubicación

- **Cada timestamp registra su fuente** (GPS → NTP → sistema) e incertidumbre. (`integrity/timestamp.py`)
- **La geolocalización es explícita y offline-first.** No se consultan APIs externas por defecto. (`analysis/device_inventory.py`)

### 7.4 Aislamiento y degradación

- **Un módulo que falla no tumba el sistema.** El `ModuleRegistry` carga módulos de forma declarativa y aísla fallos.
- **La verificación es un comando de primera clase** (`sentinel verify`), no un script opcional.

### 7.5 Cadena de suministro

- **Dependencias pinneadas** y escaneadas con `pip-audit` en CI. (`.github/workflows/ci.yml`)
- **SBOM generado** en cada release con `cyclonedx-py`.
- **Releases firmadas** con `sigstore` o GPG; checksums SHA-256 publicados. (`docs/release.md`)

### 7.6 Calidad

- **SAST** (`bandit`), **linting** (`ruff`), **tipado estricto** (`mypy`) bloqueantes en CI.
- **Fuzzing** de parsers críticos (SigMF, PCAPNG, manifiesto, custodia) en CI nocturno.
- **Tests de comportamiento** para auth, cifrado, custodia y verificación.

---

## 8. Limitaciones conocidas y aceptadas

Documentadas en `docs/forensics/threat-model.md`, Sección 6. **No son vulnerabilidades**, son decisiones de diseño con justificación.

| ID | Limitación | Impacto | Mitigación futura |
|---|---|---|---|
| R01 | Dependencias comprometidas por ataque de día cero no detectables con SBOM/`pip-audit`. | Medio | Builds reproducibles + atestación (v2.0) |
| R02 | Clasificador de señales determinista pero auditable; un atacante con acceso al código puede alterarlo. | Bajo | Firma de releases cubre distribución (T14) |
| R03 | Ataques de canal lateral sobre el SDR no cubiertos. | Bajo | Fuera de alcance; requiere laboratorio |
| R04 | Firmware del SDR manipulado no detectado. | Alto | Asumimos hardware confiable |
| R05 | Operador con root puede manipular binario, claves y evidencia. | Alto | Atestación de hardware / TPM 2.0 (v2.0) |
| R06 | Pérdida de dispositivo sin backup = pérdida de evidencia. | Medio | Procedimiento de backup documentado |

Si tu hallazgo encaja en esta tabla, avísanos igualmente: queremos saberlo para reevaluar el riesgo.

---

## 9. Divulgación coordinada

Nuestra política:

1. Recibimos el reporte y lo confirmamos.
2. Trabajamos en el parche en el plazo de la Sección 5.
3. Preparamos un **GitHub Security Advisory** con: descripción, severidad, versiones afectadas, versiones parcheadas, mitigación y crédito al reportero (si lo desea).
4. Publicamos el advisory **junto con el release que incluye el parche**, o antes si el riesgo lo justifica.
5. Añadimos el CVE si aplica (solicitamos uno a MITRE o GitHub).
6. Actualizamos el threat model y `CHANGELOG.md` si el hallazgo cambia el modelo de amenazas.

**Crédito:** damos crédito público al reportero en el advisory y en `CHANGELOG.md`, salvo que prefiera el anonimato.

**Embargo:** respetamos un embargo de 90 días desde el reporte, o el plazo acordado por escrito. Si el parche está listo antes, publicamos antes.

---

## 10. Agradecimientos

A las personas que han reportado vulnerabilidades de forma responsable. Lista mantenida en `docs/security/hall-of-fame.md` (se creará cuando exista el primer reporte).

---

## 11. Contacto

- **Seguridad:** bernalmariano457@gmail.com
- **PGP:** `docs/security/pgp-key.asc` 
- **GitHub Security Advisories:** pestaña `Security` del repositorio
- **Discusiones generales (no seguridad):** GitHub Discussions

**No uses los canales públicos para reportar vulnerabilidades.**

---

*Este documento se revisa en cada release mayor. Última revisión: 2026-10-26.*