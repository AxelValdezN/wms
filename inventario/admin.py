from django.contrib import admin
from .models import Articulo, Localizacion, Existencia, Entrada, DetalleEntrada, Movimiento

admin.site.register(Articulo)
admin.site.register(Localizacion)
admin.site.register(Existencia)
admin.site.register(Entrada)
admin.site.register(DetalleEntrada)
admin.site.register(Movimiento)