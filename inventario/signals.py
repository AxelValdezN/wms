from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db import transaction
from .models import Movimiento, Existencia

@receiver(post_save, sender=Movimiento)
def actualizar_existencia(sender, instance, created, **kwargs):
    if created:
        # Abrimos la bóveda ANTES de buscar o crear
        with transaction.atomic():
            # select_for_update() encadena el bloqueo desde el momento de la consulta
            existencia_lock, _ = Existencia.objects.select_for_update().get_or_create(
                articulo=instance.articulo,
                localizacion=instance.localizacion,
                lote=instance.lote,
                estado_calidad=instance.estado_calidad,
                defaults={'cantidad_actual': 0}
            )
            
            # Matemática fría y aislada
            existencia_lock.cantidad_actual += instance.cantidad_entrada
            existencia_lock.cantidad_actual -= instance.cantidad_salida
            existencia_lock.save()