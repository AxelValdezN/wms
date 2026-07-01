from django.urls import path
from . import views

app_name = 'inventario'
urlpatterns = [
    path('dashboard/', views.dashboard_inventario, name='dashboard'),
    path('entradas/nueva/', views.registrar_entrada, name='nueva_entrada'),
    path('cambiar_liberacion/', views.cambiar_estatus, name='cambiar_estatus'),
    path('salidas/nueva/', views.registrar_salida, name='nueva_salida'),
    path('catalogos/articulos/', views.catalogo_articulos, name='catalogo_articulos'),
    path('catalogos/localizaciones/', views.catalogo_localizaciones, name='catalogo_localizaciones'),
    path('picking_list/<str:folio>/', views.generar_picking_list, name='picking_list'),
    path('bitacora/', views.bitacora_movimientos, name='bitacora'),
    path('salidas/nueva-orden/', views.crear_orden_salida, name='crear_orden_salida'),
    path('salidas/surtir/<int:orden_id>/', views.ejecutar_surtido, name='ejecutar_surtido'),
    path('salidas/tally/nueva/', views.crear_tally_cabecera, name='crear_tally_cabecera'),
    path('entradas/tally/nueva/', views.crear_tally_cabecera, name='crear_tally_cabecera'),
    path('entradas/tally/<int:entrada_id>/detalles/', views.capturar_tally_detalles, name='capturar_tally_detalles'),
    path('entradas/tally/<int:entrada_id>/imprimir/', views.imprimir_tally, name='imprimir_tally'),
    path('auditoria/documentos/', views.centro_documentacion, name='centro_documentacion'),
    path('salidas/despacho/', views.registrar_embarque, name='registrar_embarque'),
    path('auditoria/recibos/detalle/<int:entrada_id>/', views.detalle_recibo, name='detalle_recibo'),
    path('auditoria/surtidos/detalle/<int:salida_id>/', views.detalle_surtido, name='detalle_surtido'),
    path('catalogo/', views.catalogo_articulos, name='catalogo_articulos'),
    path('catalogo/eliminar/<int:articulo_id>/', views.eliminar_sku_hibrido, name='eliminar_sku'),
    path('catalogo/detalle/<int:articulo_id>/', views.sku, name='detalle_sku'),
    path('catalogo/reactivar/<int:articulo_id>/'), views.reactivar_sku, name='reactivar_sku)',
]