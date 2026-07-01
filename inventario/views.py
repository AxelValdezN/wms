from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from decimal import Decimal
from .models import DetalleEntrada, Entrada, Existencia, Articulo, Localizacion, Movimiento, OrdenSalida, DetalleSalida, Lote, Embarque
from django.db import transaction
from django.utils.dateparse import parse_date
from django.db.models import Q, F, Sum, Count, ProtectedError
from django.shortcuts import render, redirect, get_object_or_404    
import time, json
from django.utils import timezone
from datetime import timedelta
from django.http import JsonResponse
from django.urls import reverse
from django.core.paginator import Paginator

@login_required
def dashboard_inventario(request):
    hoy = timezone.now()
    inicio_mes = hoy.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # El termometro de
    flujo = Movimiento.objects.filter(fecha__gte=inicio_mes).aggregate(
        entradas=Sum('cantidad_entrada', filter=Q(tipo_movimiento='ENTRADA')),
        salidas=Sum('cantidad_salida', filter=Q(tipo_movimiento='SALIDA'))
    )

    # saluda del inventario
    salud = Existencia.objects.aggregate(
        disponible=Sum('cantidad_actual', filter=Q(estado_calidad='DISPONIBLE')),
        merma=Sum('cantidad_actual', filter=Q(estado_calidad='MERMA')),
        cuarentena=Sum('cantidad_actual', filter=Q(estado_calidad='CUARENTENA'))
    )

    # KPI Tasa de cumplimiento
    ordenes = OrdenSalida.objects.aggregate(
        total=Count('id'),
        completadas=Count('id', filter=Q(estatus='COMPLETADA')),
    )
    total_ordenes = ordenes['total'] or 0
    ordenes_completadas = ordenes['completadas'] or 0
    tasa_cumplimiento = (ordenes_completadas / total_ordenes * 100) if total_ordenes > 0 else 0

    # los primeros cinco articulos
    top_articulos = Existencia.objects.values(
        'articulo__clave', 'articulo__descripcion'
    ).annotate(
        total_stock=Sum('cantidad_actual')
    ).filter(total_stock__gt=0).order_by('-total_stock')[:5]

    # Ordenes activas
    # Traemos las órdenes que no han sido cerradas, ordenadas por folio (las más antiguas primero)
    ordenes_activas = OrdenSalida.objects.filter(
        estatus__in=['PENDIENTE', 'EN_PROCESO']
    ).order_by('id')

    # TABLA INFERIOR Y BUSCADOR 
    inventario = Existencia.objects.values(
        'articulo__clave', 
        'articulo__descripcion', 
        'localizacion__clave', 
        'estado_calidad'
    ).annotate(
        total_piezas=Sum('cantidad_actual')
    ).filter(total_piezas__gt=0).order_by('articulo__clave')

    query = request.GET.get('q', '')
    if query:
        inventario = inventario.filter(
            Q(articulo__clave__icontains=query) |
            Q(articulo__descripcion__icontains=query) |
            Q(localizacion__clave__icontains=query)
        )

    contexto = {
        'total_entradas': flujo['entradas'] or 0,
        'total_salidas': flujo['salidas'] or 0,
        'stock_disponible': salud['disponible'] or 0,
        'stock_merma': salud['merma'] or 0,
        'stock_cuarentena': salud['cuarentena'] or 0,
        'tasa_cumplimiento': round(tasa_cumplimiento, 1),
        'ordenes': ordenes,
        'top_articulos': top_articulos,
        'ordenes_activas': ordenes_activas, # Pasamos los datos al HTML
        'inventario': inventario,
        'query': query,
    }
    
    return render(request, 'inventario/dashboard.html', contexto)
