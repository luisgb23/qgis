# Scripts de análisis GIS y cartografía — ProNutrition

Colección de algoritmos de **QGIS Processing** para automatizar análisis de lotes agropecuarios y generar informes cartográficos en PDF. Los scripts están orientados al trabajo con información territorial de **Uruguay** y se ejecutan desde la caja de herramientas de QGIS.

## Scripts incluidos

| Script | Función principal | Archivos de salida |
|---|---|---|
| [`interseccion_lotes_coneat_pdf(1).py`](interseccion_lotes_coneat_pdf%281%29.py) | Intersección espacial de lotes con polígonos de suelos CONEAT y cálculo de superficies | Shapefile de intersección y PDF cartográfico |
| [`mdt_pendientes_drenaje_pronutrition.py`](mdt_pendientes_drenaje_pronutrition.py) | Procesamiento de MDT, mapa de pendientes y red de drenaje | **Tres PDF independientes**: MDT, pendientes y drenaje |

> **Nota:** Los nombres de archivo corresponden a los scripts adjuntos. Si se renombran en el repositorio, actualizar también los enlaces de esta tabla.

## Requisitos

- **QGIS 3.x** con el proveedor de algoritmos **Processing** habilitado. Los scripts se desarrollaron para el entorno de **QGIS 3.44**; no se garantiza compatibilidad con todas las versiones.
- Python y bibliotecas del entorno de QGIS: **PyQGIS, GDAL/OGR, NumPy y Matplotlib**.
- **SAGA Next Gen** instalado y habilitado en QGIS para ejecutar el algoritmo **Channel Network and Drainage Basins** del informe de drenaje.
- **pypdf** es opcional para ciertas páginas anexas del informe de pendientes; si no está disponible, el script puede omitir ese anexo.
- Datos de entrada apropiados y sistemas de referencia de coordenadas correctos. Para el script MDT se necesita un ráster de elevación en un **CRS proyectado con unidades en metros**.

## Instalación en Windows

### 1. Descargar los scripts

Descargar los archivos `.py` del repositorio (individualmente o mediante **Code → Download ZIP** y descomprimirlos).

### 2. Copiarlos en la carpeta de scripts de QGIS

Guardar ambos archivos `.py` en la siguiente ruta, sustituyendo `--(Usuario local)--` por el nombre del usuario de Windows:

```text
C:\Users\--(Usuario local)--\AppData\Roaming\QGIS\QGIS3\profiles\default\processing\scripts
```

Por ejemplo, si el usuario de Windows es `Usuario`, la ruta será:

```text
C:\Users\Usuario\AppData\Roaming\QGIS\QGIS3\profiles\default\processing\scripts
```

**Acceso rápido:** presionar `Win + R`, pegar la siguiente ruta y pulsar **Enter**:

```text
%APPDATA%\QGIS\QGIS3\profiles\default\processing\scripts
```

Si la carpeta `scripts` no existe, crearla dentro de `processing`. La carpeta `AppData` suele estar oculta en el Explorador de archivos.

> Si se utiliza un perfil distinto de `default`, sustituir `default` por el nombre de ese perfil de QGIS.

### 3. Reiniciar QGIS

**Cerrar QGIS completamente y volver a abrirlo** para que cargue los scripts copiados.

### 4. Ejecutar los algoritmos

1. Abrir **QGIS**.
2. Ir a **Procesos → Caja de herramientas**.
3. Expandir **Scripts** y localizar el grupo **ProNutrition**.
4. Ejecutar el algoritmo deseado:
   - **Lotes x CONEAT + PDF**.
   - **MDT, pendientes y drenaje - tres PDF**.
5. Seleccionar las capas de entrada, completar los parámetros y elegir las rutas de salida.
6. Pulsar **Ejecutar** y revisar la pestaña **Registro** para consultar el resultado o diagnosticar errores.

Si no aparecen, comprobar que los `.py` estén en la carpeta del **perfil activo**, que Processing esté habilitado y que se haya reiniciado QGIS.

## 1. Intersección de lotes con suelos CONEAT

**Archivo:** `interseccion_lotes_coneat_pdf(1).py`  
**Nombre en QGIS:** `Lotes x CONEAT + PDF`

### Entradas

- **Capa de lotes:** polígonos de los lotes a analizar.
- **Mapa de Suelos CONEAT:** capa poligonal con la clasificación de suelos.
- **Campo de suelo CONEAT:** atributo identificador del grupo de suelo; el valor predeterminado es `SC`.
- **Campo de establecimiento/cliente:** opcional.
- **Nombre del establecimiento:** texto alternativo si no se utiliza un campo.
- **Logo:** imagen PNG/JPG opcional para el PDF.
- **Rutas de salida:** Shapefile y PDF.

