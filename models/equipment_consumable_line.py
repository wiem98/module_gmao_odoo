
from odoo import models, fields

class EquipmentConsumableLine(models.Model):
    _name = 'equipment.consumable.line'
    _description = 'Consumable Part for Equipment'

    equipment_id = fields.Many2one('maintenance.equipment', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string="Consumable Product", domain=[('type', '=', 'product')], required=True)
    quantity = fields.Float(string="Recommended Quantity", default=1.0)
    uom_id = fields.Many2one(related='product_id.uom_id', readonly=True)
