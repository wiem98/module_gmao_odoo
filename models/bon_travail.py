from odoo import models, fields, api
from odoo.exceptions import ValidationError
from . import bt_stages

class GmaoBonTravail(models.Model):
    _name = 'gmao.bt'
    _description = 'Bon de Travail'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string="Référence", required=True, default='New', copy=False)
    description = fields.Text(string="Description")
    equipment_id = fields.Many2one('maintenance.equipment', string="Équipement concerné")
    intervention_type = fields.Selection([
        ('preventive', 'Préventive'),
        ('corrective', 'Corrective'),
        ('curative', 'Curative'),
        ('systematic', 'Systématique'),
        ('conditional', 'Conditionnelle'),
        ('predictive', 'Prédictive'),
    ], string="Type d'intervention")
    used_parts_ids = fields.Many2many('product.product', string="Pièces utilisées")
    technician_id = fields.Many2one('res.users', string="Technicien")
    supervisor_id = fields.Many2one('res.users', string="Superviseur")
    stage_id = fields.Many2one(
        'bt.stages',
        string='Étape',
        group_expand='_read_group_stage_ids')
    technician_signature = fields.Binary(string="Signature Technicien")
    supervisor_signature = fields.Binary(string="Signature Superviseur")
    priority = fields.Selection(
        bt_stages.AVAILABLE_PRIORITIES, string='Priority', index=True,
        default=bt_stages.AVAILABLE_PRIORITIES[0][0])
    schedule_date = fields.Date(string="Date Planifiée")
    contract_id = fields.Many2one('maintenance.service.contract', string="Contrat de Maintenance")
    contract_start_date = fields.Date(related='contract_id.contract_start_date', store=True, readonly=True)
    contract_end_date = fields.Date(related='contract_id.contract_end_date', store=True, readonly=True)
    sla_duration = fields.Integer(related='contract_id.sla_duration', store=True, readonly=True)
    contract_cost = fields.Float(related='contract_id.cost', store=True, readonly=True)
    contract_client_id = fields.Many2one(related='contract_id.client_id', store=True, readonly=True)
    contract_supplier_id = fields.Many2one(related='contract_id.supplier_id', store=True, readonly=True)




    @api.model
    def _read_group_stage_ids(self, stages, domain, order=None):
        return stages.search([], order=order or 'sequence, id')


    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('gmao.bt') or 'New'

            if vals.get('technician_id') and not vals.get('stage_id'):
                assigned_stage = self.env['bt.stages'].search([('name', '=', 'Affecté')], limit=1)
                if assigned_stage:
                    vals['stage_id'] = assigned_stage.id

        return super().create(vals_list)

    def write(self, vals):
        # Récupération des étapes cibles
        stage_realise = self.env['bt.stages'].search([('name', '=', 'Réalisé')], limit=1)
        stage_cloture = self.env['bt.stages'].search([('name', '=', 'Clôturé')], limit=1)

        for rec in self:
            # Empêcher le passage manuel à "Réalisé" sans signature technicien
            if vals.get('stage_id') == stage_realise.id:
                if not vals.get('technician_signature') and not rec.technician_signature:
                    raise ValidationError("Vous devez ajouter la signature du technicien avant de passer à l'étape 'Réalisé'.")

            # Empêcher le passage manuel à "Clôturé" sans les deux signatures
            if vals.get('stage_id') == stage_cloture.id:
                has_tech_sig = vals.get('technician_signature') or rec.technician_signature
                has_sup_sig = vals.get('supervisor_signature') or rec.supervisor_signature
                if not (has_tech_sig and has_sup_sig):
                    raise ValidationError("Vous devez ajouter les signatures du technicien ET du superviseur avant de passer à l'étape 'Clôturé'.")


            # Affecter automatiquement l'étape "Affecté"
            if 'technician_id' in vals and vals['technician_id'] and not vals.get('stage_id'):
                assigned_stage = self.env['bt.stages'].search([('name', '=', 'Affecté')], limit=1)
                if assigned_stage:
                    vals['stage_id'] = assigned_stage.id

            # Passage automatique à "Réalisé" via signature
            if 'technician_signature' in vals and vals['technician_signature']:
                if stage_realise and rec.stage_id != stage_realise:
                    vals['stage_id'] = stage_realise.id

            # Passage automatique à "Clôturé" via signature
            if 'supervisor_signature' in vals and vals['supervisor_signature']:
                if stage_cloture and rec.stage_id != stage_cloture:
                    vals['stage_id'] = stage_cloture.id

        return super().write(vals)



    def action_print_bt(self):
        self.ensure_one()
        return self.env.ref('gmao.action_report_gmao_bt').report_action(self)


    @api.model
    def check_late_bt(self):
        today = fields.Date.context_today(self)

        # 1. BT en retard → notifier le technicien
        late_bts = self.search([
            ('stage_id.name', 'not in', ['Clôturé', 'Réalisé']),
            ('schedule_date', '!=', False),
            ('schedule_date', '<', today),
            ('technician_id', '!=', False)
        ])

        for bt in late_bts:
            technician = bt.technician_id
            msg = f"Le Bon de Travail « {bt.name} » est en retard (prévu le {bt.schedule_date})."

            # Notification interne
            bt.message_post(body=msg, subject="⚠️ BT en Retard", partner_ids=[technician.partner_id.id])

            # E-mail
            if technician.email:
                bt.message_post(
                    body=msg,
                    subject="Alerte : BT en Retard",
                    partner_ids=[technician.partner_id.id],
                    message_type='email'
                )