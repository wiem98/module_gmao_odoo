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
