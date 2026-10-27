# LEGAL.md — Sentinel-Anubis OS

**Versión:** 1.0  
**Fecha:** 2026-10-26  
**Jurisdicción primaria:** Estados Unidos Mexicanos  
**Autor:** Mariano Bernal (@bernalmariano457)  

---

## 1. Propósito de este documento

Este documento establece las condiciones legales de uso, los límites de responsabilidad del autor y las obligaciones que asume cualquier persona que utilice Sentinel-Anubis OS (en adelante, "el Software").

**No es asesoría legal.** Es un documento informativo que describe el contexto regulatorio mexicano aplicable y las responsabilidades del usuario. Si tienes dudas sobre tu situación legal concreta, consulta a un abogado con experiencia en derecho penal informático, telecomunicaciones y protección de datos.

**Al descargar, instalar o utilizar el Software, aceptas los términos de este documento.** Si no estás de acuerdo, no utilices el Software.

---

## 2. Naturaleza del Software

Sentinel-Anubis OS es una **herramienta de seguridad ofensiva y forense** de código abierto. Está diseñada para:

- Auditorías de seguridad autorizadas.
- Investigación de incidentes en entornos controlados.
- Operaciones de campo profesionales (consultoría, inspección, análisis de RF).
- Formación y aprendizaje en seguridad.

El Software **no es un juguete** y **no está destinado al público general**. Su uso requiere conocimientos técnicos y, en muchos casos, **autorización expresa y por escrito** del propietario del sistema, red o espectro que se pretenda analizar.

---

## 3. Uso aceptable

El usuario se compromete a utilizar el Software **únicamente** en los siguientes contextos:

1. **Sistemas y redes propios**, o sobre los que tenga autorización escrita y verificable del propietario.
2. **Auditorías de seguridad contratadas**, con un alcance definido por escrito y firmado por el cliente.
3. **Entornos de laboratorio aislados**, sin conexión a redes de producción ni a infraestructuras críticas.
4. **Investigación académica**, con las aprobaciones institucionales correspondientes.
5. **Análisis de espectro radioeléctrico** dentro de los límites que la legislación mexicana permite (ver Sección 5).

---

## 4. Uso prohibido

Queda **estrictamente prohibido** utilizar el Software para:

- **Interceptar comunicaciones privadas** sin mandato de autoridad judicial competente. El artículo 177 del Código Penal Federal sanciona esta conducta con **seis a doce años de prisión y de trescientos a seiscientos días multa**[reference:0].
- **Acceder sin autorización** a sistemas, equipos o datos informáticos protegidos por mecanismos de seguridad. El artículo 211 bis 1 del Código Penal Federal sanciona esta conducta con prisión y multa[reference:1].
- **Capturar, almacenar o difundir datos personales** de terceros sin base legal o consentimiento, en violación de la LFPDPPP (ver Sección 6).
- **Interferir, dañar o degradar** servicios de comunicaciones, redes o infraestructuras.
- **Operar en el espectro radioeléctrico** sin las concesiones, permisos o autorizaciones que el IFT exija para la transmisión (ver Sección 5).
- **Eludir medidas de seguridad** de sistemas ajenos.
- **Acosar, vigilar o perfilizar** a personas sin su consentimiento.
- **Cualquier actividad delictiva** tipificada en el Código Penal Federal, la Ley Federal de Telecomunicaciones y Radiodifusión, la LFPDPPP o cualquier otra norma aplicable.

---

## 5. Regulación del espectro radioeléctrico (IFT)

El espectro radioeléctrico en México es **propiedad de la Nación** y su uso, aprovechamiento y explotación está regulado por el **Instituto Federal de Telecomunicaciones (IFT)**[reference:2].

### 5.1 Recepción vs. transmisión

- **Recepción pasiva** (escuchar, analizar, capturar señales) es, en general, legal en México, siempre que no implique interceptación de comunicaciones privadas (ver Sección 4) ni vulnere derechos de terceros. Sentinel-Anubis está diseñado para **recepción y análisis**, no para transmisión.
- **Transmisión** (emitir en el espectro) requiere **concesión o autorización del IFT**, salvo en bandas de uso libre y con las condiciones de potencia que la normativa establezca. El Software **no incluye funcionalidad de transmisión** en su alcance v1.0.

### 5.2 Bandas de uso libre

México cuenta con bandas de uso libre (por ejemplo, 2.4 GHz y 5 GHz para Wi-Fi, con límites de potencia). El usuario debe verificar las condiciones específicas de cada banda antes de operar cualquier equipo, incluso en modo recepción, si su actividad pudiera considerarse "uso" del espectro.

### 5.3 Monitoreo del espectro

