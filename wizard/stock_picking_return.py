# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare
import json


class StockReturnPickingLine(models.TransientModel):
    _inherit = 'stock.return.picking.line'

    # ==================== CAMPOS DE LOTE ====================
    lot_ids = fields.Many2many(
        'stock.lot',
        string='Lotes a devolver',
        help='Seleccione uno o más lotes a devolver',
    )
    allowed_lot_ids = fields.Many2many(
        'stock.lot',
        'stock_return_line_allowed_lot_rel',
        'line_id', 'lot_id',
        string='Lotes permitidos',
        compute='_compute_allowed_lot_ids',
        help='Lotes entregados en este movimiento',
    )
    to_return = fields.Boolean(
        string='Devolver',
        default=True,
        help='Marcar para incluir en la devolución',
    )

    # ==================== CAMPO AUXILIAR ====================
    is_lot_tracked = fields.Boolean(
        string='Rastreo por Lote',
        readonly=True,
    )

    # JSON con {lot_id: qty} para saber cuánto corresponde a cada lote
    lot_qty_json = fields.Text(
        string='Cantidades por Lote (JSON)',
        help='Mapa interno de cantidad entregada por lote',
    )

    # ==================== CAMPOS RELATED DEL LOTE (info del primer lote seleccionado) ====================
    # Estos se mantienen para las columnas opcionales, muestran info del primer lote
    first_lot_id = fields.Many2one(
        'stock.lot',
        string='Primer Lote',
        compute='_compute_first_lot_info',
    )
    lot_bloque = fields.Char(related='first_lot_id.x_bloque', string='Bloque', readonly=True)
    lot_pedimento = fields.Char(related='first_lot_id.x_pedimento', string='Pedimento', readonly=True)
    lot_grosor = fields.Char(related='first_lot_id.x_grosor', string='Grosor', readonly=True)
    lot_alto = fields.Float(related='first_lot_id.x_alto', string='Alto (m)', readonly=True)
    lot_ancho = fields.Float(related='first_lot_id.x_ancho', string='Ancho (m)', readonly=True)
    lot_peso = fields.Float(related='first_lot_id.x_peso', string='Peso (kg)', readonly=True)
    lot_numero_placa = fields.Integer(related='first_lot_id.x_numero_placa', string='No. Placa', readonly=True)
    lot_atado = fields.Char(related='first_lot_id.x_atado', string='Atado', readonly=True)
    lot_color = fields.Char(related='first_lot_id.x_color', string='Color', readonly=True)
    lot_tipo = fields.Selection(related='first_lot_id.x_tipo', string='Tipo', readonly=True)
    lot_detalles = fields.Text(related='first_lot_id.x_detalles_placa', string='Detalles', readonly=True)
    lot_contenedor = fields.Char(related='first_lot_id.x_contenedor', string='Contenedor', readonly=True)
    lot_origen = fields.Char(related='first_lot_id.x_origen', string='Origen', readonly=True)
    lot_proveedor = fields.Char(related='first_lot_id.x_proveedor', string='Proveedor', readonly=True)

    # ==================== COMPUTES ====================
    @api.depends('move_id')
    def _compute_allowed_lot_ids(self):
        """Solo los lotes que están en la entrega original."""
        for line in self:
            if line.move_id and line.move_id.product_id.tracking in ('lot', 'serial'):
                done_lines = line.move_id.move_line_ids.filtered(
                    lambda ml: ml.state == 'done' and ml.lot_id
                )
                line.allowed_lot_ids = done_lines.mapped('lot_id')
            else:
                line.allowed_lot_ids = False

    @api.depends('lot_ids')
    def _compute_first_lot_info(self):
        """Primer lote seleccionado para los campos related."""
        for line in self:
            line.first_lot_id = line.lot_ids[:1] if line.lot_ids else False

    # ==================== ONCHANGE ====================
    @api.onchange('lot_ids')
    def _onchange_lot_ids(self):
        """Al cambiar la selección de lotes, sumar cantidades correspondientes."""
        for line in self:
            if not line.lot_ids or not line.is_lot_tracked:
                if line.is_lot_tracked:
                    line.quantity = 0.0
                    line.to_return = False
                continue

            # Obtener mapa de cantidades
            lot_qty_map = {}
            if line.lot_qty_json:
                try:
                    lot_qty_map = json.loads(line.lot_qty_json)
                except (json.JSONDecodeError, TypeError):
                    lot_qty_map = {}

            # Sumar cantidades de los lotes seleccionados
            total = 0.0
            for lot in line.lot_ids:
                lot_key = str(lot.id)
                if lot_key in lot_qty_map:
                    total += lot_qty_map[lot_key]
                elif line.move_id:
                    # Fallback: calcular desde move_lines
                    move_lines = line.move_id.move_line_ids.filtered(
                        lambda ml: ml.lot_id == lot and ml.state == 'done'
                    )
                    total += sum(move_lines.mapped('quantity'))

            line.quantity = total
            line.to_return = total > 0

    @api.onchange('to_return')
    def _onchange_to_return(self):
        """Al desmarcar, poner cantidad en 0."""
        for line in self:
            if line.is_lot_tracked:
                if not line.to_return:
                    line.quantity = 0.0
                elif line.lot_ids:
                    # Restaurar: recalcular desde lotes
                    line._onchange_lot_ids()


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
        Extiende default_get:
        - Productos sin tracking: línea normal (sin cambios)
        - Productos con tracking: una línea por producto con lot_ids pre-llenados
          con TODOS los lotes de la entrega, cantidad = suma total,
          y lot_qty_json con el mapa de cantidades por lote.
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

            if move.product_id.tracking not in ('lot', 'serial'):
                vals['is_lot_tracked'] = False
                vals['to_return'] = True
                new_lines.append((0, 0, vals))
                continue

            # === CON TRACKING ===
            done_move_lines = move.move_line_ids.filtered(
                lambda ml: ml.state == 'done' and ml.lot_id
            )

            lot_qty_map = {}
            for ml in done_move_lines:
                lot = ml.lot_id
                if lot.id not in lot_qty_map:
                    lot_qty_map[lot.id] = 0.0
                lot_qty_map[lot.id] += ml.quantity

            if not lot_qty_map:
                vals['is_lot_tracked'] = True
                vals['to_return'] = True
                new_lines.append((0, 0, vals))
                continue

            # Descontar devoluciones previas
            returned_by_lot = self._get_returned_qty_by_lot(move)

            # Calcular remaining por lote
            lot_ids_to_select = []
            lot_qty_remaining = {}
            total_remaining = 0.0

            for lot_id, delivered_qty in lot_qty_map.items():
                already_returned = returned_by_lot.get(lot_id, 0.0)
                remaining = delivered_qty - already_returned
                if float_compare(remaining, 0.0, precision_digits=4) > 0:
                    lot_ids_to_select.append(lot_id)
                    lot_qty_remaining[str(lot_id)] = remaining
                    total_remaining += remaining

            if not lot_ids_to_select:
                continue

            lot_vals = dict(vals)
            lot_vals.update({
                'lot_ids': [(6, 0, lot_ids_to_select)],
                'quantity': total_remaining,
                'to_return': True,
                'is_lot_tracked': True,
                'lot_qty_json': json.dumps(lot_qty_remaining),
            })
            new_lines.append((0, 0, lot_vals))

        res['product_return_moves'] = new_lines
        return res

    def _get_returned_qty_by_lot(self, original_move):
        """Cuánto se ha devuelto previamente por lote."""
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
        1. Poner en 0 las líneas desmarcadas
        2. Ejecutar wizard estándar
        3. Asignar lotes específicos al picking de devolución
        """
        self.ensure_one()

        lot_lines = self.product_return_moves.filtered(
            lambda l: l.is_lot_tracked and l.lot_ids
        )
        active_lot_lines = lot_lines.filtered('to_return')
        inactive_lot_lines = lot_lines.filtered(lambda l: not l.to_return)

        saved_quantities = {}
        for line in inactive_lot_lines:
            saved_quantities[line.id] = line.quantity
            line.quantity = 0.0

        # Mapa de lotes y cantidades para asignar después
        move_lot_map = {}
        for line in active_lot_lines:
            lot_qty_map = {}
            if line.lot_qty_json:
                try:
                    lot_qty_map = json.loads(line.lot_qty_json)
                except (json.JSONDecodeError, TypeError):
                    lot_qty_map = {}

            assignments = []
            for lot in line.lot_ids:
                lot_key = str(lot.id)
                if lot_key in lot_qty_map:
                    qty = lot_qty_map[lot_key]
                else:
                    # Fallback
                    move_lines = line.move_id.move_line_ids.filtered(
                        lambda ml: ml.lot_id == lot and ml.state == 'done'
                    )
                    qty = sum(move_lines.mapped('quantity'))

                if float_compare(qty, 0.0, precision_digits=4) > 0:
                    assignments.append({
                        'lot_id': lot.id,
                        'quantity': qty,
                    })

            if assignments:
                move_lot_map[line.move_id.id] = assignments

        # Validar
        total_to_return = sum(l.quantity for l in active_lot_lines)
        total_no_lot = sum(
            l.quantity for l in self.product_return_moves
            if not l.is_lot_tracked and l.quantity > 0
        )
        if float_compare(total_to_return + total_no_lot, 0.0, precision_digits=4) <= 0:
            raise UserError(_('Seleccione al menos un lote o producto para devolver.'))

        result = super().action_create_returns()

        for line_id, qty in saved_quantities.items():
            line = self.product_return_moves.browse(line_id)
            if line.exists():
                line.quantity = qty

        if result and isinstance(result, dict):
            new_picking_id = result.get('res_id')
            if new_picking_id and move_lot_map:
                self._assign_lots_to_return_picking(new_picking_id, move_lot_map)

        return result

    def _assign_lots_to_return_picking(self, picking_id, move_lot_map):
        """Crea una move_line por cada lote seleccionado en el picking de devolución."""
        picking = self.env['stock.picking'].browse(picking_id)
        if not picking.exists():
            return

        for move in picking.move_ids:
            original_move_id = move.origin_returned_move_id.id
            if original_move_id not in move_lot_map:
                continue

            lot_assignments = move_lot_map[original_move_id]

            move.move_line_ids.unlink()

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