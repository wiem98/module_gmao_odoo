from odoo import models, fields, api
from datetime import date, timedelta
from odoo.exceptions import ValidationError

STATE_SELECTION = [
    ("draft", "Draft"),
    ("approved", "Approved"),
    ("active", "Active"),
    ("expired", "Expired"),
    ("cancelled", "Cancelled"),
]


class MaintenanceServiceContract(models.Model):
    _name = "maintenance.service.contract"
    _description = "Maintenance Service Contract"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(string="Contract Name", required=True)
    contract_start_date = fields.Date(string="Contract Start Date")
    contract_end_date = fields.Date(string="Contract End Date")
    renewal_alert_days = fields.Integer(string="Renewal Alert Days", default=30)

    associated_equipments = fields.Many2many(
        "maintenance.equipment", string="Associated Equipments"
    )
    supplier_id = fields.Many2one(
        "res.partner",
        string="Supplier",
        domain="[('supplier_rank', '>', 0)]",
        required=True,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
        readonly=True,
    )
    client_id = fields.Many2one(
        "res.partner",
        string="Client",
        domain="[('customer_rank', '>', 0)]",
        required=True,
    )
    cost = fields.Float(string="Contract Cost")

    sla_duration = fields.Integer(
        string="SLA Duration (Days)",
        help="SLA Duration for resolving maintenance requests.",
    )
    sla_breached = fields.Boolean(
        string="SLA Breached", compute="_compute_sla_breached", store=True
    )
    renewal_period = fields.Integer(string="Renewal Period (days)", default=365)

    client_signature = fields.Binary(string="Client Signatory")
    company_signature = fields.Binary(string="Company Signatory")

    state = fields.Selection(
        selection=STATE_SELECTION,
        string="Status",
        default="draft",
        tracking=True,
        readonly=True,
    )

    def action_approve_contract(self):
        for contract in self:
            if not contract.client_signature or not contract.company_signature:
                raise ValidationError(
                    "Both client and company signatures are required to approve the contract."
                )
            contract.state = "approved"
            contract.message_post(body="Contract approved successfully.")

    def action_activate_contract(self):
        for contract in self:
            if contract.state != "approved":
                raise ValidationError("Only approved contracts can be activated.")
            if not contract.contract_start_date or not contract.contract_end_date:
                raise ValidationError("Please set both start and end dates.")
            contract.state = "active"
            contract.message_post(body="Contract activated.")

    def action_reset_to_draft(self):
        for contract in self:
            if contract.state not in ["active", "cancelled"]:
                raise ValidationError(
                    "Seuls les contrats actifs ou annulés peuvent être réinitialisés."
                )
            contract.state = "draft"
            contract.message_post(
                body="Contrat réinitialisé à l'état brouillon (draft)."
            )

    def action_cancelled_contract(self):
        for contract in self:
            if contract.state != "draft":
                raise ValidationError(
                    "Seuls les contrats en brouillon peuvent être annulés."
                )
            contract.state = "cancelled"
            contract.message_post(body="Contrat annulé.")


    @api.depends("sla_duration", "contract_end_date")
    def _compute_sla_breached(self):
        for contract in self:
            if contract.sla_duration and contract.contract_end_date:
                sla_deadline = contract.contract_end_date - timedelta(
                    days=contract.sla_duration
                )
                contract.sla_breached = date.today() > sla_deadline
            else:
                contract.sla_breached = False

    @api.model
    def check_contract_renewal(self):
        contracts = self.search([("contract_end_date", "!=", False)])
        for contract in contracts:
            if contract.contract_end_date - date.today() <= timedelta(
                days=contract.renewal_alert_days
            ):
                contract.message_post(
                    body=f"Contract '{contract.name}' is nearing its end date ({contract.contract_end_date}). Please consider renewing."
                )

    @api.model
    def update_expired_contracts(self):
        today = date.today()
        expired_contracts = self.search([
            ("contract_end_date", "<", today),
            ("state", "=", "active"),
            ("contract_end_date", "!=", False),
        ])
        for contract in expired_contracts:
            contract.state = "expired"
            contract.message_post(
                body=f"Le contrat '{contract.name}' est arrivé à expiration ({contract.contract_end_date}) et a été automatiquement mis à jour en 'expiré'."
            )

    def action_print_contract(self):
        self.ensure_one()
        return self.env.ref(
            "module_gmao_odoo.report_maintenance_contract_pdf"
        ).report_action(self.id)

    

    def _get_report_base_filename(self):
        self.ensure_one()
        return f"Contract_{self.name.replace(' ', '_')}"
    
    def action_send_email(self):
        self.ensure_one()
        