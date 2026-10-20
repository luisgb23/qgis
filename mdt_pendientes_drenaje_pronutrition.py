# -*- coding: utf-8 -*-
"""ProNutrition - MDT, Pendientes e Hidrologia en tres PDF A4 separados. QGIS 3.44 / GDAL.
Instalar desde Procesos > Scripts > Anadir script.
Se requieren GeoTIFF de MODELO DIGITAL DE TERRENO, no imagenes NDVI.
"""
import os
import math
import tempfile
import json
import zlib
import base64
import numpy as np
from osgeo import gdal, ogr, osr
from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (QgsProcessing, QgsProcessingAlgorithm, QgsProcessingException,
    QgsProcessingParameterFeatureSource, QgsProcessingParameterMultipleLayers,
    QgsProcessingParameterString, QgsProcessingParameterFile,
    QgsProcessingParameterFileDestination, QgsProcessingParameterNumber,
    QgsProcessingParameterEnum, QgsProcessingParameterBoolean, QgsProcessingParameterField,
    QgsVectorFileWriter, QgsVectorLayer, QgsProject, QgsCoordinateReferenceSystem,
    QgsCoordinateTransform, QgsGeometry, QgsFeatureRequest)

class MDTYPendientesHidrologiaPDF(QgsProcessingAlgorithm):
    def name(self): return 'mdt_pendientes_drenaje_vectorial_tres_pdf'
    def displayName(self): return 'MDT, pendientes y drenaje - tres PDF'
    def group(self): return 'ProNutrition'
    def groupId(self): return 'pronutrition'
    def createInstance(self): return MDTYPendientesHidrologiaPDF()
    def shortHelpString(self):
        return ('Combina una o varias hojas MDT IDEuy, calcula pendientes porcentuales '
                'sobre el mosaico completo y recorta ambos mapas por lotes. '
                'Genera TRES PDF A4 independientes: MDT en metros (5 cuantiles, Spectral invertida), '
                'y pendientes en porcentaje (0-1, 1-2, 2-3, 3-4, >4; verde a rojo). '
                'El drenaje de SAGA se calcula a partir del mosaico MDT, no del shapefile de lotes; '
                'la red vectorial se recorta geometricamente por los lotes. '
                'Tablas de pendientes: media de bloques 20x20, superficie por lote y hectareas por clase. '
                'No guarda TIFF de salida; utiliza archivos temporales.')
    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource('LOTES','Lotes (poligonos)',[QgsProcessing.TypeVectorPolygon]))
        self.addParameter(QgsProcessingParameterMultipleLayers('MDT','Modelo Digital del Terreno - hojas GeoTIFF (una o varias)',QgsProcessing.TypeRaster))
        self.addParameter(QgsProcessingParameterField('CAMPO_LOTE','Campo con nombre de lote',parentLayerParameterName='LOTES',type=QgsProcessingParameterField.Any))
        self.addParameter(QgsProcessingParameterString('EST','Nombre del establecimiento',defaultValue='Establecimiento'))
        self.addParameter(QgsProcessingParameterFile('LOGO','Logo ProNutrition (opcional)',optional=True,extension=''))
        self.addParameter(QgsProcessingParameterFileDestination('PDF_MDT','PDF Modelo Digital del Terreno','PDF (*.pdf)'))
        self.addParameter(QgsProcessingParameterFileDestination('PDF_PEND','PDF Mapa de Pendientes','PDF (*.pdf)'))
        self.addParameter(QgsProcessingParameterFileDestination('PDF_DRENAJE','PDF Red de drenaje y cuencas','PDF (*.pdf)'))
        self.addParameter(QgsProcessingParameterNumber('UMBRAL','Umbral de inicio de canales (celdas)',type=QgsProcessingParameterNumber.Integer,defaultValue=1000,minValue=1))
    def processAlgorithm(self, p, context, feedback):
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_pdf import PdfPages
        from matplotlib.patches import Rectangle, Polygon
        from matplotlib.colors import ListedColormap, BoundaryNorm
        from matplotlib import colormaps
        import matplotlib.image as mpimg
        src = self.parameterAsSource(p,'LOTES',context)
        layers = self.parameterAsLayerList(p,'MDT',context)
        est = self.parameterAsString(p,'EST',context)
        campo_lote = self.parameterAsString(p,'CAMPO_LOTE',context)
        logo = self.parameterAsFile(p,'LOGO',context)
        out_mdt = self.parameterAsFileOutput(p,'PDF_MDT',context)
        out_pend = self.parameterAsFileOutput(p,'PDF_PEND',context)
        out_drenaje = self.parameterAsFileOutput(p,'PDF_DRENAJE',context)
        umbral = self.parameterAsInt(p,'UMBRAL',context)
        if len({os.path.normcase(os.path.abspath(x)) for x in (out_mdt,out_pend,out_drenaje)}) != 3:
            raise QgsProcessingException('Seleccione tres rutas PDF diferentes.')
        if not src or src.featureCount() == 0: raise QgsProcessingException('La capa de lotes esta vacia.')
        if not layers: raise QgsProcessingException('Seleccione al menos un GeoTIFF MDT.')
        if campo_lote not in src.fields().names(): raise QgsProcessingException('Seleccione el campo que contiene el nombre de los lotes.')
        paths=[]
        for lyr in layers:
            path=lyr.source().split('|')[0]
            if not os.path.isfile(path) or gdal.Open(path) is None:
                raise QgsProcessingException('No se puede leer el raster: '+path)
            ds=gdal.Open(path)
            if ds.RasterCount != 1:
                raise QgsProcessingException('El MDT debe ser un raster de una banda: '+path)
            paths.append(path)
        for ruta in (out_mdt,out_pend,out_drenaje):
            os.makedirs(os.path.dirname(os.path.abspath(ruta)),exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='mdt_pronutrition_', ignore_cleanup_errors=True) as td:
            cut=os.path.join(td,'lotes.gpkg')
            # El origen se transforma automaticamente al CRS del primer MDT por GDAL Warp.
            opt=QgsVectorFileWriter.SaveVectorOptions()
            opt.driverName='GPKG'; opt.layerName='lotes'; opt.fileEncoding='UTF-8'
            # Exportar solo las geometrías efectivamente usadas, desde la fuente de procesamiento.
            from qgis.core import QgsVectorLayer, QgsFeature, QgsFields, QgsWkbTypes, QgsGeometry, QgsCoordinateReferenceSystem
            mem=QgsVectorLayer('MultiPolygon?crs='+src.sourceCrs().authid(),'lotes','memory')
            dp=mem.dataProvider()
            for f in src.getFeatures():
                if f.geometry().isEmpty(): continue
                nf=QgsFeature(mem.fields()); nf.setGeometry(QgsGeometry(f.geometry())); dp.addFeatures([nf])
            mem.updateExtents()
            result=QgsVectorFileWriter.writeAsVectorFormatV3(mem,cut,QgsProject.instance().transformContext(),opt)
            if result[0]!=QgsVectorFileWriter.NoError:
                raise QgsProcessingException('No se pudo exportar mascara de lotes: '+str(result))
            feedback.pushInfo('Creando mosaico MDT continuo de '+str(len(paths))+' hojas...')
            mosaico=os.path.join(td,'mosaico_mdt.tif')
            # Calcular sobre el mosaico sin recortar evita bordes artificiales entre hojas y lotes.
            md=gdal.Warp(mosaico,paths,format='GTiff',dstNodata=-9999.0,
                outputType=gdal.GDT_Float32,
                creationOptions=['COMPRESS=DEFLATE','TILED=YES','PREDICTOR=3'],
                multithread=True,warpOptions=['NUM_THREADS=ALL_CPUS'])
            if md is None: raise QgsProcessingException('No se pudo crear el mosaico MDT.')
            sr=osr.SpatialReference(wkt=md.GetProjection())
            if not sr.IsProjected():
                raise QgsProcessingException('El MDT debe estar en un CRS proyectado con unidades en metros (por ejemplo EPSG:32721).')
            if sr.GetLinearUnits()<=0:
                raise QgsProcessingException('No se pudieron determinar las unidades horizontales del MDT.')
            factor=1.0/sr.GetLinearUnits()  # Convierte unidades del CRS a metros para la derivada.
            md.FlushCache(); md=None
            out_r=os.path.join(td,'pendiente_recortada.tif')
            out_c=os.path.join(td,'pendiente_clases.tif')
            pendiente_completa=os.path.join(td,'pendiente_completa.tif')
            feedback.pushInfo('Calculando pendiente GDAL en porcentaje (Horn), antes del recorte...')
            pend=gdal.DEMProcessing(pendiente_completa,mosaico,'slope',format='GTiff',
                slopeFormat='percent',alg='Horn',computeEdges=True,scale=factor,
                creationOptions=['COMPRESS=DEFLATE','TILED=YES','PREDICTOR=3'])
            if pend is None: raise QgsProcessingException('Fallo el calculo de pendientes GDAL.')
            pend.FlushCache(); pend=None
            feedback.pushInfo('Recortando la pendiente por los lotes...')
            ds=gdal.Warp(out_r,pendiente_completa,format='GTiff',cutlineDSName=cut,
                cropToCutline=True,dstNodata=-9999.0,outputType=gdal.GDT_Float32,
                creationOptions=['COMPRESS=DEFLATE','TILED=YES','PREDICTOR=3'],
                multithread=True,warpOptions=['NUM_THREADS=ALL_CPUS'])
            if ds is None: raise QgsProcessingException('Fallo el recorte de pendientes por lotes.')
            ds.FlushCache(); ds=None
            ds=gdal.Open(out_r)
            b=ds.GetRasterBand(1)
            arr=b.ReadAsArray()
            nd=b.GetNoDataValue()
            mask=np.isfinite(arr)
            if nd is not None: mask &= (arr!=nd)
            if not np.any(mask): raise QgsProcessingException('El MDT no tiene pixeles validos dentro de los lotes.')
            # Cinco intervalos FIJOS de pendiente (%) y no cuantiles.
            # Clase 1: [0,1); 2: [1,2); 3: [2,3); 4: [3,4); 5: >=4.
            edges=np.array([0.,1.,2.,3.,4.,np.inf])
            nreal=5
            classified=np.zeros(arr.shape,dtype=np.uint8)
            classified[mask]=np.searchsorted([1.,2.,3.,4.],arr[mask],side='right').astype(np.uint8)+1
            feedback.pushInfo('Pendiente porcentual: intervalos 0-1, 1-2, 2-3, 3-4, >=4%.')
            # Verde para menor pendiente; rojo para mayor pendiente.
            spectral=colormaps['RdYlGn_r']
            colors=[spectral((i+.5)/5) for i in range(5)]
            cmap=ListedColormap(colors); cmap.set_bad((1,1,1,0))
            gt=ds.GetGeoTransform()
            bounds=[gt[0],gt[0]+gt[1]*ds.RasterXSize,gt[3]+gt[5]*ds.RasterYSize,gt[3]]
            scale=max(1,int(math.ceil(max(arr.shape)/1500)))
            shown=np.ma.masked_where(classified[::scale,::scale]==0,classified[::scale,::scale])
            # Escala automatica: ajustar el establecimiento al area cartografica
            # EXCLUSIVA (por encima de referencias y tablas). Los limites se
            # amplian sin deformar la relacion espacial del MDT.
            # Figura A4: ancho 8.27 pulgadas y alto 11.69 pulgadas.
            MAP_BOX=(.105,.405,.79,.405)  # x, y, ancho, alto en coordenadas de figura
            def limites_mapa_automaticos(b, margen=.075):
                xmin,xmax,ymin,ymax=map(float,b)
                cx=(xmin+xmax)/2.; cy=(ymin+ymax)/2.
                ancho=max(abs(xmax-xmin),1.)*(1.+2.*margen)
                alto=max(abs(ymax-ymin),1.)*(1.+2.*margen)
                proporcion=(MAP_BOX[2]*8.27)/(MAP_BOX[3]*11.69)
                if ancho/alto > proporcion:
                    alto=ancho/proporcion
                else:
                    ancho=alto*proporcion
                return cx-ancho/2.,cx+ancho/2.,cy-alto/2.,cy+alto/2.
            limites_vista=limites_mapa_automaticos(bounds)
            ancho_vista=limites_vista[1]-limites_vista[0]
            feedback.pushInfo('Escala automatica: extension de vista ajustada al panel del mapa, sin invadir leyendas ni tablas.')
            fig=Figure(figsize=(8.27,11.69),facecolor='white')
            # Composicion cartografica como CONEAT: marco exterior,
            # recuadros de ubicacion y titulo arriba, panel inferior separado.
            # No dibujar un segundo marco global que cruce estos recuadros.
            fig.add_artist(Rectangle((.025,.02),.95,.955,fill=False,lw=1.9,transform=fig.transFigure))
            fig.add_artist(Rectangle((.065,.845),.235,.115,fill=False,lw=.85,transform=fig.transFigure))
            fig.add_artist(Rectangle((.34,.855),.61,.105,fill=False,lw=.85,transform=fig.transFigure))
            fig.add_artist(Rectangle((.065,.078),.885,.752,fill=False,lw=.65,transform=fig.transFigure))
            fig.text(.645,.908,'MAPA DE PENDIENTES\n'+est.upper(),ha='center',va='center',color='#237d3b',weight='bold',fontsize=11)
            axi=fig.add_axes([.065,.845,.235,.115]); axi.set_axis_off()
            # Contorno departamental incorporado: funciona sin capas auxiliares.
            axi=fig.add_axes([.065,.845,.235,.115]); axi.set_axis_off()
            departamentos=json.loads(zlib.decompress(base64.b64decode(''.join(UY_DEPTOS_B64.split()))).decode('ascii'))
            for pol in departamentos:
                axi.add_patch(Polygon(pol,closed=True,facecolor='#3aaa35',edgecolor='#222222',lw=.55))
            axi.set_xlim(-58.8,-52.8)
            axi.set_ylim(-35.4,-29.7)
            axi.set_aspect('equal')
            # Ubicacion del establecimiento: centro de la extension de los lotes.
            try:
                from qgis.core import QgsCoordinateTransform
                tr_uy=QgsCoordinateTransform(src.sourceCrs(),QgsCoordinateReferenceSystem('EPSG:4326'),QgsProject.instance())
                ext_lotes=src.sourceExtent()
                centro_uy=tr_uy.transform((ext_lotes.xMinimum()+ext_lotes.xMaximum())/2,
                                           (ext_lotes.yMinimum()+ext_lotes.yMaximum())/2)
                if -58.8 <= centro_uy.x() <= -52.8 and -35.4 <= centro_uy.y() <= -29.7:
                    axi.add_patch(Rectangle((centro_uy.x()-.15,centro_uy.y()-.12),.30,.24,
                                            fill=False,edgecolor='black',lw=1.35))
            except Exception as e:
                feedback.pushInfo('No se pudo marcar la ubicacion en Uruguay: '+str(e))
            ax=fig.add_axes(MAP_BOX); ax.set_aspect('equal'); ax.axis('off')
            ax.imshow(shown,cmap=cmap,vmin=.5,vmax=nreal+.5,extent=bounds,origin='upper',interpolation='nearest')
            # Contornos de lotes con reproyeccion al CRS del MDT.
            from qgis.core import QgsCoordinateTransform
            raster_crs=QgsCoordinateReferenceSystem()
            raster_crs.createFromWkt(ds.GetProjection())
            trans=QgsCoordinateTransform(src.sourceCrs(),raster_crs,QgsProject.instance())
            # Alinear las alturas originales del MDT con la grilla de pendientes.
            # La leyenda y el mapa usan grados, pero la tabla usa metros s.n.m.
            elev_path=os.path.join(td,'mdt_para_estadisticas.tif')
            elev_ds=gdal.Warp(elev_path,mosaico,format='GTiff',
                outputBounds=(bounds[0],bounds[2],bounds[1],bounds[3]),
                width=ds.RasterXSize,height=ds.RasterYSize,
                dstSRS=ds.GetProjection(),resampleAlg='near',
                dstNodata=-9999.0,outputType=gdal.GDT_Float32,
                creationOptions=['COMPRESS=DEFLATE','TILED=YES'])
            if elev_ds is None:
                raise QgsProcessingException('No se pudo alinear el MDT para calcular las alturas por lote.')
            elev_arr=elev_ds.GetRasterBand(1).ReadAsArray()
            elev_nd=elev_ds.GetRasterBand(1).GetNoDataValue()
            elev_mask=np.isfinite(elev_arr) & mask
            if elev_nd is not None: elev_mask &= (elev_arr!=elev_nd)
            if not np.any(elev_mask):
                raise QgsProcessingException('No hay alturas MDT validas dentro de los lotes.')
            # Estadisticas zonales por lote sobre alturas originales del MDT.
            # Se rasteriza cada poligono en una ventana local, sin cargar otra
            # copia completa del raster en memoria.
            from qgis.PyQt.QtCore import QVariant
            estadisticas=[]
            pendientes_por_lote=[]
            hectareas_clase_por_lote=[]
            geotransform=ds.GetGeoTransform()
            inv_gt=gdal.InvGeoTransform(geotransform)
            for feat in src.getFeatures():
                geom=QgsGeometry(feat.geometry())
                if geom.isEmpty(): continue
                try: geom.transform(trans)
                except Exception as e:
                    feedback.pushWarning('No se pudo transformar lote: '+str(e)); continue
                nombre=str(feat[campo_lote]) if feat[campo_lote] is not None else ''
                nombre=nombre.strip() or 'Lote '+str(feat.id())
                superficie_ha=geom.area()/10000.0  # CRS del MDT proyectado en metros
                geoms=geom.asMultiPolygon() if geom.isMultipart() else [geom.asPolygon()]
                for poly in geoms:
                    for ring in poly[:1]:
                        if ring: ax.plot([pt.x() for pt in ring],[pt.y() for pt in ring],color='#262626',lw=.55)
                try:
                    punto=geom.pointOnSurface().asPoint()
                    ax.text(punto.x(),punto.y(),nombre,ha='center',va='center',
                        fontsize=7,weight='bold',color='#111111',zorder=9,
                        path_effects=[__import__('matplotlib.patheffects',fromlist=['withStroke']).withStroke(linewidth=2.5,foreground='white')])
                except Exception: pass
                bb=geom.boundingBox()
                xy=[gdal.ApplyGeoTransform(inv_gt,x,y) for x,y in
                    [(bb.xMinimum(),bb.yMinimum()),(bb.xMaximum(),bb.yMaximum()),
                     (bb.xMinimum(),bb.yMaximum()),(bb.xMaximum(),bb.yMinimum())]]
                x0=max(0,int(math.floor(min(q[0] for q in xy))))
                x1=min(ds.RasterXSize,int(math.ceil(max(q[0] for q in xy))))
                y0=max(0,int(math.floor(min(q[1] for q in xy))))
                y1=min(ds.RasterYSize,int(math.ceil(max(q[1] for q in xy))))
                if x1<=x0 or y1<=y0:
                    estadisticas.append((nombre,None,None,None,0))
                    pendientes_por_lote.append((nombre,None,0,superficie_ha))
                    hectareas_clase_por_lote.append((nombre,[0.0]*5))
                    continue
                local_gt=gdal.ApplyGeoTransform(geotransform,x0,y0)
                local_transform=(local_gt[0],geotransform[1],geotransform[2],
                                 local_gt[1],geotransform[4],geotransform[5])
                mem_ds=gdal.GetDriverByName('MEM').Create('',x1-x0,y1-y0,1,gdal.GDT_Byte)
                mem_ds.SetGeoTransform(local_transform)
                mem_ds.SetProjection(ds.GetProjection())
                ogr_geom=ogr.CreateGeometryFromWkb(bytes(geom.asWkb()))
                ogr_drv=ogr.GetDriverByName('Memory')
                ogr_ds=ogr_drv.CreateDataSource('')
                ogr_layer=ogr_ds.CreateLayer('lote',geom_type=ogr.wkbUnknown)
                ogr_feat=ogr.Feature(ogr_layer.GetLayerDefn())
                ogr_feat.SetGeometry(ogr_geom)
                ogr_layer.CreateFeature(ogr_feat)
                ogr_feat=None
                gdal.RasterizeLayer(mem_ds,[1],ogr_layer,burn_values=[1])
                inside=mem_ds.ReadAsArray().astype(bool)
                sub=elev_arr[y0:y1,x0:x1]
                valid=inside & elev_mask[y0:y1,x0:x1]
                vals=sub[valid]
                # Promediar bloques de 20 x 20 pixeles de pendiente dentro del lote.
                # Cada bloque con al menos un pixel valido aporta una media al promedio del lote.
                local_pend=arr[y0:y1,x0:x1]
                valid_p=inside & mask[y0:y1,x0:x1]
                # Superficie por clase a resolucion nativa del raster de pendiente.
                # Cada pixel valido se asigna a su clase y aporta su area en hectareas.
                # Esto no utiliza los bloques 20x20, reservados para la pendiente media.
                local_clases=classified[y0:y1,x0:x1]
                pixel_ha=abs(geotransform[1]*geotransform[5] - geotransform[2]*geotransform[4])/10000.0
                conteos=np.bincount(local_clases[valid_p],minlength=6)
                hectareas_clase_por_lote.append((nombre,[float(conteos[k])*pixel_ha for k in range(1,6)]))
                promedios_bloque=[]
                for yy in range(0,valid_p.shape[0],20):
                    for xx in range(0,valid_p.shape[1],20):
                        mblock=valid_p[yy:yy+20,xx:xx+20]
                        if mblock.any():
                            block=local_pend[yy:yy+20,xx:xx+20]
                            promedios_bloque.append(float(block[mblock].mean()))
                pendientes_por_lote.append((nombre,float(np.mean(promedios_bloque)) if promedios_bloque else None,len(promedios_bloque),superficie_ha))
                if vals.size:
                    estadisticas.append((nombre,float(vals.min()),float(vals.max()),float(vals.mean()),int(vals.size)))
                else:
                    estadisticas.append((nombre,None,None,None,0))
                mem_ds=None; ogr_ds=None
            if not estadisticas:
                raise QgsProcessingException('No se pudieron calcular estadisticas por lote.')
            feedback.pushInfo('Altura minima, maxima y desnivel por lote (m):')
            for nombre,mi,ma,pro,cuenta in estadisticas:
                feedback.pushInfo(f'{nombre}: altura min={mi}, max={ma}, desnivel={ma-mi if mi is not None and ma is not None else None} m; pixeles={cuenta}')
            ax.set_xlim(limites_vista[0],limites_vista[1]); ax.set_ylim(limites_vista[2],limites_vista[3])
            # Norte dentro del panel del mapa, separado del borde superior.
            fig.text(.855,.785,'N',ha='center',va='center',fontsize=10,weight='bold')
            fig.text(.855,.758,'▲',ha='center',va='center',fontsize=21)
            fig.text(.09,.365,'Pendiente (%)',fontsize=10,weight='bold')
            for i in range(nreal):
                y=.337-i*.020
                if y<.068: break
                fig.add_artist(Rectangle((.09,y),.022,.014,transform=fig.transFigure,facecolor=colors[i],edgecolor='black',lw=.35))
                etiqueta=['0 – 1 %','1 – 2 %','2 – 3 %','3 – 4 %','> 4 %'][i]
                fig.text(.12,y+.003,etiqueta,fontsize=8,va='center')
            # Escala grafica horizontal en metros (independiente de las pendientes en grados).
            if raster_crs.mapUnits()==0:  # metros (QGIS DistanceMeters)
                width=ancho_vista; raw=width*.20
                magnitude=10**math.floor(math.log10(raw))
                unit=min([1,2,5,10],key=lambda z:abs(z*magnitude-raw))*magnitude
                y=.095; w=.79*(unit/width) if width else .20
                w=min(.26,w)
                # Centrar la escala en el espacio entre referencias y logo.
                x=.565-w/2
                for j in range(2):
                    fig.add_artist(Rectangle((x+j*w/2,y),w/2,.011,transform=fig.transFigure,
                        facecolor='black' if j==0 else 'white',edgecolor='black',lw=.6))
                fig.text(x,y+.016,'0',fontsize=8,ha='center')
                fig.text(x+w/2,y+.016,f'{unit/2:g}',fontsize=8,ha='center')
                fig.text(x+w,y+.016,f'{unit:g} m',fontsize=8,ha='center')
            # Tablas compactas a la misma altura: y=0.145..0.225.
            # Titulo y=0.238, por debajo de la ultima clase de leyenda (y=0.257).
            # Logo y=0.080..0.132, completamente por debajo de ambas tablas.
            # Tabla de pendientes por lote: promedio de bloques de 20x20 px y superficie geometrica (ha).
            def fmt_num(valor):
                return '—' if valor is None else f'{valor:.2f}'.replace('.',',')
            resumen=[(nm,fmt_num(media),fmt_num(ha)) for nm,media,nbloques,ha in pendientes_por_lote]
            # Total: media ponderada por cantidad de bloques validos; superficie sumada en ha.
            bloques_totales=sum(c for _,_,c,_ in pendientes_por_lote)
            media_total=(sum(media*c for _,media,c,_ in pendientes_por_lote if media is not None)/bloques_totales) if bloques_totales else None
            resumen.append(('Total',fmt_num(media_total),fmt_num(sum(ha for _,_,_,ha in pendientes_por_lote))))
            visible=resumen if len(resumen)<=6 else resumen[:5]+[('Ver anexo','—','—')]
            ax_tab=fig.add_axes([.555,.145,.345,.080]); ax_tab.axis('off')
            tabla=ax_tab.table(cellText=[list(r) for r in visible],
                colLabels=['Lote','Pend. media (%)','Superficie (ha)'],
                cellLoc='center',loc='center',bbox=[0,0,1,1],colWidths=[.42,.30,.28])
            tabla.auto_set_font_size(False); tabla.set_fontsize(5.2)
            for (rr,cc),celda in tabla.get_celld().items():
                celda.set_linewidth(.3); celda.set_edgecolor('#9a9a9a')
                if rr==0: celda.set_facecolor('#b4e2a3'); celda.set_text_props(weight='bold')
                elif rr%2==0: celda.set_facecolor('#eff7eb')
                if rr>0 and visible[rr-1][0]=='Total':
                    celda.set_facecolor('#b4e2a3'); celda.set_text_props(weight='bold')
            # Segunda tabla a la izquierda, debajo de la leyenda: hectareas por clase y lote.
            # Los intervalos son [0,1), [1,2), [2,3), [3,4), [4,infinito).
            totales_clase=[sum(areas[k] for _,areas in hectareas_clase_por_lote) for k in range(5)]
            tabla_clases=[(nm, *[fmt_num(v) for v in areas]) for nm,areas in hectareas_clase_por_lote]
            tabla_clases.append(('Total',*[fmt_num(v) for v in totales_clase]))
            # Hasta 5 lotes en la primera pagina; los restantes aparecen en un anexo.
            visibles_clases=tabla_clases if len(tabla_clases)<=6 else tabla_clases[:5]+[('Ver anexo',*(['—']*5))]
            fig.text(.09,.238,'Superficie por clase de pendiente (ha)',fontsize=6.2,weight='bold')
            ax_clases=fig.add_axes([.09,.145,.345,.080]); ax_clases.axis('off')
            t_clases=ax_clases.table(cellText=[list(r) for r in visibles_clases],
                colLabels=['Lote','0–1 %','1–2 %','2–3 %','3–4 %','>4 %'],
                cellLoc='center',loc='center',bbox=[0,0,1,1],
                colWidths=[.32,.136,.136,.136,.136,.136])
            t_clases.auto_set_font_size(False); t_clases.set_fontsize(4.1)
            for (rr,cc),celda in t_clases.get_celld().items():
                celda.set_linewidth(.3); celda.set_edgecolor('#9a9a9a')
                if rr==0 or (rr>0 and visibles_clases[rr-1][0]=='Total'):
                    celda.set_facecolor('#b4e2a3'); celda.set_text_props(weight='bold')
                elif rr%2==0: celda.set_facecolor('#eff7eb')
            if logo and os.path.isfile(logo):
                try:
                    ax_logo=fig.add_axes([.80,.080,.105,.052]); ax_logo.imshow(mpimg.imread(logo)); ax_logo.axis('off')
                except Exception: pass
            fig.text(.5,.068,'Fuente: MDT IDE Uruguay | Pendiente GDAL (%) | Intervalos fijos | RdYlGn invertida',ha='center',fontsize=7,color='#555555')
            # Segundo mapa: MDT (primera pagina), misma composicion cartografica.
            # Los limites de las cinco clases se obtienen por cuantiles del MDT.
            elev_vals=elev_arr[elev_mask]
            elev_edges=np.quantile(elev_vals,np.linspace(0,1,6))
            if len(np.unique(elev_edges))<6:
                feedback.pushWarning('El MDT tiene cuantiles repetidos; algunas clases pueden estar vacias.')
            elev_cls=np.zeros(elev_arr.shape,dtype=np.uint8)
            elev_cls[elev_mask]=np.searchsorted(elev_edges[1:-1],elev_arr[elev_mask],side='right').astype(np.uint8)+1
            elev_colors=[colormaps['Spectral_r']((i+.5)/5) for i in range(5)]
            elev_cmap=ListedColormap(elev_colors); elev_cmap.set_bad((1,1,1,0))
            mdt_fig=Figure(figsize=(8.27,11.69),facecolor='white')
            for box,linewidth in [((.025,.02),1.9),((.065,.845),.85),((.34,.855),.85),((.065,.078),.65)]:
                x,y=box
                w,h={.025:(.95,.955),.065:(.235,.115),.34:(.61,.105)}.get(x,(.885,.752))
                if x==.065 and y==.078: w,h=.885,.752
                mdt_fig.add_artist(Rectangle((x,y),w,h,fill=False,lw=linewidth,transform=mdt_fig.transFigure))
            mdt_fig.text(.645,.908,'MODELO DIGITAL DEL TERRENO\n'+est.upper(),ha='center',va='center',color='#237d3b',weight='bold',fontsize=11)
            uy_ax=mdt_fig.add_axes([.065,.845,.235,.115]); uy_ax.set_axis_off()
            for pol in departamentos:
                uy_ax.add_patch(Polygon(pol,closed=True,facecolor='#3aaa35',edgecolor='#222222',lw=.55))
            uy_ax.set_xlim(-58.8,-52.8); uy_ax.set_ylim(-35.4,-29.7); uy_ax.set_aspect('equal')
            try:
                if -58.8 <= centro_uy.x() <= -52.8 and -35.4 <= centro_uy.y() <= -29.7:
                    uy_ax.add_patch(Rectangle((centro_uy.x()-.15,centro_uy.y()-.12),.30,.24,fill=False,edgecolor='black',lw=1.35))
            except Exception: pass
            elev_ax=mdt_fig.add_axes(MAP_BOX); elev_ax.set_aspect('equal'); elev_ax.axis('off')
            elev_show=np.ma.masked_where(elev_cls[::scale,::scale]==0,elev_cls[::scale,::scale])
            elev_ax.imshow(elev_show,cmap=elev_cmap,vmin=.5,vmax=5.5,extent=bounds,origin='upper',interpolation='nearest')
            from matplotlib import patheffects as pe
            for feat in src.getFeatures():
                geom=QgsGeometry(feat.geometry())
                if geom.isEmpty(): continue
                try: geom.transform(trans)
                except Exception: continue
                polys=geom.asMultiPolygon() if geom.isMultipart() else [geom.asPolygon()]
                for poly in polys:
                    for ring in poly[:1]:
                        if ring: elev_ax.plot([pt.x() for pt in ring],[pt.y() for pt in ring],color='#262626',lw=.55)
                try:
                    point=geom.pointOnSurface().asPoint()
                    elev_ax.text(point.x(),point.y(),str(feat[campo_lote]),ha='center',va='center',fontsize=7,weight='bold',color='#111111',path_effects=[pe.withStroke(linewidth=2.5,foreground='white')])
                except Exception: pass
            elev_ax.set_xlim(limites_vista[0],limites_vista[1]); elev_ax.set_ylim(limites_vista[2],limites_vista[3])
            mdt_fig.text(.855,.785,'N',ha='center',va='center',fontsize=10,weight='bold')
            mdt_fig.text(.855,.758,'▲',ha='center',va='center',fontsize=21)
            mdt_fig.text(.09,.365,'Altura m s.n.m.',fontsize=10,weight='bold')
            for i in range(5):
                y=.337-i*.020
                mdt_fig.add_artist(Rectangle((.09,y),.022,.014,transform=mdt_fig.transFigure,facecolor=elev_colors[i],edgecolor='black',lw=.35))
                mdt_fig.text(.12,y+.003,f'{elev_edges[i]:.1f} – {elev_edges[i+1]:.1f} m',fontsize=8,va='center')
            if raster_crs.mapUnits()==0:
                width=ancho_vista; raw=width*.20
                magnitude=10**math.floor(math.log10(raw))
                unit=min([1,2,5,10],key=lambda z:abs(z*magnitude-raw))*magnitude
                y=.095; w=min(.26,.79*(unit/width) if width else .20); x=.565-w/2
                for j in range(2):
                    mdt_fig.add_artist(Rectangle((x+j*w/2,y),w/2,.011,transform=mdt_fig.transFigure,facecolor='black' if j==0 else 'white',edgecolor='black',lw=.6))
                for xp,label in [(x,'0'),(x+w/2,f'{unit/2:g}'),(x+w,f'{unit:g} m')]:
                    mdt_fig.text(xp,y+.016,label,fontsize=8,ha='center')
            def fmt_m(v): return '—' if v is None else f'{v:.2f}'.replace('.',',')
            tabla_mdt=[(nm,fmt_m(mi),fmt_m(ma),fmt_m(media)) for nm,mi,ma,media,_ in estadisticas]
            tabla_mdt.append(('Total',fmt_m(float(elev_vals.min())),fmt_m(float(elev_vals.max())),fmt_m(float(elev_vals.mean()))))
            visible_mdt=tabla_mdt if len(tabla_mdt)<=6 else tabla_mdt[:5]+[('Ver anexo','—','—','—')]
            mdt_tab=mdt_fig.add_axes([.09,.145,.47,.095]); mdt_tab.axis('off')
            t=mdt_tab.table(cellText=[list(r) for r in visible_mdt],colLabels=['Lote','Mín. (m)','Máx. (m)','Prom. (m)'],cellLoc='center',loc='center',bbox=[0,0,1,1],colWidths=[.37,.21,.21,.21])
            t.auto_set_font_size(False);t.set_fontsize(6.4)
            for (rr,cc),cell in t.get_celld().items():
                cell.set_linewidth(.3);cell.set_edgecolor('#9a9a9a')
                if rr==0 or (rr>0 and visible_mdt[rr-1][0]=='Total'):
                    cell.set_facecolor('#b4e2a3');cell.set_text_props(weight='bold')
                elif rr%2==0: cell.set_facecolor('#eff7eb')
            if logo and os.path.isfile(logo):
                try:
                    la=mdt_fig.add_axes([.77,.085,.14,.075]);la.imshow(mpimg.imread(logo));la.axis('off')
                except Exception: pass
            mdt_fig.text(.5,.068,'Fuente: MDT IDE Uruguay | Cuantiles | Spectral invertida',ha='center',fontsize=7,color='#555555')
            # Cada informe contiene exclusivamente su mapa y, si corresponde, sus anexos.
            def guardar_informe(destino, figura, titulo, headers, filas, nombre_temporal):
                temporal=os.path.join(td,nombre_temporal)
                with PdfPages(temporal) as pdf:
                    pdf.savefig(figura)
                    if len(filas)>6:
                        for ini in range(0,len(filas),28):
                            bloque=filas[ini:ini+28]
                            pagina=Figure(figsize=(8.27,11.69),facecolor='white')
                            pagina.add_artist(Rectangle((.045,.045),.91,.91,fill=False,lw=1.4,transform=pagina.transFigure))
                            pagina.text(.5,.92,titulo,ha='center',fontsize=13,color='#237d3b',weight='bold')
                            pagina.text(.5,.885,est.upper(),ha='center',fontsize=10)
                            ax_p=pagina.add_axes([.10,.12,.80,.73]); ax_p.axis('off')
                            alto=min(1,(len(bloque)+1)*.032)
                            tab=ax_p.table(cellText=[list(r) for r in bloque],colLabels=headers,
                                cellLoc='center',loc='upper center',bbox=[0,1-alto,1,alto])
                            tab.auto_set_font_size(False); tab.set_fontsize(8)
                            for (rr,cc),cell in tab.get_celld().items():
                                cell.set_linewidth(.4); cell.set_edgecolor('#a0a0a0')
                                if rr==0: cell.set_facecolor('#b4e2a3'); cell.set_text_props(weight='bold')
                                elif rr%2==0: cell.set_facecolor('#eff7eb')
                            pdf.savefig(pagina)
                try:
                    os.replace(temporal,destino)
                except PermissionError:
                    raise QgsProcessingException('No se puede reemplazar el PDF: '+destino+'. Cierre el archivo en Acrobat y reintente.')
            guardar_informe(out_mdt,mdt_fig,'ALTURAS POR LOTE (m)',
                ['Lote','Mín. (m)','Máx. (m)','Prom. (m)'],tabla_mdt,'mdt.pdf')
            # Si la tabla por clase supera el espacio disponible, se agrega
            # un anexo al PDF de pendientes, sin crear archivos adicionales.
            guardar_informe(out_pend,fig,'PENDIENTE MEDIA POR LOTE (%)',
                ['Lote','Pend. media (%)','Superficie (ha)'],resumen,'pendientes.pdf')
            if len(tabla_clases)>6:
                from matplotlib.backends.backend_pdf import PdfPages as _PdfPages
                # Reescribir el PDF incorporando la pagina de detalle antes de publicarlo.
                # Se conserva el PDF original y se agregan paginas con PyPDF2 si esta disponible.
                try:
                    from pypdf import PdfReader, PdfWriter
                    detalle=os.path.join(td,'detalle_clases.pdf')
                    with _PdfPages(detalle) as pdf_det:
                        for inicio in range(0,len(tabla_clases),24):
                            grupo=tabla_clases[inicio:inicio+24]
                            pagina=Figure(figsize=(8.27,11.69),facecolor='white')
                            pagina.add_artist(Rectangle((.045,.045),.91,.91,fill=False,lw=1.4,transform=pagina.transFigure))
                            pagina.text(.5,.92,'SUPERFICIE POR CLASE DE PENDIENTE (ha)',ha='center',fontsize=12,color='#237d3b',weight='bold')
                            pagina.text(.5,.885,est.upper(),ha='center',fontsize=10)
                            ax_d=pagina.add_axes([.07,.13,.86,.72]);ax_d.axis('off')
                            alto=min(1,(len(grupo)+1)*.04)
                            t=ax_d.table(cellText=[list(r) for r in grupo],colLabels=['Lote','0–1 %','1–2 %','2–3 %','3–4 %','>4 %'],cellLoc='center',loc='upper center',bbox=[0,1-alto,1,alto])
                            t.auto_set_font_size(False);t.set_fontsize(7)
                            for (rr,cc),cell in t.get_celld().items():
                                cell.set_linewidth(.4);cell.set_edgecolor('#999999')
                                if rr==0 or (rr>0 and grupo[rr-1][0]=='Total'):
                                    cell.set_facecolor('#b4e2a3');cell.set_text_props(weight='bold')
                                elif rr%2==0:cell.set_facecolor('#eff7eb')
                            pdf_det.savefig(pagina)
                    reader=PdfReader(out_pend); extra=PdfReader(detalle);writer=PdfWriter()
                    for page in reader.pages:writer.add_page(page)
                    for page in extra.pages:writer.add_page(page)
                    nuevo=os.path.join(td,'pendientes_completo.pdf')
                    with open(nuevo,'wb') as fp:writer.write(fp)
                    os.replace(nuevo,out_pend)
                except ImportError:
                    feedback.pushWarning('No se pudo agregar anexo de clases: falta pypdf. La tabla principal se mantiene en el PDF.')
            # Tercer informe: SAGA Next Gen Channel Network and Drainage Basins.
            # Ejecutar sobre mosaico completo, no sobre lotes recortados.
            import processing
            from qgis.core import QgsApplication, QgsRasterLayer
            algs = [a for a in QgsApplication.processingRegistry().algorithms()
                    if 'channel network and drainage basins' in a.displayName().lower()
                    and 'saga' in a.provider().id().lower()]
            if not algs:
                raise QgsProcessingException(
                    'No se encuentra Channel Network and Drainage Basins de SAGA Next Gen. '
                    'Instale/active SAGA Next Gen y verifique que el algoritmo aparezca en Procesos.')
            saga_alg = algs[0]
            feedback.pushInfo('Ejecutando SAGA Next Gen: ' + saga_alg.id())
            parametros = {x.name().upper(): x for x in saga_alg.parameterDefinitions()}
            entradas = {}
            # Nombres estandar de la herramienta SAGA; se consulta el proveedor en tiempo de ejecucion.
            for key in ('ELEVATION','DEM','GRID'):
                if key in parametros:
                    entradas[parametros[key].name()] = mosaico
                    break
            else:
                raise QgsProcessingException('No se reconocio el parametro de elevacion de SAGA: '
                                             + ', '.join(parametros))
            for key in ('THRESHOLD',):
                if key in parametros: entradas[parametros[key].name()] = umbral
            # Dejar que el proveedor elija el formato apropiado (grid o vector).
            from qgis.core import QgsProcessingParameterRasterDestination, QgsProcessingParameterVectorDestination
            for definition in saga_alg.parameterDefinitions():
                if isinstance(definition,(QgsProcessingParameterRasterDestination,QgsProcessingParameterVectorDestination)):
                    entradas[definition.name()] = 'TEMPORARY_OUTPUT'
            try:
                resultado_saga = processing.run(saga_alg.id(),entradas,context=context,feedback=feedback)
            except Exception as exc:
                raise QgsProcessingException('SAGA no pudo calcular la red y cuencas: '+str(exc)+
                    '. Revise los parametros disponibles de '+saga_alg.id())
            feedback.pushInfo('Salidas de SAGA: '+str(resultado_saga))
            # Priorizar la red vectorial de SAGA (SHAPES): es la salida que
            # corresponde al recorte vectorial mostrado en QGIS.
            def es_linea(geom):
                if geom is None: return False
                return ogr.GT_Flatten(geom.GetGeometryType()) in (ogr.wkbLineString, ogr.wkbMultiLineString)
            # SAGA Next Gen entrega las lineas en SEGMENTS (no en SHAPES).
            # Inspeccionar todas las salidas vectoriales, priorizando SEGMENTS.
            canales_vector = None
            candidatos = sorted(resultado_saga.items(),
                key=lambda kv: (0 if kv[0].upper() == 'SEGMENTS' else
                                1 if 'SEGMENT' in kv[0].upper() else
                                2 if 'CHANNEL' in kv[0].upper() else 3))
            diagnostico = []
            for key, value in candidatos:
                if not isinstance(value, str):
                    continue
                if not os.path.isfile(value):
                    diagnostico.append(str(key)+': archivo no encontrado')
                    continue
                # Abrir con OGR y verificar que sean lineas reales.
                v = ogr.Open(value, 0)
                if v is None:
                    continue  # salida raster u otro formato
                try:
                    if v.GetLayerCount() < 1:
                        continue
                    lyr = v.GetLayer(0)
                    tipo = ogr.GT_Flatten(lyr.GetGeomType())
                    # Algunas capas declaran geometria desconocida; mirar una entidad.
                    if tipo in (ogr.wkbUnknown, ogr.wkbGeometryCollection):
                        first = lyr.GetNextFeature()
                        if first is not None and first.GetGeometryRef() is not None:
                            tipo = ogr.GT_Flatten(first.GetGeometryRef().GetGeometryType())
                        lyr.ResetReading()
                    diagnostico.append('{}: tipo={}, entidades={}'.format(key,tipo,lyr.GetFeatureCount()))
                    if tipo in (ogr.wkbLineString, ogr.wkbMultiLineString):
                        canales_vector = value
                        break
                finally:
                    lyr = None
                    v = None
            if not canales_vector:
                raise QgsProcessingException(
                    'SAGA no genero una salida vectorial de lineas reconocible. '
                    'Diagnostico: '+ '; '.join(diagnostico) +
                    '. Salidas: '+str(resultado_saga))
            feedback.pushInfo('Red vectorial de canales: '+str(canales_vector))
            # Recortar geometricamente las lineas por los lotes, no solamente
            # limitar el dibujo a su extension. Ambos se llevan al CRS del MDT.
            dst_sr = osr.SpatialReference(wkt=ds.GetProjection())
            red = ogr.Open(canales_vector)
            red_lyr = red.GetLayer(0)
            red_sr = red_lyr.GetSpatialRef()
            tx_red = (osr.CoordinateTransformation(red_sr, dst_sr)
                      if red_sr is not None and not red_sr.IsSame(dst_sr) else None)
            lotes_ogr = []
            for feat in src.getFeatures():
                g = QgsGeometry(feat.geometry())
                if g.isEmpty(): continue
                try: g.transform(trans)
                except Exception: continue
                og = ogr.CreateGeometryFromWkb(bytes(g.asWkb()))
                if og is not None and not og.IsEmpty(): lotes_ogr.append(og)
            if not lotes_ogr:
                raise QgsProcessingException('No se encontraron lotes validos para recortar canales.')
            # Union de lotes: evita duplicar lineas en limites compartidos.
            mascara_ogr = lotes_ogr[0].Clone()
            for og in lotes_ogr[1:]:
                mascara_ogr = mascara_ogr.Union(og)
            segmentos = []
            def guardar_segmentos(g):
                if g is None or g.IsEmpty(): return
                tipo = ogr.GT_Flatten(g.GetGeometryType())
                if tipo == ogr.wkbLineString:
                    if g.GetPointCount() >= 2:
                        segmentos.append([(g.GetX(i), g.GetY(i)) for i in range(g.GetPointCount())])
                elif tipo in (ogr.wkbMultiLineString, ogr.wkbGeometryCollection):
                    for i in range(g.GetGeometryCount()):
                        guardar_segmentos(g.GetGeometryRef(i))
            for feature in red_lyr:
                original = feature.GetGeometryRef()
                if original is None: continue
                geom = original.Clone()
                if tx_red: geom.Transform(tx_red)
                if not geom.Intersects(mascara_ogr): continue
                guardar_segmentos(geom.Intersection(mascara_ogr))
            red_lyr = None
            red = None
            feedback.pushInfo('Segmentos de canales dentro de lotes: '+str(len(segmentos)))
            if not segmentos:
                feedback.pushWarning('La red vectorial de SAGA no intersecta los lotes. '
                                     'Pruebe un umbral de canales menor.')
            hydro_fig=Figure(figsize=(8.27,11.69),facecolor='white')
            for x,y,w,h,lw in [(.025,.02,.95,.955,1.9),(.065,.845,.235,.115,.85),
                                (.34,.855,.61,.105,.85),(.065,.078,.885,.752,.65)]:
                hydro_fig.add_artist(Rectangle((x,y),w,h,fill=False,lw=lw,transform=hydro_fig.transFigure))
            hydro_fig.text(.645,.908,'RED DE DRENAJE\n'+est.upper(),
                ha='center',va='center',color='#237d3b',weight='bold',fontsize=11)
            uy_h=hydro_fig.add_axes([.065,.845,.235,.115]);uy_h.axis('off')
            for pol in departamentos:
                uy_h.add_patch(Polygon(pol,closed=True,facecolor='#3aaa35',edgecolor='#222',lw=.55))
            uy_h.set_xlim(-58.8,-52.8);uy_h.set_ylim(-35.4,-29.7);uy_h.set_aspect('equal')
            try:
                if -58.8<=centro_uy.x()<=-52.8 and -35.4<=centro_uy.y()<=-29.7:
                    uy_h.add_patch(Rectangle((centro_uy.x()-.15,centro_uy.y()-.12),.30,.24,
                                             fill=False,edgecolor='black',lw=1.35))
            except Exception: pass
            hydro_ax=hydro_fig.add_axes(MAP_BOX);hydro_ax.set_aspect('equal');hydro_ax.axis('off')
            # Mapa como la capa vectorial recortada de QGIS: fondo blanco,
            # lineas de drenaje y limites de lotes, sin relleno de cuencas.
            for linea in segmentos:
                hydro_ax.plot([xy[0] for xy in linea], [xy[1] for xy in linea],
                              color='#8e6bc0', lw=.65, zorder=3)
            for feat in src.getFeatures():
                geom=QgsGeometry(feat.geometry())
                if geom.isEmpty(): continue
                try: geom.transform(trans)
                except Exception: continue
                polys=geom.asMultiPolygon() if geom.isMultipart() else [geom.asPolygon()]
                for poly in polys:
                    for ring in poly[:1]:
                        if ring: hydro_ax.plot([pt.x() for pt in ring],[pt.y() for pt in ring],color='black',lw=.8)
                try:
                    pt=geom.pointOnSurface().asPoint()
                    hydro_ax.text(pt.x(),pt.y(),str(feat[campo_lote]),ha='center',va='center',fontsize=7,
                        weight='bold',path_effects=[pe.withStroke(linewidth=2.5,foreground='white')])
                except Exception: pass
            hydro_ax.set_xlim(limites_vista[0],limites_vista[1]);hydro_ax.set_ylim(limites_vista[2],limites_vista[3])
            hydro_fig.text(.855,.785,'N',ha='center',va='center',fontsize=10,weight='bold')
            hydro_fig.text(.855,.758,'▲',ha='center',va='center',fontsize=21)
            hydro_fig.text(.09,.36,'Referencias',fontsize=11,weight='bold')
            hydro_fig.text(.09,.305,'━━',color='#8e6bc0',fontsize=13,weight='bold')
            hydro_fig.text(.125,.313,'Red de drenaje (SAGA)',fontsize=8,va='center')
            hydro_fig.text(.09,.285,'━━',color='black',fontsize=13,weight='bold')
            hydro_fig.text(.125,.293,'Limites de lotes',fontsize=8,va='center')
            if raster_crs.mapUnits()==0:
                width=ancho_vista;raw=width*.20
                magnitude=10**math.floor(math.log10(raw))
                unit=min([1,2,5,10],key=lambda z:abs(z*magnitude-raw))*magnitude
                y=.095;w=min(.26,.79*(unit/width) if width else .20);x=.565-w/2
                for j in range(2):
                    hydro_fig.add_artist(Rectangle((x+j*w/2,y),w/2,.011,
                        transform=hydro_fig.transFigure,facecolor='black' if j==0 else 'white',edgecolor='black',lw=.6))
                for xp,label in [(x,'0'),(x+w/2,f'{unit/2:g}'),(x+w,f'{unit:g} m')]:
                    hydro_fig.text(xp,y+.016,label,fontsize=8,ha='center')
            if logo and os.path.isfile(logo):
                try:
                    la=hydro_fig.add_axes([.77,.085,.14,.075]);la.imshow(mpimg.imread(logo));la.axis('off')
                except Exception: pass
            hydro_fig.text(.5,.068,'Fuente: MDT IDE Uruguay | SAGA Next Gen | Umbral: '+str(umbral)+' celdas',
                           ha='center',fontsize=7,color='#555')
            guardar_informe(out_drenaje,hydro_fig,'RED DE DRENAJE',[],[],'drenaje.pdf')
            elev_ds=None
            ds=None
        feedback.pushInfo('PDF MDT: '+out_mdt)
        feedback.pushInfo('PDF Pendientes: '+out_pend)
        feedback.pushInfo('PDF Drenaje: '+out_drenaje)
        return {'PDF_MDT':out_mdt,'PDF_PEND':out_pend,'PDF_DRENAJE':out_drenaje}


