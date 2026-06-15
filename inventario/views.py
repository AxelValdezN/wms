from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from decimal import Decimal
from .models import DetalleEntrada, Entrada, Existencia, Articulo, Localizacion, Movimiento, OrdenSalida, DetalleSalida
from django.db import transaction
from django.utils.dateparse import parse_date
from django.db.models import Q, F, Sum
from django.shortcuts import render, redirect, get_object_or_404
import time

@login_required 
def dashboard_inventario(request):
    query = request.GET.get('q', '').strip()
    existencias_base = Existencia.objects.filter(cantidad_actual__gt=0)

    if query:
        existencias = existencias.filter(
            Q(articulo__clave__icontains=query) |
            Q(articulo__descripcion__icontains=query) |
            Q(localizacion__clave__icontains=query)
        )
    inventario = existencias_base.values(
        'articulo__clave',
        'articulo__descripcion',
        'localizacion__clave',
        'estado_calidad'
    ).annotate(
        total_piezas=Sum('cantidad_actual')
    ).order_by('articulo__clave')

    contexto = {
        'inventario': inventario,
        'query': query,
    }
    return render(request, 'inventario/dashboard.html', contexto)
@login_required 
def registrar_entrada(request):
    # Si el usuario le dio clic al botón "Guardar" (Método POST)
    if request.method == 'POST':
        articulo_id = request.POST.get('articulo')
        localizacion_id = request.POST.get('localizacion')
        cliente = request.POST.get('cliente', 'Proveedor Interno').strip()
        folio = request.POST.get('folio').strip()
        lote = request.POST.get('lote', 'S/N').strip()

        try:
            cantidad_entrada = Decimal(request.POST.get('cantidad'))
        except (TypeError, ValueError):
            messages.error(request, "La cantidad debe ser un número válido.")
            return redirect('inventario:nueva_entrada')
        fecha_caducidad_str = request.POST.get('fecha_caducidad')
        fechas_caducidad = parse_date (fecha_caducidad_str) if fecha_caducidad_str else None
        articulo = Articulo.objects.get(id=articulo_id)
        localizacion = Localizacion.objects.get(id=localizacion_id)

        with transaction.atomic(): 
            entrada_obj, create = Entrada.objects.get_or_create(
                folio_entrada=folio,
                defaults={'cliente': cliente, 'usuario': request.user.username}
            )
            DetalleEntrada.objects.create(
                entrada=entrada_obj, articulo=articulo, localizacion=localizacion,
                cantidad_recibida=cantidad_entrada, lote=lote, fecha_caducidad=fechas_caducidad
            )

            #Bitacora inmutable 
            Movimiento.objects.create(
                tipo_movimiento='ENTRADA',
                folio_referencia=folio,
                articulo=articulo,
                localizacion=localizacion,
                lote=lote,
                cantidad_entrada=cantidad_entrada,
                cantidad_salida=0,
                usuario=request.user.username,
                observaciones='Ingreso directo a rack (disponible)'
            )
        messages.success(request, f"Recepcion exitosa: {cantidad_entrada} piezas del lote {lote} ingresadas.")
        return redirect('inventario:dashboard')
    contexto = {
        'articulos': Articulo.objects.filter(estatus=True).order_by('clave'),
        'localizaciones': Localizacion.objects.filter(estatus=True).order_by('clave'),
    }
    return render(request, 'inventario/nueva_entrada.html', contexto)

