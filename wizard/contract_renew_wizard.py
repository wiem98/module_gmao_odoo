from odoo import models, fields, api

class ContractRenewWizard(models.TransientModel):
    _name = "maintenance.contract.renew.wizard"
    _description = "Contract Renewal Wizard"

    contract_id = fields.Many2one(
        "maintenance.service.contract", string="Original Contract", required=True
    )
    name = fields.Char(string="Contract Name")
    contract_start_date = fields.Date(string="New Start Date", required=True)
    contract_end_date = fields.Date(string="New End Date", required=True)
    cost = fields.Float(string="Cost")
    sla_duration = fields.Integer(string="SLA Duration")
    associated_equipments = fields.Many2many(
        'maintenance.equipment', string="Associated Equipments"
    )

    @api.model
    def default_get(self, fields):
        res = super().default_get(fields)
        if self.env.context.get('active_model') == 'maintenance.service.contract':
            contract = self.env['maintenance.service.contract'].browse(self.env.context.get('active_id'))
            res.update({
                'contract_id': contract.id,
                'cost': contract.cost,
                'sla_duration': contract.sla_duration,
                'associated_equipments': [(6, 0, contract.associated_equipments.ids)],
            })
        return res


    def action_confirm_renewal(self):
        self.ensure_one()
        self.contract_id.ensure_one()

        new_contract = self.env["maintenance.service.contract"].create({
            "name": self.name or f"Renew from {self.contract_id.name}",
            "contract_start_date": self.contract_start_date,
            "contract_end_date": self.contract_end_date,
            "cost": self.cost,
            "sla_duration": self.sla_duration,
            "supplier_id": self.contract_id.supplier_id.id,
            "client_id": self.contract_id.client_id.id,
            "project_id": self.contract_id.project_id.id,
            'associated_equipments': [(6, 0, self.associated_equipments.ids)],
            "company_id": self.contract_id.company_id.id,
            "client_signature": self.contract_id.client_signature,
            "company_signature": self.contract_id.company_signature,
            "renewed_from_contract_id": self.contract_id.id,
            "state": "draft"
        })

        return {
            "type": "ir.actions.act_window",
            "res_model": "maintenance.service.contract",
            "res_id": new_contract.id,
            "view_mode": "form",
            "target": "current",
        }