@login_required 
def registrar_entrada(request):
    if request.method == 'POST':
        articulo_id = request.POST.get('articulo')
        localizacion_id = request.POST.get('localizacion')
        cliente = request.POST.get('cliente', 'Proveedor Interno').strip()
        folio = request.POST.get('folio').strip()
        lote_texto = request.POST.get('lote', 'S/N').strip() # Capturamos el texto

        try:
            cantidad_entrada = Decimal(request.POST.get('cantidad'))
        except (TypeError, ValueError):
            messages.error(request, "La cantidad debe ser un número válido.")
            return redirect('inventario:nueva_entrada')
            
        fecha_caducidad_str = request.POST.get('fecha_caducidad')
        fecha_caducidad = parse_date(fecha_caducidad_str) if fecha_caducidad_str else None
        
        articulo = get_object_or_404(Articulo, id=articulo_id)
        localizacion = get_object_or_404(Localizacion, id=localizacion_id)

        with transaction.atomic(): 
            entrada_obj, created = Entrada.objects.get_or_create(
                folio_entrada=folio,
                defaults={'cliente': cliente, 'usuario': request.user}
            )
            
            # Buscamos si el lote ya existe para ese artículo. Si no, lo creamos.
            lote_obj, lote_creado = Lote.objects.get_or_create(
                articulo=articulo,
                clave=lote_texto,
                defaults={'fecha_caducidad': fecha_caducidad}
            )
            
            # Pasamos la INSTANCIA lote_obj, no el texto
            DetalleEntrada.objects.create(
                entrada=entrada_obj, 
                articulo=articulo, 
                localizacion=localizacion,
                cantidad_recibida=cantidad_entrada, 
                lote=lote_obj
            )

            # Bitácora inmutable 
            Movimiento.objects.create(
                tipo_movimiento='ENTRADA',
                folio_referencia=folio,
                articulo=articulo,
                localizacion=localizacion,
                lote=lote_obj, # INSTANCIA
                cantidad_entrada=cantidad_entrada,
                cantidad_salida=0,
                usuario=request.user,
                observaciones='Ingreso directo a rack (disponible)'
            )
            
        messages.success(request, f"Recepción exitosa: {cantidad_entrada} piezas del lote {lote_texto} ingresadas.")
        return redirect('inventario:dashboard')
        
    contexto = {
        'articulos': Articulo.objects.filter(estatus=True).order_by('clave'),
        'localizaciones': Localizacion.objects.filter(estatus=True).order_by('clave'),
    }
    return render(request, 'inventario/nueva_entrada.html', contexto)

@login_required
@permission_required('inventario.change_existencia', raise_exception=True)
def cambiar_estatus(request):
    if request.method == 'POST':
        existencia_id = request.POST.get('existencia_id')
        nuevo_estado = request.POST.get('nuevo_estado')

        try:
            cantidad_a_cambiar = Decimal(request.POST.get('cantidad'))
        except (TypeError, ValueError):
            messages.error(request, "La cantidad debe ser un número válido.")
            return redirect('inventario:cambiar_estatus')
            
        try:
            # 1. ABRIMOS LA BÓVEDA
            with transaction.atomic():
                # 2. BUSCAMOS CON CANDADO DE CONCURRENCIA
                existencia_original = Existencia.objects.select_for_update().get(id=existencia_id)
                
                # Validamos que la cantidad en el stock esté disponible 
                if cantidad_a_cambiar > existencia_original.cantidad_actual:
                    messages.error(
                        request,
                        f"Operación denegada: Stock insuficiente. Intenta mover {cantidad_a_cambiar} piezas, pero solo hay {existencia_original.cantidad_actual} disponibles."
                    )
                    return redirect('inventario:cambiar_estatus')
                    
                # 3. CREAMOS LOS MOVIMIENTOS INYECTANDO EL LOTE Y EL USUARIO CORRECTO
                # Restamos el movimiento viejo (movimiento de salida)
                Movimiento.objects.create(
                    tipo_movimiento='CAMBIO_ESTADO',
                    folio_referencia='Ajuste de calidad',
                    articulo=existencia_original.articulo,
                    localizacion=existencia_original.localizacion,
                    lote=existencia_original.lote,  # <-- AQUÍ ESTÁ LA SOLUCIÓN
                    estado_calidad=existencia_original.estado_calidad,
                    cantidad_entrada=0,
                    cantidad_salida=cantidad_a_cambiar,
                    usuario=request.user,           # Objeto User real
                    observaciones='Salida por cambio de estatus'
                )
                
                # Sumamos el movimiento nuevo (movimiento de entrada al nuevo estado)
                Movimiento.objects.create(
                    tipo_movimiento='CAMBIO_ESTADO',
                    folio_referencia='Ajuste de calidad',
                    articulo=existencia_original.articulo,  
                    localizacion=existencia_original.localizacion,
                    lote=existencia_original.lote,  # <-- AQUÍ ESTÁ LA SOLUCIÓN
                    estado_calidad=nuevo_estado,    
                    cantidad_entrada=cantidad_a_cambiar,
                    cantidad_salida=0,
                    usuario=request.user,           # Objeto User real
                    observaciones='Entrada por cambio de estatus'
                )
                
            messages.success(request, "Estatus de inventario actualizado exitosamente.")
            return redirect('inventario:dashboard')
            
        except Existencia.DoesNotExist:
            messages.error(request, "La existencia seleccionada no existe.")
            return redirect('inventario:cambiar_estatus')
            
    # Si entra por primera vez a la página, le mandamos el inventario actual
    contexto = {
        # Filtramos para que solo vea mercancia donde haya más de 0 piezas
        'existencias': Existencia.objects.filter(cantidad_actual__gt=0).order_by('articulo__clave'),
        'estados': Existencia.ESTADO_CHOICES,
    }
    return render(request, 'inventario/cambio_estatus.html', contexto)

