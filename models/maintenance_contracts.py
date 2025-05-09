from odoo import models, fields, api
from datetime import date, timedelta

class MaintenanceServiceContract(models.Model):
    _name = 'maintenance.service.contract'
    _description = 'Maintenance Service Contract'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string="Contract Name", required=True)
    contract_start_date = fields.Date(string="Contract Start Date")
    contract_end_date = fields.Date(string="Contract End Date")
    renewal_alert_days = fields.Integer(string="Renewal Alert Days", default=30)

    associated_equipments = fields.Many2many('maintenance.equipment', string="Associated Equipments")
    supplier_id = fields.Many2one('res.partner', string="Supplier", domain="[('supplier_rank', '>', 0)]")
    client_id = fields.Many2one('res.partner', string="Client", domain="[('customer_rank', '>', 0)]")
    cost = fields.Float(string="Contract Cost")

    sla_duration = fields.Integer(string="SLA Duration (Days)", help="SLA Duration for resolving maintenance requests.")
    sla_breached = fields.Boolean(string="SLA Breached", compute="_compute_sla_breached", store=True)

    @api.depends('sla_duration', 'contract_end_date')
    def _compute_sla_breached(self):
        for contract in self:
            if contract.sla_duration and contract.contract_end_date:
                sla_deadline = contract.contract_end_date - timedelta(days=contract.sla_duration)
                contract.sla_breached = date.today() > sla_deadline
            else:
                contract.sla_breached = False

    @api.model
    def check_contract_renewal(self):
        contracts = self.search([('contract_end_date', '!=', False)])
        for contract in contracts:
            if contract.contract_end_date - date.today() <= timedelta(days=contract.renewal_alert_days):
                contract.message_post(body=f"Contract '{contract.name}' is nearing its end date ({contract.contract_end_date}). Please consider renewing.")