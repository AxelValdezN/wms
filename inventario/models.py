from django.db import models
#genera automaticamente el campo id_articulo como PK
class Articulo (models.Model):
    clave = models.CharField(max_length=50, unique=True)
    descripcion = models.CharField(max_length=255)
    unidad_medida = models.CharField(max_length=20)
    familia = models.CharField(max_length=100)

    CLASIFICACION_CHOICES = [
        ('A', 'Alta rotación (Ubicaciones cercanas)'),
        ('B', 'Media rotación'),
        ('C', 'Baja rotación(Ubicaciones lejanas)'),
    ]
    clasificacion = models.CharField(max_length=1, choices=CLASIFICACION_CHOICES)
    estatus = models.BooleanField(default=True)
    def __str__(self):
        return f"{self.clave} - {self.descripcion}"
#genera automaticamente el campo id_localizacion como PK
class Localizacion(models.Model):
    TIPO_CHOICES = [
        ('RACK', 'Rack'),
        ('PISO', 'Piso'),
    ]
    clave = models.CharField(max_length=50, unique=True)
    almacen = models.CharField(max_length=50)
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES, default='RACK')
    estatus = models.BooleanField(default=True)
    def __str__(self):
        return f"{self.almacen} - {self.clave}"
    
class Existencia(models.Model):
    ESTADO_CHOICES = [
        ('DISPONIBLE', 'Disponible para uso'),
        ('EN_CUARENTENA', 'En cuarentena / Pendiente de revisión / Pendiente de liberación'),
        ('MERMA', 'Merma / Dañado / Perdido / Obsoleto'),
    ]
    articulo = models.ForeignKey(Articulo, on_delete=models.RESTRICT)
    localizacion = models.ForeignKey(Localizacion, on_delete=models.RESTRICT)
    lote = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='DISPONIBLE')
    estado_calidad = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='DISPONIBLE')
    cantidad_actual = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    fecha_ultimo_movimiento = models.DateTimeField(auto_now=True)
#agregamos la restriccion logica para UNIQUE en la combinacion de articulo y localizacion
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['articulo', 'localizacion', 'lote', 'estado_calidad'],
                name='unique_existencia_art_loc_lote_estado'
            )
        ]
    def __str__(self):
        return f"{self.articulo.clave} | Lote: {self.lote} | {self.estado_calidad} | {self.cantidad_actual}"

class Entrada(models.Model):
    folio_entrada = models.CharField(max_length=50, unique=True)
    fecha = models.DateTimeField(auto_now_add=True)
    cliente = models.CharField(max_length=100)
    documento_referencia = models.CharField(max_length=100, blank=True, null=True)
    usuario = models.CharField(max_length=100)
    estatus = models.BooleanField(default=True)
    def __str__(self):
        return f"Entrada {self.folio_entrada}"
class DetalleEntrada(models.Model):
    entrada = models.ForeignKey(Entrada, on_delete=models.CASCADE, related_name='detalles')
    articulo = models.ForeignKey(Articulo, on_delete=models.RESTRICT)
    localizacion = models.ForeignKey(Localizacion, on_delete=models.RESTRICT)
    cantidad_recibida = models.DecimalField(max_digits=12, decimal_places=2)
    lote = models.CharField(max_length=50, blank=True, null=True)
    fecha_caducidad = models.DateField(blank=True, null=True)
    def __str__(self):
        return f"{self.entrada.folio_entrada} de {self.articulo.clave}"
class Movimiento(models.Model):
    TIPO_MOVIMIENTO_CHOICES = [
        ('ENTRADA', 'Entrada'),
        ('SALIDA', 'Salida'),
        ('AJUSTE', 'Ajuste'),
        ('TRANSFERENCIA', 'Transferencia'),
        ('CAMBIO_ESTADO', 'Cambio de estatus de calidad'),
    ]
    ESTADO_CHOICES = [
        ('DISPONIBLE', 'Disponible'),
        ('EN_CUARENTENA', 'En cuarentena'),
        ('MERMA', 'Merma'),
    ]
    tipo_movimiento = models.CharField(max_length=20, choices=TIPO_MOVIMIENTO_CHOICES)
    fecha = models.DateTimeField(auto_now_add=True)
    folio_referencia = models.CharField(max_length=50, blank=True, null=True)
    articulo = models.ForeignKey(Articulo, on_delete=models.RESTRICT)
    localizacion = models.ForeignKey(Localizacion, on_delete=models.RESTRICT)
    lote = models.CharField(max_length=50, default='S/N')
    estado_calidad = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='DISPONIBLE')
    cantidad_entrada = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cantidad_salida = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    usuario = models.CharField(max_length=100)
    observaciones = models.TextField(blank=True, null=True)
   
    def __str__(self):
        return f"{self.tipo_movimiento} | {self.articulo.clave} | (Lote {self.lote}) | {self.fecha.strftime('%Y-%m-%d')}"
class OrdenSalida(models.Model):
    ESTATUS_CHOICES = [
        ('PENDIENTE', 'Pendiente de Surtir'),
        ('EN_PROCESO', 'Surtido en Proceso'),
        ('COMPLETADA', 'Completada y Validada'),
    ]
    
    folio_salida = models.CharField(max_length=50, unique=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    solicitante = models.CharField(max_length=100)
    asignado_a = models.CharField(max_length=100)
    destino = models.CharField(max_length=100)
    meta_total = models.DecimalField(max_digits=12, decimal_places=2)
    estatus = models.CharField(max_length=20, choices=ESTATUS_CHOICES, default='PENDIENTE')
    
    def _str_(self):
        return f"Orden {self.folio_salida} | Destino: {self.destino} | Asignado a: {self.asignado_a}"

class DetalleSalida(models.Model):
    orden = models.ForeignKey(OrdenSalida, on_delete=models.CASCADE, related_name='detalles')
    articulo = models.ForeignKey(Articulo, on_delete=models.RESTRICT)
    localizacion = models.ForeignKey(Localizacion, on_delete=models.RESTRICT)
    lote = models.CharField(max_length=50)
    cantidad_surtida = models.DecimalField(max_digits=12, decimal_places=2)

    def _str_(self):
        return f"{self.cantidad_surtida} de {self.articulo.clave} (Lote: {self.lote})"
    
    