@login_required
def registrar_salida(request):
    if request.method == "POST":
        articulo_id = request.POST.get('articulo')
        localizacion_id = request.POST.get("localizacion")
        motivo = request.POST.get('motivo', 'Salida Rapida').strip()

        try:
            cantidad = Decimal(request.POST.get('cantidad', 0))
        except (TypeError, ValueError):
            messages.error(request, "La cantidad debe ser un número válido.")
            return redirect('inventario:nueva_salida')
        
        try:
            # 1 abrimos el inventario
            with transaction.atomic():
                # 2. Usamos filter() para traer todos los lotes de ese rack
                existencias = Existencia.objects.select_for_update().filter(
                    articulo_id=articulo_id, 
                    localizacion_id=localizacion_id,
                    cantidad_actual__gt=0
                ).order_by('id') # El ID mas antiguo primero (PEPS)
                
                if not existencias.exists():
                    messages.error(request, "No hay existencias registradas de este artículo en esta ubicación.")
                    return redirect('inventario:nueva_salida')

                # 3. Verificamos que la suma de todos los lotes alcance para la salida
                stock_total = sum(e.cantidad_actual for e in existencias)
                
                if cantidad > stock_total:
                    messages.error(request, f"Operación denegada: Solo hay {stock_total} piezas disponibles en ese rack sumando todos los lotes.")
                    return redirect('inventario:nueva_salida')

                cantidad_restante = cantidad
                folio_rapido = f"SR-{str(int(time.time()))[-4:]}"

                # 4. Iteramos y creamos los movimientos (El Signal se encarga de las restas físicas)
                for existencia in existencias:
                    if cantidad_restante <= 0:
                        break # Terminamos si ya se cubrio la cuota
                    
                    # Determinamos cuánto le vamos a descontar a este lote específico
                    descuento = min(cantidad_restante, existencia.cantidad_actual)
                    
                    # Al crear esto, disparamos el Signal que hara la resta automática en la base
                    Movimiento.objects.create(
                        tipo_movimiento='SALIDA',
                        folio_referencia=folio_rapido,
                        articulo=existencia.articulo,
                        localizacion=existencia.localizacion,
                        lote=existencia.lote, # Pasamos el lote exacto para que el Signal sepa de dónde restar
                        cantidad_entrada=0,
                        cantidad_salida=descuento,
                        usuario=request.user,
                        observaciones=f"Ajuste/Merma: {motivo}"
                    )
                    
                    cantidad_restante -= descuento
                    
                messages.success(request, f"Salida rápida procesada: se retiraron {cantidad} piezas.")
                return redirect('inventario:dashboard')

        except Exception as e:
            # Captura general por si ocurre un error inesperado en la base de datos
            messages.error(request, f"Error en la transacción: {str(e)}")
            return redirect('inventario:nueva_salida')
            
    articulos = Articulo.objects.all().order_by('clave')
    localizaciones = Localizacion.objects.all().order_by('clave')

    contexto = {
        'articulos': articulos,
        'localizaciones': localizaciones
    }
    return render(request, 'inventario/nueva_salida.html', contexto)
@login_required
@permission_required('inventario.view_articulo', raise_exception=True)
def catalogo_articulos(request):
    if request.method == 'POST':
        clave = request.POST.get('clave').strip()
        descripcion = request.POST.get('descripcion')
        unidad_medida = request.POST.get('unidad_medida')
        familia = request.POST.get('familia')
        clasificacion = request.POST.get('clasificacion')
        #Evitamos que se duplique la clave del artículo
        if Articulo.objects.filter(clave=clave).exists():
            messages.error(request, f"Ya existe un artículo con la clave '{clave}'. Por favor, elige una clave diferente.")
            return redirect('inventario:catalogo_articulos')
        Articulo.objects.create(
            clave=clave,
            descripcion=descripcion,
            unidad_medida=unidad_medida,
            familia=familia,
            clasificacion=clasificacion
        )
        messages.success(request, f"Artículo '{clave}' agregado exitosamente al catalogo.")
        return redirect('inventario:catalogo_articulos')
    #Se muestra el formulario vacio y la lista de articulos existentes
    contexto = {
        'articulos': Articulo.objects.all().order_by('clave'),
        'clasificaciones': Articulo.CLASIFICACION_CHOICES
    }
    return render(request, 'inventario/catalogo_articulos.html', contexto)
@login_required
@permission_required('inventario.view_localizacion', raise_exception=True)
def catalogo_localizaciones(request):
    if request.method == 'POST':
        clave = request.POST.get('clave').strip().upper()
        almacen = request.POST.get('almacen').strip()
        tipo = request.POST.get('tipo', 'RACK')
        Localizacion.objects.create(
            clave=clave,
            almacen=almacen,
            tipo=tipo
        )
        messages.success(request, f"Localización '{clave}' registrada en {almacen}.")
        return redirect('inventario:catalogo_localizaciones')
    localizaciones = Localizacion.objects.all().order_by('almacen', 'clave')
    return render(request, 'inventario/catalogo_localizaciones.html', {'localizaciones': localizaciones})