### Resultados

- **Shapefile:** intersección de lotes y suelos CONEAT, conservando los atributos de los lotes e incorporando el código de suelo.
- **PDF cartográfico A4:** mapa de los suelos, referencias, nombres/códigos, tabla de superficies por lote y grupo CONEAT, escala, orientación y mapa de ubicación en Uruguay. El PDF puede tener varias páginas.

**Recomendación:** revisar que el campo elegido contenga realmente los códigos CONEAT y que las geometrías de las capas sean válidas.

## 2. Modelo Digital del Terreno, pendientes y drenaje

**Archivo:** `mdt_pendientes_drenaje_pronutrition.py`  
**Nombre en QGIS:** `MDT, pendientes y drenaje - tres PDF`

### Entradas

- **Lotes:** capa poligonal de los lotes.
- **Modelo Digital del Terreno:** una o varias hojas **GeoTIFF de elevación**, por ejemplo, descargadas de IDE Uruguay. **No son imágenes NDVI.**
- **Campo con nombre de lote:** atributo que se utilizará para identificar los lotes en mapas y tablas.
- **Nombre del establecimiento:** título de los informes.
- **Logo ProNutrition:** imagen opcional.
- **Tres rutas PDF diferentes:** una para MDT, otra para pendientes y otra para drenaje.
- **Umbral de inicio de canales:** número de celdas empleado en el análisis de SAGA; valor inicial del script: **1.000**. Su elección modifica la densidad de la red de drenaje.

### Resultados

**A. PDF del Modelo Digital del Terreno (MDT)**

- Elevaciones en **metros sobre el nivel del mar (m s.n.m.)**.
- Clasificación en **cinco cuantiles** con rampa **Spectral invertida**.
- Tabla de alturas mínima, máxima y promedio por lote.

**B. PDF del mapa de pendientes**

- Pendiente calculada a partir del MDT, expresada en **porcentaje (%)**.
- Cinco clases fijas: **0–1 %, 1–2 %, 2–3 %, 3–4 % y ≥4 %**.
- Colores de verde a rojo para representar pendientes crecientes.
- Tabla de **pendiente media por lote** (promedio de bloques de **20 × 20 píxeles**) y **superficie en hectáreas**.
- Tabla de **hectáreas por lote y por clase de pendiente**.

**C. PDF de la red de drenaje**

- Cálculo de canales mediante **SAGA Next Gen — Channel Network and Drainage Basins**, usando como entrada el **MDT**.
- Recorte de la **red vectorial de drenaje** por los polígonos de lotes.
- Representación de canales, límites y nombres de lotes.

El script combina las hojas MDT cuando se selecciona más de una y utiliza archivos ráster **temporales** durante el procesamiento; **no entrega GeoTIFF definitivos** como salida.

## Recomendaciones de uso

- Utilizar capas de lotes correctamente georreferenciadas y un MDT que cubra completamente el área de estudio.
- Para drenaje, disponer de MDT alrededor de los lotes: calcular sobre una extensión continua ayuda a evitar efectos artificiales en sus bordes.
- Verificar que las tres rutas PDF sean **distintas** y que los archivos PDF de salida no estén abiertos en otro programa durante la ejecución.
- Comprobar visualmente las salidas y revisar los resultados numéricos antes de usarlos en decisiones técnicas.
- La superficie obtenida mediante conteo de píxeles puede diferir ligeramente de la superficie geométrica del lote, especialmente en los bordes.

## Solución de problemas

| Situación | Qué revisar |
|---|---|
| No aparecen los algoritmos en QGIS | Ruta del perfil activo, extensión `.py`, habilitación de Processing y reinicio de QGIS. |
| SAGA Next Gen no está disponible | Instalación/activación del proveedor y disponibilidad de **Channel Network and Drainage Basins**. |
| El análisis hidrológico no muestra canales | Salidas vectoriales de SAGA (por ejemplo, `SEGMENTS`), umbral de canales y cobertura del MDT. |
| Error al guardar un PDF | Carpeta de destino, permisos y si el PDF está abierto en Adobe Acrobat u otro visor. |
| Error al eliminar archivos temporales en Windows | Verificar si QGIS, GDAL u otro proceso mantiene abierto un TIFF temporal; revisar el **Registro**. |
| No se generan estadísticas válidas | Cobertura del MDT, valores NoData, geometrías de lotes y CRS de las capas. |

## Licencia

No se especifica una licencia en estos archivos. Si el repositorio será público, agregar un archivo `LICENSE` con la licencia elegida antes de indicar condiciones de reutilización.

---

**Proyecto:** ProNutrition — Automatización de análisis GIS y generación de cartografía para establecimientos agropecuarios.