El IFT opera el **Sistema Nacional de Vigilancia del Espectro Radioeléctrico**[reference:3]. El usuario debe ser consciente de que sus actividades de análisis de RF pueden ser detectadas y, si se consideran infracciones, sancionadas por el IFT.

### 5.4 Advertencia específica para RF

**El análisis de radiofrecuencia no es una actividad exenta de riesgo legal.** Capturar señales en bandas restringidas, analizar comunicaciones de terceros o realizar barridos de espectro sin justificación técnica puede ser interpretado como una conducta sospechosa o, en casos graves, como interceptación. El usuario debe documentar la base legal de su actividad (autorización del cliente, contrato de auditoría, laboratorio aislado) **antes** de operar.

---

## 6. Protección de datos personales (LFPDPPP)

La **Ley Federal de Protección de Datos Personales en Posesión de los Particulares (LFPDPPP)**, vigente desde el 21 de marzo de 2025, regula el tratamiento de datos personales por parte de particulares[reference:4]. La supervisión corresponde a la **Secretaría Anticorrupción y Buen Gobierno** (el INAI desapareció)[reference:5].

### 6.1 ¿Son las MACs, UIDs y ubicaciones datos personales?

Bajo la LFPDPPP, un dato personal es cualquier información concerniente a una persona física identificada o identificable. **Las direcciones MAC, los UIDs de tarjetas NFC/RFID y las coordenadas de geolocalización pueden constituir datos personales** cuando permiten identificar, directa o indirectamente, a una persona (por ejemplo, a través de la vinculación de una MAC con un dispositivo y su propietario).

La LFPDPPP 2025 exige que el tratamiento de datos personales sea **legítimo, controlado e informado**, y que los titulares conserven el control sobre su información[reference:6]. El consentimiento debe ser libre, específico e informado; para datos sensibles, debe ser expreso y por escrito[reference:7].

### 6.2 Implicaciones para el usuario de Sentinel-Anubis

Si tu actividad de captura genera artefactos que contienen MACs, UIDs o ubicaciones de terceros, **puedes estar tratando datos personales** y, por tanto, sujeto a la LFPDPPP. Obligaciones que podrían aplicarte:

- Contar con una **base legal** para el tratamiento (consentimiento, contrato, interés legítimo, obligación legal).
- Informar a los titulares mediante un **aviso de privacidad** cuando corresponda.
- Implementar **medidas de seguridad** para proteger los datos.
- Atender **derechos ARCO** (acceso, rectificación, cancelación, oposición) en los plazos legales (20 días hábiles para respuesta, 15 para ejecución)[reference:8].
- **Limitar la retención** de los datos al tiempo necesario para la finalidad.

**Sanciones:** las multas por incumplimiento pueden llegar hasta **320,000 veces la UMA** y pueden duplicarse si se trata de datos sensibles[reference:9]. El incumplimiento también puede acarrear responsabilidad penal en casos graves.

### 6.3 Recomendación práctica

- **Minimiza la captura de datos personales** siempre que sea posible.
- **Documenta la base legal** de tu actividad antes de capturar.
- **Cifra los artefactos** que contengan datos personales (el cifrado en reposo está implementado en Sentinel-Anubis; ver `SECURITY.md`).
- **Destruye los datos** cuando ya no sean necesarios para la finalidad legítima.
- Si vas a operar como proveedor de servicios para terceros, **formaliza un contrato** que incluya las obligaciones de protección de datos.

---

## 7. Limitación de responsabilidad del autor

### 7.1 Software "tal cual"

Sentinel-Anubis OS se distribuye **"TAL CUAL" ("AS IS")**, sin garantías de ningún tipo, expresas o implícitas, incluyendo, sin limitación, garantías de comerciabilidad, idoneidad para un propósito particular y no infracción.

### 7.2 Sin responsabilidad por uso indebido

**El autor no será responsable, en ningún caso, por daños directos, indirectos, incidentales, especiales, consecuentes o punitivos** derivados del uso o la imposibilidad de uso del Software, incluso si se ha advertido de la posibilidad de tales daños.

Esto incluye, sin limitación:

- Sanciones penales o administrativas impuestas al usuario por uso indebido.
- Demandas civiles de terceros.
- Pérdida de datos, evidencia o reputación.
- Daños a sistemas, redes o infraestructuras.
- Consecuencias legales derivadas de la captura de datos personales sin base legal.

**El usuario asume la totalidad del riesgo legal** derivado de su uso del Software.

### 7.3 Sin relación de agencia

Nada en este documento crea una relación de agencia, sociedad, empleo o empresa conjunta entre el autor y el usuario. El autor no autoriza, respalda ni supervisa el uso que el usuario haga del Software.

---

## 8. Licencia de código abierto

