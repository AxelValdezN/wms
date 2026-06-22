from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from decimal import Decimal
from .models import DetalleEntrada, Entrada, Existencia, Articulo, Localizacion, Movimiento, OrdenSalida, DetalleSalida, Lote
from django.db import transaction
from django.utils.dateparse import parse_date
from django.db.models import Q, F, Sum, Count
from django.shortcuts import render, redirect, get_object_or_404
import time
from django.utils import timezone
from datetime import timedelta

@login_required
def dashboard_inventario(request):
    hoy = timezone.now()
    # Obtenemos el inicio del mes actual para medir el flujo
    inicio_mes = hoy.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # --- KPI 1: Termómetro de Actividad ---
    flujo = Movimiento.objects.filter(fecha__gte=inicio_mes).aggregate(
        entradas=Sum('cantidad_entrada', filter=Q(tipo_movimiento='ENTRADA')),
        salidas=Sum('cantidad_salida', filter=Q(tipo_movimiento='SALIDA'))
    )

    # --- KPI 2: Salud del Inventario ---
    salud = Existencia.objects.aggregate(
        disponible=Sum('cantidad_actual', filter=Q(estado_calidad='DISPONIBLE')),
        merma=Sum('cantidad_actual', filter=Q(estado_calidad='MERMA')),
        cuarentena=Sum('cantidad_actual', filter=Q(estado_calidad='CUARENTENA'))
    )

    # --- KPI 3: Tasa de Cumplimiento ---
    ordenes = OrdenSalida.objects.aggregate(
        total=Count('id'),
        completadas=Count('id', filter=Q(estatus='COMPLETADA')),
    )
    total_ordenes = ordenes['total'] or 0
    ordenes_completadas = ordenes['completadas'] or 0
    tasa_cumplimiento = (ordenes_completadas / total_ordenes * 100) if total_ordenes > 0 else 0

    # --- KPI 4: Top 5 Artículos 
    top_articulos = Existencia.objects.values(
        'articulo__clave', 'articulo__descripcion'
    ).annotate(
        total_stock=Sum('cantidad_actual')
    ).filter(total_stock__gt=0).order_by('-total_stock')[:5]


    # --- TABLA INFERIOR Y BUSCADOR
    # Aquí agrupamos todo el inventario usando los dobles guiones bajos
    inventario = Existencia.objects.values(
        'articulo__clave', 
        'articulo__descripcion', 
        'localizacion__clave', 
        'estado_calidad'
    ).annotate(
        total_piezas=Sum('cantidad_actual')
    ).filter(total_piezas__gt=0).order_by('articulo__clave')

    # Lógica de la barra de búsqueda superior
    query = request.GET.get('q', '')
    if query:
        inventario = inventario.filter(
            Q(articulo__clave__icontains=query) |
            Q(articulo__descripcion__icontains=query) |
            Q(localizacion__clave__icontains=query)
        )

    # Empaquetamos todo para enviarlo a tu HTML ortogonal
    contexto = {
        'total_entradas': flujo['entradas'] or 0,
        'total_salidas': flujo['salidas'] or 0,
        'stock_disponible': salud['disponible'] or 0,
        'stock_merma': salud['merma'] or 0,
        'stock_cuarentena': salud['cuarentena'] or 0,
        'tasa_cumplimiento': round(tasa_cumplimiento, 1),
        'ordenes': ordenes,
        'top_articulos': top_articulos,
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
        
        # --- ALGORITMO PEPS / FEFO PURO CON BLOQUEO ---
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
                
    # Vista GET: Agrupamos el stock por artículo para mostrarlo de forma ejecutiva
    articulos_con_stock = Articulo.objects.filter(
        existencia__cantidad_actual__gt=0,
        existencia__estado_calidad='DISPONIBLE'
    ).distinct().order_by('clave')

    contexto = {
        'orden': orden,
        'detalles': orden.detalles.all().order_by('-id'),
        'total_surtido': total_surtido,
        'faltante': faltante,
        'articulos': articulos_con_stock,
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
