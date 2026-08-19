Prototipo WMS para operaciones de almacén

Aplicación web desarrollada con Django para digitalizar procesos de recepción, inventario, surtido y embarque que anteriormente se controlaban mediante hojas de cálculo y registros manuales.

English summary: Functional Warehouse Management System prototype built with Django and PostgreSQL. It models inbound operations, stock by SKU/location/lot, quality status, picking, outbound orders, shipments, audit logs and printable operational documents.

Objetivo

Centralizar la información operativa de un almacén y dar trazabilidad a los movimientos de producto desde la recepción hasta el despacho. El proyecto se construyó como un prototipo funcional para validar procesos con usuarios operativos.

Funcionalidades principales

Autenticación y control de acceso con el sistema de usuarios de Django.

Panel general de inventario y movimientos.

Registro de entradas, vehículos, operadores, documentos y tiempos de maniobra.

Captura e impresión de formatos tally.

Catálogo de artículos y localizaciones.

Control de existencias por artículo, ubicación, lote y estado de calidad.

Estados de inventario disponible, en cuarentena y merma.

Creación y surtido de órdenes de salida.

Generación de picking lists.

Registro de embarques, cortinas, transportes y sellos de seguridad.

Bitácora de movimientos y centro de documentación para auditoría.

Arquitectura

flowchart TD
    U[Usuario operativo] --> T[Plantillas Django]
    T --> V[Vistas y reglas de negocio]
    V --> M[Modelos Django ORM]
    M --> DB[(PostgreSQL)]
    V --> D[Documentos y reportes]

La aplicación utiliza una arquitectura monolítica basada en el patrón Model-Template-View de Django. El dominio está representado por modelos relacionados para artículos, localizaciones, lotes, existencias, entradas, movimientos, órdenes de salida y embarques.

Tecnologías

Python

Django 6

PostgreSQL

Django ORM

HTML y plantillas Django

WhiteNoise para archivos estáticos

Gunicorn como servidor WSGI

Git y GitHub

Modelo del dominio

El prototipo incluye diez entidades principales:

Articulo

Localizacion

Lote

Existencia

Entrada

DetalleEntrada

Movimiento

OrdenSalida

DetalleSalida

Embarque

Ejecución local

Requisitos

Python 3.12 o superior

PostgreSQL

Entorno virtual de Python

Instalación

git clone https://github.com/AxelValdezN/wms.git
cd wms

python -m venv .venv

Activa el entorno virtual:

# Windows
.venv\Scripts\activate

# macOS o Linux
source .venv/bin/activate

Instala las dependencias:

pip install -r requirements.txt

Configura la conexión a PostgreSQL mediante una variable de entorno:

DATABASE_URL=postgresql://usuario:contraseña@localhost:5432/wms

Después ejecuta:

python manage.py migrate
python manage.py createsuperuser
python manage.py runserver

La aplicación estará disponible en http://127.0.0.1:8000/.

Estructura del repositorio

wms/
├── inventario/              # Modelos, vistas, rutas y plantillas del dominio
├── wms_core/                # Configuración principal de Django
├── manage.py
└── requirements.txt

Estado y alcance

Este repositorio representa un prototipo funcional de portafolio. Fue utilizado para validar flujos operativos, pero no constituye una implementación productiva completa. La configuración de despliegue, los permisos por rol y las pruebas automatizadas requieren trabajo adicional antes de utilizarlo en una operación real.

Próximas mejoras

Agregar pruebas unitarias y de integración.

Implementar roles y permisos por tipo de usuario.

Exponer una API REST para integraciones externas.

Incorporar Docker y un flujo de integración continua.

Añadir métricas operativas y exportación de reportes.

Mejorar la gestión segura de variables de entorno.

Autor

Axel Nathel Valdez Noriega

GitHub · LinkedIn