El Software se distribuye bajo la licencia **MIT** (o la licencia que figure en el archivo `LICENSE` del repositorio). Esta licencia permite el uso, copia, modificación y distribución del Software, siempre que se incluya el aviso de copyright y la licencia original.

**La licencia de código abierto no sustituye ni modifica las obligaciones legales descritas en este documento.** Un usuario que modifique o redistribuya el Software sigue sujeto a las leyes aplicables y asume la responsabilidad de sus actos.

---

## 9. Propiedad intelectual

El Software, su código fuente, documentación y materiales asociados son propiedad del autor y de los colaboradores que hayan contribuido, y están protegidos por las leyes de propiedad intelectual aplicables.

"Sentinel-Anubis" y el logotipo asociado (si existe) son marcas del proyecto. Su uso comercial requiere autorización expresa del autor.

---

## 10. Privacidad del propio Software

### 10.1 Offline-first

Sentinel-Anubis OS está diseñado para operar **offline-first**. Por defecto, el Software **no envía datos a servidores del autor ni a terceros**. La geolocalización es explícita y offline (ver `SECURITY.md`, Sección 7.3).

### 10.2 Telemetría

El Software **no incluye telemetría** en su alcance v1.0. Si en el futuro se añade, será **opt-in**, documentada y desactivable.

### 10.3 Datos del usuario

El autor no recopila, almacena ni procesa datos personales de los usuarios del Software. Los datos generados por el uso del Software (artefactos, claves, logs) permanecen en el dispositivo del usuario, bajo su control y responsabilidad.

---

## 11. Divulgación de vulnerabilidades

La política de divulgación de vulnerabilidades se describe en `SECURITY.md`. **No uses los canales públicos para reportar problemas de seguridad.** El autor se compromete a tratar los reportes de forma responsable y coordinada.

---

## 12. Legislación aplicable y jurisdicción

Este documento se rige por las leyes de los **Estados Unidos Mexicanos**. Cualquier controversia derivada de la interpretación o aplicación de este documento se someterá a los tribunales competentes de México, renunciando el usuario a cualquier otro fuero que pudiera corresponderle.

**Advertencia para usuarios fuera de México:** si utilizas el Software desde otra jurisdicción, eres responsable de cumplir con las leyes locales aplicables. El autor no garantiza que el Software cumpla con normativas distintas a las mexicanas.

---

## 13. Modificaciones a este documento

El autor puede actualizar este documento en cualquier momento. La versión vigente estará siempre disponible en el repositorio. El uso continuado del Software después de una modificación constituye aceptación de la nueva versión.

**Historial de cambios:**

| Versión | Fecha | Cambio |
|---|---|---|
| 1.0 | 2026-10-26 | Versión inicial |

---

## 14. Contacto

Para cuestiones legales relacionadas con el Software:

- **Correo:** bernalmariano457@gmail.com
- **Repositorio:** [github.com/bernalmariano457-hash/Sentinel-Anubis-os-](https://github.com/bernalmariano457-hash/Sentinel-Anubis-os-.git)

Para reportes de seguridad, usa el canal descrito en `SECURITY.md`.

---

## Apéndice A — Referencias normativas clave (México)

| Norma | Relevancia para Sentinel-Anubis |
|---|---|
| **Código Penal Federal, Art. 177** | Interceptación de comunicaciones privadas sin orden judicial: 6–12 años de prisión[reference:10] |
| **Código Penal Federal, Art. 211 bis 1** | Acceso ilícito a sistemas informáticos: prisión y multa[reference:11] |
| **LFPDPPP (2025)** | Protección de datos personales; multas de hasta 320,000 UMA[reference:12] |
| **Ley Federal de Telecomunicaciones y Radiodifusión** | Regulación del espectro radioeléctrico; facultades del IFT |
| **Constitución Política, Art. 16** | Derecho a la privacidad de las comunicaciones; requiere orden judicial para intervención[reference:13] |

---

## Apéndice B — Checklist de uso legal

Antes de operar Sentinel-Anubis, verifica:

- [ ] Tengo autorización escrita del propietario del sistema, red o espectro.
- [ ] Mi actividad tiene una base legal documentada (contrato, consentimiento, laboratorio aislado).
- [ ] No voy a interceptar comunicaciones privadas sin orden judicial.
- [ ] Si capturo MACs, UIDs o ubicaciones, tengo base legal para tratar esos datos personales.
- [ ] Cifro los artefactos que contengan datos personales.
- [ ] Destruyo los datos cuando ya no son necesarios.
- [ ] Conozco las bandas de espectro que voy a analizar y sus restricciones.
- [ ] Mi actividad no interfiere con servicios de terceros.
- [ ] Si opero fuera de México, cumplo con la legislación local.

