# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare
import json

_logger = logging.getLogger(__name__)


class StockReturnPickingLine(models.TransientModel):
    _inherit = 'stock.return.picking.line'

    lot_ids = fields.Many2many(
        'stock.lot',
        string='Lotes a devolver',
    )
    allowed_lot_ids = fields.Many2many(
        'stock.lot',
        'stock_return_line_allowed_lot_rel',
        'line_id', 'lot_id',
        string='Lotes permitidos',
        compute='_compute_allowed_lot_ids',
    )
    to_return = fields.Boolean(
        string='Devolver',
        default=True,
    )
    is_lot_tracked = fields.Boolean(
        string='Rastreo por Lote',
        readonly=True,
    )
    # JSON: {"lot_id_str": qty, ...}
    lot_qty_json = fields.Text(
        string='Cantidades por Lote',
    )

    @api.depends('move_id')
    def _compute_allowed_lot_ids(self):
        for line in self:
            if line.move_id and line.move_id.product_id.tracking in ('lot', 'serial'):
                done_lines = line.move_id.move_line_ids.filtered(
                    lambda ml: ml.state == 'done' and ml.lot_id
                )
                line.allowed_lot_ids = done_lines.mapped('lot_id')
            else:
                line.allowed_lot_ids = False

    @api.onchange('lot_ids')
    def _onchange_lot_ids(self):
        for line in self:
            _logger.info(
                '[LOT_RETURN] onchange lot_ids fired. '
                'is_lot_tracked=%s, lot_ids=%s, lot_qty_json=%s, move_id=%s',
                line.is_lot_tracked,
                line.lot_ids.ids if line.lot_ids else [],
                line.lot_qty_json,
                line.move_id.id if line.move_id else False,
            )

            if not line.is_lot_tracked:
                continue

            if not line.lot_ids:
                line.quantity = 0.0
                line.to_return = False
                _logger.info('[LOT_RETURN] No lots selected, qty=0')
                continue

            # Intentar obtener cantidades del JSON pre-calculado
            lot_qty_map = {}
            if line.lot_qty_json:
                try:
                    lot_qty_map = json.loads(line.lot_qty_json)
                    _logger.info('[LOT_RETURN] lot_qty_map from JSON: %s', lot_qty_map)
                except (json.JSONDecodeError, TypeError) as e:
                    _logger.warning('[LOT_RETURN] Failed to parse lot_qty_json: %s', e)

            total = 0.0
            for lot in line.lot_ids:
                lot_key = str(lot.id)
                qty = 0.0

                if lot_key in lot_qty_map:
                    qty = lot_qty_map[lot_key]
                    _logger.info('[LOT_RETURN] Lot %s (id=%s) from JSON: qty=%s', lot.name, lot.id, qty)
                elif line.move_id:
                    # Fallback: buscar en move_lines
                    mls = line.move_id.move_line_ids.filtered(
                        lambda ml, l=lot: ml.lot_id.id == l.id and ml.state == 'done'
                    )
                    qty = sum(mls.mapped('quantity'))
                    _logger.info('[LOT_RETURN] Lot %s (id=%s) from move_lines fallback: qty=%s', lot.name, lot.id, qty)
                else:
                    _logger.warning('[LOT_RETURN] Lot %s (id=%s) - no JSON and no move_id!', lot.name, lot.id)

                total += qty

            line.quantity = total
            line.to_return = total > 0
            _logger.info('[LOT_RETURN] Final quantity=%s, to_return=%s', total, line.to_return)

    @api.onchange('to_return')
    def _onchange_to_return(self):
        for line in self:
            if line.is_lot_tracked:
                if not line.to_return:
                    line.quantity = 0.0
                elif line.lot_ids:
                    line._onchange_lot_ids()


class StockReturnPicking(models.TransientModel):
    _inherit = 'stock.return.picking'

    has_lot_products = fields.Boolean(
        compute='_compute_has_lot_products',
    )

    @api.depends('product_return_moves.is_lot_tracked')
    def _compute_has_lot_products(self):
        for wizard in self:
            wizard.has_lot_products = any(
                line.is_lot_tracked for line in wizard.product_return_moves
            )

    @api.model
    def default_get(self, fields_list):
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
                lid = ml.lot_id.id
                lot_qty_map[lid] = lot_qty_map.get(lid, 0.0) + ml.quantity

            if not lot_qty_map:
                vals['is_lot_tracked'] = True
                vals['to_return'] = True
                new_lines.append((0, 0, vals))
                continue

            returned_by_lot = self._get_returned_qty_by_lot(move)

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

            json_str = json.dumps(lot_qty_remaining)
            _logger.info(
                '[LOT_RETURN] default_get: move=%s, lots=%s, qty_json=%s, total=%s',
                move_id, lot_ids_to_select, json_str, total_remaining,
            )

            lot_vals = dict(vals)
            lot_vals.update({
                'lot_ids': [(6, 0, lot_ids_to_select)],
                'quantity': total_remaining,
                'to_return': True,
                'is_lot_tracked': True,
                'lot_qty_json': json_str,
            })
            new_lines.append((0, 0, lot_vals))

        res['product_return_moves'] = new_lines
        return res

    def _get_returned_qty_by_lot(self, original_move):
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

        move_lot_map = {}
        for line in active_lot_lines:
            lot_qty_map = {}
            if line.lot_qty_json:
                try:
                    lot_qty_map = json.loads(line.lot_qty_json)
                except (json.JSONDecodeError, TypeError):
                    pass

            assignments = []
            for lot in line.lot_ids:
                lot_key = str(lot.id)
                if lot_key in lot_qty_map:
                    qty = lot_qty_map[lot_key]
                else:
                    mls = line.move_id.move_line_ids.filtered(
                        lambda ml, l=lot: ml.lot_id.id == l.id and ml.state == 'done'
                    )
                    qty = sum(mls.mapped('quantity'))

                if float_compare(qty, 0.0, precision_digits=4) > 0:
                    assignments.append({
                        'lot_id': lot.id,
                        'quantity': qty,
                    })

            if assignments:
                move_lot_map[line.move_id.id] = assignments

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