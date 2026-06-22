from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db import transaction
from .models import Movimiento, Existencia

@receiver(post_save, sender=Movimiento)
def actualizar_existencia(sender, instance, created, **kwargs):
    if created:
        # : garantisamos que la existencia base esté ahí (sin el bloqueo aun)
        existencia_base, _ = Existencia.objects.get_or_create(
            articulo=instance.articulo,
            localizacion=instance.localizacion,
            lote=instance.lote,
            estado_calidad=instance.estado_calidad,
            defaults={'cantidad_actual': 0}
        )

        # Abrimos la transiction atomic y ponemos el candado a ESA fila exacta
        with transaction.atomic():
            # select_for_update() impide que otro Signal toque este saldo al mismo tiempo
            existencia_lock = Existencia.objects.select_for_update().get(id=existencia_base.id)
            
            # Matemática fría y aislada
            existencia_lock.cantidad_actual += instance.cantidad_entrada
            existencia_lock.cantidad_actual -= instance.cantidad_salida
            existencia_lock.save()