# Geometria simplificada de los departamentos de Uruguay (mismo recurso de CONEAT v10).
UY_DEPTOS_B64 = """
eNqFXVmyAyuu3FD3CeZhLTd6/9t4xqRSRSW+79MKzIyQUinqn3/++W/tfyPE//w3h7/ex//+syVbMGM2QcpbkqpJxoTEyszQt6Sw
TKsfSfwLqZmkzy0Zg/8aX0mMlMSvIMVpgrz/lLpVM8cuk73MbFvCImgpjy0Znzb3n0qtb8mgJJevpEYTJJTorHdAUkzSdpkaKLFa
QjJJzUdLS9K3hB1OEPRICfo7OecQJE6nVcKVq/hTY5lU0bTV2wck3TrTuw3bmurocE028I5VqOxfm/gXW2+7g5W/S0MJq7dl1MuJ
qG2PoU7bSKXtelu1lnLfo2rNZivHXaYnqzlidrhJIqaiY6XaZ9v0tyTvDo5QTRLiSzLQ5d47JB17qw8r0+vuzojRJPavOSFp2Dkj
J5PgfIxk9bSI1ovVU9Fn/1etqKfaKGqxfw2TZPyrWT0FCzo6JVjQka31EtGfDAFK9DkowJzaVGQckG59yXHPaJsssitt/J0Hlpe1
orctWd9yw8aZ1reMbVwL64nn2Wx/qU4cEBtAQj2FY0wJZTjn0VQHNMVHYrqDRbAIObEIFjyH+JKkwT/tHqfCPxVIbCnDrjZyfkPf
Kxm7NY3tGLgmAYcsFNYy9tKGmNkQFPgslKQtqT6mLciRMwPB5ORBEjl536lypf9ZBKs3WksllK9kcI/srfcpE6zHxWr2bY5/zcem
xnUyeIAa5iKYpGP3hcKTudcysJoZMDnZtQDKZFMdoeBWomLFwgTqrQgN6VdZyrgAm+mt1DGljXorYh2yadFcMSoqO9y1D30IQbPr
pI6EIp1adNfSp5XpuHx7paTjVi+JElzzdjM87v2P6Md2i9hutlIhYA90L1KxmltSP/sOHZ4sstsekTsd263z1AVsiu57vw0MoXOr
TwzTJNEGTv0YcxLJFkQ/vVtAHR8xoY03Q2y7jF05D0nhMcPCND/zmPTmRybuHrdgZVLeE1ipMxOWvPI+SXWPvDYbQ0JbtfEsQpCo
ISHgic51t1QmJVYLDytKtEkNv2eilMlbAWVyfB3oQjVQyj6+hSqoYEyZYyp7IjKVXcXU5MYj394CVMJqK4bkt2HfguRqwqrllm04
holr2XZ3EzdoS5BQWWO1E++kht2YuIcbhpQib3SMIAXrcMOMR6rihhlO3H2ffbjL9HbosY+kUbPtxmOyjT8wN4GLO8b+kxnXS/mh
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
"""
