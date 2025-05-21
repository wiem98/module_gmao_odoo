# models/wizard_send_contract_email.py
from odoo import models, fields, api
import base64

class WizardSendContractEmail(models.TransientModel):
    _name = 'wizard.send.contract.email'
    _description = 'Wizard to Send Contract Email'

    contract_id = fields.Many2one('maintenance.service.contract', required=True)
    email_to = fields.Char(string="To", required=True)
    subject = fields.Char(string="Subject", required=True)
    body = fields.Html(string="Body", required=True)

    @api.model
    def default_get(self, fields):
        res = super().default_get(fields)
        contract = self.env['maintenance.service.contract'].browse(self.env.context.get('active_id'))
        res.update({
            'contract_id': contract.id,
            'email_to': contract.client_id.email,
            'subject': f"Your Contract: {contract.name}",
            'body': f"""
                <p>Hello {contract.client_id.name},</p>
                <p>Please find your maintenance contract details below:</p>
                <ul>
                    <li><strong>Start:</strong> {contract.contract_start_date}</li>
                    <li><strong>End:</strong> {contract.contract_end_date}</li>
                    <li><strong>Cost:</strong> {contract.cost} {contract.company_id.currency_id.symbol}</li>
                </ul>
                <p>Best regards,<br/>{contract.company_id.name}</p>
            """,
        })
        return res

    def send_contract_email(self):
        self.ensure_one()

        # Send email without using mail.template
        mail_values = {
            'email_to': self.email_to,
            'subject': self.subject,
            'body_html': self.body,
            'body': self.body,
            'auto_delete': True,
            'email_from': self.env.user.email or self.env.company.email,
        }

        self.env['mail.mail'].create(mail_values).send()

        return {'type': 'ir.actions.act_window_close'}