@login_required
@permission_required('inventario.view_ordensalida', raise_exception=True)
def generar_picking_list(request, folio):
    # Ya no leemos Movimientos sueltos, ahora leemos la Orden Maestra
    orden = get_object_or_404(OrdenSalida, folio_salida=folio)
    
    # Traemos los detalles ordenados por Rack para facilitar la caminata
    detalles = orden.detalles.all().order_by('localizacion__clave')
        
    contexto = {
        'orden': orden,
        'detalles': detalles,
    }
    return render(request, 'inventario/picking_list.html', contexto)
@login_required
@permission_required('inventario.view_Movimiento', raise_exception=True)
def bitacora_movimientos(request):
    movimientos = Movimiento.objects.all().order_by('-id') [:500]
    contexto = {
        'movimientos': movimientos
    }
    return render(request, 'inventario/bitacora.html', contexto)
@login_required
@permission_required('inventario.view_ordensalida', raise_exception=True)
def ejecutar_surtido(request, orden_id):
    orden = get_object_or_404(OrdenSalida, id=orden_id)
    
    # Calculamos la balanza del CC (Cantidad de Control)
    total_surtido = orden.detalles.aggregate(total=Sum('cantidad_surtida'))['total'] or Decimal('0.00')
    faltante = orden.meta_total - total_surtido

    if request.method == 'POST': 
        articulo_id = request.POST.get('articulo_id')
        try:
            cantidad_solicitada = Decimal(request.POST.get('cantidad'))
        except (TypeError, ValueError):
            messages.error(request, "La cantidad debe ser un número válido.")
            return redirect('inventario:ejecutar_surtido', orden_id=orden.id)
        
        articulo = get_object_or_404(Articulo, id=articulo_id)

        # Validaciones de la orden
        if cantidad_solicitada > faltante:
            messages.error(request, f"Operación denegada: Excedes el CC. Solo faltan {faltante} piezas para cerrar la orden.")
            return redirect('inventario:ejecutar_surtido', orden_id=orden.id)
            
        # Validar stock global disponible del artículo
        stock_global = Existencia.objects.filter(
            articulo=articulo, estado_calidad='DISPONIBLE'
        ).aggregate(total=Sum('cantidad_actual'))['total'] or Decimal('0.00')

        if cantidad_solicitada > stock_global:
            messages.error(request, f"Stock insuficiente en todo el almacén. Solicitando: {cantidad_solicitada}, Total disponible: {stock_global}")
            return redirect('inventario:ejecutar_surtido', orden_id=orden.id)
        
        # ALGORITMO PEPS / FEFO PURO CON BLOQUEO 
        cantidad_restante_por_surtir = cantidad_solicitada

        # Entramos a la bóveda: a partir de aquí, nadie más toca estos lotes
        with transaction.atomic():
            
            # SELECT FOR UPDATE congela temporalmente las filas que cumplen los requisitos
            lotes_disponibles = Existencia.objects.select_for_update().filter(
                articulo=articulo,
                estado_calidad='DISPONIBLE',
                cantidad_actual__gt=0
            ).order_by(
                F('lote__fecha_caducidad').asc(nulls_last=True),
                'lote__fecha_ingreso'
            )

            for stock in lotes_disponibles:
                if cantidad_restante_por_surtir <= 0:
                    break 

                if stock.cantidad_actual <= cantidad_restante_por_surtir:
                    a_descontar = stock.cantidad_actual
                else:
                    a_descontar = cantidad_restante_por_surtir
                
                cantidad_restante_por_surtir -= a_descontar

                DetalleSalida.objects.create(
                    orden=orden,
                    articulo=articulo,
                    localizacion=stock.localizacion,
                    lote=stock.lote,
                    cantidad_surtida=a_descontar
                )
                
                Movimiento.objects.create(
                    tipo_movimiento='SALIDA',
                    folio_referencia=orden.folio_salida,
                    articulo=articulo,
                    localizacion=stock.localizacion,
                    lote=stock.lote,
                    estado_calidad='DISPONIBLE',
                    cantidad_entrada=0,
                    cantidad_salida=a_descontar,
                    usuario=request.user, # Usando el objeto User directamente por el cambio anterior
                    observaciones=f"Picking PEPS Aut. | Orden: {orden.folio_salida} | Destino: {orden.destino}"
                )

            nuevo_total = total_surtido + cantidad_solicitada
            if nuevo_total >= orden.meta_total:
                orden.estatus = 'COMPLETADA'
                orden.save()
                messages.success(request, f"Orden {orden.folio_salida} completada exitosamente al 100%.")
                return redirect('inventario:picking_list', folio=orden.folio_salida)
            else:
                orden.estatus = 'EN_PROCESO'
                orden.save()
                messages.success(request, f"Artículos asignados correctamente. Faltan {orden.meta_total - nuevo_total} unidades.")
                return redirect('inventario:ejecutar_surtido', orden_id=orden.id)
                
    # Vista GET: Agrupamos el stock por artículo y SUMAMOS la cantidad disponible real
    articulos_con_stock = Articulo.objects.filter(
        existencia__cantidad_actual__gt=0,
        existencia__estado_calidad='DISPONIBLE'
    ).annotate(
        stock_real_disponible=Sum('existencia__cantidad_actual', filter=Q(existencia__estado_calidad='DISPONIBLE'))
    ).distinct().order_by('clave')

    contexto = {
        'orden': orden,
        'detalles': orden.detalles.all().order_by('-id'),
        'total_surtido': total_surtido,
        'faltante': faltante,
        'articulos': articulos_con_stock, # Ahora cada artículo trae 'stock_real_disponible'
    }
    return render(request, 'inventario/surtido.html', contexto)

