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
        default=False,
        help='Marcar para incluir este lote en la devolución',
    )
    lot_delivered_qty = fields.Float(
        string='Qty Entregada',
        digits='Product Unit of Measure',
        readonly=True,
        help='Cantidad original entregada de este lote',
    )

    # ==================== CAMPOS RELATED DEL LOTE ====================
    lot_bloque = fields.Char(
        related='lot_id.x_bloque',
        string='Bloque',
        readonly=True,
    )
    lot_pedimento = fields.Char(
        related='lot_id.x_pedimento',
        string='Pedimento',
        readonly=True,
    )
    lot_grosor = fields.Char(
        related='lot_id.x_grosor',
        string='Grosor',
        readonly=True,
    )
    lot_alto = fields.Float(
        related='lot_id.x_alto',
        string='Alto (m)',
        readonly=True,
    )
    lot_ancho = fields.Float(
        related='lot_id.x_ancho',
        string='Ancho (m)',
        readonly=True,
    )
    lot_peso = fields.Float(
        related='lot_id.x_peso',
        string='Peso (kg)',
        readonly=True,
    )
    lot_numero_placa = fields.Integer(
        related='lot_id.x_numero_placa',
        string='No. Placa',
        readonly=True,
    )
    lot_atado = fields.Char(
        related='lot_id.x_atado',
        string='Atado',
        readonly=True,
    )
    lot_color = fields.Char(
        related='lot_id.x_color',
        string='Color',
        readonly=True,
    )
    lot_tipo = fields.Selection(
        related='lot_id.x_tipo',
        string='Tipo',
        readonly=True,
    )
    lot_detalles = fields.Text(
        related='lot_id.x_detalles_placa',
        string='Detalles',
        readonly=True,
    )
    lot_contenedor = fields.Char(
        related='lot_id.x_contenedor',
        string='Contenedor',
        readonly=True,
    )
    lot_origen = fields.Char(
        related='lot_id.x_origen',
        string='Origen',
        readonly=True,
    )
    lot_proveedor = fields.Char(
        related='lot_id.x_proveedor',
        string='Proveedor',
        readonly=True,
    )

    # ==================== CAMPO AUXILIAR ====================
    is_lot_tracked = fields.Boolean(
        string='Rastreo por Lote',
        readonly=True,
        help='Indica si el producto se rastrea por lote',
    )

    # ==================== ONCHANGE ====================
    @api.onchange('lot_id')
    def _onchange_lot_id(self):
        """Al cambiar el lote, auto-completar la cantidad entregada de ese lote."""
        for line in self:
            if line.lot_id and line.move_id:
                # Buscar en las move_lines del movimiento original la cantidad de este lote
                move_lines = line.move_id.move_line_ids.filtered(
                    lambda ml: ml.lot_id == line.lot_id and ml.state == 'done'
                )
                qty = sum(move_lines.mapped('quantity'))
                line.quantity = qty
                line.lot_delivered_qty = qty
                if qty > 0:
                    line.to_return = True

    @api.onchange('to_return')
    def _onchange_to_return(self):
        """Al desmarcar, poner cantidad en 0. Al marcar, restaurar."""
        for line in self:
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

    @api.depends('product_return_moves.lot_id')
    def _compute_has_lot_products(self):
        for wizard in self:
            wizard.has_lot_products = any(
                line.is_lot_tracked for line in wizard.product_return_moves
            )

    @api.model
    def default_get(self, fields_list):
        """
        Extiende el default_get para explotar las líneas por lote.

        Lógica:
        - El wizard estándar crea una línea por producto/movimiento
        - Nosotros interceptamos DESPUÉS y explotamos cada línea en N líneas,
          una por cada lote que fue entregado en ese movimiento
        - Para productos sin tracking por lote, se deja la línea original intacta
        """
        res = super().default_get(fields_list)

        if 'product_return_moves' not in fields_list:
            return res

        # Obtener el picking original
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
            # line_tuple es (0, 0, {vals}) formato command
            if line_tuple[0] != 0:
                new_lines.append(line_tuple)
                continue

            vals = line_tuple[2]
            move_id = vals.get('move_id')
            if not move_id:
                new_lines.append(line_tuple)
                continue

            move = self.env['stock.move'].browse(move_id)

            # Verificar si el producto tiene tracking por lote
            if move.product_id.tracking not in ('lot', 'serial'):
                # Sin tracking: dejar la línea como está
                vals['is_lot_tracked'] = False
                new_lines.append((0, 0, vals))
                continue

            # Con tracking por lote: explotar por cada lote en las move_lines done
            done_move_lines = move.move_line_ids.filtered(
                lambda ml: ml.state == 'done' and ml.lot_id
            )

            # Agrupar por lote y sumar cantidades
            lot_qty_map = {}
            for ml in done_move_lines:
                lot = ml.lot_id
                if lot.id not in lot_qty_map:
                    lot_qty_map[lot.id] = {
                        'lot': lot,
                        'qty': 0.0,
                    }
                lot_qty_map[lot.id]['qty'] += ml.quantity

            if not lot_qty_map:
                # Si no hay move_lines con lote (raro), dejar línea original
                vals['is_lot_tracked'] = True
                new_lines.append((0, 0, vals))
                continue

            # Calcular cuánto ya fue devuelto por lote (de devoluciones previas)
            returned_by_lot = self._get_returned_qty_by_lot(move)

            # Crear una línea por cada lote entregado
            for lot_data in lot_qty_map.values():
                lot = lot_data['lot']
                delivered_qty = lot_data['qty']

                # Restar lo ya devuelto de este lote
                already_returned = returned_by_lot.get(lot.id, 0.0)
                remaining_qty = delivered_qty - already_returned

                if float_compare(remaining_qty, 0.0, precision_digits=4) <= 0:
                    # Este lote ya fue devuelto completamente, no mostrar
                    continue

                lot_vals = dict(vals)
                lot_vals.update({
                    'lot_id': lot.id,
                    'quantity': remaining_qty,
                    'lot_delivered_qty': remaining_qty,
                    'to_return': False,  # El usuario marca cuáles devolver
                    'is_lot_tracked': True,
                })
                new_lines.append((0, 0, lot_vals))

        res['product_return_moves'] = new_lines
        return res

    def _get_returned_qty_by_lot(self, original_move):
        """
        Calcula cuánto se ha devuelto previamente por lote para un movimiento dado.
        Busca en los movimientos de devolución (origin_returned_move_id) que ya estén done.

        Returns:
            dict: {lot_id: qty_returned}
        """
        returned_moves = self.env['stock.move'].search([
            ('origin_returned_move_id', '=', original_move.id),
            ('state', '=', 'done'),
        ])

        result = {}
        for ret_move in returned_moves:
            for ml in ret_move.move_line_ids.filtered(lambda l: l.state == 'done' and l.lot_id):
                lot_id = ml.lot_id.id
                result[lot_id] = result.get(lot_id, 0.0) + ml.quantity

        return result

    def action_create_returns(self):
        """
        Extiende la creación de devoluciones.
        Para productos con lote: solo devuelve las líneas marcadas con to_return=True
        y crea move_lines específicas por lote en el picking de devolución.
        """
        self.ensure_one()

        # Separar líneas con lote marcadas para devolver y líneas normales
        lot_lines = self.product_return_moves.filtered(
            lambda l: l.is_lot_tracked and l.lot_id
        )
        active_lot_lines = lot_lines.filtered('to_return')
        inactive_lot_lines = lot_lines.filtered(lambda l: not l.to_return)

        # Para las líneas con lote NO marcadas, poner cantidad en 0
        # para que el wizard estándar no las procese
        saved_quantities = {}
        for line in inactive_lot_lines:
            saved_quantities[line.id] = line.quantity
            line.quantity = 0.0

        # Mapear move_id -> lista de (lot_id, qty) para después asignar lotes
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

        # Ejecutar el wizard estándar
        result = super().action_create_returns()

        # Restaurar cantidades (por si el TransientModel persiste)
        for line_id, qty in saved_quantities.items():
            line = self.product_return_moves.browse(line_id)
            if line.exists():
                line.quantity = qty

        # Ajustar las move_lines del picking de devolución creado
        # para asignar los lotes correctos
        if result and isinstance(result, dict):
            new_picking_id = result.get('res_id')
            if new_picking_id and move_lot_map:
                self._assign_lots_to_return_picking(new_picking_id, move_lot_map)

        return result

    def _assign_lots_to_return_picking(self, picking_id, move_lot_map):
        """
        Ajusta las move_lines del picking de devolución para asignar los lotes específicos.

        Args:
            picking_id: ID del picking de devolución creado
            move_lot_map: dict {original_move_id: [{lot_id, quantity}, ...]}
        """
        picking = self.env['stock.picking'].browse(picking_id)
        if not picking.exists():
            return

        for move in picking.move_ids:
            # El move de devolución tiene origin_returned_move_id apuntando al original
            original_move_id = move.origin_returned_move_id.id
            if original_move_id not in move_lot_map:
                continue

            lot_assignments = move_lot_map[original_move_id]

            # Eliminar las move_lines genéricas que creó el wizard estándar
            move.move_line_ids.unlink()

            # Crear una move_line por cada lote
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
                })
