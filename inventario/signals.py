from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Movimiento, Existencia
# Este signal se ejecuta cada vez que se crea un nuevo movimiento de entrada o salida, solo actua si es un movimiento nuevo, no una edicion.
@receiver(post_save, sender=Movimiento)
def actualizar_existencia(sender, instance, created, **kwargs):
    if created:
        existencia, _ = Existencia.objects.get_or_create(
            articulo=instance.articulo,
            localizacion=instance.localizacion,
            lote=instance.lote,
            estado_calidad=instance.estado_calidad,
            defaults={'cantidad_actual': 0}
        )
#Se actualiza con la logica limpia (matematica)
    existencia.cantidad_actual += instance.cantidad_entrada 
    existencia.cantidad_actual -= instance.cantidad_salida
    existencia.save()