@login_required
@permission_required('inventario.add_ordensalida', raise_exception=True)
def crear_orden_salida(request):
    if request.method == 'POST':
        folio = request.POST.get('folio').strip()
        destino = request.POST.get('destino').strip() # Ej. Rampa 1
        asignado_a = request.POST.get('asignado_a').strip() # El almacenista
        
        try:
            meta_total = Decimal(request.POST.get('meta_total'))
        except (TypeError, ValueError):
            messages.error(request, "La cantidad meta (CC) debe ser un número válido.")
            return redirect('inventario:crear_orden_salida')

        # Verificamos que el folio no exista ya para no duplicar salidas
        if OrdenSalida.objects.filter(folio_salida=folio).exists():
            messages.error(request, f"El folio {folio} ya está registrado.")
            return redirect('inventario:crear_orden_salida')

        # Creamos la cabecera de la orden
        orden = OrdenSalida.objects.create(
            folio_salida=folio,
            solicitante=request.user,
            asignado_a=asignado_a,
            destino=destino,
            meta_total=meta_total
        )
        
        # Inmediatamente después de crearla, mandamos al operador al Carrito PEPS
        return redirect('inventario:ejecutar_surtido', orden_id=orden.id)

    return render(request, 'inventario/crear_orden_salida.html')

@login_required
def crear_tally_cabecera(request):
    if request.method == 'POST':
        # Identificacion Logstica
        folio = request.POST.get('folio_entrada').strip()
        cliente = request.POST.get('cliente').strip()
        cortina = request.POST.get('cortina', '').strip()
        piezas_esperadas = request.POST.get('piezas_esperadas', 0)
        
        # Documentos Referenciados
        documento_ref = request.POST.get('documento_referencia', '').strip()
        orden_ref = request.POST.get('orden_referencia', '').strip()
        ro_po = request.POST.get('ro_po', '').strip()
        pedimento = request.POST.get('pedimento', '').strip()
        
        # Transporte y Vehiculo
        transporte = request.POST.get('transporte_linea', '').strip()
        chofer = request.POST.get('nombre_chofer', '').strip()
        tipo_transporte = request.POST.get('tipo_transporte', 'TRAILER')
        placas_trac = request.POST.get('placas_tractor', '').strip()
        placas_cj = request.POST.get('placas_caja', '').strip()
        num_economico = request.POST.get('numero_economico', '').strip()
        sellos = request.POST.get('sellos_seguridad', '').strip()
        
        # Maniobra y Tiempos
        tipo_descarga = request.POST.get('tipo_descarga', 'PALETIZADO')
        fecha_maniobra = request.POST.get('fecha_maniobra') or None
        hora_llegada = request.POST.get('hora_llegada') or None
        hora_termino = request.POST.get('hora_termino') or None
        
        # Auditoria
        supervisor = request.POST.get('supervisor_turno', '').strip()
        observaciones = request.POST.get('observaciones', '').strip()

        # Candado de seguridad: Evitar hojas duplicadas
        if Entrada.objects.filter(folio_entrada=folio).exists():
            messages.error(request, f"El folio de hoja {folio} ya se encuentra registrado en el sistema.")
            return redirect('inventario:crear_tally_cabecera')

        # Creamos la cabecera inmutable con el 100% de los datos físicos
        entrada = Entrada.objects.create(
            folio_entrada=folio,
            cliente=cliente,
            cortina=cortina,
            documento_referencia=documento_ref,
            orden_referencia=orden_ref,
            ro_po=ro_po,
            pedimento=pedimento,
            transporte_linea=transporte,
            nombre_chofer=chofer,
            tipo_transporte=tipo_transporte,
            placas_tractor=placas_trac,
            placas_caja=placas_cj,
            numero_economico=num_economico,
            sellos_seguridad=sellos,
            tipo_descarga=tipo_descarga,
            fecha_maniobra=fecha_maniobra,
            hora_llegada=hora_llegada,
            hora_termino=hora_termino,
            supervisor_turno=supervisor,
            observaciones=observaciones,
            piezas_esperadas=piezas_esperadas,
            usuario=request.user
        )
        
        return redirect('inventario:capturar_tally_detalles', entrada_id=entrada.id)

    # Vista GET: Mandamos los catálogos de opciones a la plantilla
    return render(request, 'inventario/tally_cabecera.html', {
        'choices_descarga': Entrada.TIPO_DESCARGA_CHOICES,
        'choices_transporte': Entrada.TIPO_TRANSPORTE_CHOICES,
    })
