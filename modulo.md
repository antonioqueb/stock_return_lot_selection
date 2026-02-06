## ./__init__.py
```py
# -*- coding: utf-8 -*-
from . import wizard
```

## ./__manifest__.py
```py
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
    'depends': ['stock', 'stock_lot_dimensions'],
    'installable': True,
    'auto_install': False,
    'application': False,
}
```

## ./views/stock_return_picking_views.xml
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>

    <!--
        Herencia de la vista del wizard de devolución de picking.
        ID externo original: stock.view_stock_return_picking_form
        Modelo: stock.return.picking

        Estrategia:
        - Reemplazar el tree de product_return_moves para agregar los campos de lote
        - Agregar checkbox de selección, campo de lote y campos related
        - Los campos de lote solo se muestran cuando el producto tiene tracking
    -->
    <record id="view_stock_return_picking_form_lot_selection" model="ir.ui.view">
        <field name="name">stock.return.picking.form.lot.selection</field>
        <field name="model">stock.return.picking</field>
        <field name="inherit_id" ref="stock.view_stock_return_picking_form"/>
        <field name="priority">20</field>
        <field name="arch" type="xml">

            <!-- Agregar indicador arriba del tree -->
            <xpath expr="//field[@name='product_return_moves']" position="before">
                <div invisible="not has_lot_products" class="alert alert-info mb-2" role="alert">
                    <strong>📦 Productos con lotes detectados.</strong>
                    Marque la casilla <strong>"Devolver"</strong> en los lotes que desea regresar.
                    La cantidad se auto-completa.
                </div>
                <field name="has_lot_products" invisible="1"/>
            </xpath>

            <!-- Reemplazar el contenido del tree de product_return_moves -->
            <xpath expr="//field[@name='product_return_moves']/list" position="replace">
                <list editable="bottom"
                      create="1"
                      decoration-warning="not move_id"
                      decoration-success="to_return and is_lot_tracked"
                      decoration-muted="is_lot_tracked and not to_return">

                    <!-- Campos originales (ocultos y técnicos) -->
                    <field name="move_quantity" column_invisible="1"/>
                    <field name="move_id" column_invisible="True"/>
                    <field name="is_lot_tracked" column_invisible="1"/>
                    <field name="lot_delivered_qty" column_invisible="1"/>

                    <!-- Checkbox para devolver -->
                    <field name="to_return" string="✓" width="40px"/>

                    <!-- Producto -->
                    <field name="product_id" force_save="1" readonly="is_lot_tracked"/>

                    <!-- Lote -->
                    <field name="lot_id"
                           string="Lote / Serie"
                           options="{'no_create': True}"
                           readonly="0"/>

                    <!-- Campos del lote - info visual rápida -->
                    <field name="lot_bloque" string="Bloque" optional="show"/>
                    <field name="lot_numero_placa" string="No. Placa" optional="show"/>
                    <field name="lot_atado" string="Atado" optional="hide"/>
                    <field name="lot_grosor" string="Grosor" optional="show"/>
                    <field name="lot_alto" string="Alto" optional="hide"/>
                    <field name="lot_ancho" string="Ancho" optional="hide"/>
                    <field name="lot_peso" string="Peso" optional="hide"/>
                    <field name="lot_color" string="Color" optional="hide"/>
                    <field name="lot_pedimento" string="Pedimento" optional="hide"/>
                    <field name="lot_contenedor" string="Contenedor" optional="hide"/>
                    <field name="lot_origen" string="Origen" optional="hide"/>
                    <field name="lot_proveedor" string="Proveedor" optional="hide"/>
                    <field name="lot_tipo" string="Tipo" optional="hide"/>
                    <field name="lot_detalles" string="Nota" optional="hide"/>

                    <!-- Cantidad a devolver -->
                    <field name="quantity"
                           string="Cantidad a Devolver"
                           decoration-danger="move_quantity &lt; quantity"/>

                    <!-- UdM -->
                    <field name="uom_id" widget="many2one_uom" groups="uom.group_uom"/>
                </list>
            </xpath>

        </field>
    </record>

</odoo>
```

## ./wizard/__init__.py
```py
# -*- coding: utf-8 -*-
from . import stock_picking_return
```

## ./wizard/stock_picking_return.py
```py
# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare


