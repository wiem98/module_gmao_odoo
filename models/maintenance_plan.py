from odoo import models, fields, api
from datetime import timedelta, date
from dateutil.relativedelta import relativedelta

class MaintenancePlan(models.Model):
    _name = 'maintenance.plan'
    _description = 'Maintenance Plan'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(required=True)
    equipment_id = fields.Many2one('maintenance.equipment', string="Equipment", required=True)
    maintenance_type = fields.Selection([
        ('preventive', 'Préventive'),
        ('corrective', 'Corrective'),
        ('curative', 'Curative'),
        ('systematic', 'Systématique'),
        ('conditional', 'Conditionnelle'),
        ('predictive', 'Prédictive'),
    ], required=True)
    interval_number = fields.Integer(string="Repeat Every", required=True, default=30)
    interval_type = fields.Selection([
        ('days', 'Days'),
        ('weeks', 'Weeks'),
        ('months', 'Months')
    ], default='days', required=True)
    next_date = fields.Date(string="Next Scheduled Date", required=True, default=fields.Date.today)
    project_id = fields.Many2one('project.project', string="Project")
    responsible_id = fields.Many2one('res.users', string="Technician")
    active = fields.Boolean(default=True)

    # Predictive maintenance fields
    expected_failure_date = fields.Date(string="Expected Failure Date")
    mtbf_days = fields.Integer(string="MTBF (Days)", help="Mean Time Between Failures")
    prediction_source = fields.Char(string="Prediction Source", help="Algorithm, Sensor, or Manual")
    
    contract_name = fields.Char(string="Contract Name")
    sla_duration = fields.Integer(string="SLA Duration (Days)", help="SLA Duration for resolving maintenance requests.")
    contract_start_date = fields.Date(string="Contract Start Date")
    contract_end_date = fields.Date(string="Contract End Date")
    renewal_alert_days = fields.Integer(string="Renewal Alert Days", default=30)
    associated_equipments = fields.Many2many('maintenance.equipment', string="Associated Equipments")
    supplier_id = fields.Many2one('res.partner', string="Supplier", domain="[('supplier_rank', '>', 0)]")
    client_id = fields.Many2one('res.partner', string="Client", domain="[('customer_rank', '>', 0)]")
    cost = fields.Float(string="Contract Cost")
    sla_breached = fields.Boolean(string="SLA Breached", compute="_compute_sla_breached", store=True)

    @api.depends('sla_duration', 'next_date')
    def _compute_sla_breached(self):
        """Automatically check if SLA is breached."""
        for plan in self:
            if plan.sla_duration and plan.next_date:
                sla_deadline = plan.next_date + timedelta(days=plan.sla_duration)
                plan.sla_breached = date.today() > sla_deadline
            else:
                plan.sla_breached = False
    
    @api.model
    def check_contract_renewal(self):
        plans = self.search([('contract_end_date', '!=', False)])
        for plan in plans:
            if plan.contract_end_date - date.today() <= timedelta(days=plan.renewal_alert_days):
                plan.message_post(body=f"⚠️ Contract '{plan.contract_name}' is nearing its end date ({plan.contract_end_date}). Please consider renewing.")
                
    @api.depends('equipment_id.latest_failure_date', 'mtbf_days')
    def _compute_next_date(self):
        """Auto-compute next date depending on type."""
        for plan in self:
            if plan.maintenance_type == 'predictive' and plan.mtbf_days:
                failure_date = plan.equipment_id.latest_failure_date or date.today()
                plan.next_date = failure_date + timedelta(days=plan.mtbf_days)
            else:
                if plan.interval_type == 'days':
                    plan.next_date += timedelta(days=plan.interval_number)
                elif plan.interval_type == 'weeks':
                    plan.next_date += timedelta(weeks=plan.interval_number)
                elif plan.interval_type == 'months':
                    plan.next_date = plan.next_date + relativedelta(months=plan.interval_number)

    def generate_maintenance_requests(self):
        """Cron or button-based generation of maintenance requests."""
        today = date.today()
        plans = self.search([('next_date', '<=', today), ('active', '=', True)])
        for plan in plans:
            self.env['maintenance.request'].create({
                'name': f"{plan.name} ({fields.Date.today()})",
                'equipment_id': plan.equipment_id.id,
                'maintenance_type': plan.maintenance_type,
                'project_id': plan.project_id.id,
                'user_id': plan.responsible_id.id if plan.responsible_id else False,
                'request_date': fields.Date.today(),
                'plan_id': plan.id,
            })
            plan._compute_next_date()

    def action_recalculate_predictive_date(self):
        """Manually refresh next date for predictive plans."""
        for plan in self:
            if plan.maintenance_type == 'predictive' and plan.mtbf_days:
                failure_date = plan.equipment_id.latest_failure_date or date.today()
                plan.next_date = failure_date + timedelta(days=plan.mtbf_days)
    def create_plan_from_request(self):
        for request in self:
            # Create or open Maintenance Plan with pre-filled values
            plan = self.env['maintenance.plan'].create({
                'name': f"Plan for {request.name}",
                'equipment_id': request.equipment_id.id,
                'maintenance_type': request.maintenance_type,
                'project_id': request.project_id.id if request.project_id else False,
                'responsible_id': request.user_id.id if request.user_id else False,
                'interval_number': 30,  # Default value, you can customize it
                'interval_type': 'days',
                'next_date': date.today() + timedelta(days=30),
                'active': True,
            })

            # Redirect directly to the newly created plan
            return {
                'name': "Maintenance Plan",
                'type': 'ir.actions.act_window',
                'res_model': 'maintenance.plan',
                'view_mode': 'form',
                'res_id': plan.id,
                'target': 'current',
            }