@login_required
def capturar_tally_detalles(request, entrada_id):
    # recuperamos la cabecera creada
    entrada = get_object_or_404(Entrada, id=entrada_id)

    if request.method == 'POST':
        try:
            # Recibimos el paquete de datos dinámico desde JavaScript
            data = json.loads(request.body)
            partidas = data.get('partidas', [])

            # Si se falla una linea se cancela todo el proceso
            with transaction.atomic():
                total_piezas_camion = Decimal('0.00')

                # se recorrer los skus 
                for partida in partidas:
                    articulo = Articulo.objects.get(clave=partida['sku'])
                    
                    # Si no existe se crea y si ya existe se recicla
                    lote, created_lote = Lote.objects.get_or_create(
                        articulo=articulo,
                        clave=partida['lote'].strip().upper(),
                        defaults={'fecha_caducidad': partida['caducidad'] if partida['caducidad'] else None}
                    )

                    # Se recorren los racks de ese lote
                    for dist in partida['distribuciones']:
                        localizacion = Localizacion.objects.get(clave=dist['rack'])
                        cantidad = Decimal(str(dist['cantidad']))

                        # Guardamos en "detalle entrada"
                        DetalleEntrada.objects.create(
                            entrada=entrada,
                            articulo=articulo,
                            localizacion=localizacion,
                            cantidad_recibida=cantidad,
                            lote=lote
                        )

                        # Disparar el Movimiento de bitacora
                        Movimiento.objects.create(
                            tipo_movimiento='ENTRADA',
                            folio_referencia=entrada.folio_entrada,
                            articulo=articulo,
                            localizacion=localizacion,
                            lote=lote,
                            estado_calidad='DISPONIBLE',
                            cantidad_entrada=cantidad,
                            usuario=request.user,
                            observaciones=f'Descarga Masiva Tally | Tráiler: {entrada.placas_caja or "N/A"}'
                        )

                        # Sumamos al acumulado matemático de la hoja
                        total_piezas_camion += cantidad

                entrada.total_piezas_final = total_piezas_camion
                entrada.save()
                if total_piezas_camion != entrada.piezas_esperadas:
                    # Si no cuadra, disparamos un error que CANCELA automáticamente toda la transacción de la Base de Datos.
                    raise ValueError(f"AUDITORÍA FALLIDA: El manifiesto exige {entrada.piezas_esperadas} piezas, pero se escanearon {total_piezas_camion}. Diferencia de {total_piezas_camion - entrada.piezas_esperadas} piezas. Se bloqueó el ingreso.")

                # Si el código llega aquí, es porque la suma fue perfecta.
                entrada.total_piezas_final = total_piezas_camion
                entrada.save()

            # respondemos en java que todo fue creado correctanmente
            messages.success(request, f"¡Hoja Tally {entrada.folio_entrada} cerrada! Se ingresaron {total_piezas_camion} piezas al andén.")
            url_impresion = reverse('inventario:imprimir_tally', kwargs={'entrada_id': entrada.id})
            return JsonResponse({'status': 'success', 'redirect_url': url_impresion})

        except Exception as e:
            # Al minimo error lo mandamos
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

    # Mandamos los datos a la pantalla para el JS pueda mostrarlos y ocuparlos
    articulos_json = list(Articulo.objects.filter(estatus=True).values('clave', 'descripcion'))
    racks_json = list(Localizacion.objects.filter(estatus=True).values('clave'))

    return render(request, 'inventario/capturar_tally_detalles.html', {
        'entrada': entrada,
        'articulos_json': articulos_json,
        'racks_json': racks_json
    })

@login_required
def imprimir_tally(request, entrada_id):
    # Recuperamos el documento maestro y todos sus detalles anidados
    entrada = get_object_or_404(Entrada, id=entrada_id)
    detalles = entrada.detalles.all().select_related('articulo', 'localizacion', 'lote').order_by('articulo__clave', 'localizacion__clave')
    
    return render(request, 'inventario/imprimir_tally.html', {
        'entrada': entrada,
        'detalles': detalles,
    })
