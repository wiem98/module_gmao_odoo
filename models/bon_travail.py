from odoo import models, fields, api
from odoo.exceptions import ValidationError
from . import bt_stages


class GmaoBonTravail(models.Model):
    _name = "gmao.bt"
    _description = "Bon de Travail"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(string="Référence", required=True, default="New", copy=False)
    description = fields.Text(string="Description")
    equipment_id = fields.Many2one(
        "maintenance.equipment", string="Équipement concerné"
    )
    intervention_type = fields.Selection(
        [
            ("preventive", "Préventive"),
            ("corrective", "Corrective"),
            ("curative", "Curative"),
            ("systematic", "Systématique"),
            ("conditional", "Conditionnelle"),
            ("predictive", "Prédictive"),
        ],
        string="Type d'intervention",
    )
    used_parts_ids = fields.Many2many("product.product", string="Pièces utilisées")
    technician_id = fields.Many2one("res.users", string="Technicien")
    supervisor_id = fields.Many2one("res.users", string="Superviseur")
    stage_id = fields.Many2one(
        "bt.stages",
        string="Étape",
        default=lambda self: self.env['bt.stages'].search([('name', '=', 'Soumis')], limit=1).id,
        group_expand="_read_group_stage_ids"
    )
    technician_signature = fields.Binary(string="Signature Technicien")
    supervisor_signature = fields.Binary(string="Signature Superviseur")
    
    # Updated priority field to match maintenance request criticity
    priority = fields.Selection(
        selection=[
            ('0', 'Very Low'),
            ('1', 'Low'),
            ('2', 'Normal'),
            ('3', 'High')
        ],
        string="Priority",
        index=True,
        help="Priority of this work order (matches Maintenance Request criticity)"
    )
    
    schedule_date = fields.Date(string="Date Planifiée")
    contract_id = fields.Many2one(
        "maintenance.service.contract", string="Contrat de Maintenance"
    )
    contract_start_date = fields.Date(
        related="contract_id.contract_start_date", store=True, readonly=True
    )
    contract_end_date = fields.Date(
        related="contract_id.contract_end_date", store=True, readonly=True
    )
    sla_duration = fields.Integer(
        related="contract_id.sla_duration", store=True, readonly=True
    )
    contract_cost = fields.Float(related="contract_id.cost", store=True, readonly=True)
    contract_client_id = fields.Many2one(
        related="contract_id.client_id", store=True, readonly=True
    )
    contract_supplier_id = fields.Many2one(
        related="contract_id.supplier_id", store=True, readonly=True
    )
    
    # Fields for late notification tracking
    late_notification_sent = fields.Boolean(
        string="Notification de retard envoyée", 
        default=False,
        help="Indique si une notification de retard a déjà été envoyée"
    )
    last_late_notification_date = fields.Date(
        string="Date dernière notification",
        help="Date à laquelle la dernière notification de retard a été envoyée"
    )

    is_stage_affecte = fields.Boolean(
        compute="_compute_is_stage_affecte", store=True
    )

    is_stage_realised = fields.Boolean(
        compute="_compute_is_stage_realised", store=True
    )

    # New field to link to maintenance request
    maintenance_request_id = fields.Many2one(
        'maintenance.request',
        string="Maintenance Request",
        help="The maintenance request that generated this work order"
    )

    @api.depends("stage_id")
    def _compute_is_stage_affecte(self):
        for rec in self:
            rec.is_stage_affecte = rec.stage_id.name == "Affecté"

    @api.depends("stage_id")
    def _compute_is_stage_realised(self):
        for rec in self:
            rec.is_stage_realised = rec.stage_id.name == "Réalisé"

    @api.model
    def _read_group_stage_ids(self, stages, domain, order=None):
        return stages.search([], order=order or "sequence, id")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code("gmao.bt") or "New"

            if vals.get("technician_id"):
                assigned_stage = self.env["bt.stages"].search(
                    [("name", "=", "Affecté")], limit=1
                )
                if assigned_stage:
                    vals["stage_id"] = assigned_stage.id


        return super().create(vals_list)

    def write(self, vals):
        # Reset notification flags if schedule date or stage changes
        if 'schedule_date' in vals or 'stage_id' in vals:
            vals.update({
                'late_notification_sent': False,
                'last_late_notification_date': False
            })
        
        # Update priority if maintenance request criticity changes
        if 'maintenance_request_id' in vals:
            request = self.env['maintenance.request'].browse(vals['maintenance_request_id'])
            if request:
                vals['priority'] = request.priority
        
        return super().write(vals)

    def action_print_bt(self):
        self.ensure_one()
        return self.env.ref("module_gmao_odoo.action_report_gmao_bt").report_action(
            self
        )

    @api.model
    def check_late_bt(self):
        today = fields.Date.context_today(self)

        # 1. BT en retard → notifier le technicien
        late_bts = self.search([
            ("stage_id.name", "not in", ["Clôturé", "Réalisé"]),
            ("schedule_date", "!=", False),
            ("schedule_date", "<", today),
            ("technician_id", "!=", False),
            ("late_notification_sent", "=", False),  # Only those not yet notified
        ])

        for bt in late_bts:
            technician = bt.technician_id
            msg = f"Le Bon de Travail « {bt.name} » est en retard (prévu le {bt.schedule_date})."

            # Notification interne
            bt.message_post(
                body=msg,
                subject="⚠️ BT en Retard",
                partner_ids=[technician.partner_id.id],
            )

            # E-mail
            if technician.email:
                bt.message_post(
                    body=msg,
                    subject="Alerte : BT en Retard",
                    partner_ids=[technician.partner_id.id],
                    message_type="email",
                )
            
            # Update notification tracking
            bt.write({
                'late_notification_sent': True,
                'last_late_notification_date': today
            })

    def action_reset_late_notification(self):
        """Action to manually reset late notification flags"""
        self.write({
            'late_notification_sent': False,
            'last_late_notification_date': False
        })
        return True

    def action_set_realise(self):
        for bt in self:
            if not bt.technician_signature:
                raise ValidationError(
                    "Vous devez ajouter la signature du technicien avant de passer à l'étape 'Réalisé'."
                )

            realise_stage = self.env["bt.stages"].search(
                [("name", "=", "Réalisé")], limit=1
            )
            if not realise_stage:
                raise ValidationError(
                    "L'étape 'Réalisé' n'existe pas. Veuillez la créer."
                )

            bt.stage_id = realise_stage.id

    def action_set_cloture(self):
        for record in self:
            if record.stage_id.name != "Réalisé":
                raise ValidationError(
                    "L'étape actuelle doit être 'Réalisé' pour clôturer."
                )
            if not record.supervisor_signature:
                raise ValidationError(
                    "La signature du superviseur est requise pour clôturer."
                )

            stage_cloture = self.env["bt.stages"].search(
                [("name", "=", "Clôturé")], limit=1
            )
            if not stage_cloture:
                raise ValidationError("L'étape 'Clôturé' n'existe pas.")

            record.stage_id = stage_cloture
            record.message_post(body="Le bon de travail a été clôturé.")