class StockReturnPickingLine(models.TransientModel):
    _inherit = 'stock.return.picking.line'

    # ==================== CAMPOS DE LOTE ====================
    lot_id = fields.Many2one(
        'stock.lot',
        string='Lote',
        help='Lote específico a devolver',
    )
    to_return = fields.Boolean(
        string='Devolver',
        default=True,
        help='Marcar para incluir este lote en la devolución',
    )
    lot_delivered_qty = fields.Float(
        string='Qty Entregada',
        digits='Product Unit of Measure',
        readonly=True,
        help='Cantidad original entregada de este lote',
    )

    # ==================== CAMPOS RELATED DEL LOTE ====================
    lot_bloque = fields.Char(related='lot_id.x_bloque', string='Bloque', readonly=True)
    lot_pedimento = fields.Char(related='lot_id.x_pedimento', string='Pedimento', readonly=True)
    lot_grosor = fields.Char(related='lot_id.x_grosor', string='Grosor', readonly=True)
    lot_alto = fields.Float(related='lot_id.x_alto', string='Alto (m)', readonly=True)
    lot_ancho = fields.Float(related='lot_id.x_ancho', string='Ancho (m)', readonly=True)
    lot_peso = fields.Float(related='lot_id.x_peso', string='Peso (kg)', readonly=True)
    lot_numero_placa = fields.Integer(related='lot_id.x_numero_placa', string='No. Placa', readonly=True)
    lot_atado = fields.Char(related='lot_id.x_atado', string='Atado', readonly=True)
    lot_color = fields.Char(related='lot_id.x_color', string='Color', readonly=True)
    lot_tipo = fields.Selection(related='lot_id.x_tipo', string='Tipo', readonly=True)
    lot_detalles = fields.Text(related='lot_id.x_detalles_placa', string='Detalles', readonly=True)
    lot_contenedor = fields.Char(related='lot_id.x_contenedor', string='Contenedor', readonly=True)
    lot_origen = fields.Char(related='lot_id.x_origen', string='Origen', readonly=True)
    lot_proveedor = fields.Char(related='lot_id.x_proveedor', string='Proveedor', readonly=True)

    # ==================== CAMPO AUXILIAR ====================
    is_lot_tracked = fields.Boolean(
        string='Rastreo por Lote',
        readonly=True,
        help='Indica si el producto se rastrea por lote',
    )

    # ==================== ONCHANGE ====================
    @api.onchange('to_return')
    def _onchange_to_return(self):
        """Al desmarcar, poner cantidad en 0. Al marcar, restaurar."""
        for line in self:
            if line.is_lot_tracked:
                if not line.to_return:
                    line.quantity = 0.0
                elif line.lot_delivered_qty > 0:
                    line.quantity = line.lot_delivered_qty