from django.core.exceptions import PermissionDenied
from django.db.models import Q

def es_supervisor(user):
    # Verifica si el usuario pertenece al grupo configurado en el django 
    return user.groups.filter(name='Supervisor').exists() or user.is_superuser

@login_required
def centro_documentacion(request):
    # Candado definitivo a nivel Servidor: Si no es Supervisor, lo manda al Error 403
    if not es_supervisor(request.user):
        raise PermissionDenied

    # Recuperamos los parámetros de búsqueda del único buscador
    query = request.GET.get('q', '').strip()
    fecha_inicio = request.GET.get('fecha_inicio', '')
    fecha_fin = request.GET.get('fecha_fin', '')

    # Querysets base
    entradas = Entrada.objects.all().order_by('-fecha')
    salidas = OrdenSalida.objects.filter(estatus='COMPLETADA').order_by('-fecha_creacion')

    # Aplicamos el motor de búsqueda omnidireccional si hay texto
    if query:
        # Filtro inteligente para Entradas
        entradas = entradas.filter(
            Q(folio_entrada__icontains=query) |
            Q(cliente__icontains=query) |
            Q(ro_po__icontains=query) |
            Q(documento_referencia__icontains=query) |
            Q(orden_referencia__icontains=query) |
            Q(pedimento__icontains=query) |
            Q(transporte_linea__icontains=query)
        )
        # Filtro inteligente para Salida
        salidas = salidas.filter(
            Q(folio_salida__icontains=query) |
            Q(destino__icontains=query) |
            Q(asignado_a__icontains=query)
        )

    # Filtro por rango de fechas si se especifican
    if fecha_inicio and fecha_fin:
        entradas = entradas.filter(fecha__date__range=[fecha_inicio, fecha_fin])
        salidas = salidas.filter(fecha_creacion__date__range=[fecha_inicio, fecha_fin])

    return render(request, 'inventario/centro_documentacion.html', {
        'entradas': entradas,
        'salidas': salidas,
        'query': query,
        'fecha_inicio': fecha_inicio,
        'fecha_fin': fecha_fin,
    })

@login_required
def registrar_embarque(request):
    if request.method == 'POST':
        # Recibimos los datps del transporte
        folio_embarque = request.POST.get('folio_embarque')
        cortina = request.POST.get('cortina')
        transporte_linea = request.POST.get('transporte_linea')
        nombre_chofer = request.POST.get('nombre_chofer')
        placas_tractor = request.POST.get('placas_tractor')
        placas_caja = request.POST.get('placas_caja')
        sellos_seguridad = request.POST.get('sellos_seguridad')
        
        # se reciben las ID de las casillas que se marcaron
        ordenes_ids = request.POST.getlist('ordenes_seleccionadas')
        
        # Asegurar que el personal selecciono las mercancias
        if not ordenes_ids:
            messages.error(request, "ERROR: DEBE SELECCIONAR AL MENOS UNA ORDEN PARA CARGAR AL TRÁILER.")
            ordenes_disponibles = OrdenSalida.objects.filter(estatus='COMPLETADA', embarque__isnull=True)
            return render(request, 'inventario/registrar_embarque.html', {'ordenes_disponibles': ordenes_disponibles})

        try:
            # Aislamiento total mediante Transacción Atómica
            with transaction.atomic():
                
                # Construir el Contenedor Virtual (creacion del registro maestro del embarque)
                nuevo_embarque = Embarque.objects.create(
                    folio_embarque=folio_embarque,
                    cortina=cortina,
                    transporte_linea=transporte_linea,
                    nombre_chofer=nombre_chofer,
                    placas_tractor=placas_tractor,
                    placas_caja=placas_caja,
                    sellos_seguridad=sellos_seguridad,
                    auditor_rampa=request.user,
                    estatus='CARGANDO'
                )
                
                # Filtramos las ordenes seleccionadas que siguen huerfanas en rampa
                ordenes_a_embarcar = OrdenSalida.objects.filter(id__in=ordenes_ids, embarque__isnull=True)
                
                for orden in ordenes_a_embarcar:
                    orden.embarque = nuevo_embarque
                    orden.estatus = 'DESPACHADO'  # Cerramos el ciclo comercial de la orden
                    orden.save()
                
                # Una vez que los registros internos se amarraron, sellamos el estatus del camion
                nuevo_embarque.estatus = 'DESPACHADO'
                nuevo_embarque.save()
                
            messages.success(request, f"DESPACHO EXITOSO: UNIDAD {folio_embarque} EN RUTA. CORTINA LIBERADA.")
            return redirect('inventario:registrar_embarque')
            
        except Exception as e:
            # Si algo falla aqui adentro, la transacción atomica borra el camion y regresa las ordenes a rampa
            messages.error(request, f"ERROR CRÍTICO DE CONCURRENCIA EN POSTGRESQL: {str(e)}")
            
    # OPERACIÓN GET: Alimentar la tabla del panel derecho con ordenes listas en rampa
    # Buscamos ordenes que esten completadas internamente pero que no pertenezcan a ningún trailer todavia
    ordenes_disponibles = OrdenSalida.objects.filter(estatus='COMPLETADA', embarque__isnull=True)
    
    return render(request, 'inventario/registrar_embarque.html', {
        'ordenes_disponibles': ordenes_disponibles
    })