@login_required
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
            existencia_original = Existencia.objects.get(id=existencia_id)
        except Existencia.DoesNotExist:
            messages.error(request, "La existencia seleccionada no existe.")
            return redirect('inventario:cambiar_estatus')
        #Validamos que la cantidad en el stock este disponible 
        if cantidad_a_cambiar > existencia_original.cantidad_actual:
            messages.error(
                request,
                f"Operacion denegada: Stock insuficiente. Intenta mover {cantidad_a_cambiar} piezas, pero solo hay {existencia_original.cantidad_actual} disponibles."
            )
            return redirect('inventario:cambiar_estatus')
        #restamos el movimiento viejo (movimiento de salida)
        Movimiento.objects.create(
            tipo_movimiento='CAMBIO_ESTADO',
            folio_referencia='Ajuste de calidad',
            articulo=existencia_original.articulo,
            localizacion=existencia_original.localizacion,
            estado_calidad=existencia_original.estado_calidad,
            cantidad_entrada=0,
            cantidad_salida=cantidad_a_cambiar,
            usuario='Jefe / Supervisor',
            observaciones='Salida por cambio de estatus'
        )
        Movimiento.objects.create(
            tipo_movimiento='CAMBIO_ESTADO',
            folio_referencia='Ajuste de calidad',
            articulo=existencia_original.articulo,  
            localizacion=existencia_original.localizacion,
            estado_calidad=nuevo_estado,    
            cantidad_entrada=cantidad_a_cambiar,
            cantidad_salida=0,
            usuario='Jefe / Supervisor',
            observaciones='Entrada por cambio de estatus'
        )
        messages.success(request, "Estatus de inventari actualizado exitosamente.")
        return redirect('inventario:dashboard')
         # Si entra por primera vez a la página, le mandamos el inventario actual
    contexto = {
        # Filtramos para que solo vea mercancía donde haya más de 0 piezas
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
            existencia = Existencia.objects.get(articulo_id=articulo_id, localizacion_id=localizacion_id)
            if existencia.cantidad_actual >= cantidad:
                with transaction.atomic():
                    existencia.cantidad_actual -= cantidad
                    existencia.save()

                    folio_rapido = f"SR-{str(int(time.time()))[-4:]}"
                    Movimiento.objects.create(
                        tipo_movimiento='SALIDA',
                        folio_referencia=folio_rapido,
                        articulo=existencia.articulo,
                        localizacion=existencia.localizacion,
                        lote=existencia.lote,
                        cantidad_entrada=0,
                        cantidad_salida=cantidad,
                        usuario=request.user.username,
                        observaciones=f"Ajuste/Merma: {motivo}"
                    )
                messages.success(request, f"Salida rapida procesada: se retiraron {cantidad} piezas.")
                return redirect('inventario:dashboard')
            else:
                messages.error(request, f"Operacion denegada: Solo hay {existencia.cantidad_actual} piezas disponibles en ese rack.")
        except Existencia.DoesNotExist:
            messages.error(request, "No hay existencias registradas de este articulo en esta ubicacion.")
    articulos = Articulo.objects.all().order_by('clave')
    localizaciones = Localizacion.objects.all().order_by('clave')

    contexto = {
        'articulos': articulos,
        'localizaciones': localizaciones
    }
    return render(request, 'inventario/nueva_salida.html', contexto)
@login_required
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
def bitacora_movimientos(request):
    movimientos = Movimiento.objects.all().order_by('-id') [:500]
    contexto = {
        'movimientos': movimientos
    }
    return render(request, 'inventario/bitacora.html', contexto)
@login_required
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
            messages.error(request, "La cantidad debe ser un numero valido")
            return redirect('inventario:ejecutar_surtido', orden_id=orden.id)
        
        articulo = get_object_or_404(Articulo, id=articulo_id)

        #validaciones de las ordenes
        if cantidad_solicitada > faltante:
            messages.error(request, f"Operacion denegada: Excedes el CC. Solo faltan {faltante} piezas para cerrar la orden")
            return redirect('Inventario:ejecutar_surtido', orden_id=orden.id)
        #Validar stock global disponible del articulo
        stock_global = Existencia.objects.filter(
            articulo=articulo, estado_calidad='DISPONIBLE'
        ).aggregate(total=Sum('cantidad_actual'))['total'] or Decimal('0.00')

        if cantidad_solicitada > stock_global:
            messages.error(request, f"Stock insuficiente en todo el almacen. Solicitando: {cantidad_solicitada}, Total disponible: {stock_global}")
            return redirect('inventario:ejecutar_surtido', orden_id=orden.id)
        
        #Algoritmo de asignacion en cascada
        cantidad_restante_por_surtir = cantidad_solicitada
        lotes_disponibles = Existencia.objects.filter(
            articulo=articulo,
            estado_calidad='DISPONIBLE',
            cantidad_actual__gt=0
        ).order_by('id')

        with transaction.atomic():
            for stock in lotes_disponibles:
                if cantidad_restante_por_surtir <= 0:
                    break 

                if stock.cantidad_actual <= cantidad_restante_por_surtir:
                    a_descontar = stock.cantidad_actual
                    cantidad_restante_por_surtir -= a_descontar
                    stock.cantidad_actual = Decimal('0.00')
                    stock.save()
                else:
                    a_descontar = cantidad_restante_por_surtir
                    stock.cantidad_actual = F('cantidad_actual') - a_descontar
                    stock.save()
                    cantidad_restante_por_surtir = Decimal('0.00')

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
                    usuario=request.user.username,
                    observaciones=f"Picking PEPS Aut. | Orden: {orden.folio_salida} | Destino: {orden.destino}"
                )

            nuevo_total = total_surtido + cantidad_solicitada
            if nuevo_total >= orden.meta_total:
                orden.estatus = 'COMPLETADA'
                orden.save()
                messages.success(request, f"Orden {orden.folio_salida} completada exitosamente al 100%")
                return redirect('inventario:picking_list', folio=orden.folio_salida)
            else:
                orden.estatus = 'EN_PROCESO'
                orden.save()
                messages.success(request= f"Articulos asinados correctamente. Faltan {orden.meta_total - nuevo_total} unidades")
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
            solicitante=request.user.username,
            asignado_a=asignado_a,
            destino=destino,
            meta_total=meta_total
        )
        
        # Inmediatamente después de crearla, mandamos al operador al Carrito PEPS
        return redirect('inventario:ejecutar_surtido', orden_id=orden.id)

    return render(request, 'inventario/crear_orden_salida.html')
