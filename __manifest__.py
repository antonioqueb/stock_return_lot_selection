# -*- coding: utf-8 -*-
{
    'name': 'Devoluciones por Lote',
    'version': '19.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': 'Selección de lotes específicos en devoluciones de entregas',
    'description': """
Devoluciones por Lote
=====================
Extiende el wizard de devoluciones de Odoo para permitir seleccionar
lotes específicos al devolver materiales desde entregas.

Funcionalidades:
- Al abrir el wizard de devolución, se muestran las líneas explotadas por lote
- Cada lote muestra su cantidad entregada y datos relevantes (bloque, pedimento, dimensiones, etc.)
- Se puede marcar con checkbox qué lotes devolver
- La cantidad se auto-completa al seleccionar un lote
- Compatible con productos rastreados por lote del módulo de inventario de piedra/mármol
    """,
    'author': 'Alphaqueb Consulting',
    'website': 'https://www.alphaqueb.com',
    'license': 'LGPL-3',
    'depends': ['stock'],
    'data': [
        'views/stock_return_picking_views.xml',
    ],
    'installable': True,
    'auto_install': False,
    'application': False,
}