class StockReturnPicking(models.TransientModel):
    _inherit = 'stock.return.picking'

    has_lot_products = fields.Boolean(
        compute='_compute_has_lot_products',
        string='Tiene productos con lotes',
    )

    @api.depends('product_return_moves.is_lot_tracked')
    def _compute_has_lot_products(self):
        for wizard in self:
            wizard.has_lot_products = any(
                line.is_lot_tracked for line in wizard.product_return_moves
            )

    @api.model
    def default_get(self, fields_list):
        """
        Extiende el default_get para explotar las líneas por lote.
        
        El wizard estándar crea una línea por stock.move (producto).
        Nosotros la explotamos en N líneas: una por cada lote entregado.
        """
        res = super().default_get(fields_list)

        if 'product_return_moves' not in fields_list:
            return res

        active_id = self.env.context.get('active_id')
        if not active_id:
            return res

        picking = self.env['stock.picking'].browse(active_id)
        if not picking.exists() or picking.state != 'done':
            return res

        original_lines = res.get('product_return_moves', [])
        if not original_lines:
            return res

        new_lines = []

        for line_tuple in original_lines:
            if line_tuple[0] != 0:
                new_lines.append(line_tuple)
                continue

            vals = line_tuple[2]
            move_id = vals.get('move_id')
            if not move_id:
                vals['is_lot_tracked'] = False
                vals['to_return'] = True
                new_lines.append((0, 0, vals))
                continue

            move = self.env['stock.move'].browse(move_id)

            # Sin tracking por lote: dejar la línea original
            if move.product_id.tracking not in ('lot', 'serial'):
                vals['is_lot_tracked'] = False
                vals['to_return'] = True
                new_lines.append((0, 0, vals))
                continue

            # === CON TRACKING POR LOTE ===
            # Explotar por cada lote en las move_lines done
            done_move_lines = move.move_line_ids.filtered(
                lambda ml: ml.state == 'done' and ml.lot_id
            )

            # Agrupar por lote
            lot_qty_map = {}
            for ml in done_move_lines:
                lot = ml.lot_id
                if lot.id not in lot_qty_map:
                    lot_qty_map[lot.id] = {'lot': lot, 'qty': 0.0}
                lot_qty_map[lot.id]['qty'] += ml.quantity

            if not lot_qty_map:
                vals['is_lot_tracked'] = True
                vals['to_return'] = True
                new_lines.append((0, 0, vals))
                continue

            # Descontar devoluciones previas
            returned_by_lot = self._get_returned_qty_by_lot(move)

            for lot_data in lot_qty_map.values():
                lot = lot_data['lot']
                delivered_qty = lot_data['qty']
                already_returned = returned_by_lot.get(lot.id, 0.0)
                remaining_qty = delivered_qty - already_returned

                if float_compare(remaining_qty, 0.0, precision_digits=4) <= 0:
                    continue

                lot_vals = dict(vals)
                lot_vals.update({
                    'lot_id': lot.id,
                    'quantity': remaining_qty,
                    'lot_delivered_qty': remaining_qty,
                    'to_return': True,
                    'is_lot_tracked': True,
                })
                new_lines.append((0, 0, lot_vals))

        res['product_return_moves'] = new_lines
        return res

    def _get_returned_qty_by_lot(self, original_move):
        """Cuánto se ha devuelto previamente por lote para un movimiento."""
        returned_moves = self.env['stock.move'].search([
            ('origin_returned_move_id', '=', original_move.id),
            ('state', '=', 'done'),
        ])
        result = {}
        for ret_move in returned_moves:
            for ml in ret_move.move_line_ids.filtered(
                lambda l: l.state == 'done' and l.lot_id
            ):
                lot_id = ml.lot_id.id
                result[lot_id] = result.get(lot_id, 0.0) + ml.quantity
        return result

    def action_create_returns(self):
        """
        Extiende para:
        1. Poner en 0 las líneas de lote desmarcadas (to_return=False)
        2. Ejecutar el wizard estándar
        3. Asignar lotes específicos en el picking de devolución
        """
        self.ensure_one()

        lot_lines = self.product_return_moves.filtered(
            lambda l: l.is_lot_tracked and l.lot_id
        )
        active_lot_lines = lot_lines.filtered('to_return')
        inactive_lot_lines = lot_lines.filtered(lambda l: not l.to_return)

        # Guardar y anular cantidades de líneas no marcadas
        saved_quantities = {}
        for line in inactive_lot_lines:
            saved_quantities[line.id] = line.quantity
            line.quantity = 0.0

        # Mapa de lotes para asignar después
        move_lot_map = {}
        for line in active_lot_lines:
            if line.move_id.id not in move_lot_map:
                move_lot_map[line.move_id.id] = []
            move_lot_map[line.move_id.id].append({
                'lot_id': line.lot_id.id,
                'quantity': line.quantity,
            })

        # Validar que haya algo que devolver
        total_to_return = sum(l.quantity for l in active_lot_lines)
        total_no_lot = sum(
            l.quantity for l in self.product_return_moves
            if not l.is_lot_tracked and l.quantity > 0
        )
        if float_compare(total_to_return + total_no_lot, 0.0, precision_digits=4) <= 0:
            raise UserError(_('Seleccione al menos un lote o producto para devolver.'))

        # Ejecutar wizard estándar
        result = super().action_create_returns()

        # Restaurar cantidades
        for line_id, qty in saved_quantities.items():
            line = self.product_return_moves.browse(line_id)
            if line.exists():
                line.quantity = qty

        # Asignar lotes en el picking de devolución
        if result and isinstance(result, dict):
            new_picking_id = result.get('res_id')
            if new_picking_id and move_lot_map:
                self._assign_lots_to_return_picking(new_picking_id, move_lot_map)

        return result

    def _assign_lots_to_return_picking(self, picking_id, move_lot_map):
        """Asigna lotes específicos en las move_lines del picking de devolución."""
        picking = self.env['stock.picking'].browse(picking_id)
        if not picking.exists():
            return

        for move in picking.move_ids:
            original_move_id = move.origin_returned_move_id.id
            if original_move_id not in move_lot_map:
                continue

            lot_assignments = move_lot_map[original_move_id]

            # Eliminar move_lines genéricas del wizard estándar
            move.move_line_ids.unlink()

            # Crear una move_line por cada lote seleccionado
            for assignment in lot_assignments:
                if float_compare(assignment['quantity'], 0.0, precision_digits=4) <= 0:
                    continue
                self.env['stock.move.line'].create({
                    'move_id': move.id,
                    'picking_id': picking.id,
                    'product_id': move.product_id.id,
                    'product_uom_id': move.product_uom.id,
                    'lot_id': assignment['lot_id'],
                    'quantity': assignment['quantity'],
                    'location_id': move.location_id.id,
                    'location_dest_id': move.location_dest_id.id,
                    'company_id': move.company_id.id,
                })```

