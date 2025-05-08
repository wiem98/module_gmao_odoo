from odoo import models, fields


AVAILABLE_PRIORITIES = [
    ('0', 'Low'),
    ('1', 'Medium'),
    ('2', 'High'),
    ('3', 'Very High'),
]

class BtStages(models.Model):
    _name = 'bt.stages'
    _description = 'Stages de bon de travail'
    _order = 'sequence, id'

    name = fields.Char(string='Stage Name', required=True)
    sequence = fields.Integer(default=1)
    fold = fields.Boolean(string='Folded in Kanban', default=False)
    done = fields.Boolean(string='Stage Done', default=False)