@login_required
def detalle_recibo(request, entrada_id):
    # Usamos get_object_or_404: Si alguien escribe una URL con un ID que no existe, 
    # Django lanza un error 404 limpio en lugar de colapsar el servidor
    recibo = get_object_or_404(Entrada, id=entrada_id)

    # Buscamos todos los registros en DetalleEntrada que pertenezcan a este recibo específico.
    partidas = DetalleEntrada.objects.filter(entrada=recibo)

    context = {
        'recibo': recibo,
        'partidas': partidas,
    }
    
    return render(request, 'inventario/detalle_recibo.html', context)
@login_required
def detalle_surtido(request, salida_id):
    salida = get_object_or_404(OrdenSalida, id=salida_id)

    # NOTA: Verifica en tu models.py si la relación inversa en DetalleSalida se llama 'orden_salida' o 'salida'.
    partidas = DetalleSalida.objects.filter(orden=salida)
    
    context = {
        'salida': salida,
        'partidas': partidas,
    }
    
    return render(request, 'inventario/detalle_surtido.html', context)

@login_required
def catalogo_articulos(request):
    """
    Motor de búsqueda y paginación para el Master Data Management de SKUs.
    """
    query = request.GET.get('q', '')
    
    # Extraemos todos los artículos ordenados por el más reciente
    articulos_list = Articulo.objects.all().order_by('-id')

    # Filtro asíncrono multiparamétrico
    if query:
        articulos_list = articulos_list.filter(
            Q(clave__icontains=query) |
            Q(descripcion__icontains=query) |
            Q(familia__icontains=query)
        )

    # Paginación estricta: 50 SKUs por bloque para no asfixiar la memoria del navegador
    paginator = Paginator(articulos_list, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'query': query,
    }
    
    return render(request, 'inventario/catalogo_articulos.html', context)


@login_required
def eliminar_sku_hibrido(request, articulo_id):
    """
    Algoritmo de Destrucción Híbrida:
    Intenta un Hard Delete. Si PostgreSQL detecta integridad referencial (historial),
    el motor atrapa el ProtectedError y ejecuta un Soft Delete (Baja Lógica).
    """
    if request.method == 'POST':
        articulo = get_object_or_404(Articulo, id=articulo_id)
        clave_temporal = articulo.clave
        
        try:
            # Borramos desde la raiz con un HARDDELETE si no hay historial con el SKU
            articulo.delete()
            messages.success(request, f"DESTRUCCIÓN FÍSICA: El SKU {clave_temporal} fue eliminado de raíz al no contar con historial operativo.")
            
        except ProtectedError:
            # Soft DELETE: Bloqueamos el "delete" al detectar registros y lo cambiamos a un estado inactivo para proteger la seccion completa 
            articulo.estatus = False
            articulo.save()
            messages.warning(request, f"BAJA LÓGICA: El SKU {clave_temporal} posee historial en andenes. Se cambió su estatus a INACTIVO para proteger la auditoría.")

    return redirect('inventario:catalogo_articulos')

@login_required
def detalle_sku(request, articulo_id):
    """
    Radiografia del articulo y mapa de existencias
    """
    articulo = get_object_or_404(Articulo, id=articulo_id)
    # recuperamos todas las existencias realcionadas e intentamos un MAPA DE CALOR 
    try:
        from.models import Existencia
        stock_activo = Existencia.objects.filter(articulos=articulo, cantidad__gt=0).order_by('localizacion__clave')
        total_piezas = sum(item.cantidad for item in stock_activo)
    except Exception:
        stock_activo = []
        total_piezas = 0
    context = {
        'articulo': articulo,
        'stock_activo': stock_activo,
        'total_piezas': total_piezas,
    }
    return render(request, 'inventario/detalle_sku.html', context)

@login_required
def reactivar_sku(request, articulo_id):
    """
    Revierte una baja logica (SOFT DELETE)
    """
    if request.method == 'POST':
        articulo = get_object_or_404(Articulo, id=articulo_id)
        articulo.estatus = True
        articulo.save()
        messages.success(request, f"REACTIVACION: EL SKU {articulo.clave} vuelve a estar activo en el catalogo.")
    return redirect('inventario:detalle_sku', articulo_id=articulo.id)